from __future__ import annotations

"""
Crypto data/prediction/trade API surface.

Why this module exists:
- Provide market data and prediction endpoints for the crypto panel.
- Keep demo-safe trading behavior and telemetry in one router.
"""

import hashlib
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
from fastapi import APIRouter, Depends, HTTPException, Query, Response
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
from app.services.crypto_trade_log import clear_trades, compute_pnl, list_trades, log_trade
from app.utils.ml_helpers import sentiment_score as _sentiment_score

_pd = None
_meta_module = None
_trained_bundle_cache: Dict[str, Dict[str, Any]] = {}
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
    consensus_metrics: Optional[Dict[str, Any]],
    threshold_rec: Optional[Dict[str, Any]],
    require_trained: bool,
    adaptive_policy: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    confidence = max(0.0, min(1.0, max(p_up, 1.0 - p_up)))
    if confidence >= 0.8:
        confidence_bucket = "high"
    elif confidence >= 0.62:
        confidence_bucket = "medium"
    else:
        confidence_bucket = "low"

    route_mode = "trained" if prediction_engine == "trained" else "demo"
    route_reason = "trained_model_available" if prediction_engine == "trained" else "demo_fallback"
    if require_trained and prediction_engine != "trained":
        route_reason = "trained_required_unavailable"
    if isinstance(credibility, dict) and bool(credibility.get("should_abstain")):
        route_reason = "credibility_abstain"
    elif action_decision in {"BUY", "SELL"} and threshold_rec:
        route_reason = "threshold_edge_passed"
    elif action_decision == "HOLD" and model_decision in {"BUY", "SELL"}:
        route_reason = str((credibility or {}).get("status") or "gated")

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
        "consensus": consensus_metrics,
        "gates": {
            "execution_margin": _execution_margin_for_credibility(credibility),
            "required_support_ratio": (
                _consensus_requirements_for_credibility(credibility).get("min_support_ratio")
                if credibility is not None
                else None
            ),
            "required_max_spread": (
                _consensus_requirements_for_credibility(credibility).get("max_spread")
                if credibility is not None
                else None
            ),
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


class TradeResponse(BaseModel):
    symbol: str
    side: Literal["BUY", "SELL"]
    quantity: float
    price: Optional[float]
    status: Literal["FILLED", "SENT_TO_EXCHANGE", "SIMULATED", "REJECTED"]
    ts: int
    message: Optional[str] = None


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
            "trained_model_type": trained.model_type,
            "trained_artifact": trained.artifact_path,
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
    action_decision = model_decision
    execution_margin = 0.0
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
        execution_margin = _execution_margin_for_credibility(credibility)
        consensus_requirements = _consensus_requirements_for_credibility(credibility)
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
        consensus_metrics={
            **(consensus_metrics or {}),
            **{
                "required_support_ratio": (consensus_requirements or {}).get("min_support_ratio"),
                "max_spread": (consensus_requirements or {}).get("max_spread"),
            },
        },
        threshold_rec=threshold_rec,
        require_trained=require_trained,
        adaptive_policy=adaptive_policy,
    )
    if isinstance(raw, dict):
        raw["model_decision"] = model_decision
        raw["action_decision"] = action_decision
        raw["actionable"] = actionable
        raw["credibility"] = credibility
        raw["execution_margin"] = execution_margin
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
                "execution_margin": execution_margin,
                "threshold_edge": threshold_edge,
                "execution_gate_reason": execution_gate_reason,
                "consensus": (raw or {}).get("consensus"),
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
                        "execution_margin": execution_margin,
                        "threshold_edge": threshold_edge,
                        "execution_gate_reason": execution_gate_reason,
                        "consensus": (raw or {}).get("consensus"),
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
            "execution_margin": execution_margin,
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
            "recommendation": rec,
            "credibility": credibility,
            "adaptive": adaptive,
            "summary": {
                "route_mode": "trained" if credibility and credibility.get("status") != "blocked" else "demo",
                "should_abstain": bool(credibility and credibility.get("should_abstain")),
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

    if api_key and api_secret:
        if not order.test and not live_trading_enabled:
            price = price_live if price_live is not None else (100 + (hash(symbol_pair) % 500))
            return TradeResponse(
                symbol=symbol_pair,
                side=order.side,
                quantity=order.quantity,
                price=round(price or 0.0, 2),
                status="SIMULATED",
                ts=int(time.time()),
                message="Simulated trade (set BINANCE_LIVE_TRADING=1 to allow live orders)",
            )
        path = "/api/v3/order/test" if order.test else "/api/v3/order"
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
            status: Literal["FILLED", "SENT_TO_EXCHANGE", "SIMULATED", "REJECTED"] = (
                "SIMULATED" if order.test else "SENT_TO_EXCHANGE"
            )
            msg = "Binance test order ok" if order.test else "Order sent to Binance"
            resp = TradeResponse(
                symbol=symbol_pair,
                side=order.side,
                quantity=order.quantity,
                price=round(price_live or 0.0, 2),
                status=status,
                ts=int(time.time()),
                message=msg,
            )
            try:
                log_trade(
                    {
                        "symbol": resp.symbol,
                        "side": resp.side,
                        "quantity": resp.quantity,
                        "price": resp.price,
                        "status": resp.status,
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

    price = price_live if price_live is not None else (100 + (hash(symbol_pair) % 500))
    resp = TradeResponse(
        symbol=symbol_pair,
        side=order.side,
        quantity=order.quantity,
        price=round(price, 2),
        status="SIMULATED",
        ts=int(time.time()),
        message="Simulated trade (set BINANCE_API_KEY/SECRET for live or test orders)",
    )
    try:
        log_trade(
            {
                "symbol": resp.symbol,
                "side": resp.side,
                "quantity": resp.quantity,
                "price": resp.price,
                "status": resp.status,
                "test": order.test,
                "ts": resp.ts,
            }
        )
    except Exception:
        pass
    return resp


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


@router.post("/predictions/evaluate")
def evaluate_predictions(
    limit: int = Query(400, ge=10, le=2000),
) -> Dict[str, Any]:
    try:
        preds = list_predictions(limit=limit)
        outs = list_outcomes(limit=limit * 2)
        already = {o.get("log_id") for o in outs if o.get("log_id")}
        now_ts = int(time.time())
        evaluated = 0
        for p in preds:
            pid = p.get("id")
            if not pid or pid in already:
                continue
            horizon = int(p.get("horizon_minutes") or 0)
            ts = int(p.get("ts") or 0)
            if horizon <= 0 or ts <= 0 or now_ts - ts < horizon * 60:
                continue
            sym = (p.get("symbol") or "").upper()
            if not sym:
                continue
            live = _binance_spot_price(sym) or p.get("current_price")
            if live is None:
                continue
            current = p.get("current_price") or live
            decision = p.get("decision") or "HOLD"
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
                    "log_id": pid,
                    "symbol": sym,
                    "horizon_minutes": horizon,
                    "decision": decision,
                    "probability_up": p.get("probability_up"),
                    "model": p.get("model"),
                    "predicted_price": current,
                    "actual_price": live,
                    "delta_pct": delta_pct,
                    "hit": hit,
                }
            )
            evaluated += 1
        return {"evaluated": evaluated}
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
