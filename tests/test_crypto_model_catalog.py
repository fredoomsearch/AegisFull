from __future__ import annotations

from pathlib import Path
import json


def test_discover_trained_models_ignores_non_crypto_artifacts(tmp_path: Path, monkeypatch):
    from app.models.ml import models as model_catalog

    models_root = tmp_path / "models"
    models_root.mkdir(parents=True, exist_ok=True)
    (models_root / "DreamShaper_8_pruned.safetensors").write_text("x", encoding="utf-8")
    (models_root / "rf_model.joblib").write_text("x", encoding="utf-8")

    monkeypatch.setenv("CRYPTO_MODELS_DIR", str(models_root))
    discovered = model_catalog.discover_trained_models()
    paths = {Path(item.artifact_path or "").name for item in discovered}

    assert "rf_model.joblib" in paths
    assert "DreamShaper_8_pruned.safetensors" not in paths


def test_discover_trained_models_reads_latest_artifact_version(tmp_path: Path, monkeypatch):
    from app.models.ml import models as model_catalog

    artifacts = tmp_path / "artifacts" / "crypto_models"
    version = artifacts / "20260314_010101"
    version.mkdir(parents=True, exist_ok=True)
    model_file = version / "calibrated_stacking_model.joblib"
    model_file.write_text("x", encoding="utf-8")
    (artifacts / "latest.txt").write_text("20260314_010101", encoding="utf-8")

    monkeypatch.delenv("CRYPTO_MODELS_DIR", raising=False)
    monkeypatch.setenv("CRYPTO_ARTIFACTS_DIR", str(artifacts))

    discovered = model_catalog.discover_trained_models()
    paths = {Path(item.artifact_path or "").resolve() for item in discovered if item.artifact_path}

    assert model_file.resolve() in paths


def test_discover_trained_models_uses_provenance_metadata(tmp_path: Path, monkeypatch):
    from app.models.ml import models as model_catalog

    artifacts = tmp_path / "artifacts" / "crypto_models" / "20260316_120000"
    artifacts.mkdir(parents=True, exist_ok=True)
    model_file = artifacts / "calibrated_stacking_model.joblib"
    model_file.write_text("x", encoding="utf-8")
    (artifacts.parent / "latest.txt").write_text("20260316_120000", encoding="utf-8")
    (artifacts / "calibrated_stacking_model.joblib.meta.json").write_text(
        json.dumps(
            {
                "supported_symbols": ["BTCUSDT", "ETHUSDT"],
                "dataset_hash": "abc123",
                "trained_at": "2026-03-16T12:00:00+00:00",
                "validation_mode": "walk_forward",
                "time": {"interval_minutes": 5},
                "training": {"horizon_minutes": 30},
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.delenv("CRYPTO_MODELS_DIR", raising=False)
    monkeypatch.setenv("CRYPTO_ARTIFACTS_DIR", str(artifacts.parent))

    discovered = model_catalog.discover_trained_models()
    by_symbol = {item.symbol: item for item in discovered}

    assert by_symbol["BTCUSDT"].horizon_minutes == 30
    assert by_symbol["BTCUSDT"].dataset_hash == "abc123"
    assert by_symbol["BTCUSDT"].interval_minutes == 5
    assert by_symbol["ETHUSDT"].validation_mode == "walk_forward"


def test_build_model_registry_groups_symbol_and_horizon(tmp_path: Path, monkeypatch):
    from app.models.ml import models as model_catalog

    artifacts = tmp_path / "artifacts" / "crypto_models" / "20260316_120000"
    artifacts.mkdir(parents=True, exist_ok=True)
    for name in ("rf_model.joblib", "xgb_model.joblib", "calibrated_stacking_model.joblib"):
        (artifacts / name).write_text("x", encoding="utf-8")
    (artifacts.parent / "latest.txt").write_text("20260316_120000", encoding="utf-8")
    (artifacts / "calibrated_stacking_model.joblib.meta.json").write_text(
        json.dumps(
            {
                "supported_symbols": ["BTCUSDT"],
                "dataset_hash": "abc123",
                "trained_at": "2026-03-16T12:00:00+00:00",
                "validation_mode": "walk_forward",
                "time": {"interval_minutes": 5},
                "training": {"horizon_minutes": 15},
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.delenv("CRYPTO_MODELS_DIR", raising=False)
    monkeypatch.setenv("CRYPTO_ARTIFACTS_DIR", str(artifacts.parent))

    registry = model_catalog.build_model_registry()

    assert len(registry) == 1
    entry = registry[0]
    assert entry.symbol == "BTCUSDT"
    assert entry.horizon_minutes == 15
    assert entry.interval_minutes == 5
    assert set(entry.available_model_types) >= {"ensemble", "rf", "xgb", "seta"}


def test_discover_trained_models_maps_lstm_to_dl(tmp_path: Path, monkeypatch):
    from app.models.ml import models as model_catalog

    models_root = tmp_path / "models"
    models_root.mkdir(parents=True, exist_ok=True)
    (models_root / "lstm_model.joblib").write_text("x", encoding="utf-8")

    monkeypatch.setenv("CRYPTO_MODELS_DIR", str(models_root))
    monkeypatch.setenv("CRYPTO_ARTIFACTS_DIR", str(tmp_path / "artifacts" / "crypto_models"))
    monkeypatch.setenv("MODEL_DIR", str(tmp_path / "empty_models"))

    discovered = model_catalog.discover_trained_models()
    dl_rows = [item for item in discovered if Path(item.artifact_path or "").name == "lstm_model.joblib"]
    assert len(dl_rows) == 1
    assert dl_rows[0].model_type == "dl"
