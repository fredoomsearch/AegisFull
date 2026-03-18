from __future__ import annotations

"""
Training script for AEGIS crypto ensemble models.

What changed in the strict refactor:
- Uses rolling OHLCV-derived feature windows instead of single-row assumptions.
- Uses walk-forward time-series validation by default.
- Trains the stacking model on out-of-fold base-model predictions.
- Writes model provenance (dataset hash / horizon / interval / validation mode).
- Reports grouped after-fees evaluation by symbol and regime.
"""

import argparse
import hashlib
import json
import logging
import os
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Dict, List, Sequence, Tuple

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, classification_report, f1_score, roc_auc_score
from sklearn.model_selection import TimeSeriesSplit
from sklearn.neural_network import MLPClassifier

from app.core import meta as meta_module

try:
    from xgboost import XGBClassifier  # type: ignore

    HAS_XGB = True
except Exception:
    XGBClassifier = None
    HAS_XGB = False

try:
    from catboost import CatBoostClassifier  # type: ignore

    HAS_CAT = True
except Exception:
    CatBoostClassifier = None
    HAS_CAT = False

from app.core.meta import (
    CALIBRATED_MODEL_PATH,
    CAT_MODEL_PATH,
    DL_MODEL_PATH,
    MODEL_DIR,
    RF_MODEL_PATH,
    SetaFeatureEnricher,
    XGB_MODEL_PATH,
)

logging.basicConfig(level=logging.INFO, format="[train] %(message)s")
log = logging.getLogger("train_models")


ARTIFACTS_DIR = Path(os.getenv("CRYPTO_ARTIFACTS_DIR", "artifacts/crypto_models"))
BUY_THRESHOLD = 0.63
SELL_THRESHOLD = 0.37
TRAIN_EXTERNAL_FEATURES = os.getenv("AEGIS_CRYPTO_TRAIN_EXTERNAL_FEATURES", "").strip().lower() in {"1", "true", "yes", "on"}


def load_csv(csv_path: str) -> pd.DataFrame:
    if not os.path.exists(csv_path):
        raise FileNotFoundError(csv_path)
    df = pd.read_csv(csv_path, low_memory=False)
    for col in ["timestamp", "date", "time", "last_updated", "datetime"]:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce", utc=True)
            if col != "timestamp" and "timestamp" not in df.columns:
                df["timestamp"] = df[col]
    return df


def _sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _normalize_symbol(value: Any) -> str:
    text = str(value or "").strip().upper()
    text = "".join(ch for ch in text if ch.isalnum())
    if not text:
        return "BTCUSDT"
    for quote in ("USDT", "USDC", "BUSD", "FDUSD", "TUSD", "BTC", "ETH"):
        if text.endswith(quote) and len(text) > len(quote):
            return text
    return f"{text}USDT"


def _infer_interval_minutes(ts_series: pd.Series, override: int | None = None) -> int:
    if override and override > 0:
        return int(override)
    ts = pd.to_datetime(ts_series, errors="coerce", utc=True).dropna().sort_values()
    if len(ts) < 2:
        return 1
    diffs = ts.diff().dropna().dt.total_seconds() / 60.0
    diffs = diffs[diffs > 0]
    if diffs.empty:
        return 1
    return max(1, int(round(float(diffs.median()))))


def _label_market_regime(df: pd.DataFrame) -> pd.Series:
    if df.empty:
        return pd.Series(dtype="object")
    ema_fast = pd.to_numeric(df.get("ema_20"), errors="coerce").fillna(pd.to_numeric(df.get("current_price"), errors="coerce"))
    ema_slow = pd.to_numeric(df.get("ema_50"), errors="coerce").fillna(ema_fast)
    rolling_vol = pd.to_numeric(df.get("rolling_vol_14"), errors="coerce").fillna(0.0)
    try:
        low_cut = float(rolling_vol.quantile(0.33))
        high_cut = float(rolling_vol.quantile(0.67))
    except Exception:
        low_cut = 0.0
        high_cut = 0.0
    vol_regime = np.where(
        rolling_vol >= high_cut,
        "high_vol",
        np.where(rolling_vol <= low_cut, "low_vol", "mid_vol"),
    )
    trend_regime = np.where(
        ema_fast > ema_slow * 1.002,
        "bull",
        np.where(ema_fast < ema_slow * 0.998, "bear", "sideways"),
    )
    return pd.Series([f"{trend}_{vol}" for trend, vol in zip(trend_regime, vol_regime)], index=df.index)


def _prepare_symbol_frame(
    df_symbol: pd.DataFrame,
    *,
    horizon_minutes: int,
    interval_minutes: int | None,
) -> Tuple[pd.DataFrame, int]:
    if df_symbol.empty:
        return pd.DataFrame(), 1
    work = df_symbol.copy()
    if "timestamp" not in work.columns:
        work["timestamp"] = pd.date_range(
            start="1970-01-01T00:00:00Z",
            periods=len(work),
            freq="min",
            tz="UTC",
        )
    else:
        work["timestamp"] = pd.to_datetime(work["timestamp"], errors="coerce", utc=True)
        work["timestamp"] = work["timestamp"].ffill().bfill()
    work = work.sort_values("timestamp").reset_index(drop=True)
    symbol_value = _normalize_symbol(work.get("binance_symbol", work.get("symbol", "BTCUSDT")).iloc[0] if len(work) else "BTCUSDT")
    work["symbol"] = symbol_value
    work["binance_symbol"] = symbol_value

    previous_external = getattr(meta_module, "CRYPTO_EXTERNAL_FEATURES", False)
    if not TRAIN_EXTERNAL_FEATURES:
        meta_module.CRYPTO_EXTERNAL_FEATURES = False
    try:
        enricher = SetaFeatureEnricher()
        enriched = enricher.enrich_features(work)
    finally:
        meta_module.CRYPTO_EXTERNAL_FEATURES = previous_external

    step_minutes = _infer_interval_minutes(enriched.get("timestamp", work["timestamp"]), override=interval_minutes)
    horizon_steps = max(1, int(round(horizon_minutes / max(step_minutes, 1))))
    enriched["future_price"] = pd.to_numeric(enriched.get("current_price"), errors="coerce").shift(-horizon_steps)
    current_price = pd.to_numeric(enriched.get("current_price"), errors="coerce")
    enriched["future_return_pct"] = (enriched["future_price"] / current_price) - 1.0
    enriched["price_direction"] = (enriched["future_return_pct"] > 0).astype(int)
    enriched["market_regime"] = _label_market_regime(enriched).fillna("sideways_mid_vol")
    enriched["horizon_minutes"] = int(horizon_minutes)
    enriched["interval_minutes"] = int(step_minutes)
    enriched["timestamp_source"] = "timestamp" if "timestamp" in df_symbol.columns else "row_order"
    enriched = enriched.iloc[:-horizon_steps] if horizon_steps < len(enriched) else enriched.iloc[0:0]
    return enriched, step_minutes


def prepare_training_frame(
    df_raw: pd.DataFrame,
    *,
    horizon_minutes: int,
    interval_minutes: int | None,
) -> Tuple[pd.DataFrame, List[str], Dict[str, int]]:
    if df_raw.empty:
        raise ValueError("CSV dataset is empty")
    source = df_raw.copy()
    if "binance_symbol" not in source.columns and "symbol" not in source.columns:
        source["symbol"] = "BTCUSDT"
    group_col = "binance_symbol" if "binance_symbol" in source.columns else "symbol"

    prepared_frames: List[pd.DataFrame] = []
    per_symbol_interval: Dict[str, int] = {}
    for _, group in source.groupby(group_col, sort=False):
        frame, step_minutes = _prepare_symbol_frame(
            group,
            horizon_minutes=horizon_minutes,
            interval_minutes=interval_minutes,
        )
        if frame.empty:
            continue
        symbol = str(frame["binance_symbol"].iloc[0]).upper()
        per_symbol_interval[symbol] = step_minutes
        prepared_frames.append(frame)

    if not prepared_frames:
        raise ValueError("No prepared samples available after horizon labeling")

    training_frame = pd.concat(prepared_frames, ignore_index=True)
    training_frame = training_frame.sort_values(["timestamp", "binance_symbol"]).reset_index(drop=True)

    exclude = {
        "price_direction",
        "future_price",
        "future_return_pct",
        "horizon_minutes",
        "interval_minutes",
        "timestamp",
    }
    feature_cols = [
        col
        for col in list(training_frame.select_dtypes(include=[np.number]).columns)
        if col not in exclude
    ]
    if not feature_cols:
        raise ValueError("No numeric feature columns available after preparation")

    return training_frame, feature_cols, per_symbol_interval


def _version_artifacts(meta_path: Path, model_paths: List[str]) -> None:
    try:
        ts = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
        version_dir = ARTIFACTS_DIR / ts
        version_dir.mkdir(parents=True, exist_ok=True)

        for p in model_paths:
            src = Path(p)
            if src.exists():
                shutil.copy2(src, version_dir / src.name)
        if meta_path.exists():
            shutil.copy2(meta_path, version_dir / meta_path.name)

        latest_path = ARTIFACTS_DIR / "latest.txt"
        previous_path = ARTIFACTS_DIR / "previous.txt"
        if latest_path.exists():
            try:
                prev_val = latest_path.read_text(encoding="utf-8").strip()
                if prev_val:
                    previous_path.write_text(prev_val, encoding="utf-8")
            except Exception:
                log.debug("Could not update previous.txt", exc_info=True)
        latest_path.write_text(ts, encoding="utf-8")
        log.info("Versioned artifacts under %s", version_dir)
    except Exception as exc:  # noqa: BLE001
        log.warning("Could not version artifacts: %s", exc)


def _binary_metrics(y_true: np.ndarray, y_pred: np.ndarray, y_prob: np.ndarray) -> Dict[str, Any]:
    auc = float(roc_auc_score(y_true, y_prob)) if len(np.unique(y_true)) > 1 else None
    return {
        "acc": float(accuracy_score(y_true, y_pred)),
        "f1": float(f1_score(y_true, y_pred)),
        "auc": auc,
    }


def _fit_base_models(
    X_train: pd.DataFrame,
    y_train: np.ndarray,
    *,
    quick: bool,
    random_state: int,
) -> Dict[str, Any]:
    models: Dict[str, Any] = {}

    rf = RandomForestClassifier(
        n_estimators=80 if quick else 300,
        max_depth=None,
        n_jobs=-1,
        random_state=random_state,
    )
    rf.fit(X_train, y_train)
    models["rf"] = rf

    dl = MLPClassifier(
        hidden_layer_sizes=(32,) if quick else (64, 32),
        activation="relu",
        alpha=1e-4,
        learning_rate_init=0.001,
        max_iter=250 if quick else 500,
        early_stopping=True,
        random_state=random_state,
    )
    dl.fit(X_train, y_train)
    models["dl"] = dl

    if HAS_XGB and XGBClassifier is not None:
        xgb = XGBClassifier(
            n_estimators=120 if quick else 400,
            max_depth=4 if quick else 6,
            learning_rate=0.08 if quick else 0.05,
            subsample=0.8,
            colsample_bytree=0.8,
            random_state=random_state,
            n_jobs=-1,
            eval_metric="logloss",
        )
        xgb.fit(X_train, y_train)
        models["xgb"] = xgb

    if HAS_CAT and CatBoostClassifier is not None:
        cat = CatBoostClassifier(
            depth=4 if quick else 6,
            learning_rate=0.08 if quick else 0.05,
            iterations=200 if quick else 500,
            loss_function="Logloss",
            random_seed=random_state,
            verbose=False,
        )
        cat.fit(X_train, y_train)
        models["cat"] = cat

    return models


def _predict_base_probs(models: Dict[str, Any], X: pd.DataFrame) -> Dict[str, np.ndarray]:
    def _proba(name: str) -> np.ndarray:
        model = models.get(name)
        if model is None:
            return np.zeros(len(X), dtype=float)
        return np.asarray(model.predict_proba(X)[:, 1], dtype=float)

    return {
        "rf": _proba("rf"),
        "dl": _proba("dl"),
        "xgb": _proba("xgb"),
        "cat": _proba("cat"),
    }


def _build_walk_forward_splits(
    n_samples: int,
    requested_splits: int,
) -> List[Tuple[np.ndarray, np.ndarray]]:
    if n_samples < 40:
        raise ValueError("Need at least 40 clean samples for walk-forward validation")
    max_splits = min(max(2, n_samples // 25), 8)
    n_splits = max(2, min(requested_splits, max_splits, n_samples - 1))
    splitter = TimeSeriesSplit(n_splits=n_splits)
    return list(splitter.split(np.arange(n_samples)))


def _decision_from_prob(probability_up: float) -> str:
    if probability_up > BUY_THRESHOLD:
        return "BUY"
    if probability_up < SELL_THRESHOLD:
        return "SELL"
    return "HOLD"


def _signal_return_pct(future_return_pct: float, decision: str) -> float:
    if decision == "BUY":
        return future_return_pct
    if decision == "SELL":
        return -future_return_pct
    return 0.0


def _max_drawdown_pct(returns_pct: List[float]) -> float | None:
    if not returns_pct:
        return None
    equity = 0.0
    peak = 0.0
    worst = 0.0
    for ret in returns_pct:
        equity += ret
        peak = max(peak, equity)
        worst = max(worst, peak - equity)
    return float(worst)


def _trade_eval(rows: pd.DataFrame, *, fee_bps: float, slippage_bps: float) -> Dict[str, Any]:
    if rows.empty:
        return {
            "count": 0,
            "trade_count": 0,
            "hold_count": 0,
            "accuracy": None,
            "net_expectancy_pct": None,
            "positive_net_rate": None,
            "max_drawdown_pct": None,
        }
    round_trip_cost_pct = (max(0.0, fee_bps) * 2.0 + max(0.0, slippage_bps) * 2.0) / 10000.0
    hits = rows["hit"].astype(bool)
    trade_rows = rows[rows["decision"].isin(["BUY", "SELL"])].copy()
    trade_rows["net_return_pct"] = trade_rows["gross_return_pct"] - round_trip_cost_pct
    net_returns = [float(v) for v in trade_rows["net_return_pct"].tolist()]
    positive = sum(1 for value in net_returns if value > 0)
    return {
        "count": int(len(rows)),
        "trade_count": int(len(trade_rows)),
        "hold_count": int((rows["decision"] == "HOLD").sum()),
        "accuracy": float(hits.mean()) if len(rows) else None,
        "net_expectancy_pct": float(np.mean(net_returns)) if net_returns else None,
        "positive_net_rate": (positive / len(net_returns)) if net_returns else None,
        "max_drawdown_pct": _max_drawdown_pct(net_returns),
    }


def _group_eval(rows: pd.DataFrame, by: str, *, fee_bps: float, slippage_bps: float) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    if by not in rows.columns:
        return out
    for key, group in rows.groupby(by):
        label = str(key or "").strip()
        if not label:
            continue
        out[label] = _trade_eval(group, fee_bps=fee_bps, slippage_bps=slippage_bps)
    return out


def train_models(
    csv_path: str,
    test_size: float = 0.2,
    random_state: int = 42,
    *,
    quick: bool = False,
    horizon_minutes: int = 15,
    walk_forward_splits: int = 5,
    interval_minutes: int | None = None,
    fee_bps: float = 10.0,
    slippage_bps: float = 5.0,
    symbol_filter: str | None = None,
) -> None:
    del test_size  # legacy arg retained for CLI compatibility; walk-forward is the default validation mode now.
    log.info("CSV path: %s", csv_path)
    df_raw = load_csv(csv_path)
    if symbol_filter:
        target_symbol = _normalize_symbol(symbol_filter)
        group_col = "binance_symbol" if "binance_symbol" in df_raw.columns else "symbol"
        if group_col not in df_raw.columns:
            raise ValueError("Cannot apply symbol filter: dataset has no symbol/binance_symbol column")
        df_raw = df_raw[df_raw[group_col].astype(str).map(_normalize_symbol) == target_symbol].copy()
        if df_raw.empty:
            raise ValueError(f"No rows found for symbol filter {target_symbol}")
        log.info("Applied symbol filter: %s (%d rows)", target_symbol, len(df_raw))
    log.info("Loaded CSV with shape: %s", df_raw.shape)

    training_frame, feature_cols, per_symbol_interval = prepare_training_frame(
        df_raw,
        horizon_minutes=horizon_minutes,
        interval_minutes=interval_minutes,
    )
    arr = training_frame[feature_cols].astype(float).values
    mask = np.isfinite(arr).all(axis=1)
    train_df = training_frame.loc[mask].reset_index(drop=True)
    if train_df.empty:
        raise ValueError("No clean samples available after feature preparation")

    X = train_df[feature_cols].astype(float).reset_index(drop=True)
    y = train_df["price_direction"].astype(int).to_numpy()
    log.info("Total clean samples: %d", len(train_df))
    log.info("Number of features: %d", len(feature_cols))

    folds = _build_walk_forward_splits(len(train_df), walk_forward_splits)
    stack_feature_names = ["rf", "dl", "xgb", "cat"]
    oof_meta = pd.DataFrame(0.0, index=train_df.index, columns=stack_feature_names)
    fold_id = pd.Series(-1, index=train_df.index, dtype="int64")
    valid_fold_metrics: List[Dict[str, Any]] = []

    for fold_no, (train_idx, val_idx) in enumerate(folds, start=1):
        y_train = y[train_idx]
        y_val = y[val_idx]
        if len(np.unique(y_train)) < 2 or len(np.unique(y_val)) < 2:
            log.info("Skipping fold %d due to single-class train/validation slice", fold_no)
            continue
        models = _fit_base_models(X.iloc[train_idx], y_train, quick=quick, random_state=random_state + fold_no)
        probs = _predict_base_probs(models, X.iloc[val_idx])
        for name in stack_feature_names:
            oof_meta.loc[val_idx, name] = probs[name]
        fold_id.loc[val_idx] = fold_no
        valid_fold_metrics.append(
            {
                "fold": fold_no,
                "count": int(len(val_idx)),
                "rf": _binary_metrics(y_val, (probs["rf"] >= 0.5).astype(int), probs["rf"]),
                "dl": _binary_metrics(y_val, (probs["dl"] >= 0.5).astype(int), probs["dl"]),
                "xgb": (
                    _binary_metrics(y_val, (probs["xgb"] >= 0.5).astype(int), probs["xgb"])
                    if np.any(probs["xgb"])
                    else None
                ),
                "cat": (
                    _binary_metrics(y_val, (probs["cat"] >= 0.5).astype(int), probs["cat"])
                    if np.any(probs["cat"])
                    else None
                ),
            }
        )

    valid_meta_mask = fold_id > 0
    unique_folds = sorted(int(v) for v in fold_id[valid_meta_mask].unique())
    if len(unique_folds) < 2:
        raise ValueError("Need at least two valid walk-forward folds for OOF stacking")

    eval_fold = unique_folds[-1]
    meta_train_mask = valid_meta_mask & (fold_id != eval_fold)
    meta_eval_mask = valid_meta_mask & (fold_id == eval_fold)
    if len(np.unique(y[meta_train_mask.to_numpy()])) < 2:
        raise ValueError("Meta-training OOF slice has only one class")

    lr = LogisticRegression(max_iter=1000, class_weight="balanced")
    lr.fit(oof_meta.loc[meta_train_mask].to_numpy(), y[meta_train_mask.to_numpy()])
    eval_probs = lr.predict_proba(oof_meta.loc[meta_eval_mask].to_numpy())[:, 1]
    eval_pred = lr.predict(oof_meta.loc[meta_eval_mask].to_numpy())
    meta_metrics = _binary_metrics(y[meta_eval_mask.to_numpy()], eval_pred, eval_probs)
    log.info(
        "STACKING (walk-forward eval fold %s) - acc=%.4f, f1=%.4f, auc=%s",
        eval_fold,
        meta_metrics["acc"],
        meta_metrics["f1"],
        f"{meta_metrics['auc']:.4f}" if meta_metrics["auc"] is not None else "nan",
    )
    log.info(
        "STACKING classification report:\n%s",
        classification_report(y[meta_eval_mask.to_numpy()], eval_pred),
    )

    final_models = _fit_base_models(X, y, quick=quick, random_state=random_state)
    final_lr = LogisticRegression(max_iter=1000, class_weight="balanced")
    final_lr.fit(oof_meta.loc[valid_meta_mask].to_numpy(), y[valid_meta_mask.to_numpy()])

    os.makedirs(MODEL_DIR, exist_ok=True)
    joblib.dump(final_models["rf"], RF_MODEL_PATH)
    joblib.dump(final_models["dl"], DL_MODEL_PATH)
    if final_models.get("xgb") is not None:
        joblib.dump(final_models["xgb"], XGB_MODEL_PATH)
    if final_models.get("cat") is not None:
        joblib.dump(final_models["cat"], CAT_MODEL_PATH)
    joblib.dump(final_lr, CALIBRATED_MODEL_PATH)
    log.info("Saved RF model to %s", RF_MODEL_PATH)
    log.info("Saved DL model to %s", DL_MODEL_PATH)
    if final_models.get("xgb") is not None:
        log.info("Saved XGB model to %s", XGB_MODEL_PATH)
    if final_models.get("cat") is not None:
        log.info("Saved CatBoost model to %s", CAT_MODEL_PATH)
    log.info("Saved calibrated stacking model to %s", CALIBRATED_MODEL_PATH)

    eval_rows = train_df.loc[meta_eval_mask].copy()
    eval_rows["probability_up"] = eval_probs
    eval_rows["decision"] = eval_rows["probability_up"].apply(_decision_from_prob)
    eval_rows["gross_return_pct"] = [
        _signal_return_pct(float(ret), decision)
        for ret, decision in zip(eval_rows["future_return_pct"], eval_rows["decision"])
    ]
    eval_rows["hit"] = np.where(
        eval_rows["decision"] == "BUY",
        eval_rows["future_return_pct"] > 0,
        np.where(
            eval_rows["decision"] == "SELL",
            eval_rows["future_return_pct"] < 0,
            eval_rows["future_return_pct"].abs() < 0.01,
        ),
    )

    dataset_hash = _sha256_file(csv_path)
    supported_symbols = sorted({str(sym).upper() for sym in train_df["binance_symbol"].dropna().unique()})
    common_interval = None
    if per_symbol_interval:
        values = list(per_symbol_interval.values())
        if len(set(values)) == 1:
            common_interval = int(values[0])
    meta_info_path = Path(CALIBRATED_MODEL_PATH + ".meta.json")
    meta_payload = {
        "trained_at": datetime.now(UTC).isoformat(),
        "dataset_hash": dataset_hash,
        "feature_columns": feature_cols,
        "stacking_feature_names": stack_feature_names,
        "label_column": "price_direction",
        "target_return_column": "future_return_pct",
        "supported_symbols": supported_symbols,
        "validation_mode": "walk_forward",
        "walk_forward_splits": len(unique_folds),
        "quick": quick,
        "dataset": {
            "path": str(Path(csv_path).resolve()),
            "sha256": dataset_hash,
            "rows_raw": int(len(df_raw)),
            "rows_prepared": int(len(training_frame)),
            "rows_clean": int(len(train_df)),
        },
        "time": {
            "interval_minutes": common_interval,
            "interval_minutes_per_symbol": per_symbol_interval,
            "min_ts": str(train_df["timestamp"].min().isoformat()) if "timestamp" in train_df.columns else None,
            "max_ts": str(train_df["timestamp"].max().isoformat()) if "timestamp" in train_df.columns else None,
        },
        "training": {
            "horizon_minutes": int(horizon_minutes),
            "random_state": int(random_state),
            "fee_bps": float(fee_bps),
            "slippage_bps": float(slippage_bps),
            "eval_fold": int(eval_fold),
            "external_features_enabled": bool(TRAIN_EXTERNAL_FEATURES),
        },
        "metrics": {
            "rf": valid_fold_metrics[-1]["rf"] if valid_fold_metrics else None,
            "dl": valid_fold_metrics[-1]["dl"] if valid_fold_metrics else None,
            "xgb": valid_fold_metrics[-1]["xgb"] if valid_fold_metrics else None,
            "cat": valid_fold_metrics[-1]["cat"] if valid_fold_metrics else None,
            "calibrated": meta_metrics,
            "folds": valid_fold_metrics,
        },
        "offline_evaluation": {
            "summary": _trade_eval(eval_rows, fee_bps=fee_bps, slippage_bps=slippage_bps),
            "per_symbol": _group_eval(eval_rows, "binance_symbol", fee_bps=fee_bps, slippage_bps=slippage_bps),
            "per_regime": _group_eval(eval_rows, "market_regime", fee_bps=fee_bps, slippage_bps=slippage_bps),
            "per_horizon": {f"{int(horizon_minutes)}m": _trade_eval(eval_rows, fee_bps=fee_bps, slippage_bps=slippage_bps)},
        },
        "models": {
            "rf": RF_MODEL_PATH,
            "dl": DL_MODEL_PATH if final_models.get("dl") is not None else None,
            "xgb": XGB_MODEL_PATH if final_models.get("xgb") is not None else None,
            "cat": CAT_MODEL_PATH if final_models.get("cat") is not None else None,
            "calibrated": CALIBRATED_MODEL_PATH,
        },
    }
    meta_info_path.write_text(json.dumps(meta_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info("Wrote meta file to %s", meta_info_path)

    _version_artifacts(
        meta_path=meta_info_path,
        model_paths=[
            p
            for p in [RF_MODEL_PATH, DL_MODEL_PATH, XGB_MODEL_PATH, CAT_MODEL_PATH, CALIBRATED_MODEL_PATH]
            if p and Path(p).exists()
        ],
    )
    log.info("Training pipeline finished successfully.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Train AEGIS crypto ensemble models.")
    parser.add_argument("--csv-path", type=str, default="data/crypto_data.csv")
    parser.add_argument("--test-size", type=float, default=0.2, help="Legacy arg kept for compatibility.")
    parser.add_argument("--random-state", type=int, default=42)
    parser.add_argument("--quick", action="store_true", help="Use smaller/faster models.")
    parser.add_argument("--horizon-minutes", type=int, default=15, help="Target prediction horizon in minutes.")
    parser.add_argument("--walk-forward-splits", type=int, default=5, help="Requested number of walk-forward splits.")
    parser.add_argument("--interval-minutes", type=int, default=0, help="Optional candle interval override in minutes.")
    parser.add_argument("--fee-bps", type=float, default=10.0, help="Fee bps per side for offline evaluation.")
    parser.add_argument("--slippage-bps", type=float, default=5.0, help="Slippage bps per side for offline evaluation.")
    parser.add_argument("--symbol", type=str, default="", help="Optional symbol filter for per-symbol bundle training.")
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        train_models(
            csv_path=args.csv_path,
            test_size=args.test_size,
            random_state=args.random_state,
            quick=args.quick,
            horizon_minutes=args.horizon_minutes,
            walk_forward_splits=args.walk_forward_splits,
            interval_minutes=(args.interval_minutes or None),
            fee_bps=args.fee_bps,
            slippage_bps=args.slippage_bps,
            symbol_filter=(args.symbol or None),
        )
    except KeyboardInterrupt:
        log.info("Interrupted by user (Ctrl+C). Exiting.")
        sys.exit(1)
    except Exception as exc:  # noqa: BLE001
        log.exception("Training failed: %s", exc)
        sys.exit(1)


if __name__ == "__main__":
    main()
