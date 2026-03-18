from __future__ import annotations

"""
Crypto prediction/outcome log store.

Why this module exists:
- Persist prediction telemetry for stats/evaluation endpoints.
- Keep append-only local logs simple and deterministic.
"""

import json
import os
import threading
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, DefaultDict, Dict, List, Optional

from app.services.jsonl_log_utils import ensure_log_dir, iter_recent_lines

LOG_DIR = Path(os.getenv("CRYPTO_PRED_LOG_DIR", "logs"))
LOG_FILE = LOG_DIR / "predictions.jsonl"
OUTCOME_FILE = LOG_DIR / "prediction_outcomes.jsonl"
_lock = threading.Lock()
_ALLOWED_ENGINES = {"trained", "demo"}
DEFAULT_FEE_BPS = float(os.getenv("AEGIS_CRYPTO_FEE_BPS", "10") or "10")
DEFAULT_SLIPPAGE_BPS = float(os.getenv("AEGIS_CRYPTO_SLIPPAGE_BPS", "5") or "5")
DEFAULT_CREDIBILITY_MIN_TRADES = int(os.getenv("AEGIS_CRYPTO_CREDIBILITY_MIN_TRADES", "12") or "12")
DEFAULT_CREDIBILITY_MIN_PRECISION = float(os.getenv("AEGIS_CRYPTO_CREDIBILITY_MIN_PRECISION", "0.60") or "0.60")
DEFAULT_CREDIBILITY_MIN_POSITIVE_NET = float(os.getenv("AEGIS_CRYPTO_CREDIBILITY_MIN_POSITIVE_NET", "0.55") or "0.55")
DEFAULT_CREDIBILITY_MIN_NET_EXPECTANCY = float(os.getenv("AEGIS_CRYPTO_CREDIBILITY_MIN_NET_EXPECTANCY", "0.0") or "0.0")
DEFAULT_CREDIBILITY_MAX_DRAWDOWN = float(os.getenv("AEGIS_CRYPTO_CREDIBILITY_MAX_DRAWDOWN", "0.12") or "0.12")


def normalize_engine_filter(engine: Optional[str]) -> Optional[str]:
    raw = str(engine or "").strip().lower()
    if not raw or raw == "all":
        return None
    if raw not in _ALLOWED_ENGINES:
        raise ValueError("engine must be one of: all, trained, demo")
    return raw


def _matches_scope(
    item: Dict[str, Any],
    *,
    symbol: Optional[str],
    engine_filter: Optional[str],
    horizon_minutes: Optional[int],
    regime: Optional[str],
) -> bool:
    sym = symbol.upper() if symbol else None
    if sym and (item.get("symbol") or "").upper() != sym:
        return False
    item_engine = str(item.get("engine") or "unknown").strip().lower() or "unknown"
    if engine_filter and item_engine != engine_filter:
        return False
    if horizon_minutes is not None:
        try:
            if int(item.get("horizon_minutes") or 0) != int(horizon_minutes):
                return False
        except Exception:
            return False
    if regime:
        item_regime = str(item.get("regime") or "").strip().lower()
        if item_regime != regime.strip().lower():
            return False
    return True


def log_prediction(entry: Dict[str, Any]) -> str:
    ensure_log_dir(LOG_DIR)
    entry = dict(entry)
    entry.setdefault("id", f"pred_{int(time.time()*1e6)}")
    entry.setdefault("ts", int(time.time()))
    with _lock:
        with LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry["id"]


def list_predictions(
    limit: int = 50,
    symbol: Optional[str] = None,
    engine: Optional[str] = None,
    horizon_minutes: Optional[int] = None,
    regime: Optional[str] = None,
) -> List[Dict[str, Any]]:
    ensure_log_dir(LOG_DIR)
    if not LOG_FILE.exists():
        return []
    out: List[Dict[str, Any]] = []
    engine_filter = normalize_engine_filter(engine)
    for line in iter_recent_lines(LOG_FILE):
        try:
            item = json.loads(line)
        except Exception:
            continue
        if not _matches_scope(
            item,
            symbol=symbol,
            engine_filter=engine_filter,
            horizon_minutes=horizon_minutes,
            regime=regime,
        ):
            continue
        out.append(item)
        if len(out) >= limit:
            break
    out.sort(key=lambda x: x.get("ts") or 0, reverse=True)
    return out


def get_prediction(pid: str) -> Optional[Dict[str, Any]]:
    for p in list_predictions(limit=500):
        if p.get("id") == pid:
            return p
    return None


def log_outcome(entry: Dict[str, Any]) -> str:
    ensure_log_dir(LOG_DIR)
    entry = dict(entry)
    entry.setdefault("id", f"out_{int(time.time()*1e6)}")
    entry.setdefault("ts", int(time.time()))
    with _lock:
        with OUTCOME_FILE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry["id"]


def list_outcomes(
    limit: int = 50,
    symbol: Optional[str] = None,
    engine: Optional[str] = None,
    horizon_minutes: Optional[int] = None,
    regime: Optional[str] = None,
) -> List[Dict[str, Any]]:
    ensure_log_dir(LOG_DIR)
    if not OUTCOME_FILE.exists():
        return []
    out: List[Dict[str, Any]] = []
    engine_filter = normalize_engine_filter(engine)
    for line in iter_recent_lines(OUTCOME_FILE):
        try:
            item = json.loads(line)
        except Exception:
            continue
        if not _matches_scope(
            item,
            symbol=symbol,
            engine_filter=engine_filter,
            horizon_minutes=horizon_minutes,
            regime=regime,
        ):
            continue
        out.append(item)
        if len(out) >= limit:
            break
    out.sort(key=lambda x: x.get("ts") or 0, reverse=True)
    return out


def _aggregate_outcome_stats(outs: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not outs:
        return {"count": 0, "accuracy": None, "avg_delta_pct": None}

    hits = [o for o in outs if o.get("hit") is True]
    acc = len(hits) / len(outs) if outs else None
    deltas = [o.get("delta_pct") for o in outs if isinstance(o.get("delta_pct"), (int, float))]
    avg_delta = sum(deltas) / len(deltas) if deltas else None
    return {
        "count": len(outs),
        "accuracy": acc,
        "avg_delta_pct": avg_delta,
    }


def _as_float(value: Any) -> Optional[float]:
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(value)
    except Exception:
        return None


def _as_int(value: Any) -> Optional[int]:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return int(value)
    try:
        return int(value)
    except Exception:
        return None


def _normalize_regime(value: Any) -> Optional[str]:
    text = str(value or "").strip().lower()
    return text or None


def _effective_decision(item: Dict[str, Any]) -> str:
    action = str(item.get("action_decision") or "").strip().upper()
    if action in {"BUY", "SELL", "HOLD"}:
        return action
    return str(item.get("decision") or "").strip().upper()


def _signal_return_pct(outcome: Dict[str, Any]) -> Optional[float]:
    decision = _effective_decision(outcome)
    delta_pct = _as_float(outcome.get("delta_pct"))
    if delta_pct is None:
        return None
    if decision == "BUY":
        return delta_pct
    if decision == "SELL":
        return -delta_pct
    if decision == "HOLD":
        return 0.0
    return None


def _max_drawdown_pct(returns_pct: List[float]) -> Optional[float]:
    if not returns_pct:
        return None
    equity = 0.0
    peak = 0.0
    max_drawdown = 0.0
    for ret in returns_pct:
        equity += ret
        if equity > peak:
            peak = equity
        drawdown = peak - equity
        if drawdown > max_drawdown:
            max_drawdown = drawdown
    return max_drawdown


def _trade_eval_stats(
    outs: List[Dict[str, Any]],
    *,
    fee_bps: float,
    slippage_bps: float,
) -> Dict[str, Any]:
    round_trip_cost_bps = max(0.0, float(fee_bps)) * 2.0 + max(0.0, float(slippage_bps)) * 2.0
    round_trip_cost_pct = round_trip_cost_bps / 10000.0
    trade_net_returns: List[float] = []
    trade_gross_returns: List[float] = []
    hold_count = 0
    positive_net = 0
    ordered_trade_rows = sorted(
        [
            row for row in outs
            if _effective_decision(row) in {"BUY", "SELL"}
            and _signal_return_pct(row) is not None
        ],
        key=lambda row: int(row.get("ts") or 0),
    )
    for row in ordered_trade_rows:
        gross = _signal_return_pct(row)
        if gross is None:
            continue
        net = gross - round_trip_cost_pct
        trade_gross_returns.append(gross)
        trade_net_returns.append(net)
        if net > 0:
            positive_net += 1

    for row in outs:
        if _effective_decision(row) == "HOLD":
            hold_count += 1

    trade_count = len(trade_net_returns)
    gross_expectancy = sum(trade_gross_returns) / trade_count if trade_count else None
    net_expectancy = sum(trade_net_returns) / trade_count if trade_count else None
    net_cumulative = sum(trade_net_returns) if trade_count else None
    positive_net_rate = positive_net / trade_count if trade_count else None
    trade_win_rate = positive_net_rate
    max_drawdown = _max_drawdown_pct(trade_net_returns)
    trade_rows_with_ts = [row for row in outs if isinstance(row.get("ts"), (int, float))]
    window_start_ts = min((int(row.get("ts") or 0) for row in trade_rows_with_ts), default=None)
    window_end_ts = max((int(row.get("ts") or 0) for row in trade_rows_with_ts), default=None)
    window_seconds = (
        max(0, int(window_end_ts) - int(window_start_ts))
        if window_start_ts and window_end_ts
        else None
    )
    return {
        "fee_bps": float(fee_bps),
        "slippage_bps": float(slippage_bps),
        "round_trip_cost_bps": round_trip_cost_bps,
        "round_trip_cost_pct": round_trip_cost_pct,
        "trade_count": trade_count,
        "hold_count": hold_count,
        "gross_expectancy_pct": gross_expectancy,
        "net_expectancy_pct": net_expectancy,
        "net_cumulative_pct": net_cumulative,
        "positive_net_rate": trade_win_rate,
        "max_drawdown_pct": max_drawdown,
        "oos_window_start_ts": window_start_ts,
        "oos_window_end_ts": window_end_ts,
        "oos_window_seconds": window_seconds,
        "oos_window_hours": (window_seconds / 3600.0) if window_seconds is not None else None,
    }


def _group_trade_eval(
    outs: List[Dict[str, Any]],
    *,
    fee_bps: float,
    slippage_bps: float,
    key_fn,
) -> Dict[str, Dict[str, Any]]:
    buckets: DefaultDict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in outs:
        try:
            key = str(key_fn(row) or "").strip()
        except Exception:
            key = ""
        if not key:
            continue
        buckets[key].append(row)
    return {
        key: {
            **_aggregate_outcome_stats(rows),
            **_trade_eval_stats(rows, fee_bps=fee_bps, slippage_bps=slippage_bps),
        }
        for key, rows in sorted(buckets.items())
    }


def _evaluate_threshold_strategy(
    outs: List[Dict[str, Any]],
    *,
    buy_threshold: float,
    sell_threshold: float,
    fee_bps: float,
    slippage_bps: float,
) -> Dict[str, Any]:
    fee_value = _as_float(fee_bps)
    slippage_value = _as_float(slippage_bps)
    fee_bps = DEFAULT_FEE_BPS if fee_value is None else max(0.0, fee_value)
    slippage_bps = DEFAULT_SLIPPAGE_BPS if slippage_value is None else max(0.0, slippage_value)
    candidates = [
        row for row in sorted(outs, key=lambda item: int(item.get("ts") or 0))
        if _as_float(row.get("probability_up")) is not None and _as_float(row.get("delta_pct")) is not None
    ]
    hold_count = 0
    hits = 0
    net_returns: List[float] = []
    gross_returns: List[float] = []
    round_trip_cost_pct = (max(0.0, float(fee_bps)) * 2.0 + max(0.0, float(slippage_bps)) * 2.0) / 10000.0

    for row in candidates:
        prob_up = _as_float(row.get("probability_up"))
        delta_pct = _as_float(row.get("delta_pct"))
        if prob_up is None or delta_pct is None:
            continue
        if prob_up >= buy_threshold:
            gross = delta_pct
        elif prob_up <= sell_threshold:
            gross = -delta_pct
        else:
            hold_count += 1
            continue
        gross_returns.append(gross)
        net = gross - round_trip_cost_pct
        net_returns.append(net)
        if gross > 0:
            hits += 1

    trade_count = len(net_returns)
    positive_net = sum(1 for value in net_returns if value > 0)
    precision = (hits / trade_count) if trade_count else None
    return {
        "buy_threshold": float(buy_threshold),
        "sell_threshold": float(sell_threshold),
        "count": len(candidates),
        "trade_count": trade_count,
        "hold_count": hold_count,
        "hold_rate": (hold_count / len(candidates)) if candidates else None,
        "precision": precision,
        "gross_expectancy_pct": (sum(gross_returns) / trade_count) if trade_count else None,
        "net_expectancy_pct": (sum(net_returns) / trade_count) if trade_count else None,
        "positive_net_rate": (positive_net / trade_count) if trade_count else None,
        "max_drawdown_pct": _max_drawdown_pct(net_returns),
        "round_trip_cost_pct": round_trip_cost_pct,
    }


def _optimize_thresholds_from_rows(
    outs: List[Dict[str, Any]],
    *,
    fee_bps: float,
    slippage_bps: float,
    min_trades: int,
) -> Optional[Dict[str, Any]]:
    if not outs:
        return None
    thresholds = [round(value / 1000.0, 3) for value in range(550, 951, 25)]
    best: Optional[Dict[str, Any]] = None
    for buy_threshold in thresholds:
        sell_threshold = round(1.0 - buy_threshold, 3)
        if sell_threshold >= buy_threshold:
            continue
        candidate = _evaluate_threshold_strategy(
            outs,
            buy_threshold=buy_threshold,
            sell_threshold=sell_threshold,
            fee_bps=fee_bps,
            slippage_bps=slippage_bps,
        )
        if candidate["trade_count"] < max(1, int(min_trades)):
            continue
        if best is None:
            best = candidate
            continue
        current_key = (
            float(candidate.get("precision") or -1.0),
            float(candidate.get("positive_net_rate") or -1.0),
            float(candidate.get("net_expectancy_pct") or -999.0),
            int(candidate.get("trade_count") or 0),
        )
        best_key = (
            float(best.get("precision") or -1.0),
            float(best.get("positive_net_rate") or -1.0),
            float(best.get("net_expectancy_pct") or -999.0),
            int(best.get("trade_count") or 0),
        )
        if current_key > best_key:
            best = candidate
    return best


def optimize_thresholds(
    *,
    limit: int = 1000,
    symbol: Optional[str] = None,
    engine: Optional[str] = "trained",
    horizon_minutes: Optional[int] = None,
    regime: Optional[str] = None,
    fee_bps: float = DEFAULT_FEE_BPS,
    slippage_bps: float = DEFAULT_SLIPPAGE_BPS,
    min_trades: int = 8,
) -> Optional[Dict[str, Any]]:
    min_trades_value = _as_int(min_trades)
    min_trades = 8 if min_trades_value is None else max(1, int(min_trades_value))
    outs = list_outcomes(
        limit=limit,
        symbol=symbol,
        engine=engine,
        horizon_minutes=horizon_minutes,
        regime=regime,
    )
    return _optimize_thresholds_from_rows(
        outs,
        fee_bps=fee_bps,
        slippage_bps=slippage_bps,
        min_trades=min_trades,
    )


def scope_leaderboard(
    *,
    limit: int = 2000,
    engine: Optional[str] = "trained",
    fee_bps: float = DEFAULT_FEE_BPS,
    slippage_bps: float = DEFAULT_SLIPPAGE_BPS,
    min_trades: int = 8,
    top_n: int = 20,
) -> List[Dict[str, Any]]:
    min_trades_value = _as_int(min_trades)
    min_trades = 8 if min_trades_value is None else max(1, int(min_trades_value))
    top_n_value = _as_int(top_n)
    top_n = 20 if top_n_value is None else max(1, int(top_n_value))
    outs = list_outcomes(limit=limit, engine=engine)
    buckets: DefaultDict[tuple[str, int, str], List[Dict[str, Any]]] = defaultdict(list)
    for row in outs:
        symbol = str(row.get("symbol") or "").strip().upper()
        horizon = _as_int(row.get("horizon_minutes"))
        regime = _normalize_regime(row.get("regime")) or "unknown"
        if not symbol or horizon is None:
            continue
        buckets[(symbol, horizon, regime)].append(row)

    rows: List[Dict[str, Any]] = []
    for (symbol, horizon, regime), group in buckets.items():
        strategy = _optimize_thresholds_from_rows(
            group,
            fee_bps=fee_bps,
            slippage_bps=slippage_bps,
            min_trades=min_trades,
        )
        if strategy is None:
            continue
        score = (
            float(strategy.get("precision") or 0.0) * 0.55
            + float(strategy.get("positive_net_rate") or 0.0) * 0.25
            + max(0.0, float(strategy.get("net_expectancy_pct") or 0.0)) * 5.0
        )
        rows.append(
            {
                "symbol": symbol,
                "horizon_minutes": horizon,
                "regime": regime,
                "score": round(score, 6),
                **strategy,
            }
        )

    rows.sort(
        key=lambda row: (
            float(row.get("score") or 0.0),
            float(row.get("precision") or 0.0),
            float(row.get("net_expectancy_pct") or -999.0),
            int(row.get("trade_count") or 0),
        ),
        reverse=True,
    )
    return rows[: max(1, int(top_n))]


def assess_scope_credibility(
    *,
    limit: int = 1000,
    symbol: Optional[str] = None,
    engine: Optional[str] = "trained",
    horizon_minutes: Optional[int] = None,
    regime: Optional[str] = None,
    fee_bps: float = DEFAULT_FEE_BPS,
    slippage_bps: float = DEFAULT_SLIPPAGE_BPS,
    min_trades: int = DEFAULT_CREDIBILITY_MIN_TRADES,
    min_precision: float = DEFAULT_CREDIBILITY_MIN_PRECISION,
    min_positive_net_rate: float = DEFAULT_CREDIBILITY_MIN_POSITIVE_NET,
    min_net_expectancy_pct: float = DEFAULT_CREDIBILITY_MIN_NET_EXPECTANCY,
    max_drawdown_pct: float = DEFAULT_CREDIBILITY_MAX_DRAWDOWN,
) -> Dict[str, Any]:
    min_trades_value = _as_int(min_trades)
    min_trades = DEFAULT_CREDIBILITY_MIN_TRADES if min_trades_value is None else max(1, int(min_trades_value))
    outs = list_outcomes(
        limit=limit,
        symbol=symbol,
        engine=engine,
        horizon_minutes=horizon_minutes,
        regime=regime,
    )
    recommendation = _optimize_thresholds_from_rows(
        outs,
        fee_bps=fee_bps,
        slippage_bps=slippage_bps,
        min_trades=min_trades,
    )
    reasons: List[str] = []
    if recommendation is None:
        return {
            "status": "insufficient_history",
            "actionable": False,
            "should_abstain": False,
            "score": None,
            "reasons": ["not_enough_trained_scope_history"],
            "trade_count": 0,
            "recommendation": None,
            "thresholds": {
                "min_trades": min_trades,
                "min_precision": float(min_precision),
                "min_positive_net_rate": float(min_positive_net_rate),
                "min_net_expectancy_pct": float(min_net_expectancy_pct),
                "max_drawdown_pct": float(max_drawdown_pct),
            },
        }

    trade_count = int(recommendation.get("trade_count") or 0)
    precision = _as_float(recommendation.get("precision"))
    positive_net_rate = _as_float(recommendation.get("positive_net_rate"))
    net_expectancy_pct = _as_float(recommendation.get("net_expectancy_pct"))
    max_drawdown_value = _as_float(recommendation.get("max_drawdown_pct"))

    if trade_count < min_trades:
        reasons.append("trade_count_below_minimum")
    if precision is not None and precision < float(min_precision):
        reasons.append("precision_below_threshold")
    if positive_net_rate is not None and positive_net_rate < float(min_positive_net_rate):
        reasons.append("positive_net_rate_below_threshold")
    if net_expectancy_pct is not None and net_expectancy_pct <= float(min_net_expectancy_pct):
        reasons.append("net_expectancy_not_positive")
    if max_drawdown_value is not None and max_drawdown_value > float(max_drawdown_pct):
        reasons.append("drawdown_above_threshold")

    actionable = not reasons
    status = "trusted" if actionable else "blocked"
    if not actionable and trade_count >= min_trades and precision is not None and precision >= max(0.0, float(min_precision) - 0.05):
        status = "cautious"
        actionable = True
        reasons = ["marginal_scope_quality"]

    score: Optional[float] = None
    if recommendation is not None:
        precision_score = max(0.0, min(1.0, float(precision or 0.0)))
        positive_net_score = max(0.0, min(1.0, float(positive_net_rate or 0.0)))
        expectancy_score = max(0.0, min(1.0, (float(net_expectancy_pct or 0.0) + 0.02) / 0.04))
        drawdown_score = max(0.0, min(1.0, 1.0 - (float(max_drawdown_value or 0.0) / max(float(max_drawdown_pct), 1e-6))))
        score = round(
            precision_score * 0.45
            + positive_net_score * 0.25
            + expectancy_score * 0.20
            + drawdown_score * 0.10,
            4,
        )

    return {
        "status": status,
        "actionable": actionable,
        "should_abstain": status == "blocked",
        "score": score,
        "reasons": reasons,
        "trade_count": trade_count,
        "recommendation": recommendation,
        "thresholds": {
            "min_trades": min_trades,
            "min_precision": float(min_precision),
            "min_positive_net_rate": float(min_positive_net_rate),
            "min_net_expectancy_pct": float(min_net_expectancy_pct),
            "max_drawdown_pct": float(max_drawdown_pct),
        },
    }


def recent_stats(
    limit: int = 100,
    symbol: Optional[str] = None,
    engine: Optional[str] = None,
    horizon_minutes: Optional[int] = None,
    regime: Optional[str] = None,
    fee_bps: float = DEFAULT_FEE_BPS,
    slippage_bps: float = DEFAULT_SLIPPAGE_BPS,
) -> Dict[str, Any]:
    fee_bps_value = _as_float(fee_bps)
    slippage_bps_value = _as_float(slippage_bps)
    fee_bps = DEFAULT_FEE_BPS if fee_bps_value is None else max(0.0, fee_bps_value)
    slippage_bps = DEFAULT_SLIPPAGE_BPS if slippage_bps_value is None else max(0.0, slippage_bps_value)
    horizon_filter = _as_int(horizon_minutes)
    regime_filter = _normalize_regime(regime)
    engine_filter = normalize_engine_filter(engine)
    outs = list_outcomes(
        limit=limit,
        symbol=symbol,
        engine=engine_filter,
        horizon_minutes=horizon_filter,
        regime=regime_filter,
    )
    if not outs:
        return {
            "count": 0,
            "accuracy": None,
            "avg_delta_pct": None,
            "per_model": {},
            "per_engine": {},
            "engine_filter": engine_filter or "all",
            "horizon_filter": horizon_filter,
            "regime_filter": regime_filter,
            "engines_present": [],
            "fee_bps": float(fee_bps),
            "slippage_bps": float(slippage_bps),
            "round_trip_cost_bps": max(0.0, float(fee_bps)) * 2.0 + max(0.0, float(slippage_bps)) * 2.0,
            "round_trip_cost_pct": (max(0.0, float(fee_bps)) * 2.0 + max(0.0, float(slippage_bps)) * 2.0) / 10000.0,
            "trade_count": 0,
            "hold_count": 0,
            "gross_expectancy_pct": None,
            "net_expectancy_pct": None,
            "net_cumulative_pct": None,
            "positive_net_rate": None,
            "max_drawdown_pct": None,
            "oos_window_start_ts": None,
            "oos_window_end_ts": None,
            "oos_window_seconds": None,
            "oos_window_hours": None,
            "trained_count": 0,
            "demo_count": 0,
            "trained_accuracy": None,
            "demo_accuracy": None,
        }

    aggregate = _aggregate_outcome_stats(outs)

    per_model: DefaultDict[str, Dict[str, Any]] = defaultdict(lambda: {"count": 0, "hits": 0})
    per_engine_rows: DefaultDict[str, List[Dict[str, Any]]] = defaultdict(list)
    for o in outs:
        model = o.get("model") or "unknown"
        per_model[model]["count"] += 1
        if o.get("hit") is True:
            per_model[model]["hits"] += 1
        engine = str(o.get("engine") or "unknown").strip().lower() or "unknown"
        per_engine_rows[engine].append(o)

    per_model_stats = {
        m: {"count": v["count"], "accuracy": (v["hits"] / v["count"] if v["count"] else None)}
        for m, v in per_model.items()
    }
    per_engine_stats = {
        engine: {
            **_aggregate_outcome_stats(rows),
            **_trade_eval_stats(rows, fee_bps=fee_bps, slippage_bps=slippage_bps),
        }
        for engine, rows in per_engine_rows.items()
    }
    trade_eval = _trade_eval_stats(outs, fee_bps=fee_bps, slippage_bps=slippage_bps)

    with_news = [o for o in outs if o.get("news_sentiment") is not None]
    without_news = [o for o in outs if o.get("news_sentiment") is None]

    def _acc(xs):
        hits_local = [x for x in xs if x.get("hit") is True]
        return len(hits_local) / len(xs) if xs else None

    trained = per_engine_stats.get("trained") or {"count": 0, "accuracy": None}
    demo = per_engine_stats.get("demo") or {"count": 0, "accuracy": None}

    return {
        **aggregate,
        "per_model": per_model_stats,
        "per_engine": per_engine_stats,
        "per_symbol": _group_trade_eval(
            outs,
            fee_bps=fee_bps,
            slippage_bps=slippage_bps,
            key_fn=lambda row: str(row.get("symbol") or "").upper(),
        ),
        "per_horizon": _group_trade_eval(
            outs,
            fee_bps=fee_bps,
            slippage_bps=slippage_bps,
            key_fn=lambda row: (
                f"{int(row.get('horizon_minutes'))}m"
                if isinstance(row.get("horizon_minutes"), (int, float))
                else ""
            ),
        ),
        "per_regime": _group_trade_eval(
            outs,
            fee_bps=fee_bps,
            slippage_bps=slippage_bps,
            key_fn=lambda row: str(row.get("regime") or "").strip().lower(),
        ),
        "engine_filter": engine_filter or "all",
        "horizon_filter": horizon_filter,
        "regime_filter": regime_filter,
        "engines_present": sorted(per_engine_stats.keys()),
        **trade_eval,
        "trained_count": trained.get("count", 0),
        "demo_count": demo.get("count", 0),
        "trained_accuracy": trained.get("accuracy"),
        "demo_accuracy": demo.get("accuracy"),
        "with_news_accuracy": _acc(with_news),
        "without_news_accuracy": _acc(without_news),
        "with_news_count": len(with_news),
        "without_news_count": len(without_news),
    }


def pair_predictions_with_outcomes(
    limit: int = 50,
    symbol: Optional[str] = None,
    engine: Optional[str] = None,
    horizon_minutes: Optional[int] = None,
    regime: Optional[str] = None,
) -> List[Dict[str, Any]]:
    engine_filter = normalize_engine_filter(engine)
    preds = list_predictions(
        limit=limit,
        symbol=symbol,
        engine=engine_filter,
        horizon_minutes=horizon_minutes,
        regime=regime,
    )
    outs = list_outcomes(
        limit=limit * 2,
        symbol=symbol,
        engine=engine_filter,
        horizon_minutes=horizon_minutes,
        regime=regime,
    )
    out_map = {o.get("log_id"): o for o in outs if o.get("log_id")}
    merged: List[Dict[str, Any]] = []
    for p in preds:
        out = out_map.get(p.get("id"))
        merged.append({**p, "outcome": out} if out else p)
    return merged


def clear_predictions_and_outcomes() -> None:
    ensure_log_dir(LOG_DIR)
    with _lock:
        if LOG_FILE.exists():
            LOG_FILE.unlink()
        if OUTCOME_FILE.exists():
            OUTCOME_FILE.unlink()
