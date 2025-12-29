from __future__ import annotations

"""
Training script for AEGIS crypto ensemble models.

- Loads a CSV with historical crypto data.
- Enriches it using the same SetaFeatureEnricher used in inference.
- Ensures a binary label `price_direction` (next price up/down).
- Trains RF + optional XGB/Cat + calibrated LR meta model.
- Saves artifacts under MODEL_DIR (see app.api.meta).
- Writes a meta JSON with the feature columns used.

Usage (from project root, venv active):
  python -m app.scripts.train_models \
      --csv-path data/crypto_data.csv \
      --test-size 0.2 \
      --random-state 42
"""

import argparse
import json
import logging
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Sequence, Tuple

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, classification_report, f1_score, roc_auc_score
from sklearn.model_selection import train_test_split

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
    SetaFeatureEnricher,
    ensure_price_direction,
    MODEL_DIR,
    RF_MODEL_PATH,
    XGB_MODEL_PATH,
    CAT_MODEL_PATH,
    CALIBRATED_MODEL_PATH,
)

logging.basicConfig(level=logging.INFO, format="[train] %(message)s")
log = logging.getLogger("train_models")


ARTIFACTS_DIR = Path(os.getenv("CRYPTO_ARTIFACTS_DIR", "artifacts/crypto_models"))


def load_csv(csv_path: str) -> pd.DataFrame:
    if not os.path.exists(csv_path):
        raise FileNotFoundError(csv_path)
    df = pd.read_csv(csv_path)
    for col in ["timestamp", "date", "time", "last_updated", "datetime"]:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce")
    return df


def prepare_features_and_labels(df_raw: pd.DataFrame) -> Tuple[pd.DataFrame, np.ndarray, List[str]]:
    enricher = SetaFeatureEnricher()
    df_enriched = enricher.enrich_features(df_raw)
    df_enriched = ensure_price_direction(df_enriched, price_col="current_price", label_col="price_direction")

    if "price_direction" not in df_enriched.columns:
        raise ValueError("price_direction label column missing after enrichment.")

    numeric_cols = list(df_enriched.select_dtypes(include=[np.number]).columns)
    if "price_direction" in numeric_cols:
        numeric_cols.remove("price_direction")
    if not numeric_cols:
        raise ValueError("No numeric feature columns found.")

    X = df_enriched[numeric_cols].astype(float)
    y = df_enriched["price_direction"].astype(int).values

    arr = X.values
    mask = np.isfinite(arr).all(axis=1)
    X_clean = X[mask]
    y_clean = y[mask]

    log.info("Total samples after cleaning: %d", len(X_clean))
    log.info("Number of features: %d", X_clean.shape[1])

    return X_clean, y_clean, numeric_cols


def _version_artifacts(meta_path: Path, model_paths: List[str]) -> None:
    """Copy model + meta artifacts into a timestamped folder for rollback."""
    try:
        ts = datetime.utcnow().strftime("%Y%m%d%H%M%S")
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

        # Shift latest -> previous, then update latest
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


def train_models(
    csv_path: str,
    test_size: float = 0.2,
    random_state: int = 42,
    *,
    quick: bool = False,
) -> None:
    log.info("CSV path: %s", csv_path)
    df_raw = load_csv(csv_path)
    log.info("Loaded CSV with shape: %s", df_raw.shape)

    X, y, feature_cols = prepare_features_and_labels(df_raw)

    stratify = y if len(np.unique(y)) > 1 else None
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=test_size, random_state=random_state, stratify=stratify
    )

    os.makedirs(MODEL_DIR, exist_ok=True)
    log.info("Using MODEL_DIR (from app.api.meta): %s", MODEL_DIR)

    # RF
    log.info("Training RandomForest...")
    rf = RandomForestClassifier(
        n_estimators=80 if quick else 300,
        max_depth=None,
        n_jobs=-1,
        random_state=random_state,
    )
    rf.fit(X_train, y_train)
    y_pred_rf = rf.predict(X_test)
    y_prob_rf = rf.predict_proba(X_test)[:, 1]
    log.info(
        "RF - acc=%.4f, f1=%.4f, auc=%.4f",
        accuracy_score(y_test, y_pred_rf),
        f1_score(y_test, y_pred_rf),
        roc_auc_score(y_test, y_prob_rf) if len(np.unique(y_test)) > 1 else float("nan"),
    )
    log.info("RF classification report:\n%s", classification_report(y_test, y_pred_rf))
    joblib.dump(rf, RF_MODEL_PATH)
    log.info("Saved RF model to %s", RF_MODEL_PATH)

    # XGB (optional)
    xgb_model = None
    xgb_val_probs = np.zeros_like(y_prob_rf)
    if HAS_XGB and XGBClassifier is not None:
        log.info("Training XGBoost...")
        xgb_model = XGBClassifier(
            n_estimators=120 if quick else 400,
            max_depth=4 if quick else 6,
            learning_rate=0.08 if quick else 0.05,
            subsample=0.8,
            colsample_bytree=0.8,
            random_state=random_state,
            n_jobs=-1,
            eval_metric="logloss",
        )
        xgb_model.fit(X_train, y_train)
        y_pred_xgb = xgb_model.predict(X_test)
        y_prob_xgb = xgb_model.predict_proba(X_test)[:, 1]
        xgb_val_probs = y_prob_xgb
        log.info(
            "XGB - acc=%.4f, f1=%.4f, auc=%.4f",
            accuracy_score(y_test, y_pred_xgb),
            f1_score(y_test, y_pred_xgb),
            roc_auc_score(y_test, y_prob_xgb)
            if len(np.unique(y_test)) > 1
            else float("nan"),
        )
        joblib.dump(xgb_model, XGB_MODEL_PATH)
        log.info("Saved XGB model to %s", XGB_MODEL_PATH)
    else:
        log.info("xgboost not available; skipping XGB model.")

    # CatBoost (optional)
    cat_model = None
    cat_val_probs = np.zeros_like(y_prob_rf)
    if HAS_CAT and CatBoostClassifier is not None:
        log.info("Training CatBoost...")
        cat_model = CatBoostClassifier(
            depth=4 if quick else 6,
            learning_rate=0.08 if quick else 0.05,
            iterations=200 if quick else 500,
            loss_function="Logloss",
            random_seed=random_state,
            verbose=False,
        )
        cat_model.fit(X_train, y_train)
        y_pred_cat = cat_model.predict(X_test)
        y_prob_cat = cat_model.predict_proba(X_test)[:, 1]
        cat_val_probs = y_prob_cat
        log.info(
            "CAT - acc=%.4f, f1=%.4f, auc=%.4f",
            accuracy_score(y_test, y_pred_cat),
            f1_score(y_test, y_pred_cat),
            roc_auc_score(y_test, y_prob_cat)
            if len(np.unique(y_test)) > 1
            else float("nan"),
        )
        joblib.dump(cat_model, CAT_MODEL_PATH)
        log.info("Saved CatBoost model to %s", CAT_MODEL_PATH)
    else:
        log.info("catboost not available; skipping CatBoost model.")

    # Calibrated / stacking-like
    log.info("Training calibrated (LogisticRegression) model on validation probs...")
    meta_features = [y_prob_rf.reshape(-1, 1)]
    meta_features.append(xgb_val_probs.reshape(-1, 1) if xgb_model is not None else np.zeros_like(y_prob_rf).reshape(-1, 1))
    meta_features.append(cat_val_probs.reshape(-1, 1) if cat_model is not None else np.zeros_like(y_prob_rf).reshape(-1, 1))

    meta_X = np.column_stack(meta_features)
    meta_y = y_test

    lr = LogisticRegression(max_iter=1000, class_weight="balanced", n_jobs=-1)
    lr.fit(meta_X, meta_y)
    y_pred_lr = lr.predict(meta_X)
    y_prob_lr = lr.predict_proba(meta_X)[:, 1]

    lr_acc = accuracy_score(meta_y, y_pred_lr)
    lr_f1 = f1_score(meta_y, y_pred_lr)
    lr_auc = (
        roc_auc_score(meta_y, y_prob_lr) if len(np.unique(meta_y)) > 1 else float("nan")
    )
    log.info(
        "CALIBRATED (LR) - acc=%.4f, f1=%.4f, auc=%.4f",
        lr_acc,
        lr_f1,
        lr_auc,
    )
    log.info("CALIBRATED classification report:\n%s", classification_report(meta_y, y_pred_lr))

    joblib.dump(lr, CALIBRATED_MODEL_PATH)
    log.info("Saved calibrated model to %s", CALIBRATED_MODEL_PATH)

    meta_info_path = CALIBRATED_MODEL_PATH + ".meta.json"
    meta_payload = {
        "feature_columns": feature_cols,
        "label_column": "price_direction",
        "trained_at": datetime.utcnow().isoformat(),
        "quick": quick,
        "metrics": {
            "rf": {
                "acc": accuracy_score(y_test, y_pred_rf),
                "f1": f1_score(y_test, y_pred_rf),
                "auc": float(roc_auc_score(y_test, y_prob_rf)) if len(np.unique(y_test)) > 1 else None,
            },
            "xgb": (
                {
                    "acc": accuracy_score(y_test, y_pred_xgb),
                    "f1": f1_score(y_test, y_pred_xgb),
                    "auc": float(roc_auc_score(y_test, y_prob_xgb)) if len(np.unique(y_test)) > 1 else None,
                }
                if xgb_model is not None
                else None
            ),
            "cat": (
                {
                    "acc": accuracy_score(y_test, y_pred_cat),
                    "f1": f1_score(y_test, y_pred_cat),
                    "auc": float(roc_auc_score(y_test, y_prob_cat)) if len(np.unique(y_test)) > 1 else None,
                }
                if cat_model is not None
                else None
            ),
            "calibrated": {"acc": lr_acc, "f1": lr_f1, "auc": float(lr_auc) if lr_auc == lr_auc else None},
        },
        "models": {
            "rf": RF_MODEL_PATH,
            "xgb": XGB_MODEL_PATH if xgb_model is not None else None,
            "cat": CAT_MODEL_PATH if cat_model is not None else None,
            "calibrated": CALIBRATED_MODEL_PATH,
        },
    }
    with open(meta_info_path, "w", encoding="utf-8") as f:
        json.dump(meta_payload, f, indent=2)

    log.info("Wrote meta file to %s", meta_info_path)
    _version_artifacts(
        meta_path=Path(meta_info_path),
        model_paths=[p for p in [RF_MODEL_PATH, XGB_MODEL_PATH, CAT_MODEL_PATH, CALIBRATED_MODEL_PATH] if p],
    )
    log.info("Training pipeline finished successfully.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Train AEGIS crypto ensemble models.",
    )
    parser.add_argument(
        "--csv-path",
        type=str,
        default="data/crypto_data.csv",
        help="Path to the historical crypto CSV (default: data/crypto_data.csv).",
    )
    parser.add_argument(
        "--test-size",
        type=float,
        default=0.2,
        help="Test size fraction for train/test split (default: 0.2).",
    )
    parser.add_argument(
        "--random-state",
        type=int,
        default=42,
        help="Random state for reproducibility (default: 42).",
    )
    parser.add_argument(
        "--quick",
        action="store_true",
        help="Use smaller models for faster local/dev runs.",
    )
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
        )
    except KeyboardInterrupt:
        log.info("Interrupted by user (Ctrl+C). Exiting.")
        sys.exit(1)
    except Exception as exc:  # noqa: BLE001
        log.exception("Training failed: %s", exc)
        sys.exit(1)


if __name__ == "__main__":
    main()
