from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd


def test_train_models_writes_walk_forward_provenance(tmp_path: Path, monkeypatch):
    from app.core import meta as meta_module
    from app.scripts import train_models as trainer

    model_dir = tmp_path / "models"
    artifacts_dir = tmp_path / "artifacts"
    model_dir.mkdir(parents=True, exist_ok=True)
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(trainer, "MODEL_DIR", str(model_dir))
    monkeypatch.setattr(trainer, "RF_MODEL_PATH", str(model_dir / "rf_model.joblib"))
    monkeypatch.setattr(trainer, "XGB_MODEL_PATH", str(model_dir / "xgb_model.joblib"))
    monkeypatch.setattr(trainer, "CAT_MODEL_PATH", str(model_dir / "cat_model.joblib"))
    monkeypatch.setattr(trainer, "DL_MODEL_PATH", str(model_dir / "lstm_model.joblib"))
    monkeypatch.setattr(trainer, "CALIBRATED_MODEL_PATH", str(model_dir / "calibrated_stacking_model.joblib"))
    monkeypatch.setattr(trainer, "ARTIFACTS_DIR", artifacts_dir)
    monkeypatch.setattr(meta_module, "CRYPTO_EXTERNAL_FEATURES", False, raising=False)

    rows = 180
    ts = pd.date_range("2025-01-01", periods=rows, freq="5min", tz="UTC")
    price = np.linspace(100.0, 118.0, rows) + np.sin(np.arange(rows) / 5.0) * 2.5
    volume = np.linspace(1000.0, 1600.0, rows) + np.cos(np.arange(rows) / 8.0) * 75.0
    df = pd.DataFrame(
        {
            "timestamp": ts,
            "symbol": ["BTCUSDT"] * rows,
            "current_price": price,
            "high_24h": price * 1.01,
            "low_24h": price * 0.99,
            "total_volume": volume,
            "market_cap": np.linspace(1_000_000.0, 1_100_000.0, rows),
        }
    )
    csv_path = tmp_path / "crypto_train.csv"
    df.to_csv(csv_path, index=False)

    trainer.train_models(
        csv_path=str(csv_path),
        quick=True,
        horizon_minutes=15,
        walk_forward_splits=4,
        interval_minutes=5,
        fee_bps=10.0,
        slippage_bps=5.0,
    )

    meta_path = Path(str(model_dir / "calibrated_stacking_model.joblib.meta.json"))
    assert meta_path.exists()
    payload = json.loads(meta_path.read_text(encoding="utf-8"))

    assert (model_dir / "rf_model.joblib").exists()
    assert (model_dir / "lstm_model.joblib").exists()
    assert (model_dir / "calibrated_stacking_model.joblib").exists()
    assert payload["validation_mode"] == "walk_forward"
    assert payload["training"]["horizon_minutes"] == 15
    assert payload["time"]["interval_minutes"] == 5
    assert payload["supported_symbols"] == ["BTCUSDT"]
    assert payload["dataset_hash"]
    assert payload["stacking_feature_names"] == ["rf", "dl", "xgb", "cat"]
    assert payload["models"]["dl"] == str(model_dir / "lstm_model.joblib")
    assert "BTCUSDT" in payload["offline_evaluation"]["per_symbol"]
    assert payload["offline_evaluation"]["per_horizon"]["15m"]["count"] > 0


def test_train_models_symbol_filter_limits_bundle(tmp_path: Path, monkeypatch):
    from app.core import meta as meta_module
    from app.scripts import train_models as trainer

    model_dir = tmp_path / "models"
    artifacts_dir = tmp_path / "artifacts"
    model_dir.mkdir(parents=True, exist_ok=True)
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(trainer, "MODEL_DIR", str(model_dir))
    monkeypatch.setattr(trainer, "RF_MODEL_PATH", str(model_dir / "rf_model.joblib"))
    monkeypatch.setattr(trainer, "XGB_MODEL_PATH", str(model_dir / "xgb_model.joblib"))
    monkeypatch.setattr(trainer, "CAT_MODEL_PATH", str(model_dir / "cat_model.joblib"))
    monkeypatch.setattr(trainer, "DL_MODEL_PATH", str(model_dir / "lstm_model.joblib"))
    monkeypatch.setattr(trainer, "CALIBRATED_MODEL_PATH", str(model_dir / "calibrated_stacking_model.joblib"))
    monkeypatch.setattr(trainer, "ARTIFACTS_DIR", artifacts_dir)
    monkeypatch.setattr(meta_module, "CRYPTO_EXTERNAL_FEATURES", False, raising=False)

    rows = 120
    ts = pd.date_range("2025-01-01", periods=rows, freq="5min", tz="UTC")
    btc_price = np.linspace(100.0, 112.0, rows) + np.sin(np.arange(rows) / 6.0) * 1.8
    eth_price = np.linspace(200.0, 220.0, rows) + np.cos(np.arange(rows) / 5.0) * 2.4
    btc = pd.DataFrame(
        {
            "timestamp": ts,
            "symbol": ["BTCUSDT"] * rows,
            "current_price": btc_price,
            "high_24h": btc_price * 1.01,
            "low_24h": btc_price * 0.99,
            "total_volume": np.linspace(1000.0, 1400.0, rows) + np.cos(np.arange(rows) / 7.0) * 60.0,
            "market_cap": np.linspace(1_000_000.0, 1_100_000.0, rows),
        }
    )
    eth = pd.DataFrame(
        {
            "timestamp": ts,
            "symbol": ["ETHUSDT"] * rows,
            "current_price": eth_price,
            "high_24h": eth_price * 1.01,
            "low_24h": eth_price * 0.99,
            "total_volume": np.linspace(800.0, 1200.0, rows) + np.sin(np.arange(rows) / 4.0) * 55.0,
            "market_cap": np.linspace(900_000.0, 980_000.0, rows),
        }
    )
    csv_path = tmp_path / "crypto_train_multi.csv"
    pd.concat([btc, eth], ignore_index=True).to_csv(csv_path, index=False)

    trainer.train_models(
        csv_path=str(csv_path),
        quick=True,
        horizon_minutes=15,
        walk_forward_splits=4,
        interval_minutes=5,
        symbol_filter="ETHUSDT",
    )

    payload = json.loads((model_dir / "calibrated_stacking_model.joblib.meta.json").read_text(encoding="utf-8"))
    assert payload["supported_symbols"] == ["ETHUSDT"]
