from __future__ import annotations

import logging
import math
from typing import Any, Dict, Optional, Tuple

from app.services.crypto_news_service import fetch_news
from app.services.crypto_prediction_log import log_prediction

logger = logging.getLogger(__name__)

try:
    from app.services.crypto_ml_service import (
        CSV_FILE_PATH,
        load_base_csv,
        run_dl_pipeline,
        run_rf_prediction,
    )
except Exception as exc:  # noqa: BLE001
    logger.exception("crypto_service_legacy: failed to import crypto_ml_service: %s", exc)
    CSV_FILE_PATH = "crypto_data.csv"  # type: ignore[assignment]

    def load_base_csv():  # type: ignore[override]
        raise RuntimeError("crypto_ml_service not available")

    def run_dl_pipeline(*_args, **_kwargs):  # type: ignore[override]
        raise RuntimeError("crypto_ml_service not available")

    def run_rf_prediction(*_args, **_kwargs):  # type: ignore[override]
        raise RuntimeError("crypto_ml_service not available")


class CryptoServiceLegacy:
    """
    Legacy ML-facing service.

    Responsibilities:
      - Provide simple methods to train & run the old RF/DL regressors.
      - Aggregate their outputs into an easy-to-consume dict.
      - Offer basic dataset inspection helpers.
    """

    def __init__(self, csv_file_path: Optional[str] = None) -> None:
        self.csv_file_path = csv_file_path or CSV_FILE_PATH

    # ------------------------------------------------------------------
    # TRAIN + PREDICT
    # ------------------------------------------------------------------

    def retrain_and_predict_all(self) -> Dict[str, Any]:
        logger.info("CryptoServiceLegacy.retrain_and_predict_all: csv=%s", self.csv_file_path)

        rf_result = self.predict_rf(retrain=True)
        dl_result = self.predict_dl(retrain=True)
        dataset_info = self.describe_dataset()

        return {
            "dataset": dataset_info,
            "rf": rf_result,
            "dl": dl_result,
        }

    def predict_rf(self, retrain: bool = False) -> Dict[str, Any]:
        logger.info("CryptoServiceLegacy.predict_rf: retrain=%s csv=%s", retrain, self.csv_file_path)
        return run_rf_prediction(self.csv_file_path, retrain=retrain)

    def predict_dl(self, retrain: bool = False) -> Dict[str, Any]:
        logger.info("CryptoServiceLegacy.predict_dl: retrain=%s csv=%s", retrain, self.csv_file_path)
        return run_dl_pipeline(self.csv_file_path, retrain=retrain)

    # ------------------------------------------------------------------
    # DATASET INSPECTION
    # ------------------------------------------------------------------

    def describe_dataset(self) -> Dict[str, Any]:
        try:
            df = load_base_csv()
        except Exception as exc:  # noqa: BLE001
            logger.exception("CryptoServiceLegacy.describe_dataset: failed: %s", exc)
            return {
                "csv_path": self.csv_file_path,
                "error": str(exc),
            }

        return {
            "csv_path": self.csv_file_path,
            "n_rows": int(len(df)),
            "n_cols": int(df.shape[1]),
            "columns": list(df.columns),
            "sample": df.head(5).to_dict(orient="records"),
        }


# ----------------------------------------------------------------------
# Module-level default instance (easy to import)
# ----------------------------------------------------------------------

legacy_crypto_service = CryptoServiceLegacy()

# ----------------------------------------------------------------------
# Toy probabilistic predictor (news + simple heuristics)
# ----------------------------------------------------------------------

def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def predict(
    symbol: str,
    *,
    horizon_minutes: int = 30,
    price: Optional[float] = None,
    features: Optional[Dict[str, Any]] = None,
    log: bool = True,
) -> Tuple[Dict[str, Any], Optional[str]]:
    sym = (symbol or "BTC").upper().strip()
    feats = features or {}

    # Pull news momentum (sentiment average) as a weak signal.
    news = fetch_news(sym, limit=8)
    momentum = float(news.get("momentum") or 0.0)
    trust = float(news.get("trust_avg") or 0.5)

    recent_ret = float(feats.get("recent_return_pct") or 0.0)
    vol = float(feats.get("volatility") or 0.25)
    vol = _clamp(vol, 0.0, 1.5)

    # Combine signals:
    score = 0.9 * momentum + (-0.35 * recent_ret) + (0.15 * (trust - 0.5))
    prob_up = _clamp(_sigmoid(score), 0.01, 0.99)
    prob_down = 1.0 - prob_up

    raw_conf = abs(prob_up - 0.5) * 2.0
    confidence = _clamp(raw_conf * (0.7 + 0.6 * trust) * (1.0 / (1.0 + vol)), 0.05, 0.95)

    decision = "HOLD"
    if confidence >= 0.55:
        decision = "BUY" if prob_up >= 0.55 else "SELL"

    expected_delta_pct = (prob_up - 0.5) * (0.8 + 0.6 * vol)  # toy expectation

    payload = {
        "symbol": sym,
        "decision": decision,
        "prob_up": round(prob_up, 4),
        "prob_down": round(prob_down, 4),
        "confidence": round(confidence, 4),
        "expected_delta_pct": round(float(expected_delta_pct), 4),
        "horizon_minutes": int(horizon_minutes),
        "used_signals": {
            "news_momentum": round(momentum, 4),
            "news_trust_avg": round(trust, 4),
            "recent_return_pct": round(recent_ret, 4),
            "volatility": round(vol, 4),
        },
    }

    log_id = None
    if log:
        log_id = log_prediction(
            {
                "symbol": sym,
                "horizon_minutes": int(horizon_minutes),
                "price": price,
                "features": feats,
                "output": payload,
                "model": "toy_v1",
            }
        )

    return payload, log_id
