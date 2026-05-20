from __future__ import annotations

"""
Crypto runtime orchestration helpers.

Why this module exists:
- Build a single crypto state snapshot from predictions, outcomes, trades and risk metadata.
- Reconcile predictions whose horizon already elapsed without relying only on per-request timers.
- Provide an optional background reconciler for continuous, durable outcome capture.
"""

import os
import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from app.services.crypto_prediction_log import (
    assess_scope_credibility,
    list_outcomes,
    list_predictions,
    log_outcome,
    normalize_engine_filter,
    optimize_thresholds,
    pair_predictions_with_outcomes,
    recent_stats,
    scope_leaderboard,
)
from app.services.crypto_trade_log import compute_pnl, list_trades

_RECONCILER_STOP = threading.Event()
_RECONCILER_THREAD: Optional[threading.Thread] = None
_RECONCILER_LOCK = threading.Lock()


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _optional_text(value: Any) -> Optional[str]:
    text = str(value or "").strip()
    return text or None


def _optional_int(value: Any) -> Optional[int]:
    if value in {None, ""}:
        return None
    try:
        return int(value)
    except Exception:
        return None


def _optional_float(value: Any) -> Optional[float]:
    if value in {None, ""}:
        return None
    try:
        return float(value)
    except Exception:
        return None


def _normalize_scope(
    *,
    symbol: Optional[str],
    engine: Optional[str],
    horizon_minutes: Optional[int],
    regime: Optional[str],
) -> Dict[str, Any]:
    engine_filter = normalize_engine_filter(engine)
    return {
        "symbol": _optional_text(symbol),
        "engine": engine_filter,
        "horizon_minutes": _optional_int(horizon_minutes),
        "regime": _optional_text(regime),
    }


def _prediction_ref(row: Dict[str, Any] | None, *, source: str) -> Dict[str, Any] | None:
    if not isinstance(row, dict):
        return None
    log_id = str(row.get("log_id") or row.get("id") or "").strip()
    if not log_id:
        return None
    return {
        "log_id": log_id,
        "symbol": str(row.get("symbol") or "").strip().upper() or None,
        "horizon_minutes": _optional_int(row.get("horizon_minutes")),
        "ts": _optional_int(row.get("ts")),
        "source": str(source or "").strip() or None,
        "decision": str(row.get("decision") or row.get("action_decision") or "").strip().upper() or None,
        "model": str(row.get("model") or "").strip() or None,
        "predicted_price": row.get("predicted_price"),
        "current_price": row.get("current_price"),
        "actual_price": row.get("actual_price"),
        "delta_pct": _optional_float(row.get("delta_pct")),
        "gross_return_pct": _optional_float(row.get("gross_return_pct")),
        "net_return_pct": _optional_float(row.get("net_return_pct")),
        "round_trip_cost_pct": _optional_float(row.get("round_trip_cost_pct")),
        "probability_error": _optional_float(row.get("probability_error")),
        "brier_component": _optional_float(row.get("brier_component")),
        "confidence_bucket": str(row.get("confidence_bucket") or "").strip().lower() or None,
        "realized_direction": str(row.get("realized_direction") or "").strip().lower() or None,
        "hit": row.get("hit") if isinstance(row.get("hit"), bool) else None,
    }


def _trade_ref(row: Dict[str, Any] | None) -> Dict[str, Any] | None:
    if not isinstance(row, dict):
        return None
    symbol = str(row.get("symbol") or "").strip().upper()
    if not symbol:
        return None
    fill_price = _optional_float(row.get("fill_price"))
    if fill_price is None:
        fill_price = _optional_float(row.get("price"))
    return {
        "id": str(row.get("id") or "").strip() or None,
        "symbol": symbol,
        "side": str(row.get("side") or "").strip().upper() or None,
        "quantity": _optional_float(row.get("quantity")),
        "price": fill_price,
        "mid_price": _optional_float(row.get("mid_price")),
        "fill_price": _optional_float(row.get("fill_price")),
        "spread_bps": _optional_float(row.get("spread_bps")),
        "slippage_bps": _optional_float(row.get("slippage_bps")),
        "impact_bps": _optional_float(row.get("impact_bps")),
        "liquidity_bucket": str(row.get("liquidity_bucket") or "").strip() or None,
        "notional": _optional_float(row.get("notional")),
        "execution_mode": str(row.get("execution_mode") or "").strip().lower() or None,
        "execution_note": str(row.get("execution_note") or "").strip() or None,
        "status": str(row.get("status") or "").strip().upper() or None,
        "ts": _optional_int(row.get("ts")),
    }


def _confidence_bucket(probability: Optional[float]) -> Optional[str]:
    if probability is None:
        return None
    confidence = max(probability, 1.0 - probability)
    if confidence >= 0.8:
        return "high"
    if confidence >= 0.62:
        return "medium"
    return "low"


def _risk_snapshot(
    *,
    latest_prediction: Dict[str, Any] | None,
    latest_trade: Dict[str, Any] | None,
    current_price: Optional[float],
    trade_side: Optional[str] = None,
    execution_snapshot: Optional[Dict[str, Any]] = None,
    order_book_snapshot: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any] | None:
    if not isinstance(latest_prediction, dict):
        return None

    entry_price = (
        _optional_float((latest_trade or {}).get("fill_price"))
        or _optional_float((latest_trade or {}).get("price"))
        or _optional_float(latest_prediction.get("current_price"))
        or _optional_float(current_price)
    )
    predicted_price = _optional_float(latest_prediction.get("predicted_price"))
    if entry_price is None or entry_price <= 0 or predicted_price is None or predicted_price <= 0:
        return None

    decision = str(
        trade_side
        or (latest_trade or {}).get("side")
        or latest_prediction.get("action_decision")
        or latest_prediction.get("decision")
        or "HOLD"
    ).strip().upper()
    probability = _optional_float(latest_prediction.get("probability_up"))
    confidence = None
    if probability is not None:
        confidence = max(probability, 1.0 - probability)

    raw_move_pct = (predicted_price - entry_price) / entry_price
    projected_move_pct = abs(raw_move_pct)
    projected_direction = "up" if raw_move_pct > 0 else "down" if raw_move_pct < 0 else "flat"
    tradeable = decision in {"BUY", "SELL"}

    execution_drag_bps = 0.0
    if isinstance(latest_trade, dict):
        for key in ("spread_bps", "slippage_bps", "impact_bps"):
            val = _optional_float(latest_trade.get(key))
            if val is not None:
                execution_drag_bps += max(0.0, val)
    if execution_drag_bps <= 0.0:
        mode = str((execution_snapshot or {}).get("mode") or "simulated").strip().lower()
        execution_drag_bps = {
            "simulated": 12.0,
            "testnet": 8.0,
            "live": 5.0,
        }.get(mode, 10.0)
    execution_drag_pct = execution_drag_bps / 10000.0

    order_notional = _optional_float((latest_trade or {}).get("notional"))
    if order_notional is None or order_notional <= 0:
        qty = _optional_float((latest_trade or {}).get("quantity")) or 0.0
        if qty > 0 and entry_price > 0:
            order_notional = qty * entry_price
    bid_notional = _optional_float((order_book_snapshot or {}).get("bid_notional"))
    ask_notional = _optional_float((order_book_snapshot or {}).get("ask_notional"))
    if bid_notional is None:
        bid_notional = 0.0
    if ask_notional is None:
        ask_notional = 0.0
    visible_liquidity_notional = max(0.0, bid_notional + ask_notional)
    side_liquidity_notional = ask_notional if decision == "BUY" else bid_notional if decision == "SELL" else visible_liquidity_notional / 2.0
    if side_liquidity_notional <= 0:
        side_liquidity_notional = max(visible_liquidity_notional, order_notional or 0.0, 1.0)
    order_notional = max(0.0, float(order_notional or 0.0))
    order_size_pct = (order_notional / visible_liquidity_notional * 100.0) if visible_liquidity_notional > 0 else 0.0
    book_consumption_pct = (order_notional / side_liquidity_notional * 100.0) if side_liquidity_notional > 0 else 0.0
    participation_pct = (order_notional / (order_notional + side_liquidity_notional) * 100.0) if (order_notional + side_liquidity_notional) > 0 else 0.0
    others_pct = max(0.0, 100.0 - participation_pct)
    remaining_liquidity = max(0.0, side_liquidity_notional - order_notional)

    spread_bps = _optional_float((latest_trade or {}).get("spread_bps")) or _optional_float((order_book_snapshot or {}).get("spread_bps")) or 0.0
    imbalance = _optional_float((order_book_snapshot or {}).get("imbalance"))
    imbalance_penalty = abs((imbalance or 0.5) - 0.5) * 20.0
    impact_score = min(100.0, max(0.0, (min(order_size_pct, 100.0) * 0.55) + (min(execution_drag_bps, 60.0) * 0.5) + (min(spread_bps, 60.0) * 0.25) + imbalance_penalty))

    favorable_move_pct = projected_move_pct
    if decision == "BUY" and raw_move_pct < 0:
        favorable_move_pct = 0.0
    elif decision == "SELL" and raw_move_pct > 0:
        favorable_move_pct = 0.0
    elif decision == "HOLD":
        favorable_move_pct = projected_move_pct

    confidence_multiplier = 0.75
    if confidence is not None:
        if confidence >= 0.7:
            confidence_multiplier = 0.55
        elif confidence >= 0.6:
            confidence_multiplier = 0.7
        else:
            confidence_multiplier = 0.9

    stop_loss_pct = None
    if tradeable:
        stop_loss_pct = max(0.004, favorable_move_pct * confidence_multiplier, execution_drag_pct * 1.5 + 0.0015)

    net_edge_pct = favorable_move_pct - execution_drag_pct
    take_profit_pct = favorable_move_pct if tradeable else None
    expected_pnl_pct = net_edge_pct if tradeable else None
    max_loss_pct = (stop_loss_pct + execution_drag_pct) if stop_loss_pct is not None else None
    net_expected_profit_after_costs_quote = (
        round(order_notional * expected_pnl_pct, 2)
        if tradeable and expected_pnl_pct is not None and order_notional > 0
        else None
    )
    execution_cost_quote = round(order_notional * execution_drag_pct, 2) if order_notional > 0 else None

    if decision == "BUY":
        target_price = predicted_price if predicted_price >= entry_price else entry_price * (1.0 + projected_move_pct)
        stop_price = entry_price * (1.0 - stop_loss_pct) if stop_loss_pct is not None else None
    elif decision == "SELL":
        target_price = predicted_price if predicted_price <= entry_price else entry_price * (1.0 - projected_move_pct)
        stop_price = entry_price * (1.0 + stop_loss_pct) if stop_loss_pct is not None else None
    else:
        target_price = predicted_price
        stop_price = None

    risk_reward = None
    if tradeable and stop_loss_pct not in {None, 0}:
        try:
            risk_reward = (take_profit_pct or 0.0) / float(stop_loss_pct)
        except Exception:
            risk_reward = None

    return {
        "decision": decision,
        "tradeable": tradeable,
        "entry_price": round(entry_price, 2),
        "target_price": round(float(target_price), 2) if target_price is not None else None,
        "stop_price": round(float(stop_price), 2) if stop_price is not None else None,
        "predicted_price": round(predicted_price, 2),
        "current_price": round(_optional_float(current_price) or entry_price, 2),
        "raw_move_pct": round(raw_move_pct, 6),
        "projected_move_pct": round(projected_move_pct, 6),
        "projected_direction": projected_direction,
        "favorable_move_pct": round(favorable_move_pct, 6),
        "execution_drag_bps": round(execution_drag_bps, 2),
        "execution_drag_pct": round(execution_drag_pct, 6),
        "net_edge_pct": round(net_edge_pct, 6),
        "take_profit_pct": round(take_profit_pct, 6) if take_profit_pct is not None else None,
        "stop_loss_pct": round(stop_loss_pct, 6) if stop_loss_pct is not None else None,
        "expected_pnl_pct": round(expected_pnl_pct, 6) if expected_pnl_pct is not None else None,
        "net_expected_profit_after_costs_pct": round(expected_pnl_pct, 6) if expected_pnl_pct is not None else None,
        "net_expected_profit_after_costs_quote": net_expected_profit_after_costs_quote,
        "execution_cost_quote": execution_cost_quote,
        "max_loss_pct": round(max_loss_pct, 6) if max_loss_pct is not None else None,
        "risk_reward": round(risk_reward, 2) if risk_reward is not None else None,
        "probability_up": probability,
        "confidence": confidence,
        "confidence_bucket": _confidence_bucket(probability),
        "execution_mode": str((latest_trade or {}).get("execution_mode") or (execution_snapshot or {}).get("mode") or "simulated").strip().lower(),
        "liquidity_bucket": (latest_trade or {}).get("liquidity_bucket"),
        "order_notional": round(order_notional, 2),
        "visible_liquidity_notional": round(visible_liquidity_notional, 2),
        "side_liquidity_notional": round(side_liquidity_notional, 2),
        "order_size_pct": round(order_size_pct, 4),
        "book_consumption_pct": round(book_consumption_pct, 4),
        "participation_pct": round(participation_pct, 4),
        "others_pct": round(others_pct, 4),
        "remaining_liquidity": round(remaining_liquidity, 2),
        "pre_trade_price": round(_optional_float(current_price) or entry_price, 2),
        "post_trade_estimate": round(entry_price, 2),
        "impact_score": round(impact_score, 2),
        "spread_bps": round(spread_bps, 2),
        "imbalance": round(imbalance, 4) if imbalance is not None else None,
        "latest_trade_ref": _trade_ref(latest_trade),
    }


def _execution_snapshot() -> Dict[str, Any]:
    mode = str(os.getenv("BINANCE_EXECUTION_MODE", "simulated") or "simulated").strip().lower()
    if mode not in {"simulated", "testnet", "live"}:
        mode = "simulated"
    api_key = (os.getenv("BINANCE_API_KEY") or "").strip()
    api_secret = (os.getenv("BINANCE_API_SECRET") or "").strip()
    live_trading_enabled = _env_bool("BINANCE_LIVE_TRADING", False)
    return {
        "mode": mode,
        "credentials_present": bool(api_key and api_secret),
        "live_trading_enabled": live_trading_enabled,
        "testnet_enabled": mode == "testnet",
        "live_enabled": mode == "live" and live_trading_enabled,
        "simulated": mode == "simulated",
    }


def build_crypto_state_snapshot(
    *,
    symbol: Optional[str] = None,
    engine: Optional[str] = None,
    horizon_minutes: Optional[int] = None,
    regime: Optional[str] = None,
    limit: int = 20,
    trade_limit: int = 100,
    leaderboard_limit: int = 10,
    price_lookup: Optional[Callable[[str], Optional[float]]] = None,
    order_book_lookup: Optional[Callable[[str], Optional[Dict[str, Any]]]] = None,
    execution_snapshot: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Build a unified crypto snapshot from the durable logs.

    The snapshot keeps the chart / prediction / trade / stats surfaces aligned on
    the same scope (symbol + horizon + regime).
    """
    scope = _normalize_scope(
        symbol=symbol,
        engine=engine,
        horizon_minutes=horizon_minutes,
        regime=regime,
    )
    engine_filter = scope["engine"]
    stats_limit = max(1, int(limit))
    trade_limit = max(1, int(trade_limit))
    leaderboard_limit = max(1, int(leaderboard_limit))
    price_lookup = price_lookup or (lambda _sym: None)

    predictions = pair_predictions_with_outcomes(
        limit=stats_limit,
        symbol=scope["symbol"],
        engine=engine_filter,
        horizon_minutes=scope["horizon_minutes"],
        regime=scope["regime"],
    )
    outcomes = list_outcomes(
        limit=max(stats_limit * 2, trade_limit),
        symbol=scope["symbol"],
        engine=engine_filter,
        horizon_minutes=scope["horizon_minutes"],
        regime=scope["regime"],
    )
    stats = recent_stats(
        limit=stats_limit,
        symbol=scope["symbol"],
        engine=engine_filter,
        horizon_minutes=scope["horizon_minutes"],
        regime=scope["regime"],
    )
    engine_for_policy = engine_filter or "trained"
    thresholds = optimize_thresholds(
        limit=max(stats_limit * 10, 200),
        symbol=scope["symbol"],
        engine=engine_for_policy,
        horizon_minutes=scope["horizon_minutes"],
        regime=scope["regime"],
        min_trades=8,
    )
    credibility = assess_scope_credibility(
        limit=max(stats_limit * 10, 200),
        symbol=scope["symbol"],
        engine=engine_for_policy,
        horizon_minutes=scope["horizon_minutes"],
        regime=scope["regime"],
        min_trades=8,
    )
    leaderboard = scope_leaderboard(
        limit=max(leaderboard_limit * 20, 100),
        engine=engine_for_policy,
        top_n=leaderboard_limit,
    )
    trades = list_trades(limit=trade_limit, symbol=scope["symbol"])
    pnl = compute_pnl(trades, price_lookup)
    exec_snapshot = execution_snapshot or _execution_snapshot()

    current_price = None
    if scope["symbol"]:
        try:
            current_price = price_lookup(scope["symbol"])
        except Exception:
            current_price = None

    order_book = None
    if scope["symbol"] and callable(order_book_lookup):
        try:
            order_book = order_book_lookup(scope["symbol"])
        except Exception:
            order_book = None

    latest_prediction = predictions[0] if predictions else None
    latest_trade = trades[0] if trades else None
    if isinstance(latest_prediction, dict) and latest_prediction.get("outcome"):
        latest_outcome = latest_prediction.get("outcome")
    else:
        latest_outcome = outcomes[0] if outcomes else None
    risk = _risk_snapshot(
        latest_prediction=latest_prediction,
        latest_trade=latest_trade,
        current_price=current_price,
        execution_snapshot=exec_snapshot,
        order_book_snapshot=order_book,
    )

    summary = {
        "predictions_count": len(predictions),
        "outcomes_count": len(outcomes),
        "trades_count": len(trades),
        "has_order_book": bool(order_book),
        "has_price": current_price is not None,
        "has_prediction": bool(latest_prediction),
        "has_outcome": bool(latest_outcome),
        "has_risk": bool(risk),
        "engine": engine_filter or "all",
    }

    return {
        "scope": scope,
        "summary": summary,
        "current_price": current_price,
        "execution": exec_snapshot,
        "latest_prediction": latest_prediction,
        "latest_prediction_ref": _prediction_ref(latest_prediction, source="history"),
        "latest_outcome": latest_outcome,
        "latest_outcome_ref": _prediction_ref(latest_outcome, source="history"),
        "latest_trade": latest_trade,
        "latest_trade_ref": _trade_ref(latest_trade),
        "order_book": order_book,
        "risk": risk,
        "predictions": predictions,
        "outcomes": outcomes,
        "stats": stats,
        "thresholds": thresholds,
        "credibility": credibility,
        "leaderboard": leaderboard,
        "trades": trades,
        "pnl": pnl,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def reconcile_due_predictions(
    *,
    price_lookup: Callable[[str], Optional[float]],
    limit: int = 400,
    now_ts: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Reconcile overdue predictions against the current price.

    This is durable in the sense that it scans the stored logs on each run, so
    a process restart does not lose pending outcomes.
    """
    if price_lookup is None:
        raise ValueError("price_lookup is required")

    scan_limit = max(1, int(limit))
    preds = list_predictions(limit=scan_limit)
    outs = list_outcomes(limit=max(scan_limit * 4, 200))
    already = {str(o.get("log_id") or "").strip() for o in outs if str(o.get("log_id") or "").strip()}
    now_value = int(now_ts if now_ts is not None else time.time())

    evaluated = 0
    missing_price = 0
    skipped = 0
    updated_ids: List[str] = []

    for p in preds:
        pid = str(p.get("id") or "").strip()
        if not pid or pid in already:
            continue

        horizon = _optional_int(p.get("horizon_minutes"))
        ts = _optional_int(p.get("ts"))
        if horizon is None or horizon <= 0 or ts is None or ts <= 0:
            skipped += 1
            continue
        if now_value - ts < horizon * 60:
            skipped += 1
            continue

        sym = str(p.get("symbol") or "").strip().upper()
        if not sym:
            skipped += 1
            continue

        live = price_lookup(sym)
        if live is None or float(live) <= 0:
            missing_price += 1
            continue

        current = float(p.get("current_price") or live)
        delta_pct = (float(live) - current) / current if current else 0.0
        decision = str(p.get("decision") or p.get("action_decision") or "HOLD").strip().upper()
        hit = None
        if decision == "BUY":
            hit = float(live) > current
        elif decision == "SELL":
            hit = float(live) < current
        elif decision == "HOLD":
            hit = abs(delta_pct) < 0.01

        log_outcome(
            {
                "log_id": pid,
                "symbol": sym,
                "horizon_minutes": horizon,
                "decision": decision,
                "model_decision": p.get("model_decision") or p.get("decision"),
                "action_decision": p.get("action_decision") or p.get("decision"),
                "probability_up": p.get("probability_up"),
                "probability_base": p.get("probability_base"),
                "model": p.get("model"),
                "predicted_price": p.get("predicted_price") or current,
                "actual_price": float(live),
                "delta_pct": delta_pct,
                "hit": hit,
                "price_source": p.get("price_source"),
                "engine": p.get("engine"),
                "news_sentiment": p.get("news_sentiment"),
                "n_news_used": p.get("n_news_used"),
                "regime": p.get("regime"),
                "buy_threshold": p.get("buy_threshold"),
                "sell_threshold": p.get("sell_threshold"),
                "threshold_strategy": p.get("threshold_strategy"),
                "credibility": p.get("credibility"),
                "execution_margin": p.get("execution_margin"),
                "threshold_edge": p.get("threshold_edge"),
                "execution_gate_reason": p.get("execution_gate_reason"),
                "consensus": p.get("consensus"),
                "ts": int(time.time()),
            }
        )
        evaluated += 1
        updated_ids.append(pid)
        already.add(pid)

    return {
        "evaluated": evaluated,
        "skipped": skipped,
        "missing_price": missing_price,
        "updated_ids": updated_ids,
        "scanned": len(preds),
    }


def start_background_reconciler(
    *,
    price_lookup: Callable[[str], Optional[float]],
    interval_seconds: Optional[float] = None,
    limit: int = 400,
) -> bool:
    """
    Start a daemon reconciler thread.

    The loop is optional and disabled unless the caller explicitly starts it.
    """
    global _RECONCILER_THREAD
    if price_lookup is None:
        return False
    interval = float(interval_seconds if interval_seconds is not None else os.getenv("AEGIS_CRYPTO_RECONCILER_INTERVAL", "30") or 30)
    if interval <= 0:
        return False

    with _RECONCILER_LOCK:
        if _RECONCILER_THREAD and _RECONCILER_THREAD.is_alive():
            return False
        _RECONCILER_STOP.clear()

        def _runner() -> None:
            while not _RECONCILER_STOP.wait(interval):
                try:
                    reconcile_due_predictions(price_lookup=price_lookup, limit=limit)
                except Exception:
                    # Best-effort loop: never crash the app.
                    pass

        thread = threading.Thread(target=_runner, name="crypto-reconciler", daemon=True)
        _RECONCILER_THREAD = thread
        thread.start()
        return True


def stop_background_reconciler(timeout_s: float = 2.0) -> bool:
    global _RECONCILER_THREAD
    with _RECONCILER_LOCK:
        thread = _RECONCILER_THREAD
        if thread is None:
            return False
        _RECONCILER_STOP.set()
    if thread.is_alive():
        thread.join(max(0.0, float(timeout_s)))
    with _RECONCILER_LOCK:
        if thread is _RECONCILER_THREAD:
            _RECONCILER_THREAD = None
    return True
