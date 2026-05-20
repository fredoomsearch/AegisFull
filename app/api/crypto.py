from __future__ import annotations

"""
Crypto data/prediction/trade API surface.

Why this module exists:
- Provide market data and prediction endpoints for the crypto panel.
- Keep demo-safe trading behavior and telemetry in one router.
"""

import hashlib
import asyncio
import hmac
import io
import json
import logging
import math
import os
import random
import re
import threading
import time
import csv
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional
from urllib.parse import urlencode

import requests
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.api.deps import require_api_key
from app.models.ml.models import ModelCatalog, TrainedModel, build_model_registry, discover_trained_models
from app.services.crypto_news_service import fetch_news as fetch_crypto_news
from app.services.crypto_prediction_log import (
    assess_scope_credibility,
    clear_predictions_and_outcomes,
    list_outcomes,
    list_predictions,
    log_outcome,
    log_prediction,
    normalize_engine_filter,
    optimize_thresholds,
    pair_predictions_with_outcomes,
    recent_stats,
    scope_leaderboard,
)
from app.services.crypto_runtime import _optional_float, _risk_snapshot, build_crypto_state_snapshot, reconcile_due_predictions
from app.services.crypto_trade_log import clear_trades, compute_pnl, list_trades, log_trade
from app.utils.ml_helpers import sentiment_score as _sentiment_score

_pd = None
_meta_module = None
_trained_bundle_cache: Dict[str, Dict[str, Any]] = {}
_artifact_sha_cache: Dict[str, tuple[int, int, str]] = {}
_artifact_sha_lock = threading.Lock()
CRYPTO_USE_TRAINED_MODELS = (os.getenv("AEGIS_CRYPTO_USE_TRAINED_MODELS", "1") or "1").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
CRYPTO_REQUIRE_TRAINED_MODELS = (os.getenv("AEGIS_CRYPTO_REQUIRE_TRAINED_MODELS", "0") or "0").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
CRYPTO_DEFAULT_BUY_THRESHOLD = float(os.getenv("AEGIS_CRYPTO_BUY_THRESHOLD", "0.63") or "0.63")
CRYPTO_DEFAULT_SELL_THRESHOLD = float(os.getenv("AEGIS_CRYPTO_SELL_THRESHOLD", "0.37") or "0.37")
CRYPTO_THRESHOLD_LOOKBACK = int(os.getenv("AEGIS_CRYPTO_THRESHOLD_LOOKBACK", "1000") or "1000")
CRYPTO_THRESHOLD_MIN_TRADES = int(os.getenv("AEGIS_CRYPTO_THRESHOLD_MIN_TRADES", "8") or "8")


def _query_default_value(value: Any) -> Any:
    if hasattr(value, "default") and value.__class__.__module__.startswith("fastapi"):
        default = getattr(value, "default", None)
        return None if default is Ellipsis else default
    return value


def _optional_query_int(value: Any) -> Optional[int]:
    raw = _query_default_value(value)
    if raw in {None, ""}:
        return None
    return int(raw)


def _optional_query_text(value: Any) -> Optional[str]:
    raw = _query_default_value(value)
    text = str(raw or "").strip()
    return text or None


def _env_float(name: str, default: float) -> float:
    raw = str(os.getenv(name) or "").strip()
    if not raw:
        return float(default)
    try:
        return float(raw)
    except Exception:
        return float(default)


def _normalized_prediction_scope(
    *,
    symbol: Any,
    engine: Any,
    horizon_minutes: Any,
    regime: Any,
) -> Dict[str, Any]:
    return {
        "symbol": _optional_query_text(symbol),
        "engine": _optional_query_text(engine),
        "horizon_minutes": _optional_query_int(horizon_minutes),
        "regime": _optional_query_text(regime),
    }


def _decision_from_thresholds(probability_up: float, *, buy_threshold: float, sell_threshold: float) -> Literal["BUY", "SELL", "HOLD"]:
    if probability_up >= buy_threshold:
        return "BUY"
    if probability_up <= sell_threshold:
        return "SELL"
    return "HOLD"


def _execution_margin_for_credibility(credibility: Optional[Dict[str, Any]]) -> float:
    status = str((credibility or {}).get("status") or "").strip().lower()
    if status == "trusted":
        return 0.02
    if status == "cautious":
        return 0.05
    if status == "insufficient_history":
        return 0.08
    return 0.0


def _consensus_requirements_for_credibility(credibility: Optional[Dict[str, Any]]) -> Dict[str, float]:
    status = str((credibility or {}).get("status") or "").strip().lower()
    if status == "trusted":
        return {"min_support_ratio": 0.6, "max_spread": 0.3}
    if status == "cautious":
        return {"min_support_ratio": 0.8, "max_spread": 0.22}
    if status == "insufficient_history":
        return {"min_support_ratio": 0.8, "max_spread": 0.18}
    return {"min_support_ratio": 1.0, "max_spread": 0.12}


def _operator_guidance_status(operator_guidance: Optional[Dict[str, Any]]) -> str:
    return str((operator_guidance or {}).get("status") or "").strip().lower()


def _scope_operator_guidance(
    *,
    symbol: Optional[str],
    horizon_minutes: Optional[int],
    regime: Optional[str],
    limit: int,
) -> Optional[Dict[str, Any]]:
    try:
        stats = recent_stats(
            limit=limit,
            symbol=symbol,
            engine="trained",
            horizon_minutes=horizon_minutes,
            regime=regime,
        )
    except Exception:
        logger.debug("Failed to compute crypto operator guidance", exc_info=True)
        return None
    guidance = stats.get("operator_guidance") if isinstance(stats, dict) else None
    return guidance if isinstance(guidance, dict) else None


def _calibration_margin_for_operator_guidance(operator_guidance: Optional[Dict[str, Any]]) -> float:
    status = _operator_guidance_status(operator_guidance)
    if status == "downgrade":
        return 0.03
    return 0.0


def _effective_execution_margin(
    credibility: Optional[Dict[str, Any]],
    operator_guidance: Optional[Dict[str, Any]],
) -> float:
    return _execution_margin_for_credibility(credibility) + _calibration_margin_for_operator_guidance(operator_guidance)


def _effective_consensus_requirements(
    credibility: Optional[Dict[str, Any]],
    operator_guidance: Optional[Dict[str, Any]],
) -> Dict[str, float]:
    requirements = dict(_consensus_requirements_for_credibility(credibility))
    status = _operator_guidance_status(operator_guidance)
    if status == "downgrade":
        requirements["min_support_ratio"] = max(float(requirements.get("min_support_ratio") or 0.0), 0.9)
        requirements["max_spread"] = min(float(requirements.get("max_spread") or 1.0), 0.18)
    elif status == "abstain":
        requirements["min_support_ratio"] = 1.0
        requirements["max_spread"] = min(float(requirements.get("max_spread") or 1.0), 0.12)
    return requirements


def _should_calibration_abstain(operator_guidance: Optional[Dict[str, Any]]) -> bool:
    return _operator_guidance_status(operator_guidance) == "abstain"


def _effective_should_abstain(
    credibility: Optional[Dict[str, Any]],
    operator_guidance: Optional[Dict[str, Any]],
) -> bool:
    return bool((credibility or {}).get("should_abstain")) or _should_calibration_abstain(operator_guidance)


def _consensus_metrics(
    per_model_probs: Optional[Dict[str, Any]],
    *,
    decision: str,
) -> Optional[Dict[str, Any]]:
    if decision not in {"BUY", "SELL"} or not isinstance(per_model_probs, dict):
        return None
    probs: List[float] = []
    for value in per_model_probs.values():
        try:
            prob = float(value)
        except Exception:
            continue
        if math.isfinite(prob):
            probs.append(max(0.0, min(1.0, prob)))
    if not probs:
        return None
    if decision == "BUY":
        supporters = sum(1 for prob in probs if prob >= 0.5)
    else:
        supporters = sum(1 for prob in probs if prob <= 0.5)
    total = len(probs)
    return {
        "support_ratio": supporters / total if total else 0.0,
        "supporters": supporters,
        "total_models": total,
        "spread": max(probs) - min(probs) if total else 0.0,
        "mean_probability": sum(probs) / total if total else 0.0,
    }


def _crypto_policy_profile() -> Dict[str, Any]:
    return {
        "default_buy_threshold": CRYPTO_DEFAULT_BUY_THRESHOLD,
        "default_sell_threshold": CRYPTO_DEFAULT_SELL_THRESHOLD,
        "threshold_lookback": CRYPTO_THRESHOLD_LOOKBACK,
        "threshold_min_trades": CRYPTO_THRESHOLD_MIN_TRADES,
        "execution_margin": {
            "trusted": _execution_margin_for_credibility({"status": "trusted"}),
            "cautious": _execution_margin_for_credibility({"status": "cautious"}),
            "insufficient_history": _execution_margin_for_credibility({"status": "insufficient_history"}),
            "unknown": _execution_margin_for_credibility({"status": "unknown"}),
        },
        "consensus_requirements": {
            "trusted": _consensus_requirements_for_credibility({"status": "trusted"}),
            "cautious": _consensus_requirements_for_credibility({"status": "cautious"}),
            "insufficient_history": _consensus_requirements_for_credibility({"status": "insufficient_history"}),
            "unknown": _consensus_requirements_for_credibility({"status": "unknown"}),
        },
        "calibration_guidance": {
            "downgrade": {
                "margin_add": _calibration_margin_for_operator_guidance({"status": "downgrade"}),
                "min_support_ratio": 0.9,
                "max_spread": 0.18,
            },
            "abstain": {
                "blocks_execution": True,
                "route_reason": "calibration_abstain",
            },
        },
    }


def _crypto_execution_snapshot(*, requested_mode: Optional[str] = None) -> Dict[str, Any]:
    mode = str(requested_mode or os.getenv("BINANCE_EXECUTION_MODE", "simulated") or "simulated").strip().lower()
    if mode not in {"simulated", "testnet", "live"}:
        mode = "simulated"
    api_key = (os.getenv("BINANCE_API_KEY") or "").strip()
    api_secret = (os.getenv("BINANCE_API_SECRET") or "").strip()
    live_trading_enabled = (os.getenv("BINANCE_LIVE_TRADING", "0") or "0").strip().lower() in {"1", "true", "yes", "on"}
    return {
        "mode": mode,
        "requested_mode": str(requested_mode or "").strip().lower() or None,
        "credentials_present": bool(api_key and api_secret),
        "live_trading_enabled": live_trading_enabled,
        "testnet_enabled": mode == "testnet",
        "live_enabled": mode == "live" and live_trading_enabled,
        "simulated": mode == "simulated",
    }


def _crypto_state_signature(snapshot: Dict[str, Any] | None) -> str:
    if not isinstance(snapshot, dict):
        return ""
    scope = snapshot.get("scope") if isinstance(snapshot.get("scope"), dict) else {}
    execution = snapshot.get("execution") if isinstance(snapshot.get("execution"), dict) else {}
    summary = snapshot.get("summary") if isinstance(snapshot.get("summary"), dict) else {}
    latest_prediction_ref = snapshot.get("latest_prediction_ref") if isinstance(snapshot.get("latest_prediction_ref"), dict) else {}
    latest_outcome_ref = snapshot.get("latest_outcome_ref") if isinstance(snapshot.get("latest_outcome_ref"), dict) else {}
    latest_trade_ref = snapshot.get("latest_trade_ref") if isinstance(snapshot.get("latest_trade_ref"), dict) else {}
    order_book = snapshot.get("order_book") if isinstance(snapshot.get("order_book"), dict) else {}
    risk = snapshot.get("risk") if isinstance(snapshot.get("risk"), dict) else {}
    payload = {
        "scope": {
            "symbol": str(scope.get("symbol") or "").upper() or None,
            "engine": str(scope.get("engine") or "").strip().lower() or None,
            "horizon_minutes": _optional_float(scope.get("horizon_minutes")),
            "regime": str(scope.get("regime") or "").strip().lower() or None,
        },
        "execution": {
            "mode": str(execution.get("mode") or "").strip().lower() or None,
            "requested_mode": str(execution.get("requested_mode") or "").strip().lower() or None,
            "live_enabled": bool(execution.get("live_enabled")),
            "testnet_enabled": bool(execution.get("testnet_enabled")),
            "simulated": bool(execution.get("simulated")),
        },
        "summary": {
            "predictions_count": int(summary.get("predictions_count") or 0),
            "outcomes_count": int(summary.get("outcomes_count") or 0),
            "trades_count": int(summary.get("trades_count") or 0),
            "has_order_book": bool(summary.get("has_order_book")),
            "has_price": bool(summary.get("has_price")),
            "has_prediction": bool(summary.get("has_prediction")),
            "has_outcome": bool(summary.get("has_outcome")),
            "has_risk": bool(summary.get("has_risk")),
        },
        "current_price": _optional_float(snapshot.get("current_price")),
        "latest_prediction": {
            "log_id": str(latest_prediction_ref.get("log_id") or "").strip() or None,
            "ts": _optional_float(latest_prediction_ref.get("ts")),
            "decision": str(latest_prediction_ref.get("decision") or "").strip().upper() or None,
        },
        "latest_outcome": {
            "log_id": str(latest_outcome_ref.get("log_id") or "").strip() or None,
            "ts": _optional_float(latest_outcome_ref.get("ts")),
            "decision": str(latest_outcome_ref.get("decision") or "").strip().upper() or None,
        },
        "latest_trade": {
            "id": str(latest_trade_ref.get("id") or "").strip() or None,
            "ts": _optional_float(latest_trade_ref.get("ts")),
            "side": str(latest_trade_ref.get("side") or "").strip().upper() or None,
        },
        "order_book": {
            "best_bid": _optional_float(order_book.get("best_bid")),
            "best_ask": _optional_float(order_book.get("best_ask")),
            "spread_bps": _optional_float(order_book.get("spread_bps")),
            "imbalance": _optional_float(order_book.get("imbalance")),
            "bid_notional": _optional_float(order_book.get("bid_notional")),
            "ask_notional": _optional_float(order_book.get("ask_notional")),
            "liquidity_bucket": str(order_book.get("liquidity_bucket") or "").strip() or None,
        },
        "risk": {
            "decision": str(risk.get("decision") or "").strip().upper() or None,
            "entry_price": _optional_float(risk.get("entry_price")),
            "target_price": _optional_float(risk.get("target_price")),
            "stop_price": _optional_float(risk.get("stop_price")),
            "risk_reward": _optional_float(risk.get("risk_reward")),
            "order_size_pct": _optional_float(risk.get("order_size_pct")),
            "book_consumption_pct": _optional_float(risk.get("book_consumption_pct")),
            "impact_score": _optional_float(risk.get("impact_score")),
            "remaining_liquidity": _optional_float(risk.get("remaining_liquidity")),
        },
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return digest


def _crypto_state_snapshot_payload(
    *,
    symbol: Optional[str] = None,
    engine: Optional[str] = None,
    horizon_minutes: Optional[int] = None,
    regime: Optional[str] = None,
    execution_mode: Optional[Literal["simulated", "testnet", "live"]] = None,
    limit: int = 20,
    trade_limit: int = 100,
    leaderboard_limit: int = 10,
) -> Dict[str, Any]:
    scope = _normalized_prediction_scope(
        symbol=symbol,
        engine=engine,
        horizon_minutes=horizon_minutes,
        regime=regime,
    )
    limit_value = max(1, int(limit))
    trade_limit_value = max(1, int(trade_limit))
    leaderboard_limit_value = max(1, int(leaderboard_limit))
    return build_crypto_state_snapshot(
        symbol=scope["symbol"],
        engine=scope["engine"],
        horizon_minutes=scope["horizon_minutes"],
        regime=scope["regime"],
        limit=limit_value,
        trade_limit=trade_limit_value,
        leaderboard_limit=leaderboard_limit_value,
        price_lookup=_binance_spot_price,
        order_book_lookup=lambda sym: _binance_order_book(sym, limit=10),
        execution_snapshot=_crypto_execution_snapshot(requested_mode=execution_mode),
    )


def _liquidity_bucket_for_notional(notional: float) -> str:
    amount = max(0.0, float(notional or 0.0))
    if amount < 250:
        return "micro"
    if amount < 2500:
        return "small"
    if amount < 25000:
        return "medium"
    if amount < 100000:
        return "large"
    return "whale"


def _execution_profile(
    *,
    symbol_pair: str,
    side: str,
    quantity: float,
    mid_price: float,
    execution_mode: str,
) -> Dict[str, Any]:
    """
    Build a deterministic, demo-friendly execution profile.

    The goal is to make the simulated path feel closer to a real market:
    spread, slippage and market impact grow with notional size and less liquid
    symbols, while staying fully deterministic and safe.
    """
    base_asset = _base_symbol_from_pair(symbol_pair)
    mode = str(execution_mode or "simulated").strip().lower()
    if mode not in {"simulated", "testnet", "live"}:
        mode = "simulated"

    notional = max(0.0, float(quantity) * float(mid_price))
    liquidity_bucket = _liquidity_bucket_for_notional(notional)
    base_spread_bps = (
        4.0
        if base_asset in {"BTC", "ETH"}
        else 7.0
        if base_asset in {"BNB", "SOL", "XRP", "ADA", "DOGE", "LINK", "AVAX", "MATIC", "TRX"}
        else 11.0
    )
    mode_spread_bias = {"simulated": 4.0, "testnet": 2.0, "live": 1.0}[mode]
    bucket_impact = {
        "micro": 1.5,
        "small": 3.0,
        "medium": 6.0,
        "large": 12.0,
        "whale": 20.0,
    }[liquidity_bucket]
    size_impact = min(28.0, math.log10(max(notional, 1.0) + 1.0) * 2.4)
    spread_bps = round(base_spread_bps + mode_spread_bias, 2)
    impact_bps = round(bucket_impact + size_impact, 2)
    slippage_bps = round(spread_bps / 2.0 + impact_bps, 2)
    signed_slippage_bps = slippage_bps if side.upper() == "BUY" else -slippage_bps
    fill_price = round(float(mid_price) * (1.0 + signed_slippage_bps / 10000.0), 2)
    execution_note = (
        f"{liquidity_bucket} liquidity • STP/ECN-style fill • "
        f"spread {spread_bps:.1f}bps • slippage {slippage_bps:.1f}bps • "
        f"impact {impact_bps:.1f}bps"
    )
    return {
        "mid_price": round(float(mid_price), 2),
        "fill_price": fill_price,
        "spread_bps": spread_bps,
        "slippage_bps": slippage_bps,
        "impact_bps": impact_bps,
        "liquidity_bucket": liquidity_bucket,
        "notional": round(notional, 2),
        "execution_note": execution_note,
        "signed_slippage_bps": signed_slippage_bps,
    }


def _crypto_risk_policy(order: TradeRequest) -> Dict[str, float]:
    def _pick(value: Optional[float], env_name: str, default: float) -> float:
        if value is not None and float(value) > 0:
            return float(value)
        return _env_float(env_name, default)

    return {
        "max_order_notional": _pick(order.max_order_notional, "AEGIS_CRYPTO_MAX_ORDER_NOTIONAL", 15000.0),
        "max_exposure_quote": _pick(order.max_exposure_quote, "AEGIS_CRYPTO_MAX_EXPOSURE_QUOTE", 50000.0),
        "max_order_size_pct": _pick(order.max_order_size_pct, "AEGIS_CRYPTO_MAX_ORDER_SIZE_PCT", 35.0),
        "max_impact_score": _pick(order.max_impact_score, "AEGIS_CRYPTO_MAX_IMPACT_SCORE", 70.0),
        "min_risk_reward": _pick(order.min_risk_reward, "AEGIS_CRYPTO_MIN_RISK_REWARD", 1.05),
        "max_spread_bps": _pick(order.max_spread_bps, "AEGIS_CRYPTO_MAX_SPREAD_BPS", 30.0),
        "max_book_consumption_pct": _pick(order.max_book_consumption_pct, "AEGIS_CRYPTO_MAX_BOOK_CONSUMPTION_PCT", 45.0),
        "max_execution_drag_pct": _pick(None, "AEGIS_CRYPTO_MAX_EXECUTION_DRAG_PCT", 0.015),
    }


def _position_snapshot_from_pnl(
    *,
    symbol_pair: str,
    current_price: Optional[float],
    pnl: Optional[Dict[str, Any]],
    trades_count: int = 0,
) -> Dict[str, Any]:
    per_symbol = (pnl or {}).get("per_symbol") if isinstance(pnl, dict) else {}
    symbol_key = str(symbol_pair or "").upper()
    sym_pnl = per_symbol.get(symbol_key) if isinstance(per_symbol, dict) else {}
    position = _optional_float((sym_pnl or {}).get("position")) or 0.0
    avg_price = _optional_float((sym_pnl or {}).get("avg_price"))
    base_price = _optional_float(current_price)
    exposure_quote = abs(position) * (base_price if base_price and base_price > 0 else (avg_price or 0.0))
    return {
        "position": position,
        "avg_price": avg_price,
        "exposure_quote": round(exposure_quote, 2),
        "trades_count": int(trades_count or 0),
    }


def _prediction_operator_guidance(latest_prediction: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not isinstance(latest_prediction, dict):
        return None
    direct = latest_prediction.get("operator_guidance")
    if isinstance(direct, dict):
        return direct
    policy = latest_prediction.get("policy")
    if isinstance(policy, dict):
        nested = policy.get("operator_guidance")
        if isinstance(nested, dict):
            return nested
    return None


def _trade_calibration_controls(operator_guidance: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not isinstance(operator_guidance, dict):
        return None
    status = _operator_guidance_status(operator_guidance)
    controls: Dict[str, Any] = {
        "status": status or None,
        "action": str(operator_guidance.get("action") or "").strip().lower() or None,
        "reasons": [
            str(reason).strip().lower()
            for reason in (operator_guidance.get("reasons") or [])
            if str(reason).strip()
        ],
    }
    if status == "downgrade":
        controls["max_order_size_pct"] = 15.0
    return controls


def _evaluate_trade_risk_gate(
    *,
    symbol_pair: str,
    side: str,
    quantity: float,
    current_price: Optional[float],
    latest_prediction: Optional[Dict[str, Any]],
    risk: Optional[Dict[str, Any]],
    position_snapshot: Optional[Dict[str, Any]],
    policy: Optional[Dict[str, float]] = None,
    enforce_book_checks: bool = True,
    enforce_signal_gate: bool = True,
) -> Dict[str, Any]:
    policy = dict(policy or {})
    decision = str((risk or {}).get("decision") or (latest_prediction or {}).get("action_decision") or (latest_prediction or {}).get("decision") or "HOLD").strip().upper() or "HOLD"
    signal_tradeable = bool((risk or {}).get("tradeable")) if risk is not None else decision in {"BUY", "SELL"}
    side_norm = str(side or "").strip().upper()
    qty = max(0.0, float(quantity or 0.0))
    current_px = max(0.0, float(_optional_float(current_price) or 0.0))
    position = float((position_snapshot or {}).get("position") or 0.0)
    avg_price = _optional_float((position_snapshot or {}).get("avg_price"))
    exposure_basis = current_px if current_px > 0 else max(0.0, avg_price or 0.0)
    current_exposure_quote = max(0.0, abs(position) * exposure_basis)
    order_notional = _optional_float((risk or {}).get("order_notional")) or (qty * exposure_basis if exposure_basis > 0 else 0.0)
    order_size_pct = _optional_float((risk or {}).get("order_size_pct")) or 0.0
    visible_liquidity_notional = _optional_float((risk or {}).get("visible_liquidity_notional")) or 0.0
    sign = 1.0 if side_norm == "BUY" else -1.0
    post_position = position + sign * qty
    post_exposure_quote = max(0.0, abs(post_position) * exposure_basis)
    risk_reducing = bool(position and abs(post_position) + 1e-12 < abs(position))
    latest_present = latest_prediction is not None
    operator_guidance = _prediction_operator_guidance(latest_prediction)
    calibration_controls = dict(_trade_calibration_controls(operator_guidance) or {}) or None
    operator_guidance_status = _operator_guidance_status(operator_guidance)
    operator_guidance_reason = "not_available"
    operator_guidance_ok = True
    if operator_guidance_status:
        if _should_calibration_abstain(operator_guidance) and not risk_reducing:
            operator_guidance_ok = False
            operator_guidance_reason = "calibration_abstain"
        elif operator_guidance_status == "downgrade":
            operator_guidance_reason = "calibration_downgrade"
        else:
            operator_guidance_reason = f"calibration_{operator_guidance_status}"

    calibration_max_order_size_pct = _optional_float(
        (calibration_controls or {}).get("max_order_size_pct") if isinstance(calibration_controls, dict) else None
    )
    calibration_max_order_notional: Optional[float] = None
    calibration_max_quantity: Optional[float] = None
    calibration_reduction_pct: Optional[float] = None
    calibration_basis: Optional[str] = None
    if calibration_max_order_size_pct is not None and calibration_max_order_size_pct > 0:
        if visible_liquidity_notional > 0:
            calibration_max_order_notional = visible_liquidity_notional * (calibration_max_order_size_pct / 100.0)
            calibration_basis = "visible_liquidity_notional"
        elif order_size_pct > 0 and order_notional > 0:
            calibration_max_order_notional = order_notional * (calibration_max_order_size_pct / order_size_pct)
            calibration_basis = "order_size_pct"
        if calibration_max_order_notional is not None and order_notional > 0 and qty > 0:
            sizing_ratio = max(0.0, min(1.0, calibration_max_order_notional / order_notional))
            calibration_max_quantity = qty * sizing_ratio
            calibration_reduction_pct = max(0.0, 1.0 - sizing_ratio)
        if isinstance(calibration_controls, dict):
            calibration_controls["max_order_notional"] = round(calibration_max_order_notional, 2) if calibration_max_order_notional is not None else None
            calibration_controls["max_quantity"] = round(calibration_max_quantity, 8) if calibration_max_quantity is not None else None
            calibration_controls["recommended_reduction_pct"] = round(calibration_reduction_pct, 6) if calibration_reduction_pct is not None else None
            calibration_controls["sizing_basis"] = calibration_basis
    signal_ok = True
    signal_reason = "no_prediction"
    if latest_present:
        if risk_reducing:
            signal_ok = True
            signal_reason = "risk_reducing_exit"
        elif decision == "HOLD":
            signal_ok = False
            signal_reason = "signal_hold"
        elif decision != side_norm:
            signal_ok = False
            signal_reason = "signal_mismatch"
        else:
            signal_reason = "signal_aligned"

    checks: Dict[str, Dict[str, Any]] = {
        "signal_alignment": {
            "ok": signal_ok,
            "value": decision if latest_present else None,
            "reason": signal_reason,
        },
        "risk_reducing": {
            "ok": risk_reducing,
            "value": risk_reducing,
        },
        "position_quote": {
            "ok": True,
            "value": round(current_exposure_quote, 2),
        },
        "post_position_quote": {
            "ok": True,
            "value": round(post_exposure_quote, 2),
        },
        "operator_guidance": {
            "ok": operator_guidance_ok,
            "value": operator_guidance_status or None,
            "reason": operator_guidance_reason,
            "action": (calibration_controls or {}).get("action") if isinstance(calibration_controls, dict) else None,
            "reasons": (calibration_controls or {}).get("reasons") if isinstance(calibration_controls, dict) else [],
        },
    }
    blocked_checks: List[str] = []
    blocked_reason: Optional[str] = None

    def _block(name: str, reason: str, *, value: Any = None, threshold: Any = None) -> None:
        nonlocal blocked_reason
        existing = checks.get(name) if isinstance(checks.get(name), dict) else {}
        checks[name] = {
            **existing,
            "ok": False,
            "value": value,
            "threshold": threshold,
            "reason": reason,
        }
        blocked_checks.append(name)
        if blocked_reason is None:
            blocked_reason = reason

    if not risk_reducing and _should_calibration_abstain(operator_guidance):
        _block(
            "operator_guidance",
            "calibration_abstain",
            value=operator_guidance_status or None,
            threshold=(calibration_controls or {}).get("action") if isinstance(calibration_controls, dict) else None,
        )

    if not risk_reducing and calibration_max_order_notional is not None and order_notional > calibration_max_order_notional:
        _block(
            "calibration_order_notional",
            "calibration_size_reduction_required",
            value=round(order_notional, 2),
            threshold=round(calibration_max_order_notional, 2),
        )
    if not risk_reducing and calibration_max_quantity is not None and qty > calibration_max_quantity:
        _block(
            "calibration_quantity",
            "calibration_size_reduction_required",
            value=round(qty, 8),
            threshold=round(calibration_max_quantity, 8),
        )
    elif not risk_reducing and calibration_max_order_size_pct is not None and order_size_pct > calibration_max_order_size_pct:
        _block(
            "calibration_order_size_pct",
            "calibration_size_reduction_required",
            value=round(order_size_pct, 4),
            threshold=round(calibration_max_order_size_pct, 4),
        )

    if enforce_signal_gate and latest_present and not signal_ok:
        _block("signal_alignment", signal_reason, value=decision, threshold=side_norm)

    if not risk_reducing:
        max_order_notional = _optional_float(policy.get("max_order_notional"))
        if max_order_notional is not None and max_order_notional > 0 and order_notional > max_order_notional:
            _block("max_order_notional", "order_notional_too_large", value=round(order_notional, 2), threshold=round(max_order_notional, 2))

    max_exposure_quote = _optional_float(policy.get("max_exposure_quote"))
    if max_exposure_quote is not None and max_exposure_quote > 0 and post_exposure_quote > max_exposure_quote:
        _block("max_exposure_quote", "exposure_too_large", value=round(post_exposure_quote, 2), threshold=round(max_exposure_quote, 2))

    if not risk_reducing:
        max_order_size_pct = _optional_float(policy.get("max_order_size_pct"))
        if max_order_size_pct is not None and max_order_size_pct > 0:
            if order_size_pct > max_order_size_pct:
                _block("max_order_size_pct", "book_consumption_too_large", value=round(order_size_pct, 4), threshold=round(max_order_size_pct, 4))

        if enforce_book_checks and risk:
            max_book_consumption_pct = _optional_float(policy.get("max_book_consumption_pct"))
            if max_book_consumption_pct is not None and max_book_consumption_pct > 0:
                book_consumption_pct = _optional_float((risk or {}).get("book_consumption_pct")) or 0.0
                if book_consumption_pct > max_book_consumption_pct:
                    _block("max_book_consumption_pct", "book_consumption_too_large", value=round(book_consumption_pct, 4), threshold=round(max_book_consumption_pct, 4))

            max_spread_bps = _optional_float(policy.get("max_spread_bps"))
            if max_spread_bps is not None and max_spread_bps > 0:
                spread_bps = _optional_float((risk or {}).get("spread_bps")) or 0.0
                if spread_bps > max_spread_bps:
                    _block("max_spread_bps", "spread_too_wide", value=round(spread_bps, 2), threshold=round(max_spread_bps, 2))

            max_impact_score = _optional_float(policy.get("max_impact_score"))
            if max_impact_score is not None and max_impact_score > 0:
                impact_score = _optional_float((risk or {}).get("impact_score")) or 0.0
                if impact_score > max_impact_score:
                    _block("max_impact_score", "impact_too_high", value=round(impact_score, 2), threshold=round(max_impact_score, 2))

            max_drag_pct = _optional_float(policy.get("max_execution_drag_pct"))
            if max_drag_pct is not None and max_drag_pct > 0:
                drag_pct = _optional_float((risk or {}).get("execution_drag_pct")) or 0.0
                if drag_pct > max_drag_pct:
                    _block("max_execution_drag_pct", "execution_drag_too_high", value=round(drag_pct, 6), threshold=round(max_drag_pct, 6))

            min_rr = _optional_float(policy.get("min_risk_reward"))
            if min_rr is not None and min_rr > 0:
                risk_reward = _optional_float((risk or {}).get("risk_reward"))
                if risk_reward is not None and risk_reward > 0 and risk_reward < min_rr:
                    _block("min_risk_reward", "risk_reward_too_low", value=round(risk_reward, 2), threshold=round(min_rr, 2))

    allowed = not blocked_checks
    reason = blocked_reason or ("risk_reducing_exit" if risk_reducing else "ok")
    return {
        "allowed": allowed,
        "reason": reason,
        "decision": decision,
        "signal_ok": signal_ok,
        "signal_reason": signal_reason,
        "risk_reducing": risk_reducing,
        "current_position": round(position, 8),
        "current_exposure_quote": round(current_exposure_quote, 2),
        "post_trade_exposure_quote": round(post_exposure_quote, 2),
        "order_notional": round(order_notional, 2),
        "quantity": round(qty, 8),
        "side": side_norm,
        "symbol": symbol_pair,
        "checks": checks,
        "blocked_checks": blocked_checks,
        "policy": policy,
        "operator_guidance": operator_guidance,
        "calibration_controls": calibration_controls,
    }


def _build_trade_preview(
    *,
    order: TradeRequest,
    horizon_minutes: Optional[int] = None,
    regime: Optional[str] = None,
    use_order_book: bool = True,
) -> Dict[str, Any]:
    if order.quantity <= 0:
        raise HTTPException(status_code=400, detail="quantity must be > 0")

    symbol_pair = _normalize_binance_pair(order.symbol)
    if not symbol_pair:
        raise HTTPException(status_code=400, detail="Missing symbol")

    requested_mode = order.execution_mode or ("testnet" if order.test else None) or os.getenv("BINANCE_EXECUTION_MODE", "simulated")
    exec_snapshot = _crypto_execution_snapshot(requested_mode=requested_mode)
    execution_mode = exec_snapshot["mode"]
    api_key = (os.getenv("BINANCE_API_KEY") or "").strip()
    api_secret = (os.getenv("BINANCE_API_SECRET") or "").strip()
    live_trading_enabled = (os.getenv("BINANCE_LIVE_TRADING", "0") or "0").strip().lower() in {"1", "true", "yes", "on"}
    if execution_mode == "live" and not (api_key and api_secret and live_trading_enabled):
        execution_mode = "simulated"
    if execution_mode == "testnet" and not (api_key and api_secret):
        execution_mode = "simulated"

    price_live = _binance_spot_price(symbol_pair)
    mid_price = float(price_live if price_live is not None else (100 + (hash(symbol_pair) % 500)))
    execution_profile = _execution_profile(
        symbol_pair=symbol_pair,
        side=order.side,
        quantity=order.quantity,
        mid_price=mid_price,
        execution_mode=execution_mode,
    )
    preview_trade = {
        "symbol": symbol_pair,
        "side": order.side,
        "quantity": order.quantity,
        "price": execution_profile.get("fill_price"),
        "mid_price": execution_profile.get("mid_price"),
        "fill_price": execution_profile.get("fill_price"),
        "spread_bps": execution_profile.get("spread_bps"),
        "slippage_bps": execution_profile.get("slippage_bps"),
        "impact_bps": execution_profile.get("impact_bps"),
        "liquidity_bucket": execution_profile.get("liquidity_bucket"),
        "notional": execution_profile.get("notional"),
        "execution_note": execution_profile.get("execution_note"),
        "execution_mode": execution_mode,
        "status": "SIMULATED",
    }

    scope_snapshot = build_crypto_state_snapshot(
        symbol=symbol_pair,
        horizon_minutes=horizon_minutes,
        regime=regime,
        limit=5,
        trade_limit=20,
        price_lookup=_binance_spot_price,
        order_book_lookup=(lambda sym: _binance_order_book(sym, limit=10)) if use_order_book else None,
        execution_snapshot=exec_snapshot,
    )
    latest_prediction = scope_snapshot.get("latest_prediction") if isinstance(scope_snapshot, dict) else None
    risk = _risk_snapshot(
        latest_prediction=latest_prediction if isinstance(latest_prediction, dict) else None,
        latest_trade=preview_trade,
        current_price=mid_price,
        execution_snapshot=exec_snapshot,
        trade_side=order.side,
        order_book_snapshot=(scope_snapshot or {}).get("order_book") if isinstance(scope_snapshot, dict) else None,
    )

    entry_price = _optional_float((risk or {}).get("entry_price")) or float(execution_profile.get("fill_price"))
    predicted_price = _optional_float((risk or {}).get("predicted_price"))
    target_price = _optional_float((risk or {}).get("target_price"))
    stop_price = _optional_float((risk or {}).get("stop_price"))
    qty = float(order.quantity)
    position_snapshot = _position_snapshot_from_pnl(
        symbol_pair=symbol_pair,
        current_price=entry_price,
        pnl=(scope_snapshot or {}).get("pnl") if isinstance(scope_snapshot, dict) else None,
        trades_count=len((scope_snapshot or {}).get("trades") or []) if isinstance(scope_snapshot, dict) else 0,
    )
    risk_gate = _evaluate_trade_risk_gate(
        symbol_pair=symbol_pair,
        side=order.side,
        quantity=qty,
        current_price=entry_price,
        latest_prediction=latest_prediction if isinstance(latest_prediction, dict) else None,
        risk=risk,
        position_snapshot=position_snapshot,
        policy=_crypto_risk_policy(order),
        enforce_book_checks=use_order_book,
        enforce_signal_gate=False,
    )

    expected_gain_quote = None
    expected_loss_quote = None
    if predicted_price is not None and entry_price > 0:
        if order.side == "BUY":
            expected_gain_quote = max(0.0, (predicted_price - entry_price) * qty)
        else:
            expected_gain_quote = max(0.0, (entry_price - predicted_price) * qty)
    if stop_price is not None and entry_price > 0:
        if order.side == "BUY":
            expected_loss_quote = max(0.0, (entry_price - stop_price) * qty)
        else:
            expected_loss_quote = max(0.0, (stop_price - entry_price) * qty)

    latest_prediction_ref = scope_snapshot.get("latest_prediction_ref") if isinstance(scope_snapshot, dict) else None
    return {
        "symbol": symbol_pair,
        "side": order.side,
        "quantity": order.quantity,
        "price": execution_profile.get("fill_price"),
        "mid_price": execution_profile.get("mid_price"),
        "fill_price": execution_profile.get("fill_price"),
        "spread_bps": execution_profile.get("spread_bps"),
        "slippage_bps": execution_profile.get("slippage_bps"),
        "impact_bps": execution_profile.get("impact_bps"),
        "liquidity_bucket": execution_profile.get("liquidity_bucket"),
        "notional": execution_profile.get("notional"),
        "execution_note": execution_profile.get("execution_note"),
        "execution_mode": execution_mode,
        "requested_mode": exec_snapshot.get("mode") if isinstance(exec_snapshot, dict) else None,
        "horizon_minutes": horizon_minutes,
        "regime": regime,
        "current_price": mid_price,
        "predicted_price": predicted_price,
        "signal_decision": str((latest_prediction or {}).get("action_decision") or (latest_prediction or {}).get("decision") or "HOLD").strip().upper() or "HOLD",
        "signal_probability_up": _optional_float((latest_prediction or {}).get("probability_up")),
        "entry_price": entry_price,
        "target_price": target_price,
        "stop_price": stop_price,
        "expected_gain_quote": round(expected_gain_quote, 2) if expected_gain_quote is not None else None,
        "expected_loss_quote": round(expected_loss_quote, 2) if expected_loss_quote is not None else None,
        "expected_pnl_pct": _optional_float((risk or {}).get("expected_pnl_pct")),
        "risk_reward": _optional_float((risk or {}).get("risk_reward")),
        "projected_move_pct": _optional_float((risk or {}).get("projected_move_pct")),
        "execution_drag_pct": _optional_float((risk or {}).get("execution_drag_pct")),
        "confidence": _optional_float((risk or {}).get("confidence")),
        "confidence_bucket": str((risk or {}).get("confidence_bucket") or "").strip() or None,
        "order_notional": _optional_float((risk or {}).get("order_notional")),
        "visible_liquidity_notional": _optional_float((risk or {}).get("visible_liquidity_notional")),
        "side_liquidity_notional": _optional_float((risk or {}).get("side_liquidity_notional")),
        "order_size_pct": _optional_float((risk or {}).get("order_size_pct")),
        "book_consumption_pct": _optional_float((risk or {}).get("book_consumption_pct")),
        "participation_pct": _optional_float((risk or {}).get("participation_pct")),
        "others_pct": _optional_float((risk or {}).get("others_pct")),
        "remaining_liquidity": _optional_float((risk or {}).get("remaining_liquidity")),
        "pre_trade_price": _optional_float((risk or {}).get("pre_trade_price")),
        "post_trade_estimate": _optional_float((risk or {}).get("post_trade_estimate")),
        "impact_score": _optional_float((risk or {}).get("impact_score")),
        "net_expected_profit_after_costs_pct": _optional_float((risk or {}).get("net_expected_profit_after_costs_pct")),
        "net_expected_profit_after_costs_quote": _optional_float((risk or {}).get("net_expected_profit_after_costs_quote")),
        "prediction_ref": latest_prediction_ref,
        "risk": risk,
        "risk_gate": risk_gate,
        "preview_only": True,
    }


def _crypto_policy_snapshot(
    *,
    symbol: str,
    horizon_minutes: int,
    regime: Optional[str],
    prediction_engine: str,
    model_used: str,
    model_decision: str,
    action_decision: str,
    p_up: float,
    buy_threshold: float,
    sell_threshold: float,
    credibility: Optional[Dict[str, Any]],
    operator_guidance: Optional[Dict[str, Any]],
    consensus_metrics: Optional[Dict[str, Any]],
    threshold_rec: Optional[Dict[str, Any]],
    require_trained: bool,
    execution_margin: Optional[float] = None,
    consensus_requirements: Optional[Dict[str, float]] = None,
    execution_gate_reason: Optional[str] = None,
    adaptive_policy: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    confidence = max(0.0, min(1.0, max(p_up, 1.0 - p_up)))
    if confidence >= 0.8:
        confidence_bucket = "high"
    elif confidence >= 0.62:
        confidence_bucket = "medium"
    else:
        confidence_bucket = "low"

    operator_status = _operator_guidance_status(operator_guidance)
    if execution_margin is None:
        execution_margin = _effective_execution_margin(credibility, operator_guidance)
    if consensus_requirements is None:
        consensus_requirements = _effective_consensus_requirements(credibility, operator_guidance)

    route_mode = "trained" if prediction_engine == "trained" else "demo"
    route_reason = "trained_model_available" if prediction_engine == "trained" else "demo_fallback"
    if require_trained and prediction_engine != "trained":
        route_reason = "trained_required_unavailable"
    elif isinstance(credibility, dict) and bool(credibility.get("should_abstain")):
        route_reason = "credibility_abstain"
    elif _should_calibration_abstain(operator_guidance):
        route_reason = "calibration_abstain"
    elif execution_gate_reason:
        route_reason = execution_gate_reason
    elif action_decision in {"BUY", "SELL"} and threshold_rec:
        route_reason = "threshold_edge_passed"
    elif action_decision == "HOLD" and model_decision in {"BUY", "SELL"}:
        route_reason = "calibration_downgrade" if operator_status == "downgrade" else str((credibility or {}).get("status") or "gated")

    return {
        "symbol": symbol,
        "horizon_minutes": horizon_minutes,
        "regime": regime,
        "route_mode": route_mode,
        "route_reason": route_reason,
        "model_used": model_used,
        "model_decision": model_decision,
        "action_decision": action_decision,
        "actionable": action_decision in {"BUY", "SELL"},
        "confidence": confidence,
        "confidence_bucket": confidence_bucket,
        "thresholds": {
            "buy": buy_threshold,
            "sell": sell_threshold,
            "threshold_strategy": threshold_rec,
        },
        "credibility": credibility,
        "operator_guidance": operator_guidance,
        "should_abstain": _effective_should_abstain(credibility, operator_guidance),
        "consensus": consensus_metrics,
        "gates": {
            "execution_margin": execution_margin,
            "calibration_margin": _calibration_margin_for_operator_guidance(operator_guidance),
            "required_support_ratio": (consensus_requirements or {}).get("min_support_ratio"),
            "required_max_spread": (consensus_requirements or {}).get("max_spread"),
        },
        "policy_profile": _crypto_policy_profile(),
        "adaptive_policy": adaptive_policy,
    }




def _crypto_default_threshold_strategy() -> Dict[str, Any]:
    return {
        "buy_threshold": CRYPTO_DEFAULT_BUY_THRESHOLD,
        "sell_threshold": CRYPTO_DEFAULT_SELL_THRESHOLD,
        "count": 0,
        "trade_count": 0,
        "hold_count": 0,
        "hold_rate": None,
        "precision": None,
        "gross_expectancy_pct": None,
        "net_expectancy_pct": None,
        "positive_net_rate": None,
        "max_drawdown_pct": None,
        "round_trip_cost_pct": None,
        "score": None,
    }


def _best_crypto_leaderboard_candidate(
    rows: List[Dict[str, Any]],
    *,
    symbol: str,
    horizon_minutes: int,
    regime: Optional[str],
) -> tuple[Optional[Dict[str, Any]], str]:
    if not rows:
        return None, "none"
    sym = (symbol or "").strip().upper()
    horizon = int(horizon_minutes)
    regime_norm = str(regime or "").strip().lower() or "unknown"

    def _match(candidate: Dict[str, Any], *, require_regime: bool) -> bool:
        if str(candidate.get("symbol") or "").strip().upper() != sym:
            return False
        try:
            if int(candidate.get("horizon_minutes") or 0) != horizon:
                return False
        except Exception:
            return False
        if require_regime:
            cand_regime = str(candidate.get("regime") or "unknown").strip().lower() or "unknown"
            return cand_regime == regime_norm
        return True

    exact = [row for row in rows if _match(row, require_regime=True)]
    if exact:
        return exact[0], "exact_scope"
    horizon_match = [row for row in rows if _match(row, require_regime=False)]
    if horizon_match:
        return horizon_match[0], "symbol_horizon"
    symbol_match = [row for row in rows if str(row.get("symbol") or "").strip().upper() == sym]
    if symbol_match:
        return symbol_match[0], "symbol_only"
    return rows[0], "global"


def _adaptive_crypto_performance_snapshot(
    *,
    symbol: str,
    horizon_minutes: int,
    regime: Optional[str],
    engine: Optional[str],
    limit: int,
    fee_bps: float,
    slippage_bps: float,
) -> Dict[str, Any]:
    stats = recent_stats(
        limit=limit,
        symbol=symbol,
        engine=engine,
        horizon_minutes=horizon_minutes,
        regime=regime,
        fee_bps=fee_bps,
        slippage_bps=slippage_bps,
    )
    return {
        "count": stats.get("count"),
        "accuracy": stats.get("accuracy"),
        "trade_count": stats.get("trade_count"),
        "positive_net_rate": stats.get("positive_net_rate"),
        "net_expectancy_pct": stats.get("net_expectancy_pct"),
        "max_drawdown_pct": stats.get("max_drawdown_pct"),
        "trained_count": stats.get("trained_count"),
        "demo_count": stats.get("demo_count"),
        "trained_accuracy": stats.get("trained_accuracy"),
        "demo_accuracy": stats.get("demo_accuracy"),
        "engine_filter": stats.get("engine_filter"),
        "horizon_filter": stats.get("horizon_filter"),
        "regime_filter": stats.get("regime_filter"),
    }


def _adaptive_crypto_threshold_strategy(
    *,
    symbol: str,
    horizon_minutes: int,
    regime: Optional[str],
    limit: int,
    engine: Optional[str] = "trained",
    fee_bps: float = 10.0,
    slippage_bps: float = 5.0,
    min_trades: int = CRYPTO_THRESHOLD_MIN_TRADES,
    include_preview: bool = False,
) -> Dict[str, Any]:
    recommendation = optimize_thresholds(
        limit=limit,
        symbol=symbol,
        engine=engine,
        horizon_minutes=horizon_minutes,
        regime=regime,
        fee_bps=fee_bps,
        slippage_bps=slippage_bps,
        min_trades=min_trades,
    )
    leaderboard_preview: List[Dict[str, Any]] = []
    champion: Optional[Dict[str, Any]] = None
    champion_scope = "none"
    strategy_source = "exact_scope" if recommendation is not None else "defaults"
    fallback_used = recommendation is None

    if include_preview or recommendation is None:
        leaderboard_preview = scope_leaderboard(
            limit=limit,
            engine=engine,
            fee_bps=fee_bps,
            slippage_bps=slippage_bps,
            min_trades=min_trades,
            top_n=3,
        )
        if recommendation is None and leaderboard_preview:
            champion, champion_scope = _best_crypto_leaderboard_candidate(
                leaderboard_preview,
                symbol=symbol,
                horizon_minutes=horizon_minutes,
                regime=regime,
            )
            if champion is not None:
                recommendation = dict(champion)
                strategy_source = f"leaderboard:{champion_scope}"
                fallback_used = True

    if recommendation is None:
        recommendation = _crypto_default_threshold_strategy()

    return {
        "selected_strategy": recommendation,
        "strategy_source": strategy_source,
        "fallback_used": fallback_used,
        "champion": champion,
        "champion_scope": champion_scope,
        "leaderboard_preview": leaderboard_preview,
        "performance": (
            _adaptive_crypto_performance_snapshot(
                symbol=symbol,
                horizon_minutes=horizon_minutes,
                regime=regime,
                engine=engine,
                limit=limit,
                fee_bps=fee_bps,
                slippage_bps=slippage_bps,
            )
            if include_preview
            else None
        ),
    }


def _upsert_news_items(symbol: str, items: List[dict], window_minutes: int = 120) -> int:
    """Persist fetched news into DB store when available (best-effort)."""
    try:
        from app.services.news_store import upsert_news_items

        return upsert_news_items(symbol, items, window_minutes=window_minutes)
    except Exception:
        return 0


def _fetch_recent_news(symbol: str, minutes: int = 90, limit: int = 12) -> List[dict]:
    """Read recent persisted news for context enrichment (best-effort)."""
    try:
        from app.services.news_store import fetch_recent_news

        return fetch_recent_news(symbol, minutes=minutes, limit=limit)
    except Exception:
        return []


def _get_pandas():
    """Lazy-load pandas so import failures don't break API startup."""
    global _pd
    if _pd is not None:
        return _pd
    try:
        import pandas as pd  # type: ignore

        _pd = pd
        return _pd
    except Exception:  # pragma: no cover
        return None


def _get_meta_module():
    """Lazy-load optional meta analytics module."""
    global _meta_module
    if _meta_module is not None:
        return _meta_module
    try:
        from app.core import meta as meta_mod  # type: ignore

        _meta_module = meta_mod
        return _meta_module
    except Exception:  # pragma: no cover
        return None

router = APIRouter(prefix="/crypto", tags=["crypto"], dependencies=[Depends(require_api_key)])
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Binance helpers
# ---------------------------------------------------------------------------

PRICE_CACHE_TTL = float(os.getenv("BINANCE_PRICE_CACHE_TTL", "8") or "8")
_price_cache: Dict[str, tuple[float, float]] = {}
_price_source: Dict[str, str] = {}
_price_lock = threading.Lock()
_ALLOWED_BINANCE_QUOTES = ("USDT", "USDC", "BUSD", "FDUSD", "TUSD", "BTC", "ETH")
_BINANCE_PAIR_RE = re.compile(r"[A-Z]{2,12}(USDT|USDC|BUSD|FDUSD|TUSD|BTC|ETH)")
_BASE_SYMBOL_RE = re.compile(r"[A-Z0-9]{2,12}")
_BASE_SYMBOL_ALIASES = {
    "BITCOIN": "BTC",
    "BITCOINCASH": "BCH",
    "ETHEREUM": "ETH",
    "BINANCECOIN": "BNB",
    "SOLANA": "SOL",
    "RIPPLE": "XRP",
    "CARDANO": "ADA",
    "DOGECOIN": "DOGE",
    "LITECOIN": "LTC",
    "POLKADOT": "DOT",
    "POLYGON": "MATIC",
    "POLYGONECOSYSTEMTOKEN": "MATIC",
    "TRON": "TRX",
    "AVALANCHE": "AVAX",
    "CHAINLINK": "LINK",
    "UNISWAP": "UNI",
    "FILECOIN": "FIL",
    "HEDERA": "HBAR",
    "INTERNETCOMPUTER": "ICP",
    "RENDER": "RNDR",
    "THEGRAPH": "GRT",
    "FETCHAI": "FET",
    "WORLDCOIN": "WLD",
    "ARBITRUM": "ARB",
    "OPTIMISM": "OP",
    "SHIBAINU": "SHIB",
    "BONKINU": "BONK",
    "PYTHNETWORK": "PYTH",
    "JUPITER": "JUP",
}

_POPULAR_BINANCE_PAIRS: tuple[str, ...] = (
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT", "DOGEUSDT", "AVAXUSDT", "DOTUSDT", "TRXUSDT",
    "LINKUSDT", "LTCUSDT", "ATOMUSDT", "ETCUSDT", "XLMUSDT", "BCHUSDT", "APTUSDT", "ARBUSDT", "OPUSDT", "SUIUSDT",
    "NEARUSDT", "AAVEUSDT", "UNIUSDT", "XMRUSDT", "FILUSDT", "ALGOUSDT", "XTZUSDT", "MKRUSDT", "INJUSDT", "RUNEUSDT",
    "KASUSDT", "IMXUSDT", "TIAUSDT", "WIFUSDT", "PEPEUSDT", "SHIBUSDT", "BONKUSDT", "SEIUSDT", "STXUSDT", "THETAUSDT",
    "ICPUSDT", "RNDRUSDT", "GRTUSDT", "SANDUSDT", "MANAUSDT", "ENJUSDT", "EOSUSDT", "EGLDUSDT", "VETUSDT", "HBARUSDT",
    "QNTUSDT", "LDOUSDT", "JUPUSDT", "JTOUSDT", "PYTHUSDT", "FETUSDT", "WLDUSDT", "CRVUSDT", "COMPUSDT", "SNXUSDT",
    "FTMUSDT", "GALAUSDT", "DYDXUSDT", "ARUSDT", "AXSUSDT", "PENDLEUSDT", "ONDOUSDT", "STRKUSDT", "1INCHUSDT", "IOTAUSDT",
    "KAVAUSDT", "ZRXUSDT", "CAKEUSDT", "CELOUSDT", "GMXUSDT", "FLOWUSDT",
)

# ACTIVATE REAL TIME DATA "1"
def _binance_base_url() -> str:
    live = os.getenv("BINANCE_LIVE", "1").lower() in {"1", "true", "yes"}
    return "https://api.binance.com" if live else "https://testnet.binance.vision"


def _coingecko_id(sym: str) -> Optional[str]:
    sym = sym.lower()
    mapping = {
        "btc": "bitcoin",
        "eth": "ethereum",
        "bnb": "binancecoin",
        "sol": "solana",
        "ada": "cardano",
        "xrp": "ripple",
        "doge": "dogecoin",
        "dot": "polkadot",
        "matic": "polygon",
        "ltc": "litecoin",
    }
    return mapping.get(sym)


def _coingecko_spot_price(symbol: str) -> Optional[float]:
    cid = _coingecko_id(symbol)
    if not cid:
        return None
    try:
        resp = requests.get(
            "https://api.coingecko.com/api/v3/simple/price",
            params={"ids": cid, "vs_currencies": "usd"},
            timeout=6,
        )
        resp.raise_for_status()
        data = resp.json()
        val = data.get(cid, {}).get("usd")
        return float(val) if val is not None else None
    except Exception as exc:  # noqa: BLE001
        logger.warning("CoinGecko price fetch failed for %s: %s", symbol, exc)
        return None


def _normalize_binance_pair(symbol: str) -> str:
    raw = (symbol or "").upper().strip().replace("/", "")
    raw = re.sub(r"[^A-Z0-9]", "", raw)
    if not raw:
        return ""
    raw = _BASE_SYMBOL_ALIASES.get(raw, raw)
    if _BINANCE_PAIR_RE.fullmatch(raw):
        return raw
    for quote in _ALLOWED_BINANCE_QUOTES:
        if raw.endswith(quote) and len(raw) > len(quote):
            base = raw[: -len(quote)]
            if _BASE_SYMBOL_RE.fullmatch(base):
                return f"{base}{quote}"
    if _BASE_SYMBOL_RE.fullmatch(raw):
        return f"{raw}USDT"
    return f"{raw}USDT"


def _binance_spot_price(symbol: str) -> Optional[float]:
    pair = _normalize_binance_pair(symbol)
    if not pair:
        return None
    now = time.time()
    if PRICE_CACHE_TTL > 0:
        with _price_lock:
            cached = _price_cache.get(pair)
        if cached and now - cached[1] <= PRICE_CACHE_TTL:
            return cached[0]
    price_val: Optional[float] = None
    source = None
    try:
        resp = requests.get(
            f"{_binance_base_url()}/api/v3/ticker/price",
            params={"symbol": pair},
            timeout=6,
        )
        resp.raise_for_status()
        data = resp.json()
        price_str = data.get("price") or data.get("lastPrice")
        price_val = float(price_str) if price_str is not None else None
        source = "binance"
    except Exception as exc:  # noqa: BLE001
        logger.warning("Binance price fetch failed for %s: %s", pair, exc)

    if price_val is None:
        price_val = _coingecko_spot_price(pair.replace("USDT", ""))
        if price_val is not None:
            source = "coingecko"

    if price_val is None and PRICE_CACHE_TTL > 0:
        with _price_lock:
            cached = _price_cache.get(pair)
        if cached:
            _price_source[pair] = "cache"
            return cached[0]

    if price_val is not None and PRICE_CACHE_TTL > 0:
        with _price_lock:
            _price_cache[pair] = (price_val, now)
        if source:
            _price_source[pair] = source
    return price_val


def _binance_ohlcv_window(
    symbol: str,
    *,
    interval: str,
    limit: int,
) -> List[OhlcvItem]:
    sym = _normalize_binance_pair(symbol)
    if not sym:
        return []
    try:
        resp = requests.get(
            f"{_binance_base_url()}/api/v3/klines",
            params={"symbol": sym, "interval": interval, "limit": limit},
            timeout=8,
        )
        resp.raise_for_status()
        raw = resp.json()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Binance OHLCV window fetch failed for %s %s: %s", sym, interval, exc)
        return []
    series: List[OhlcvItem] = []
    for item in raw:
        try:
            series.append(
                OhlcvItem(
                    ts=int(item[6]),
                    open=float(item[1]),
                    high=float(item[2]),
                    low=float(item[3]),
                    close=float(item[4]),
                    volume=float(item[5]),
                )
            )
        except Exception:
            continue
    return series


def _binance_order_book(symbol: str, *, limit: int = 10) -> Optional[Dict[str, Any]]:
    sym = _normalize_binance_pair(symbol)
    if not sym:
        return None
    depth_limit = max(5, min(int(limit or 10), 50))
    raw: Optional[Dict[str, Any]] = None
    source = "binance"
    try:
        resp = requests.get(
            f"{_binance_base_url()}/api/v3/depth",
            params={"symbol": sym, "limit": depth_limit},
            timeout=8,
        )
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, dict):
            raw = data
    except Exception as exc:  # noqa: BLE001
        logger.warning("Binance depth fetch failed for %s: %s", sym, exc)

    def _parse_levels(levels: Any) -> List[Dict[str, Any]]:
        parsed: List[Dict[str, Any]] = []
        for row in list(levels or [])[:depth_limit]:
            try:
                price = float(row[0])
                qty = float(row[1])
            except Exception:
                continue
            parsed.append(
                {
                    "price": round(price, 2),
                    "qty": round(qty, 8),
                    "notional": round(price * qty, 2),
                }
            )
        return parsed

    bids = _parse_levels(raw.get("bids")) if raw else []
    asks = _parse_levels(raw.get("asks")) if raw else []
    if not bids or not asks:
        source = "synthetic"
        mid = float(_binance_spot_price(sym) or (100 + (hash(sym) % 500)))
        base_asset = _base_symbol_from_pair(sym)
        base_spread_bps = (
            4.5
            if base_asset in {"BTC", "ETH"}
            else 7.5
            if base_asset in {"BNB", "SOL", "XRP", "ADA", "DOGE", "LINK", "AVAX", "MATIC", "TRX"}
            else 11.5
        )
        rng = random.Random(hash(("depth", sym)))
        spread_bps = round(max(2.0, base_spread_bps + rng.uniform(-0.7, 1.6)), 2)
        best_bid = round(mid * (1.0 - (spread_bps / 2.0) / 10000.0), 2)
        best_ask = round(mid * (1.0 + (spread_bps / 2.0) / 10000.0), 2)
        total_quote = 0.0
        if base_asset in {"BTC", "ETH"}:
            total_quote = 10000.0
        elif base_asset in {"BNB", "SOL", "XRP", "ADA", "DOGE", "LINK", "AVAX", "MATIC", "TRX"}:
            total_quote = 6000.0
        else:
            total_quote = 3000.0

        bids = []
        asks = []
        for idx in range(depth_limit):
            decay = 0.88 ** idx
            bid_level_price = round(mid * (1.0 - ((spread_bps / 2.0) + idx * max(0.9, spread_bps * 0.28)) / 10000.0), 2)
            ask_level_price = round(mid * (1.0 + ((spread_bps / 2.0) + idx * max(0.9, spread_bps * 0.28)) / 10000.0), 2)
            bid_quote = total_quote * decay * rng.uniform(0.75, 1.2)
            ask_quote = total_quote * decay * rng.uniform(0.75, 1.2)
            bid_qty = round(max(0.0000001, bid_quote / max(bid_level_price, 1e-8)), 8)
            ask_qty = round(max(0.0000001, ask_quote / max(ask_level_price, 1e-8)), 8)
            bids.append({"price": bid_level_price, "qty": bid_qty, "notional": round(bid_level_price * bid_qty, 2)})
            asks.append({"price": ask_level_price, "qty": ask_qty, "notional": round(ask_level_price * ask_qty, 2)})
    else:
        best_bid = bids[0]["price"]
        best_ask = asks[0]["price"]
        mid = round((best_bid + best_ask) / 2.0, 2)
        spread_bps = round(((best_ask - best_bid) / mid) * 10000.0 if mid else 0.0, 2)

    bid_qty = round(sum(float(level["qty"]) for level in bids), 8)
    ask_qty = round(sum(float(level["qty"]) for level in asks), 8)
    bid_notional = round(sum(float(level["notional"]) for level in bids), 2)
    ask_notional = round(sum(float(level["notional"]) for level in asks), 2)
    imbalance = 0.5
    total_notional = bid_notional + ask_notional
    if total_notional > 0:
        imbalance = round(bid_notional / total_notional, 4)

    liquidity_bucket = _liquidity_bucket_for_notional(max(bid_notional, ask_notional, total_notional / 2.0))
    return {
        "symbol": sym,
        "source": source,
        "levels": depth_limit,
        "mid_price": round(float(mid), 2),
        "best_bid": round(float(best_bid), 2),
        "best_ask": round(float(best_ask), 2),
        "spread": round(float(best_ask - best_bid), 2),
        "spread_bps": round(float(spread_bps), 2),
        "imbalance": imbalance,
        "bid_qty": bid_qty,
        "ask_qty": ask_qty,
        "bid_notional": bid_notional,
        "ask_notional": ask_notional,
        "liquidity_bucket": liquidity_bucket,
        "bids": bids[:depth_limit],
        "asks": asks[:depth_limit],
        "note": (
            f"{source} order book • spread {spread_bps:.1f}bps • "
            f"imbalance {imbalance * 100:.1f}% bid side"
        ),
    }


def _interval_for_horizon(horizon_minutes: int) -> str:
    if horizon_minutes <= 15:
        return "1m"
    if horizon_minutes <= 60:
        return "5m"
    if horizon_minutes <= 240:
        return "15m"
    if horizon_minutes <= 1440:
        return "1h"
    return "4h"


def _binance_signed_request(
    *,
    method: str,
    path: str,
    params: Dict[str, Any],
    api_key: str,
    api_secret: str,
    base_url: Optional[str] = None,
) -> Dict[str, Any]:
    base = base_url or _binance_base_url()
    query = urlencode(params)
    signature = hmac.new(api_secret.encode(), query.encode(), hashlib.sha256).hexdigest()
    url = f"{base}{path}?{query}&signature={signature}"
    headers = {"X-MBX-APIKEY": api_key}

    try:
        resp = requests.request(method, url, headers=headers, timeout=10)
        resp.raise_for_status()
        return resp.json() if resp.text else {}
    except requests.HTTPError as exc:
        raise HTTPException(status_code=resp.status_code, detail=resp.text) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Binance request failed: {exc}") from exc


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class PredictRequest(BaseModel):
    symbol: str
    horizon_minutes: int = Field(default=15, ge=1, le=10080)
    model: str = "ensemble"
    save: bool = True
    require_trained: bool = False


class PredictResponse(BaseModel):
    symbol: str
    horizon_minutes: int
    current_price: Optional[float] = None
    predicted_price: Optional[float] = None
    probability_up: Optional[float] = None
    decision: Literal["BUY", "SELL", "HOLD"] = "HOLD"
    raw: Optional[Dict[str, Any]] = None
    additional_info: Optional[Dict[str, Any]] = None
    news: Optional[List[Dict[str, Any]]] = None


class OhlcvItem(BaseModel):
    ts: int
    open: float
    high: float
    low: float
    close: float
    volume: float


class TradeRequest(BaseModel):
    symbol: str
    side: Literal["BUY", "SELL"]
    quantity: float
    test: bool = True  # simulated by default
    execution_mode: Optional[Literal["simulated", "testnet", "live"]] = None
    stop_loss_pct: Optional[float] = None
    take_profit_pct: Optional[float] = None
    max_exposure_quote: Optional[float] = None
    max_order_notional: Optional[float] = None
    max_order_size_pct: Optional[float] = None
    max_impact_score: Optional[float] = None
    min_risk_reward: Optional[float] = None
    max_spread_bps: Optional[float] = None
    max_book_consumption_pct: Optional[float] = None


class TradeResponse(BaseModel):
    symbol: str
    side: Literal["BUY", "SELL"]
    quantity: float
    price: Optional[float]
    mid_price: Optional[float] = None
    fill_price: Optional[float] = None
    spread_bps: Optional[float] = None
    slippage_bps: Optional[float] = None
    impact_bps: Optional[float] = None
    liquidity_bucket: Optional[str] = None
    notional: Optional[float] = None
    execution_note: Optional[str] = None
    status: Literal["FILLED", "SENT_TO_EXCHANGE", "SIMULATED", "REJECTED"]
    ts: int
    execution_mode: Literal["simulated", "testnet", "live"] = "simulated"
    message: Optional[str] = None
    risk_gate: Optional[Dict[str, Any]] = None
    net_expected_profit_after_costs_pct: Optional[float] = None
    net_expected_profit_after_costs_quote: Optional[float] = None


class TradePreviewResponse(BaseModel):
    symbol: str
    side: Literal["BUY", "SELL"]
    quantity: float
    price: Optional[float] = None
    mid_price: Optional[float] = None
    fill_price: Optional[float] = None
    spread_bps: Optional[float] = None
    slippage_bps: Optional[float] = None
    impact_bps: Optional[float] = None
    liquidity_bucket: Optional[str] = None
    notional: Optional[float] = None
    execution_note: Optional[str] = None
    execution_mode: Literal["simulated", "testnet", "live"] = "simulated"
    requested_mode: Optional[Literal["simulated", "testnet", "live"]] = None
    horizon_minutes: Optional[int] = None
    regime: Optional[str] = None
    current_price: Optional[float] = None
    predicted_price: Optional[float] = None
    signal_decision: Optional[Literal["BUY", "SELL", "HOLD"]] = None
    signal_probability_up: Optional[float] = None
    entry_price: Optional[float] = None
    target_price: Optional[float] = None
    stop_price: Optional[float] = None
    expected_gain_quote: Optional[float] = None
    expected_loss_quote: Optional[float] = None
    expected_pnl_pct: Optional[float] = None
    risk_reward: Optional[float] = None
    projected_move_pct: Optional[float] = None
    execution_drag_pct: Optional[float] = None
    confidence: Optional[float] = None
    confidence_bucket: Optional[str] = None
    order_notional: Optional[float] = None
    visible_liquidity_notional: Optional[float] = None
    side_liquidity_notional: Optional[float] = None
    order_size_pct: Optional[float] = None
    book_consumption_pct: Optional[float] = None
    participation_pct: Optional[float] = None
    others_pct: Optional[float] = None
    remaining_liquidity: Optional[float] = None
    pre_trade_price: Optional[float] = None
    post_trade_estimate: Optional[float] = None
    impact_score: Optional[float] = None
    prediction_ref: Optional[Dict[str, Any]] = None
    risk: Optional[Dict[str, Any]] = None
    risk_gate: Optional[Dict[str, Any]] = None
    net_expected_profit_after_costs_pct: Optional[float] = None
    net_expected_profit_after_costs_quote: Optional[float] = None
    preview_only: bool = True


class TopCoin(BaseModel):
    id: str
    symbol: str
    name: str
    current_price: float
    market_cap: float
    price_change_percentage_24h: float


# ---------------------------------------------------------------------------
# Utils
# ---------------------------------------------------------------------------

def _is_valid_binance_symbol(sym: str) -> bool:
    return bool(_BINANCE_PAIR_RE.fullmatch((sym or "").upper()))


def resolve_trained_model(
    symbol: str,
    horizon_minutes: int,
    model_type: Optional[str],
) -> Optional[TrainedModel]:
    trained = discover_trained_models()
    symbol = symbol.upper()
    for m in trained:
        if m.symbol == symbol and m.horizon_minutes == horizon_minutes and (
            model_type is None or m.model_type == model_type
        ):
            return m
    for m in trained:
        if m.symbol == symbol and m.horizon_minutes == horizon_minutes:
            return m
    return None


def _base_symbol_from_pair(symbol_pair: str) -> str:
    upper = (symbol_pair or "").upper()
    for quote in _ALLOWED_BINANCE_QUOTES:
        if upper.endswith(quote) and len(upper) > len(quote):
            return upper[: -len(quote)]
    return upper


def _safe_read_json(path: Path) -> Optional[Dict[str, Any]]:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _artifact_sha256(path_value: Any) -> Optional[str]:
    raw = str(path_value or "").strip()
    if not raw:
        return None
    try:
        artifact_path = Path(raw).resolve()
        if not artifact_path.is_file():
            return None
        stat = artifact_path.stat()
    except Exception:
        return None

    cache_key = str(artifact_path)
    with _artifact_sha_lock:
        cached = _artifact_sha_cache.get(cache_key)
        if cached and cached[0] == int(stat.st_mtime_ns) and cached[1] == int(stat.st_size):
            return cached[2]

    digest = hashlib.sha256()
    try:
        with artifact_path.open("rb") as handle:
            while True:
                chunk = handle.read(1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
    except Exception:
        return None

    value = digest.hexdigest()
    with _artifact_sha_lock:
        _artifact_sha_cache[cache_key] = (int(stat.st_mtime_ns), int(stat.st_size), value)
    return value


def _trained_bundle_for_model(meta_module, trained: TrainedModel) -> Optional[Dict[str, Any]]:
    artifact_path = Path(str(trained.artifact_path or "")).resolve()
    if not artifact_path.exists():
        return None
    cache_key = str(artifact_path)
    cached = _trained_bundle_cache.get(cache_key)
    if cached is not None:
        return cached

    bundle_dir = artifact_path.parent
    meta_payload = (
        _safe_read_json(bundle_dir / "calibrated_stacking_model.joblib.meta.json")
        or _safe_read_json(artifact_path.with_suffix(f"{artifact_path.suffix}.meta.json"))
        or {}
    )
    models_payload = meta_payload.get("models") or {}

    def _resolve_model_path(model_name: str, fallback: str) -> str:
        configured = models_payload.get(model_name)
        configured_name = Path(str(configured)).name if configured else Path(fallback).name
        sibling = bundle_dir / configured_name
        return str(sibling if sibling.exists() else configured or fallback)

    bundle = {
        "artifact_path": str(artifact_path),
        "bundle_dir": str(bundle_dir),
        "meta": meta_payload,
        "feature_columns": list(meta_payload.get("feature_columns") or []),
        "stacking_feature_names": list(meta_payload.get("stacking_feature_names") or ["rf", "xgb", "cat"]),
        "rf": meta_module.load_model_safe(_resolve_model_path("rf", meta_module.RF_MODEL_PATH)),
        "dl": meta_module.load_model_safe(_resolve_model_path("dl", meta_module.DL_MODEL_PATH)),
        "xgb": meta_module.load_model_safe(_resolve_model_path("xgb", meta_module.XGB_MODEL_PATH)),
        "cat": meta_module.load_model_safe(_resolve_model_path("cat", meta_module.CAT_MODEL_PATH)),
        "calibrated": meta_module.load_model_safe(
            _resolve_model_path("calibrated", meta_module.CALIBRATED_MODEL_PATH)
        ),
    }
    _trained_bundle_cache[cache_key] = bundle
    return bundle


def _build_feature_window_frame(pd, symbol_pair: str, candles: List[OhlcvItem], interval_minutes: int) -> Any:
    if not candles:
        return pd.DataFrame()
    rows: List[Dict[str, Any]] = []
    steps_24h = max(1, int(round(1440 / max(interval_minutes, 1))))
    closes = [float(item.close) for item in candles]
    highs = [float(item.high) for item in candles]
    lows = [float(item.low) for item in candles]
    vols = [float(item.volume) for item in candles]
    for idx, item in enumerate(candles):
        lo = max(0, idx - steps_24h + 1)
        window_closes = closes[lo : idx + 1]
        window_highs = highs[lo : idx + 1]
        window_lows = lows[lo : idx + 1]
        window_vols = vols[lo : idx + 1]
        ref_idx = idx - steps_24h
        change_24h = 0.0
        if ref_idx >= 0 and closes[ref_idx] > 0:
            change_24h = ((item.close / closes[ref_idx]) - 1.0) * 100.0
        rows.append(
            {
                "symbol": _base_symbol_from_pair(symbol_pair).lower(),
                "binance_symbol": symbol_pair,
                "timestamp": int(item.ts),
                "open": float(item.open),
                "high": float(item.high),
                "low": float(item.low),
                "close": float(item.close),
                "current_price": float(item.close),
                "high_24h": max(window_highs) if window_highs else float(item.high),
                "low_24h": min(window_lows) if window_lows else float(item.low),
                "total_volume": float(sum(window_vols)),
                "change_24h": float(change_24h),
            }
        )
    return pd.DataFrame(rows)


def _predict_proba_series(model, X) -> List[float]:
    if model is None:
        return [0.0] * len(X)
    try:
        probs = model.predict_proba(X)
        return [float(row[1]) for row in probs]
    except Exception as exc:  # noqa: BLE001
        logger.warning("predict_proba failed for %s: %s", type(model), exc)
        return [0.0] * len(X)


def _bundle_probabilities(pd, bundle: Dict[str, Any], df_enriched) -> Dict[str, List[float]]:
    meta_payload = bundle.get("meta") or {}
    feature_columns = list(bundle.get("feature_columns") or [])
    if not feature_columns:
        feature_columns = [
            c
            for c in list(df_enriched.select_dtypes(include=["number"]).columns)
            if c not in {"price_direction", "future_price", "future_return_pct", "horizon_minutes", "interval_minutes"}
        ]
    X = df_enriched.reindex(columns=feature_columns).fillna(0.0)
    rf_probs = _predict_proba_series(bundle.get("rf"), X)
    dl_probs = _predict_proba_series(bundle.get("dl"), X)
    xgb_probs = _predict_proba_series(bundle.get("xgb"), X)
    cat_probs = _predict_proba_series(bundle.get("cat"), X)

    stacking_feature_names = list(
        bundle.get("stacking_feature_names")
        or meta_payload.get("stacking_feature_names")
        or ["rf", "dl", "xgb", "cat"]
    )
    stacking_map = {
        "rf": rf_probs,
        "dl": dl_probs,
        "xgb": xgb_probs,
        "cat": cat_probs,
    }
    meta_X = pd.DataFrame({name: stacking_map.get(name, [0.0] * len(X)) for name in stacking_feature_names})
    seta_probs = _predict_proba_series(bundle.get("calibrated"), meta_X)
    available_base_names = [name for name in ("rf", "dl", "xgb", "cat") if bundle.get(name) is not None]
    combined = (
        seta_probs
        if any(prob > 0.0 for prob in seta_probs)
        else [
            max(
                0.0,
                min(
                    1.0,
                    sum(float(stacking_map[name][i]) for name in available_base_names) / max(len(available_base_names), 1),
                ),
            )
            for i in range(len(X))
        ]
    )
    return {
        "feature_columns": feature_columns,
        "stacking_feature_names": stacking_feature_names,
        "rf_probs": rf_probs,
        "dl_probs": dl_probs,
        "xgb_probs": xgb_probs,
        "cat_probs": cat_probs,
        "seta_probs": seta_probs,
        "combined": combined,
    }


def _current_market_regime(df_enriched) -> Optional[str]:
    if getattr(df_enriched, "empty", True):
        return None
    try:
        value = df_enriched.iloc[-1].get("market_regime")
        text = str(value or "").strip().lower()
        return text or None
    except Exception:
        return None


def _estimate_predicted_price(
    *,
    current: float,
    probability_up: float,
    df_enriched,
    horizon_minutes: int,
    interval_minutes: int,
) -> float:
    horizon_steps = max(1, int(round(horizon_minutes / max(interval_minutes, 1))))
    row = df_enriched.iloc[-1] if len(df_enriched) else {}
    rolling_vol = abs(float(row.get("rolling_vol_14") or 0.0))
    atr = abs(float(row.get("atr_14") or 0.0))
    atr_pct = (atr / current) if current > 0 else 0.0
    base_move = max(rolling_vol, atr_pct, 0.0025)
    scaled_move = min(0.08, max(0.003, base_move * math.sqrt(max(horizon_steps, 1))))
    drift = (float(probability_up) - 0.5) * 2.0 * scaled_move
    return round(current * (1.0 + drift), 2)


def _predict_with_trained_models(
    symbol_pair: str,
    horizon_minutes: int,
    requested_model: str,
    current_price: Optional[float],
) -> Optional[Dict[str, Any]]:
    if not CRYPTO_USE_TRAINED_MODELS:
        return None
    pd = _get_pandas()
    meta_module = _get_meta_module()
    if pd is None or meta_module is None:
        return None

    model_hint = None if requested_model == "ensemble" else requested_model
    trained = resolve_trained_model(symbol_pair, horizon_minutes, model_hint)
    if trained is None:
        # Horizon-agnostic fallback for canonical model filenames (rf_model/xgb_model/etc.).
        trained = resolve_trained_model(symbol_pair, 15, model_hint) if horizon_minutes != 15 else None
    if trained is None:
        return None

    try:
        artifact_sha256 = _artifact_sha256(trained.artifact_path)
        interval_minutes = int(trained.interval_minutes or 0) or {
            "1m": 1,
            "5m": 5,
            "15m": 15,
            "1h": 60,
            "4h": 240,
            "1d": 1440,
        }.get(_interval_for_horizon(horizon_minutes), 1)
        interval = _interval_for_horizon(horizon_minutes)
        limit = max(80, int(round((horizon_minutes / max(interval_minutes, 1)) * 12)))
        candles = _binance_ohlcv_window(symbol_pair, interval=interval, limit=min(limit, 500))
        if not candles:
            return None
        bundle = _trained_bundle_for_model(meta_module, trained)
        if bundle is None:
            return None
        df_raw = _build_feature_window_frame(pd, symbol_pair, candles, interval_minutes)
        enricher = meta_module.SetaFeatureEnricher()
        df_enriched = enricher.enrich_features(df_raw)
        df_enriched = meta_module.ensure_price_direction(
            df_enriched,
            price_col="current_price",
            label_col="price_direction",
        )
        probs_info = _bundle_probabilities(pd, bundle, df_enriched)
        idx = len(df_enriched) - 1
        per_model = {
            "rf": float(probs_info["rf_probs"][idx]),
            "dl": float(probs_info["dl_probs"][idx]),
            "xgb": float(probs_info["xgb_probs"][idx]),
            "cat": float(probs_info["cat_probs"][idx]),
            "seta": float(probs_info["seta_probs"][idx]),
        }
        if requested_model in per_model:
            model_used = requested_model
            p_up = per_model[requested_model]
        else:
            model_used = "ensemble"
            p_up = float(probs_info["combined"][idx])

        p_up = max(0.05, min(0.95, float(p_up)))
        live_price = current_price if isinstance(current_price, (int, float)) else None
        current = float(live_price or df_raw.iloc[-1]["current_price"] or 0.0)
        predicted = _estimate_predicted_price(
            current=current,
            probability_up=p_up,
            df_enriched=df_enriched,
            horizon_minutes=horizon_minutes,
            interval_minutes=interval_minutes,
        )
        decision: Literal["BUY", "SELL", "HOLD"]
        if p_up > 0.63:
            decision = "BUY"
        elif p_up < 0.37:
            decision = "SELL"
        else:
            decision = "HOLD"

        return {
            "model_used": model_used,
            "probability_up": p_up,
            "predicted_price": predicted,
            "decision": decision,
            "current_price": current,
            "trained_horizon_minutes": trained.horizon_minutes,
            "trained_model_type": trained.model_type,
            "trained_artifact": trained.artifact_path,
            "trained_artifact_sha256": artifact_sha256,
            "dataset_hash": trained.dataset_hash,
            "trained_at": trained.trained_at,
            "validation_mode": trained.validation_mode,
            "interval_minutes": interval_minutes,
            "regime": _current_market_regime(df_enriched),
            "per_model_probs": per_model,
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning("trained-model prediction unavailable for %s: %s", symbol_pair, exc)
        return None


def _build_prediction_provenance(
    *,
    requested_model: str,
    model_used: str,
    requested_horizon_minutes: int,
    prediction_engine: str,
    price_source: str,
    trained_payload: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    trained_payload = trained_payload or {}
    trained_horizon_minutes = trained_payload.get("trained_horizon_minutes")
    artifact_path = trained_payload.get("trained_artifact")
    artifact_sha256 = trained_payload.get("trained_artifact_sha256") or _artifact_sha256(artifact_path)
    used_trained_horizon_fallback = (
        isinstance(trained_horizon_minutes, int)
        and int(trained_horizon_minutes) != int(requested_horizon_minutes)
    )
    return {
        "requested_model": requested_model,
        "model_used": model_used,
        "engine": prediction_engine,
        "requested_horizon_minutes": int(requested_horizon_minutes),
        "trained_horizon_minutes": trained_horizon_minutes,
        "requested_interval": _interval_for_horizon(int(requested_horizon_minutes)),
        "model_interval_minutes": trained_payload.get("interval_minutes"),
        "used_demo_fallback": prediction_engine != "trained",
        "used_trained_horizon_fallback": used_trained_horizon_fallback,
        "trained_model_type": trained_payload.get("trained_model_type"),
        "trained_artifact": artifact_path,
        "trained_artifact_sha256": artifact_sha256,
        "dataset_hash": trained_payload.get("dataset_hash"),
        "trained_at": trained_payload.get("trained_at"),
        "validation_mode": trained_payload.get("validation_mode"),
        "price_source": price_source,
    }


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/models", response_model=ModelCatalog)
def get_models() -> ModelCatalog:
    trained = discover_trained_models()
    registry = build_model_registry(trained)
    supported_models = ["rf", "xgb", "cat", "dl", "seta", "ensemble"]
    installed_models = sorted(
        {
            str(model_type)
            for entry in registry
            for model_type in (entry.available_model_types or [])
            if str(model_type).strip()
        }
    )
    available_models = installed_models or ["ensemble"]
    default_model = os.getenv("CRYPTO_DEFAULT_MODEL", "ensemble")
    return ModelCatalog(
        available=available_models,
        default=default_model if default_model in available_models else available_models[0],
        trained=trained,
        supported=supported_models,
        installed=installed_models,
    )


@router.get("/models/registry")
def get_model_registry() -> List[Dict[str, Any]]:
    return [entry.model_dump() for entry in build_model_registry(discover_trained_models())]


@router.get("/models/metrics")
def get_model_metrics(limit: int = Query(200, ge=10, le=1000)) -> Dict[str, Any]:
    """Return recent accuracy stats across models."""
    try:
        return recent_stats(limit=limit)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Error computing model metrics: {exc}") from exc


@router.post("/predict", response_model=PredictResponse)
def predict(req: PredictRequest) -> PredictResponse:
    """
    What it does:
    - Produces a crypto prediction payload with optional news adjustment/logging.

    Why it exists:
    - Single API entrypoint for model selection, telemetry, and downstream stats.

    Called from ->
    - Crypto mode UI and programmatic clients
    - Evaluation flows that read prediction/outcome logs

    Calls ->
    - market price resolvers (Binance/CoinGecko fallback)
    - news fetch + sentiment scoring
    - prediction/outcome log services

    Failure/guard behavior:
    - Fails with HTTP 400 on invalid model/symbol inputs.
    - Degrades to deterministic demo values when live price is unavailable.
    """
    sym = _normalize_binance_pair(req.symbol)
    if not sym:
        raise HTTPException(status_code=400, detail="Missing symbol")

    requested_model = (req.model or "ensemble").lower().strip()
    if requested_model not in {"rf", "xgb", "cat", "dl", "seta", "ensemble"}:
        raise HTTPException(status_code=400, detail="Unsupported model")

    require_trained = bool(req.require_trained or CRYPTO_REQUIRE_TRAINED_MODELS)
    live_price = _binance_spot_price(sym)
    price_source = _price_source.get(sym, "demo" if live_price is None else "binance")
    trained_payload = _predict_with_trained_models(sym, req.horizon_minutes, requested_model, live_price)
    prediction_engine = "trained" if trained_payload else "demo"
    threshold_rec: Optional[Dict[str, Any]] = None
    adaptive_policy: Optional[Dict[str, Any]] = None
    if require_trained and not trained_payload:
        raise HTTPException(
            status_code=503,
            detail=(
                "trained prediction unavailable for the requested symbol/horizon/model; "
                "demo fallback disabled"
            ),
        )

    if trained_payload:
        current = round(float(trained_payload["current_price"]), 2)
        p_up = max(0.05, min(0.95, float(trained_payload["probability_up"])))
        p_base = p_up
        predicted = round(float(trained_payload["predicted_price"]), 2)
        regime = trained_payload.get("regime")
        model_used = str(trained_payload.get("model_used") or requested_model)
        adaptive_policy = _adaptive_crypto_threshold_strategy(
            symbol=sym,
            horizon_minutes=req.horizon_minutes,
            regime=regime,
            limit=CRYPTO_THRESHOLD_LOOKBACK,
            engine="trained",
            min_trades=CRYPTO_THRESHOLD_MIN_TRADES,
        )
        threshold_rec = adaptive_policy["selected_strategy"]
        buy_threshold = float((threshold_rec or {}).get("buy_threshold") or CRYPTO_DEFAULT_BUY_THRESHOLD)
        sell_threshold = float((threshold_rec or {}).get("sell_threshold") or CRYPTO_DEFAULT_SELL_THRESHOLD)
        decision = _decision_from_thresholds(p_up, buy_threshold=buy_threshold, sell_threshold=sell_threshold)
        raw = {
            "per_model_probs": trained_payload.get("per_model_probs") or {},
            "trained_artifact": trained_payload.get("trained_artifact"),
            "trained_model_type": trained_payload.get("trained_model_type"),
            "dataset_hash": trained_payload.get("dataset_hash"),
            "trained_at": trained_payload.get("trained_at"),
            "validation_mode": trained_payload.get("validation_mode"),
            "interval_minutes": trained_payload.get("interval_minutes"),
            "regime": regime,
            "threshold_strategy": threshold_rec,
            "buy_threshold": buy_threshold,
            "sell_threshold": sell_threshold,
        }
    else:
        digest = int(hashlib.sha256(f"{sym}:{req.horizon_minutes}".encode()).hexdigest(), 16)
        base = 100 + (digest % 500)
        wobble = 5 * math.sin(time.time() / 60.0)
        current = round(live_price if live_price is not None else (base + wobble), 2)

        rng = random.Random(digest ^ 0xABCDEF)
        p_up = max(0.05, min(0.95, rng.random()))
        p_base = p_up
        delta = (rng.random() - 0.5) * 2.0
        predicted = round(current * (1 + delta * 0.01), 2)
        if p_up > 0.63:
            decision = "BUY"
        elif p_up < 0.37:
            decision = "SELL"
        else:
            decision = "HOLD"

        regime = None
        buy_threshold = CRYPTO_DEFAULT_BUY_THRESHOLD
        sell_threshold = CRYPTO_DEFAULT_SELL_THRESHOLD
        raw = {
            "per_model_probs": {
                "rf": round(p_up * 0.9 + 0.05, 3),
                "xgb": round(p_up * 0.85 + 0.08, 3),
                "cat": round(p_up * 0.88 + 0.06, 3),
                "dl": round(p_up * 0.92 + 0.04, 3),
                "seta": round(p_up * 0.8 + 0.1, 3),
            }
        }
        if requested_model != "ensemble":
            adjust = {"rf": -0.01, "xgb": 0.01, "cat": 0.0, "dl": 0.02, "seta": -0.02}.get(requested_model, 0.0)
            p_up = max(0.05, min(0.95, p_up + adjust))
            predicted = round(current * (1 + (p_up - 0.5) * 0.02), 2)
            decision = "BUY" if p_up > 0.63 else "SELL" if p_up < 0.37 else "HOLD"
        model_used = requested_model

    news_payload = fetch_crypto_news(sym)
    news_items = news_payload.get("items", [])[:6] if news_payload else []

    # persist news (dedupe by hash)
    try:
        _upsert_news_items(sym, news_items, window_minutes=180)
    except Exception:
        logger.debug("Failed to upsert news", exc_info=True)

    # fetch a recent window for sentiment/adjustment (DB, deduped)
    try:
        recent_news = _fetch_recent_news(sym, minutes=90, limit=12)
    except Exception:
        recent_news = []

    if recent_news:
        news_items = recent_news

    # Ajuste por sentimiento de noticias (ligero y seguro)
    news_sentiment = None
    n_news_used = 0
    if news_items:
        sentiments = [_sentiment_score((n.get("title") or "") + " " + (n.get("summary") or "")) for n in news_items]
        sentiments = [s for s in sentiments if s is not None]
        n_news_used = len(sentiments)
        if n_news_used >= 1:
            news_sentiment = sum(sentiments) / n_news_used
            p_up = max(0.05, min(0.95, p_up + news_sentiment * 0.08))
            predicted = round(current * (1 + (p_up - 0.5) * 0.02), 2)
            decision = _decision_from_thresholds(p_up, buy_threshold=buy_threshold, sell_threshold=sell_threshold)

    model_decision = decision
    credibility = None
    operator_guidance = None
    action_decision = model_decision
    execution_margin = 0.0
    calibration_margin = 0.0
    threshold_edge = None
    execution_gate_reason = None
    consensus_metrics = None
    consensus_requirements = None
    if prediction_engine == "trained":
        credibility = assess_scope_credibility(
            limit=CRYPTO_THRESHOLD_LOOKBACK,
            symbol=sym,
            engine="trained",
            horizon_minutes=req.horizon_minutes,
            regime=regime,
            min_trades=CRYPTO_THRESHOLD_MIN_TRADES,
        )
        operator_guidance = _scope_operator_guidance(
            symbol=sym,
            horizon_minutes=req.horizon_minutes,
            regime=regime,
            limit=CRYPTO_THRESHOLD_LOOKBACK,
        )
        execution_margin = _effective_execution_margin(credibility, operator_guidance)
        calibration_margin = _calibration_margin_for_operator_guidance(operator_guidance)
        consensus_requirements = _effective_consensus_requirements(credibility, operator_guidance)
        consensus_metrics = _consensus_metrics((raw or {}).get("per_model_probs"), decision=model_decision)
        if model_decision == "BUY":
            threshold_edge = p_up - buy_threshold
        elif model_decision == "SELL":
            threshold_edge = sell_threshold - p_up
        if (
            isinstance(credibility, dict)
            and bool(credibility.get("should_abstain"))
            and model_decision in {"BUY", "SELL"}
        ):
            action_decision = "HOLD"
            execution_gate_reason = "credibility_abstain"
        elif _should_calibration_abstain(operator_guidance) and model_decision in {"BUY", "SELL"}:
            action_decision = "HOLD"
            execution_gate_reason = "calibration_abstain"
        elif (
            model_decision in {"BUY", "SELL"}
            and threshold_edge is not None
            and threshold_edge < execution_margin
        ):
            action_decision = "HOLD"
            execution_gate_reason = "edge_below_margin"
        elif (
            model_decision in {"BUY", "SELL"}
            and isinstance(consensus_metrics, dict)
            and isinstance(consensus_requirements, dict)
            and float(consensus_metrics.get("support_ratio") or 0.0) < float(consensus_requirements.get("min_support_ratio") or 0.0)
        ):
            action_decision = "HOLD"
            execution_gate_reason = "low_consensus_support"
        elif (
            model_decision in {"BUY", "SELL"}
            and isinstance(consensus_metrics, dict)
            and isinstance(consensus_requirements, dict)
            and float(consensus_metrics.get("spread") or 0.0) > float(consensus_requirements.get("max_spread") or 0.0)
        ):
            action_decision = "HOLD"
            execution_gate_reason = "high_consensus_spread"
    decision = action_decision
    actionable = action_decision in {"BUY", "SELL"}
    if adaptive_policy is None:
        adaptive_policy = _adaptive_crypto_threshold_strategy(
            symbol=sym,
            horizon_minutes=req.horizon_minutes,
            regime=regime,
            limit=CRYPTO_THRESHOLD_LOOKBACK,
            engine="trained",
            min_trades=CRYPTO_THRESHOLD_MIN_TRADES,
            include_preview=False,
        )
    policy = _crypto_policy_snapshot(
        symbol=sym,
        horizon_minutes=req.horizon_minutes,
        regime=regime,
        prediction_engine=prediction_engine,
        model_used=model_used,
        model_decision=model_decision,
        action_decision=action_decision,
        p_up=p_up,
        buy_threshold=buy_threshold,
        sell_threshold=sell_threshold,
        credibility=credibility,
        operator_guidance=operator_guidance,
        consensus_metrics={
            **(consensus_metrics or {}),
            **{
                "required_support_ratio": (consensus_requirements or {}).get("min_support_ratio"),
                "max_spread": (consensus_requirements or {}).get("max_spread"),
            },
        },
        threshold_rec=threshold_rec,
        require_trained=require_trained,
        execution_margin=execution_margin,
        consensus_requirements=consensus_requirements,
        execution_gate_reason=execution_gate_reason,
        adaptive_policy=adaptive_policy,
    )
    if isinstance(raw, dict):
        raw["model_decision"] = model_decision
        raw["action_decision"] = action_decision
        raw["actionable"] = actionable
        raw["credibility"] = credibility
        raw["operator_guidance"] = operator_guidance
        raw["execution_margin"] = execution_margin
        raw["calibration_margin"] = calibration_margin
        raw["threshold_edge"] = threshold_edge
        raw["execution_gate_reason"] = execution_gate_reason
        raw["consensus"] = {
            **(consensus_metrics or {}),
            **{
                "required_support_ratio": (consensus_requirements or {}).get("min_support_ratio"),
                "max_spread": (consensus_requirements or {}).get("max_spread"),
            },
        }
        raw["adaptive_policy"] = adaptive_policy
        raw["policy"] = policy

    prediction_provenance = _build_prediction_provenance(
        requested_model=requested_model,
        model_used=model_used,
        requested_horizon_minutes=req.horizon_minutes,
        prediction_engine=prediction_engine,
        price_source=price_source,
        trained_payload=trained_payload,
    )
    if isinstance(raw, dict):
        raw["prediction_provenance"] = prediction_provenance

    log_id: Optional[str] = None
    if req.save:
        log_id = log_prediction(
            {
                "symbol": sym,
                "horizon_minutes": req.horizon_minutes,
                "model": model_used,
                "probability_up": p_up,
                "probability_base": p_base,
                "decision": decision,
                "model_decision": model_decision,
                "action_decision": action_decision,
                "current_price": current,
                "predicted_price": predicted,
                "price_source": price_source,
                "engine": prediction_engine,
                "news": news_items,
                "news_sentiment": news_sentiment,
                "n_news_used": n_news_used,
                "regime": regime,
                "buy_threshold": buy_threshold,
                "sell_threshold": sell_threshold,
                "threshold_strategy": (raw or {}).get("threshold_strategy"),
                "credibility": credibility,
                "operator_guidance": operator_guidance,
                "execution_margin": execution_margin,
                "calibration_margin": calibration_margin,
                "threshold_edge": threshold_edge,
                "execution_gate_reason": execution_gate_reason,
                "consensus": (raw or {}).get("consensus"),
                "prediction_provenance": prediction_provenance,
                "ts": int(time.time()),
            }
        )

    if log_id:
        def _capture_outcome() -> None:
            try:
                live = _binance_spot_price(sym)
                if live is None or live <= 0:
                    return
                delta_pct = (live - current) / current if current else 0.0
                hit = None
                if decision == "BUY":
                    hit = live > current
                elif decision == "SELL":
                    hit = live < current
                elif decision == "HOLD":
                    hit = abs(delta_pct) < 0.01
                log_outcome(
                    {
                        "log_id": log_id,
                        "symbol": sym,
                        "horizon_minutes": req.horizon_minutes,
                        "decision": decision,
                        "model_decision": model_decision,
                        "action_decision": action_decision,
                        "probability_up": p_up,
                        "probability_base": p_base,
                        "model": model_used,
                        "predicted_price": predicted,
                        "actual_price": live,
                        "delta_pct": delta_pct,
                        "hit": hit,
                        "price_source": price_source,
                        "engine": prediction_engine,
                        "news_sentiment": news_sentiment,
                        "n_news_used": n_news_used,
                        "regime": regime,
                        "buy_threshold": buy_threshold,
                        "sell_threshold": sell_threshold,
                        "threshold_strategy": (raw or {}).get("threshold_strategy"),
                        "credibility": credibility,
                        "operator_guidance": operator_guidance,
                        "execution_margin": execution_margin,
                        "calibration_margin": calibration_margin,
                        "threshold_edge": threshold_edge,
                        "execution_gate_reason": execution_gate_reason,
                        "consensus": (raw or {}).get("consensus"),
                        "prediction_provenance": prediction_provenance,
                    }
                )
            except Exception:
                return

        try:
            threading.Timer(req.horizon_minutes * 60, _capture_outcome).start()
        except Exception:
            pass

    return PredictResponse(
        symbol=sym,
        horizon_minutes=req.horizon_minutes,
        current_price=current,
        predicted_price=predicted,
        probability_up=p_up,
        decision=decision,
        raw=raw,
        additional_info={
            "note": (
                "trained-model prediction (not financial advice)"
                if prediction_engine == "trained"
                else "demo fallback prediction (not financial advice)"
            ),
            "engine": prediction_engine,
            "model_used": model_used,
            "require_trained": require_trained,
            "degraded": prediction_engine != "trained",
            "news_provider": news_payload.get("provider") if news_payload else None,
            "log_id": log_id,
            "price_source": price_source,
            "news_sentiment": news_sentiment,
            "regime": regime,
            "model_decision": model_decision,
            "action_decision": action_decision,
            "actionable": actionable,
            "credibility_status": (credibility or {}).get("status"),
            "credibility_score": (credibility or {}).get("score"),
            "credibility_reasons": (credibility or {}).get("reasons") or [],
            "operator_guidance_status": (operator_guidance or {}).get("status"),
            "operator_guidance_action": (operator_guidance or {}).get("action"),
            "operator_guidance_reasons": (operator_guidance or {}).get("reasons") or [],
            "execution_margin": execution_margin,
            "calibration_margin": calibration_margin,
            "threshold_edge": threshold_edge,
            "execution_gate_reason": execution_gate_reason,
            "consensus": (raw or {}).get("consensus"),
            "buy_threshold": (raw or {}).get("buy_threshold"),
            "sell_threshold": (raw or {}).get("sell_threshold"),
            "policy": policy,
            "adaptive_policy": adaptive_policy,
            "route_mode": policy.get("route_mode"),
            "route_reason": policy.get("route_reason"),
            "confidence_bucket": policy.get("confidence_bucket"),
            "prediction_provenance": prediction_provenance,
        },
        news=news_items,
    )


@router.get("/top-coins", response_model=List[TopCoin])
def top_coins(
    limit: int = Query(30, ge=1, le=250),
    max_price: Optional[float] = Query(None),
    min_price: Optional[float] = Query(None),
) -> List[TopCoin]:
    base = [
        TopCoin(id="bitcoin", symbol="btc", name="Bitcoin", current_price=50000.0, market_cap=1.0e12, price_change_percentage_24h=1.2),
        TopCoin(id="ethereum", symbol="eth", name="Ethereum", current_price=2500.0, market_cap=3.0e11, price_change_percentage_24h=-0.4),
        TopCoin(id="tether", symbol="usdt", name="Tether", current_price=1.0, market_cap=9.0e10, price_change_percentage_24h=0.0),
        TopCoin(id="bnb", symbol="bnb", name="BNB", current_price=320.0, market_cap=5.0e10, price_change_percentage_24h=0.8),
        TopCoin(id="solana", symbol="sol", name="Solana", current_price=110.0, market_cap=4.5e10, price_change_percentage_24h=2.1),
        TopCoin(id="xrp", symbol="xrp", name="XRP", current_price=0.60, market_cap=3.0e10, price_change_percentage_24h=-1.0),
        TopCoin(id="cardano", symbol="ada", name="Cardano", current_price=0.45, market_cap=1.6e10, price_change_percentage_24h=0.5),
        TopCoin(id="dogecoin", symbol="doge", name="Dogecoin", current_price=0.10, market_cap=1.4e10, price_change_percentage_24h=3.2),
        TopCoin(id="tron", symbol="trx", name="TRON", current_price=0.12, market_cap=1.0e10, price_change_percentage_24h=-0.2),
        TopCoin(id="polkadot", symbol="dot", name="Polkadot", current_price=6.1, market_cap=9.0e9, price_change_percentage_24h=1.9),
    ]
    coins = base
    if min_price is not None:
        coins = [c for c in coins if c.current_price >= min_price]
    if max_price is not None:
        coins = [c for c in coins if c.current_price <= max_price]
    return coins[:limit]


@router.get("/ohlcv", response_model=List[OhlcvItem])
def get_ohlcv(
    symbol: str = Query(...),
    interval: str = Query("1m"),
    limit: int = Query(200, ge=1, le=1000),
) -> List[OhlcvItem]:
    """
    What it does:
    - Returns OHLCV candles for a symbol/interval.

    Why it exists:
    - Provide chart-ready series to crypto UI and analysis flows.

    Called from ->
    - Crypto chart panel and E2E checks

    Calls ->
    - Binance klines endpoint, with deterministic synthetic fallback series
    """
    sym = _normalize_binance_pair(symbol)
    if not sym:
        raise HTTPException(status_code=400, detail="Missing symbol")
    step = {
        "1m": 60,
        "5m": 300,
        "15m": 900,
        "1h": 3600,
        "4h": 14400,
        "1d": 86400,
    }.get(interval, 60)

    try:
        resp = requests.get(
            "https://api.binance.com/api/v3/klines",
            params={"symbol": sym, "interval": interval, "limit": limit},
            timeout=8,
        )
        resp.raise_for_status()
        raw = resp.json()
        series: List[OhlcvItem] = []
        for item in raw:
            ts = int(item[6])  # close time
            series.append(
                OhlcvItem(
                    ts=ts,
                    open=float(item[1]),
                    high=float(item[2]),
                    low=float(item[3]),
                    close=float(item[4]),
                    volume=float(item[5]),
                )
            )
        return series
    except Exception:
        base = 100 + (hash(sym) % 500)
        now = int(time.time())
        rng = random.Random(hash((sym, interval)))
        series: List[OhlcvItem] = []
        for i in range(limit):
            ts = now - step * (limit - 1 - i)
            center = base + 5 * math.sin(i / 12.0)
            c = round(center + rng.uniform(-0.7, 0.7), 2)
            o = round(c + rng.uniform(-0.5, 0.5), 2)
            h = round(max(o, c) + rng.uniform(0, 0.8), 2)
            l = round(min(o, c) - rng.uniform(0, 0.8), 2)
            v = round(abs(rng.gauss(50, 15)), 2)
            series.append(OhlcvItem(ts=ts, open=o, high=h, low=l, close=c, volume=v))
        return series


@router.get("/news")
def crypto_news(
    symbol: str = Query(..., min_length=2, max_length=20),
    force: bool = Query(False, description="Bypass cache when true"),
) -> Dict[str, Any]:
    """
    What it does:
    - Returns normalized crypto news payload for the requested symbol.

    Why it exists:
    - Reuse canonical news enrichment service through API surface.

    Called from ->
    - Crypto mode UI panels
    - Prediction enrichment workflows

    Calls ->
    - app.services.crypto_news_service.fetch_news
    """
    try:
        return fetch_crypto_news(symbol, force=force)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Error fetching news: {exc}") from exc


@router.get("/predictions")
def recent_predictions(
    limit: int = Query(20, ge=1, le=200),
    symbol: Optional[str] = Query(None, description="Optional symbol filter"),
    engine: Optional[str] = Query(None, description="all | trained | demo"),
    horizon_minutes: Optional[int] = Query(None, ge=1, le=10080),
    regime: Optional[str] = Query(None),
) -> List[Dict[str, Any]]:
    try:
        scope = _normalized_prediction_scope(
            symbol=symbol,
            engine=engine,
            horizon_minutes=horizon_minutes,
            regime=regime,
        )
        return pair_predictions_with_outcomes(
            limit=limit,
            symbol=scope["symbol"],
            engine=scope["engine"],
            horizon_minutes=scope["horizon_minutes"],
            regime=scope["regime"],
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Error listing predictions: {exc}") from exc


@router.get("/predictions/outcomes")
def recent_outcomes(
    limit: int = Query(50, ge=1, le=500),
    symbol: Optional[str] = Query(None),
    engine: Optional[str] = Query(None, description="all | trained | demo"),
    horizon_minutes: Optional[int] = Query(None, ge=1, le=10080),
    regime: Optional[str] = Query(None),
) -> List[Dict[str, Any]]:
    try:
        scope = _normalized_prediction_scope(
            symbol=symbol,
            engine=engine,
            horizon_minutes=horizon_minutes,
            regime=regime,
        )
        return list_outcomes(
            limit=limit,
            symbol=scope["symbol"],
            engine=scope["engine"],
            horizon_minutes=scope["horizon_minutes"],
            regime=scope["regime"],
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Error listing outcomes: {exc}") from exc


@router.delete("/predictions")
def clear_predictions(_: Optional[str] = Depends(require_api_key)) -> dict:
    """Remove prediction and outcome logs (crypto history)."""
    try:
        clear_predictions_and_outcomes()
        return {"status": "ok"}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Error clearing predictions: {exc}") from exc


@router.get("/predictions/stats")
def prediction_stats(
    limit: int = Query(100, ge=1, le=500),
    symbol: Optional[str] = Query(None),
    engine: Optional[str] = Query(None, description="all | trained | demo"),
    horizon_minutes: Optional[int] = Query(None, ge=1, le=10080),
    regime: Optional[str] = Query(None),
    fee_bps: float = Query(10.0, ge=0.0, le=500.0),
    slippage_bps: float = Query(5.0, ge=0.0, le=500.0),
) -> Dict[str, Any]:
    try:
        scope = _normalized_prediction_scope(
            symbol=symbol,
            engine=engine,
            horizon_minutes=horizon_minutes,
            regime=regime,
        )
        return recent_stats(
            limit=limit,
            symbol=scope["symbol"],
            engine=scope["engine"],
            horizon_minutes=scope["horizon_minutes"],
            regime=scope["regime"],
            fee_bps=fee_bps,
            slippage_bps=slippage_bps,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Error computing stats: {exc}") from exc


@router.get("/predictions/thresholds")
def prediction_thresholds(
    limit: int = Query(1000, ge=20, le=5000),
    symbol: Optional[str] = Query(None),
    engine: Optional[str] = Query("trained", description="all | trained | demo"),
    horizon_minutes: Optional[int] = Query(None, ge=1, le=10080),
    regime: Optional[str] = Query(None),
    fee_bps: float = Query(10.0, ge=0.0, le=500.0),
    slippage_bps: float = Query(5.0, ge=0.0, le=500.0),
    min_trades: int = Query(8, ge=1, le=500),
) -> Dict[str, Any]:
    try:
        scope = _normalized_prediction_scope(
            symbol=symbol,
            engine=engine,
            horizon_minutes=horizon_minutes,
            regime=regime,
        )
        recommendation = optimize_thresholds(
            limit=limit,
            symbol=scope["symbol"],
            engine=scope["engine"] or "trained",
            horizon_minutes=scope["horizon_minutes"],
            regime=scope["regime"],
            fee_bps=fee_bps,
            slippage_bps=slippage_bps,
            min_trades=min_trades,
        )
        return {
            "scope": {
                "symbol": scope["symbol"],
                "engine": normalize_engine_filter(scope["engine"]) or "all",
                "horizon_minutes": scope["horizon_minutes"],
                "regime": scope["regime"],
                "limit": limit,
                "min_trades": min_trades,
            },
            "recommendation": recommendation,
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Error optimizing thresholds: {exc}") from exc


@router.get("/predictions/credibility")
def prediction_credibility(
    symbol: Optional[str] = Query(None),
    engine: Optional[str] = Query("trained"),
    horizon_minutes: Optional[int] = Query(None, ge=1, le=10080),
    regime: Optional[str] = Query(None),
):
    try:
        scope = _normalized_prediction_scope(
            symbol=symbol,
            engine=engine,
            horizon_minutes=horizon_minutes,
            regime=regime,
        )
        assessment = assess_scope_credibility(
            limit=CRYPTO_THRESHOLD_LOOKBACK,
            symbol=scope["symbol"],
            engine=scope["engine"] or "trained",
            horizon_minutes=scope["horizon_minutes"],
            regime=scope["regime"],
            min_trades=CRYPTO_THRESHOLD_MIN_TRADES,
        )
        return {
            "scope": {
                "symbol": scope["symbol"],
                "engine": scope["engine"] or "trained",
                "horizon_minutes": scope["horizon_minutes"],
                "regime": scope["regime"],
            },
            "assessment": assessment,
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Error assessing scope credibility: {exc}") from exc


@router.get("/policy")
def crypto_policy(
    symbol: Optional[str] = Query(None),
    engine: Optional[str] = Query("trained", description="all | trained | demo"),
    horizon_minutes: Optional[int] = Query(None, ge=1, le=10080),
    regime: Optional[str] = Query(None),
) -> Dict[str, Any]:
    try:
        scope = _normalized_prediction_scope(
            symbol=symbol,
            engine=engine,
            horizon_minutes=horizon_minutes,
            regime=regime,
        )
        limit = CRYPTO_THRESHOLD_LOOKBACK
        rec = optimize_thresholds(
            limit=limit,
            symbol=scope["symbol"],
            engine=scope["engine"] or "trained",
            horizon_minutes=scope["horizon_minutes"],
            regime=scope["regime"],
            min_trades=CRYPTO_THRESHOLD_MIN_TRADES,
        )
        credibility = assess_scope_credibility(
            limit=limit,
            symbol=scope["symbol"],
            engine=scope["engine"] or "trained",
            horizon_minutes=scope["horizon_minutes"],
            regime=scope["regime"],
            min_trades=CRYPTO_THRESHOLD_MIN_TRADES,
        )
        operator_guidance = _scope_operator_guidance(
            symbol=scope["symbol"],
            horizon_minutes=scope["horizon_minutes"],
            regime=scope["regime"],
            limit=limit,
        )
        effective_execution_margin = _effective_execution_margin(credibility, operator_guidance)
        effective_consensus_requirements = _effective_consensus_requirements(credibility, operator_guidance)
        should_abstain = _effective_should_abstain(credibility, operator_guidance)
        adaptive = _adaptive_crypto_threshold_strategy(
            symbol=scope["symbol"] or "",
            horizon_minutes=scope["horizon_minutes"] or 15,
            regime=scope["regime"],
            limit=limit,
            engine=scope["engine"] or "trained",
            fee_bps=10.0,
            slippage_bps=5.0,
            min_trades=CRYPTO_THRESHOLD_MIN_TRADES,
            include_preview=True,
        )
        return {
            "scope": {
                "symbol": scope["symbol"],
                "engine": normalize_engine_filter(scope["engine"]) or "all",
                "horizon_minutes": scope["horizon_minutes"],
                "regime": scope["regime"],
                "limit": limit,
            },
            "policy_profile": _crypto_policy_profile(),
            "execution": _crypto_execution_snapshot(),
            "recommendation": rec,
            "credibility": credibility,
            "operator_guidance": operator_guidance,
            "effective_gates": {
                "execution_margin": effective_execution_margin,
                "required_support_ratio": effective_consensus_requirements.get("min_support_ratio"),
                "required_max_spread": effective_consensus_requirements.get("max_spread"),
            },
            "adaptive": adaptive,
            "summary": {
                "route_mode": "demo" if should_abstain else ("trained" if credibility and credibility.get("status") != "blocked" else "demo"),
                "should_abstain": should_abstain,
                "calibration_status": (operator_guidance or {}).get("status"),
                "calibration_action": (operator_guidance or {}).get("action"),
                "effective_execution_margin": effective_execution_margin,
                "effective_required_support_ratio": effective_consensus_requirements.get("min_support_ratio"),
                "effective_required_max_spread": effective_consensus_requirements.get("max_spread"),
                "adaptive_strategy_source": adaptive.get("strategy_source"),
            },
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Error computing crypto policy: {exc}") from exc


@router.get("/predictions/leaderboard")
def prediction_leaderboard(
    limit: int = Query(2000, ge=50, le=10000),
    engine: Optional[str] = Query("trained", description="all | trained | demo"),
    fee_bps: float = Query(10.0, ge=0.0, le=500.0),
    slippage_bps: float = Query(5.0, ge=0.0, le=500.0),
    min_trades: int = Query(8, ge=1, le=500),
    top_n: int = Query(20, ge=1, le=100),
) -> List[Dict[str, Any]]:
    try:
        return scope_leaderboard(
            limit=limit,
            engine=_optional_query_text(engine) or "trained",
            fee_bps=fee_bps,
            slippage_bps=slippage_bps,
            min_trades=min_trades,
            top_n=top_n,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Error building leaderboard: {exc}") from exc


def _format_ratio_pct(value: Any, digits: int = 2) -> str:
    try:
        number = float(value)
    except Exception:
        return "n/a"
    if not math.isfinite(number):
        return "n/a"
    return f"{number * 100:.{digits}f}%"


def _format_hours(value: Any) -> str:
    try:
        number = float(value)
    except Exception:
        return "n/a"
    if not math.isfinite(number):
        return "n/a"
    return f"{number:.2f}h"


def _render_prediction_stats_markdown(
    *,
    stats: Dict[str, Any],
    symbol: str,
    engine_label: str,
    limit: int,
    horizon_minutes: Optional[int] = None,
    regime: Optional[str] = None,
) -> str:
    lines: List[str] = [
        "# AEGIS Crypto Evaluation Report",
        "",
        "Measured runtime window summary.",
        "",
        f"- Symbol: `{symbol}`",
        f"- Engine scope: `{engine_label}`",
        f"- Sample limit: `{limit}`",
        f"- Horizon scope: `{int(horizon_minutes)}m`" if horizon_minutes is not None else "- Horizon scope: `all`",
        f"- Regime scope: `{str(regime).strip().lower()}`" if regime else "- Regime scope: `all`",
        f"- Evaluated predictions: `{stats.get('count', 0)}`",
        f"- Trade count: `{stats.get('trade_count', 0)}`",
        f"- Hold count: `{stats.get('hold_count', 0)}`",
        f"- Round-trip cost: `{stats.get('round_trip_cost_bps', 'n/a')}` bps",
        f"- OOS window: `{_format_hours(stats.get('oos_window_hours'))}`",
        "",
        "## KPI",
        "",
        f"- Accuracy: `{_format_ratio_pct(stats.get('accuracy'), 1)}`",
        f"- Win rate: `{_format_ratio_pct(stats.get('win_rate'), 1)}`",
        f"- Avg gross move: `{_format_ratio_pct(stats.get('avg_delta_pct'))}`",
        f"- Gross expectancy: `{_format_ratio_pct(stats.get('gross_expectancy_pct'))}`",
        f"- Net expectancy: `{_format_ratio_pct(stats.get('net_expectancy_pct'))}`",
        f"- Positive net rate: `{_format_ratio_pct(stats.get('positive_net_rate'))}`",
        f"- Max drawdown: `{_format_ratio_pct(stats.get('max_drawdown_pct'))}`",
        f"- Avg probability error: `{_format_ratio_pct(stats.get('avg_probability_error'))}`",
        f"- Brier score: `{(lambda value: f'{float(value):.4f}' if isinstance(value, (int, float)) and math.isfinite(float(value)) else 'n/a')(stats.get('brier_score'))}`",
        "",
    ]
    if engine_label != "trained":
        lines.extend(
            [
                "> Warning: this report is not trained-only. Do not present it as measured trained-model performance.",
                "",
            ]
        )
    per_engine = stats.get("per_engine") or {}
    if per_engine:
        lines.extend(["## Per Engine", ""])
        for name, item in sorted(per_engine.items()):
            lines.append(
                f"- `{name}`: count=`{item.get('count', 0)}`, accuracy=`{_format_ratio_pct(item.get('accuracy'), 1)}`, "
                f"net_expectancy=`{_format_ratio_pct(item.get('net_expectancy_pct'))}`, "
                f"max_drawdown=`{_format_ratio_pct(item.get('max_drawdown_pct'))}`"
            )
        lines.append("")
    per_model = stats.get("per_model") or {}
    if per_model:
        lines.extend(["## Top Models", ""])
        top_models = sorted(
            per_model.items(),
            key=lambda item: (-(item[1] or {}).get("count", 0), -((item[1] or {}).get("accuracy") or 0.0)),
        )[:8]
        for name, item in top_models:
            lines.append(
                f"- `{name}`: count=`{item.get('count', 0)}`, accuracy=`{_format_ratio_pct(item.get('accuracy'), 1)}`"
            )
        lines.append("")
    provenance = stats.get("provenance") or {}
    if provenance:
        requested_vs_trained = provenance.get("requested_vs_trained") or {}
        interval_counts = provenance.get("model_intervals") or {}
        lines.extend(
            [
                "## Provenance",
                "",
                f"- Records with provenance: `{provenance.get('records_with_provenance', 0)}`",
                f"- Demo fallback rows: `{provenance.get('demo_fallback_count', 0)}`",
                f"- Trained horizon fallback rows: `{provenance.get('trained_horizon_fallback_count', 0)}`",
                (
                    "- Requested -> trained horizons: `"
                    + ", ".join(f"{name} ({count})" for name, count in requested_vs_trained.items())
                    + "`"
                )
                if requested_vs_trained
                else "- Requested -> trained horizons: `n/a`",
                (
                    "- Model intervals: `"
                    + ", ".join(f"{name} ({count})" for name, count in interval_counts.items())
                    + "`"
                )
                if interval_counts
                else "- Model intervals: `n/a`",
                "",
            ]
        )
    per_confidence = stats.get("per_confidence_bucket") or {}
    if per_confidence:
        lines.extend(["## Confidence Calibration", ""])
        for name, item in sorted(
            per_confidence.items(),
            key=lambda pair: ({"high": 0, "medium": 1, "low": 2}.get(pair[0], 99), pair[0]),
        ):
            lines.append(
                f"- `{name}`: count=`{item.get('count', 0)}`, accuracy=`{_format_ratio_pct(item.get('accuracy'), 1)}`, "
                f"avg_prob_error=`{_format_ratio_pct(item.get('avg_probability_error'))}`, "
                f"brier=`{(lambda value: f'{float(value):.4f}' if isinstance(value, (int, float)) and math.isfinite(float(value)) else 'n/a')(item.get('brier_score'))}`"
            )
        lines.append("")
    operator_guidance = stats.get("operator_guidance") or {}
    if operator_guidance:
        reasons = [str(reason).strip() for reason in (operator_guidance.get("reasons") or []) if str(reason).strip()]
        lines.extend(
            [
                "## Operating Guidance",
                "",
                f"- Calibration status: `{str(operator_guidance.get('status') or 'unknown').strip().lower() or 'unknown'}`",
                f"- Operator action: `{str(operator_guidance.get('action') or 'unknown').strip().lower() or 'unknown'}`",
                f"- Probability samples: `{int(operator_guidance.get('probability_count') or 0)}`",
                f"- High-confidence samples: `{int(operator_guidance.get('high_confidence_count') or 0)}`",
                f"- Focus bucket: `{str(operator_guidance.get('focus_bucket') or 'n/a').strip().lower() or 'n/a'}`",
                (
                    "- Reasons: `" + ", ".join(reasons) + "`"
                    if reasons
                    else "- Reasons: `n/a`"
                ),
                "",
            ]
        )
    lines.extend(
        [
            "## Interpretation",
            "",
            "- This report measures observed runtime outcomes only.",
            "- It does not prove future profitability or alpha.",
            "- Use trained-only results and net-after-fees metrics for portfolio claims.",
            "",
        ]
    )
    return "\n".join(lines)


@router.get("/predictions/stats/export")
def export_prediction_stats(
    limit: int = Query(200, ge=1, le=1000),
    symbol: Optional[str] = Query(None),
    engine: Optional[str] = Query(None, description="all | trained | demo"),
    horizon_minutes: Optional[int] = Query(None, ge=1, le=10080),
    regime: Optional[str] = Query(None),
    format: Literal["json", "csv", "md"] = Query("json"),
    fee_bps: float = Query(10.0, ge=0.0, le=500.0),
    slippage_bps: float = Query(5.0, ge=0.0, le=500.0),
) -> Response:
    try:
        scope = _normalized_prediction_scope(
            symbol=symbol,
            engine=engine,
            horizon_minutes=horizon_minutes,
            regime=regime,
        )
        stats = recent_stats(
            limit=limit,
            symbol=scope["symbol"],
            engine=scope["engine"],
            horizon_minutes=scope["horizon_minutes"],
            regime=scope["regime"],
            fee_bps=fee_bps,
            slippage_bps=slippage_bps,
        )
        engine_label = normalize_engine_filter(scope["engine"]) or "all"
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Error exporting stats: {exc}") from exc

    safe_symbol = (str(scope["symbol"] or "all") or "all").upper()
    filename_base = f"crypto_stats_{safe_symbol}_{engine_label}"
    if format == "json":
        fee_bps_value = stats.get("fee_bps")
        slippage_bps_value = stats.get("slippage_bps")
        payload = {
            "scope": {
                "symbol": safe_symbol,
                "engine": engine_label,
                "horizon_minutes": scope["horizon_minutes"],
                "regime": str(scope["regime"]).strip().lower() if scope["regime"] else None,
                "limit": limit,
                "fee_bps": fee_bps_value,
                "slippage_bps": slippage_bps_value,
            },
            "stats": stats,
        }
        return Response(
            content=json.dumps(payload, ensure_ascii=False, indent=2),
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="{filename_base}.json"'},
        )
    if format == "md":
        markdown = _render_prediction_stats_markdown(
            stats=stats,
            symbol=safe_symbol,
            engine_label=engine_label,
            limit=limit,
            horizon_minutes=scope["horizon_minutes"],
            regime=scope["regime"],
        )
        return Response(
            content=markdown,
            media_type="text/markdown",
            headers={"Content-Disposition": f'attachment; filename="{filename_base}.md"'},
        )

    rows: List[Dict[str, Any]] = [
        {
            "section": "summary",
            "name": "all",
            "count": stats.get("count"),
            "accuracy": stats.get("accuracy"),
            "avg_delta_pct": stats.get("avg_delta_pct"),
            "net_expectancy_pct": stats.get("net_expectancy_pct"),
            "positive_net_rate": stats.get("positive_net_rate"),
            "max_drawdown_pct": stats.get("max_drawdown_pct"),
            "avg_probability_error": stats.get("avg_probability_error"),
            "brier_score": stats.get("brier_score"),
        }
    ]
    for engine_name, item in sorted((stats.get("per_engine") or {}).items()):
        rows.append(
            {
                "section": "engine",
                "name": engine_name,
                "count": item.get("count"),
                "accuracy": item.get("accuracy"),
                "avg_delta_pct": item.get("avg_delta_pct"),
                "net_expectancy_pct": item.get("net_expectancy_pct"),
                "positive_net_rate": item.get("positive_net_rate"),
                "max_drawdown_pct": item.get("max_drawdown_pct"),
                "avg_probability_error": item.get("avg_probability_error"),
                "brier_score": item.get("brier_score"),
            }
        )
    for model_name, item in sorted((stats.get("per_model") or {}).items()):
        rows.append(
            {
                "section": "model",
                "name": model_name,
                "count": item.get("count"),
                "accuracy": item.get("accuracy"),
                "avg_delta_pct": "",
                "net_expectancy_pct": "",
                "positive_net_rate": "",
                "max_drawdown_pct": "",
                "avg_probability_error": "",
                "brier_score": "",
            }
        )
    rows.append(
        {
            "section": "news",
            "name": "with_news",
            "count": stats.get("with_news_count"),
            "accuracy": stats.get("with_news_accuracy"),
            "avg_delta_pct": "",
            "net_expectancy_pct": "",
            "positive_net_rate": "",
            "max_drawdown_pct": "",
            "avg_probability_error": "",
            "brier_score": "",
        }
    )
    rows.append(
        {
            "section": "news",
            "name": "without_news",
            "count": stats.get("without_news_count"),
            "accuracy": stats.get("without_news_accuracy"),
            "avg_delta_pct": "",
            "net_expectancy_pct": "",
            "positive_net_rate": "",
            "max_drawdown_pct": "",
            "avg_probability_error": "",
            "brier_score": "",
        }
    )
    rows.append(
        {
            "section": "window",
            "name": "runtime_oos",
            "count": stats.get("trade_count"),
            "accuracy": stats.get("accuracy"),
            "avg_delta_pct": stats.get("avg_delta_pct"),
            "net_expectancy_pct": stats.get("net_expectancy_pct"),
            "positive_net_rate": stats.get("positive_net_rate"),
            "max_drawdown_pct": stats.get("max_drawdown_pct"),
            "avg_probability_error": stats.get("avg_probability_error"),
            "brier_score": stats.get("brier_score"),
        }
    )
    provenance = stats.get("provenance") or {}
    rows.append(
        {
            "section": "provenance",
            "name": "with_provenance",
            "count": provenance.get("records_with_provenance"),
            "accuracy": "",
            "avg_delta_pct": "",
            "net_expectancy_pct": "",
            "positive_net_rate": "",
            "max_drawdown_pct": "",
            "avg_probability_error": "",
            "brier_score": "",
        }
    )
    rows.append(
        {
            "section": "provenance",
            "name": "trained_horizon_fallback",
            "count": provenance.get("trained_horizon_fallback_count"),
            "accuracy": "",
            "avg_delta_pct": "",
            "net_expectancy_pct": "",
            "positive_net_rate": "",
            "max_drawdown_pct": "",
            "avg_probability_error": "",
            "brier_score": "",
        }
    )
    for name, count in sorted((provenance.get("requested_vs_trained") or {}).items()):
        rows.append(
            {
                "section": "provenance",
                "name": f"requested_vs_trained:{name}",
                "count": count,
                "accuracy": "",
                "avg_delta_pct": "",
                "net_expectancy_pct": "",
                "positive_net_rate": "",
                "max_drawdown_pct": "",
                "avg_probability_error": "",
                "brier_score": "",
            }
        )
    for name, count in sorted((provenance.get("model_intervals") or {}).items()):
        rows.append(
            {
                "section": "provenance",
                "name": f"model_interval:{name}",
                "count": count,
                "accuracy": "",
                "avg_delta_pct": "",
                "net_expectancy_pct": "",
                "positive_net_rate": "",
                "max_drawdown_pct": "",
                "avg_probability_error": "",
                "brier_score": "",
            }
        )
    for name, item in sorted(
        (stats.get("per_confidence_bucket") or {}).items(),
        key=lambda pair: ({"high": 0, "medium": 1, "low": 2}.get(pair[0], 99), pair[0]),
    ):
        rows.append(
            {
                "section": "confidence",
                "name": name,
                "count": item.get("count"),
                "accuracy": item.get("accuracy"),
                "avg_delta_pct": item.get("avg_delta_pct"),
                "net_expectancy_pct": item.get("net_expectancy_pct"),
                "positive_net_rate": item.get("positive_net_rate"),
                "max_drawdown_pct": item.get("max_drawdown_pct"),
                "avg_probability_error": item.get("avg_probability_error"),
                "brier_score": item.get("brier_score"),
            }
        )
    operator_guidance = stats.get("operator_guidance") or {}
    if operator_guidance:
        rows.append(
            {
                "section": "guidance",
                "name": f"status:{str(operator_guidance.get('status') or 'unknown').strip().lower() or 'unknown'}",
                "count": operator_guidance.get("probability_count"),
                "accuracy": "",
                "avg_delta_pct": "",
                "net_expectancy_pct": "",
                "positive_net_rate": "",
                "max_drawdown_pct": "",
                "avg_probability_error": stats.get("avg_probability_error"),
                "brier_score": stats.get("brier_score"),
            }
        )
        rows.append(
            {
                "section": "guidance",
                "name": f"action:{str(operator_guidance.get('action') or 'unknown').strip().lower() or 'unknown'}",
                "count": operator_guidance.get("high_confidence_count"),
                "accuracy": "",
                "avg_delta_pct": "",
                "net_expectancy_pct": "",
                "positive_net_rate": "",
                "max_drawdown_pct": "",
                "avg_probability_error": "",
                "brier_score": "",
            }
        )
        weakest_bucket = operator_guidance.get("weakest_bucket") if isinstance(operator_guidance.get("weakest_bucket"), dict) else {}
        focus_bucket = str(operator_guidance.get("focus_bucket") or "").strip().lower()
        if focus_bucket:
            rows.append(
                {
                    "section": "guidance",
                    "name": f"focus_bucket:{focus_bucket}",
                    "count": weakest_bucket.get("count") if weakest_bucket else "",
                    "accuracy": weakest_bucket.get("accuracy") if weakest_bucket else "",
                    "avg_delta_pct": "",
                    "net_expectancy_pct": "",
                    "positive_net_rate": "",
                    "max_drawdown_pct": "",
                    "avg_probability_error": weakest_bucket.get("avg_probability_error") if weakest_bucket else "",
                    "brier_score": weakest_bucket.get("brier_score") if weakest_bucket else "",
                }
            )
        for reason in operator_guidance.get("reasons") or []:
            rows.append(
                {
                    "section": "guidance",
                    "name": f"reason:{str(reason).strip().lower()}",
                    "count": "",
                    "accuracy": "",
                    "avg_delta_pct": "",
                    "net_expectancy_pct": "",
                    "positive_net_rate": "",
                    "max_drawdown_pct": "",
                    "avg_probability_error": "",
                    "brier_score": "",
                }
            )

    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer,
        fieldnames=[
            "section",
            "name",
            "count",
            "accuracy",
            "avg_delta_pct",
            "net_expectancy_pct",
            "positive_net_rate",
            "max_drawdown_pct",
            "avg_probability_error",
            "brier_score",
        ],
    )
    writer.writeheader()
    writer.writerows(rows)
    return Response(
        content=buffer.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename_base}.csv"'},
    )


@router.post("/trade", response_model=TradeResponse)
def trade(order: TradeRequest) -> TradeResponse:
    """
    What it does:
    - Executes simulated or live Binance market orders.

    Why it exists:
    - Keep trade execution policy and logging in one auditable endpoint.

    Called from ->
    - Crypto trade UI and contract tests

    Calls ->
    - signed Binance request helper (when enabled)
    - trade log service

    Failure/guard behavior:
    - Live orders are blocked unless `BINANCE_LIVE_TRADING=1`.
    - Returns simulated responses when keys/flags are not eligible.
    """
    if order.quantity <= 0:
        raise HTTPException(status_code=400, detail="quantity must be > 0")

    symbol_pair = _normalize_binance_pair(order.symbol)
    if not symbol_pair:
        raise HTTPException(status_code=400, detail="Missing symbol")
    price_live = _binance_spot_price(symbol_pair)
    api_key = (os.getenv("BINANCE_API_KEY") or "").strip()
    api_secret = (os.getenv("BINANCE_API_SECRET") or "").strip()
    live_trading_enabled = (os.getenv("BINANCE_LIVE_TRADING", "0") or "0").strip().lower() in {"1", "true", "yes", "on"}
    base_url = _binance_base_url()
    requested_mode = order.execution_mode or ("testnet" if order.test else None) or os.getenv("BINANCE_EXECUTION_MODE", "simulated")
    exec_snapshot = _crypto_execution_snapshot(requested_mode=requested_mode)
    execution_mode = exec_snapshot["mode"]
    if execution_mode == "live" and not (api_key and api_secret and live_trading_enabled):
        execution_mode = "simulated"
    if execution_mode == "testnet" and not (api_key and api_secret):
        execution_mode = "simulated"

    mid_price = float(price_live if price_live is not None else (100 + (hash(symbol_pair) % 500)))
    execution_profile = _execution_profile(
        symbol_pair=symbol_pair,
        side=order.side,
        quantity=order.quantity,
        mid_price=mid_price,
        execution_mode=execution_mode,
    )
    estimated_fill_price = float(execution_profile["fill_price"])
    latest_prediction_candidates = list_predictions(limit=5, symbol=symbol_pair)
    latest_prediction = latest_prediction_candidates[0] if latest_prediction_candidates else None
    symbol_trades = list_trades(limit=200, symbol=symbol_pair)
    symbol_pnl = compute_pnl(symbol_trades, lambda _sym: mid_price)
    position_snapshot = _position_snapshot_from_pnl(
        symbol_pair=symbol_pair,
        current_price=mid_price,
        pnl=symbol_pnl,
        trades_count=len(symbol_trades),
    )
    preview_trade = {
        "symbol": symbol_pair,
        "side": order.side,
        "quantity": order.quantity,
        "price": estimated_fill_price,
        "mid_price": round(mid_price, 2),
        "fill_price": estimated_fill_price,
        "spread_bps": execution_profile.get("spread_bps"),
        "slippage_bps": execution_profile.get("slippage_bps"),
        "impact_bps": execution_profile.get("impact_bps"),
        "liquidity_bucket": execution_profile.get("liquidity_bucket"),
        "notional": execution_profile.get("notional"),
        "execution_note": execution_profile.get("execution_note"),
        "execution_mode": execution_mode,
        "status": "SIMULATED",
    }
    risk = _risk_snapshot(
        latest_prediction=latest_prediction if isinstance(latest_prediction, dict) else None,
        latest_trade=preview_trade,
        current_price=mid_price,
        execution_snapshot=exec_snapshot,
        trade_side=order.side,
        order_book_snapshot=None,
    )
    risk_gate = _evaluate_trade_risk_gate(
        symbol_pair=symbol_pair,
        side=order.side,
        quantity=order.quantity,
        current_price=mid_price,
        latest_prediction=latest_prediction if isinstance(latest_prediction, dict) else None,
        risk=risk,
        position_snapshot=position_snapshot,
        policy=_crypto_risk_policy(order),
        enforce_book_checks=False,
        enforce_signal_gate=False,
    )
    if not risk_gate.get("allowed", True):
        blocked = TradeResponse(
            symbol=symbol_pair,
            side=order.side,
            quantity=order.quantity,
            price=estimated_fill_price,
            mid_price=round(mid_price, 2),
            fill_price=estimated_fill_price,
            spread_bps=execution_profile.get("spread_bps"),
            slippage_bps=execution_profile.get("slippage_bps"),
            impact_bps=execution_profile.get("impact_bps"),
            liquidity_bucket=execution_profile.get("liquidity_bucket"),
            notional=execution_profile.get("notional"),
            execution_note=str(execution_profile.get("execution_note") or ""),
            status="REJECTED",
            ts=int(time.time()),
            execution_mode=execution_mode,
            message=f"Risk gate blocked: {risk_gate.get('reason')}",
            risk_gate=risk_gate,
            net_expected_profit_after_costs_pct=_optional_float((risk or {}).get("net_expected_profit_after_costs_pct")),
            net_expected_profit_after_costs_quote=_optional_float((risk or {}).get("net_expected_profit_after_costs_quote")),
        )
        return blocked
    if execution_mode == "live":
        path = "/api/v3/order"
        params = {
            "symbol": symbol_pair,
            "side": order.side,
            "type": "MARKET",
            "quantity": order.quantity,
            "timestamp": int(time.time() * 1000),
        }
        try:
            _binance_signed_request(
                method="POST",
                path=path,
                params=params,
                api_key=api_key,
                api_secret=api_secret,
                base_url=base_url,
            )
            resp = TradeResponse(
                symbol=symbol_pair,
                side=order.side,
                quantity=order.quantity,
                price=estimated_fill_price,
                mid_price=round(mid_price, 2),
                fill_price=estimated_fill_price,
                spread_bps=execution_profile.get("spread_bps"),
                slippage_bps=execution_profile.get("slippage_bps"),
                impact_bps=execution_profile.get("impact_bps"),
                liquidity_bucket=execution_profile.get("liquidity_bucket"),
                notional=execution_profile.get("notional"),
                execution_note=str(execution_profile.get("execution_note") or ""),
                status="SENT_TO_EXCHANGE",
                ts=int(time.time()),
                execution_mode="live",
                message=f"Order sent to Binance • estimated fill {estimated_fill_price:.2f}",
                risk_gate=risk_gate,
                net_expected_profit_after_costs_pct=_optional_float((risk or {}).get("net_expected_profit_after_costs_pct")),
                net_expected_profit_after_costs_quote=_optional_float((risk or {}).get("net_expected_profit_after_costs_quote")),
            )
            try:
                log_trade(
                    {
                        "symbol": resp.symbol,
                        "side": resp.side,
                        "quantity": resp.quantity,
                        "price": resp.price,
                        "mid_price": resp.mid_price,
                        "fill_price": resp.fill_price,
                        "spread_bps": resp.spread_bps,
                        "slippage_bps": resp.slippage_bps,
                        "impact_bps": resp.impact_bps,
                        "liquidity_bucket": resp.liquidity_bucket,
                        "notional": resp.notional,
                        "execution_note": resp.execution_note,
                "status": resp.status,
                "execution_mode": resp.execution_mode,
                "test": order.test,
                "ts": resp.ts,
            }
                )
            except Exception:
                pass
            return resp
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=502, detail=f"Binance order failed: {exc}") from exc

    if execution_mode == "testnet":
        path = "/api/v3/order"
        params = {
            "symbol": symbol_pair,
            "side": order.side,
            "type": "MARKET",
            "quantity": order.quantity,
            "timestamp": int(time.time() * 1000),
        }
        try:
            _binance_signed_request(
                method="POST",
                path=path,
                params=params,
                api_key=api_key,
                api_secret=api_secret,
                base_url=base_url,
            )
            resp = TradeResponse(
                symbol=symbol_pair,
                side=order.side,
                quantity=order.quantity,
                price=estimated_fill_price,
                mid_price=round(mid_price, 2),
                fill_price=estimated_fill_price,
                spread_bps=execution_profile.get("spread_bps"),
                slippage_bps=execution_profile.get("slippage_bps"),
                impact_bps=execution_profile.get("impact_bps"),
                liquidity_bucket=execution_profile.get("liquidity_bucket"),
                notional=execution_profile.get("notional"),
                execution_note=str(execution_profile.get("execution_note") or ""),
                status="SENT_TO_EXCHANGE",
                ts=int(time.time()),
                execution_mode="testnet",
                message=f"Binance test order ok • estimated fill {estimated_fill_price:.2f}",
                risk_gate=risk_gate,
                net_expected_profit_after_costs_pct=_optional_float((risk or {}).get("net_expected_profit_after_costs_pct")),
                net_expected_profit_after_costs_quote=_optional_float((risk or {}).get("net_expected_profit_after_costs_quote")),
            )
            try:
                log_trade(
                    {
                        "symbol": resp.symbol,
                        "side": resp.side,
                        "quantity": resp.quantity,
                        "price": resp.price,
                        "mid_price": resp.mid_price,
                        "fill_price": resp.fill_price,
                        "spread_bps": resp.spread_bps,
                        "slippage_bps": resp.slippage_bps,
                        "impact_bps": resp.impact_bps,
                        "liquidity_bucket": resp.liquidity_bucket,
                        "notional": resp.notional,
                        "execution_note": resp.execution_note,
                        "status": resp.status,
                        "execution_mode": resp.execution_mode,
                        "test": order.test,
                        "ts": resp.ts,
                    }
                )
            except Exception:
                pass
            return resp
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=502, detail=f"Binance test order failed: {exc}") from exc

    resp = TradeResponse(
        symbol=symbol_pair,
        side=order.side,
        quantity=order.quantity,
        price=estimated_fill_price,
        mid_price=round(mid_price, 2),
        fill_price=estimated_fill_price,
        spread_bps=execution_profile.get("spread_bps"),
        slippage_bps=execution_profile.get("slippage_bps"),
        impact_bps=execution_profile.get("impact_bps"),
        liquidity_bucket=execution_profile.get("liquidity_bucket"),
        notional=execution_profile.get("notional"),
        execution_note=str(execution_profile.get("execution_note") or ""),
        status="SIMULATED",
        ts=int(time.time()),
        execution_mode="simulated",
        message=(
            "Simulated trade (set BINANCE_LIVE_TRADING=1 to allow live orders)"
            if api_key and api_secret and not live_trading_enabled and execution_mode != "testnet"
            else "Simulated trade (set BINANCE_API_KEY/SECRET for live or test orders)"
        ),
        risk_gate=risk_gate,
        net_expected_profit_after_costs_pct=_optional_float((risk or {}).get("net_expected_profit_after_costs_pct")),
        net_expected_profit_after_costs_quote=_optional_float((risk or {}).get("net_expected_profit_after_costs_quote")),
    )
    try:
        log_trade(
            {
                "symbol": resp.symbol,
                "side": resp.side,
                        "quantity": resp.quantity,
                        "price": resp.price,
                        "mid_price": resp.mid_price,
                        "fill_price": resp.fill_price,
                        "spread_bps": resp.spread_bps,
                        "slippage_bps": resp.slippage_bps,
                        "impact_bps": resp.impact_bps,
                        "liquidity_bucket": resp.liquidity_bucket,
                        "notional": resp.notional,
                        "execution_note": resp.execution_note,
                        "status": resp.status,
                        "execution_mode": resp.execution_mode,
                        "test": order.test,
                        "ts": resp.ts,
                    }
        )
    except Exception:
        pass
    return resp


@router.post("/trade/preview", response_model=TradePreviewResponse)
def trade_preview(
    order: TradeRequest,
    horizon_minutes: Optional[int] = Query(None, ge=1, le=10080),
    regime: Optional[str] = Query(None),
) -> TradePreviewResponse:
    """
    What it does:
    - Builds a market-style preview for a prospective crypto order without sending it.

    Why it exists:
    - Let the UI show fill/slippage/risk before the user confirms BUY/SELL.

    Called from ->
    - Crypto trade preview card and order confirmation flow

    Notes:
    - No trade log is written here.
    - The result reuses the same execution profile used by live/test/simulated trades.
    """
    preview = _build_trade_preview(order=order, horizon_minutes=horizon_minutes, regime=regime)
    return TradePreviewResponse(**preview)


@router.get("/symbols/meta")
def symbols_meta() -> Dict[str, Any]:
    """Expose accepted Binance quote assets and base-symbol aliases for UI/help."""
    aliases = {k.lower(): v for k, v in _BASE_SYMBOL_ALIASES.items()}
    aliases.update({v.lower(): v for v in _BASE_SYMBOL_ALIASES.values()})
    return {
        "default_quote_asset": "USDT",
        "quote_assets_label": "Binance quote assets",
        "allowed_quote_assets": list(_ALLOWED_BINANCE_QUOTES),
        "base_symbol_aliases": aliases,
        "example_pairs": list(_POPULAR_BINANCE_PAIRS[:12]),
        "popular_pairs": list(_POPULAR_BINANCE_PAIRS),
        "alias_examples": {
            "btc": "BTCUSDT",
            "eth": "ETHUSDT",
            "sol": "SOLUSDT",
            "xrp": "XRPUSDT",
            "doge": "DOGEUSDT",
            "bitcoin": "BTCUSDT",
            "ethereum": "ETHUSDT",
            "bitcoincash": "BCHUSDT",
            "polygon": "MATICUSDT",
        },
    }


@router.get("/trades")
def get_trades(
    limit: int = Query(100, ge=1, le=500),
    symbol: Optional[str] = Query(None),
) -> List[Dict[str, Any]]:
    try:
        return list_trades(limit=limit, symbol=symbol)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Error listing trades: {exc}") from exc


@router.delete("/trades")
def clear_trades_history(_: Optional[str] = Depends(require_api_key)) -> dict:
    """Remove stored simulated trades."""
    try:
        clear_trades()
        return {"status": "ok"}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Error clearing trades: {exc}") from exc


@router.get("/pnl")
def get_pnl(
    limit: int = Query(200, ge=10, le=1000),
    symbol: Optional[str] = Query(None),
) -> Dict[str, Any]:
    try:
        trades = list_trades(limit=limit, symbol=symbol)
        pnl = compute_pnl(trades, _binance_spot_price)
        pnl["trades_count"] = len(trades)
        return pnl
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Error computing P&L: {exc}") from exc


@router.get("/state")
def crypto_state(
    symbol: Optional[str] = Query(None),
    engine: Optional[str] = Query("all", description="all | trained | demo"),
    horizon_minutes: Optional[int] = Query(None, ge=1, le=10080),
    regime: Optional[str] = Query(None),
    execution_mode: Optional[Literal["simulated", "testnet", "live"]] = Query(
        None,
        description="Requested execution mode for the crypto panel snapshot",
    ),
    limit: int = Query(20, ge=1, le=200),
    trade_limit: int = Query(100, ge=1, le=500),
    leaderboard_limit: int = Query(10, ge=1, le=50),
) -> Dict[str, Any]:
    """Return a unified crypto snapshot for chart/chat/trade consumers."""
    try:
        return _crypto_state_snapshot_payload(
            symbol=symbol,
            engine=engine,
            horizon_minutes=horizon_minutes,
            regime=regime,
            execution_mode=execution_mode,
            limit=int(_query_default_value(limit) or 20),
            trade_limit=int(_query_default_value(trade_limit) or 100),
            leaderboard_limit=int(_query_default_value(leaderboard_limit) or 10),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Error building crypto state: {exc}") from exc


@router.get("/stream")
async def crypto_state_stream(
    request: Request,
    symbol: Optional[str] = Query(None),
    engine: Optional[str] = Query("all", description="all | trained | demo"),
    horizon_minutes: Optional[int] = Query(None, ge=1, le=10080),
    regime: Optional[str] = Query(None),
    execution_mode: Optional[Literal["simulated", "testnet", "live"]] = Query(
        None,
        description="Requested execution mode for the crypto panel stream",
    ),
    limit: int = Query(20, ge=1, le=200),
    trade_limit: int = Query(100, ge=1, le=500),
    leaderboard_limit: int = Query(10, ge=1, le=50),
    interval_seconds: float = Query(5.0, ge=1.0, le=60.0),
) -> StreamingResponse:
    """Stream crypto snapshots so the panel can stay in sync without polling."""

    async def event_stream():
        last_signature = ""
        emitted_any_snapshot = False
        scope_symbol = str(symbol or "").strip().upper() or None
        while True:
            if await request.is_disconnected():
                break
            try:
                snapshot = _crypto_state_snapshot_payload(
                    symbol=symbol,
                    engine=engine,
                    horizon_minutes=horizon_minutes,
                    regime=regime,
                    execution_mode=execution_mode,
                    limit=int(_query_default_value(limit) or 20),
                    trade_limit=int(_query_default_value(trade_limit) or 100),
                    leaderboard_limit=int(_query_default_value(leaderboard_limit) or 10),
                )
                signature = _crypto_state_signature(snapshot)
                if not emitted_any_snapshot or signature != last_signature:
                    emitted_any_snapshot = True
                    last_signature = signature
                    yield f"event: crypto_state\ndata: {json.dumps(snapshot, default=str, separators=(',', ':'))}\n\n"
                else:
                    heartbeat = {
                        "type": "heartbeat",
                        "ts": int(time.time()),
                        "symbol": scope_symbol,
                        "scope": snapshot.get("scope"),
                        "summary": snapshot.get("summary"),
                    }
                    yield f"event: heartbeat\ndata: {json.dumps(heartbeat, default=str, separators=(',', ':'))}\n\n"
            except asyncio.CancelledError:
                break
            except Exception as exc:  # noqa: BLE001
                heartbeat = {
                    "type": "heartbeat",
                    "ts": int(time.time()),
                    "symbol": scope_symbol,
                    "error": str(exc),
                }
                yield f"event: heartbeat\ndata: {json.dumps(heartbeat, default=str, separators=(',', ':'))}\n\n"
            await asyncio.sleep(float(interval_seconds))

    headers = {
        "Cache-Control": "no-cache, no-transform",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
    }
    return StreamingResponse(event_stream(), media_type="text/event-stream", headers=headers)


@router.post("/predictions/evaluate")
def evaluate_predictions(
    limit: int = Query(400, ge=10, le=2000),
) -> Dict[str, Any]:
    try:
        return reconcile_due_predictions(price_lookup=_binance_spot_price, limit=limit)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Error evaluando predicciones: {exc}") from exc


@router.get("/live-enriched-snapshot")
def live_enriched_snapshot(
    symbols: str = Query("bitcoin:BTCUSDT,ethereum:ETHUSDT", description="coingecko_id:binance_pair"),
    save_to_csv: bool = Query(False),
) -> Dict[str, Any]:
    pd = _get_pandas()
    meta_module = _get_meta_module()
    specs: List[str] = [s.strip() for s in symbols.split(",") if s.strip()]
    if not specs:
        raise HTTPException(status_code=400, detail="No valid symbols provided.")

    if pd is None or meta_module is None:
        raw_rows = [{
            "symbol": "bitcoin",
            "binance_symbol": "BTCUSDT",
            "current_price": 50000.0,
            "high_24h": 51000.0,
            "low_24h": 49000.0,
            "total_volume": 123456789.0,
            "change_24h": 1.2,
            "timestamp": int(time.time()),
        }]
        return {
            "status": "stub",
            "reason": "pandas/meta_module not available",
            "symbols": specs,
            "rows_count": len(raw_rows),
            "saved_csv": None,
            "raw": raw_rows,
            "enriched": raw_rows,
        }

    raw_rows: List[Dict[str, Any]] = []
    invalid_specs: List[str] = []
    for spec in specs:
        try:
            cg_id, bin_symbol = spec.split(":")
        except ValueError:
            invalid_specs.append(spec)
            continue

        cg: Dict[str, Any] = {}
        try:
            cg = meta_module.fetch_coingecko(cg_id) or {}
        except Exception:
            cg = {}

        bz: Dict[str, Any] = {}
        if _is_valid_binance_symbol(bin_symbol):
            try:
                bz = meta_module.fetch_binance(bin_symbol) or {}
            except Exception:
                bz = {}
        else:
            invalid_specs.append(spec)

        row = {
            "symbol": cg_id,
            "binance_symbol": bin_symbol if _is_valid_binance_symbol(bin_symbol) else None,
            "current_price": cg.get("price") or bz.get("price"),
            "high_24h": cg.get("high_24h") or bz.get("high_24h"),
            "low_24h": cg.get("low_24h") or bz.get("low_24h"),
            "total_volume": cg.get("volume") or bz.get("volume"),
            "change_24h": cg.get("change_24h") or bz.get("change_24h"),
            "timestamp": cg.get("timestamp") or int(time.time()),
        }
        raw_rows.append(row)

    if not raw_rows:
        detail = "Could not fetch live data for any symbol."
        if invalid_specs:
            detail += f" Invalid specs: {', '.join(invalid_specs)}"
        raise HTTPException(status_code=400, detail=detail)

    df_raw = pd.DataFrame(raw_rows)
    try:
        enricher = meta_module.SetaFeatureEnricher()
        df_enriched = enricher.enrich_features(df_raw)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Feature enrichment failed: {exc}") from exc

    saved_path: Optional[str] = None
    if save_to_csv:
        os.makedirs("data", exist_ok=True)
        saved_path = "data/crypto_live_snapshot.csv"
        df_enriched.to_csv(saved_path, index=False)

    return {
        "status": "success",
        "symbols": specs,
        "rows_count": len(raw_rows),
        "saved_csv": saved_path,
        "raw": raw_rows,
        "enriched": df_enriched.to_dict(orient="records"),
    }
