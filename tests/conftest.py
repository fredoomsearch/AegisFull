import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.services import crypto_prediction_log, project_store


os.environ["DATABASE_URL"] = "postgresql+psycopg2://postgres:postgres@localhost:5432/test_aegis"
os.environ["AEGIS_SEARCH_WARMUP_ON_START"] = "0"
os.environ["AEGIS_SEARCH_WARMUP_INTERVAL"] = "0"
os.environ["AEGIS_AUTH_MODE"] = "off"
os.environ["AEGIS_DISABLE_DB"] = "1"
os.environ["AEGIS_DISABLE_RETRIEVAL"] = "1"
os.environ["AEGIS_LLM_WARMUP"] = "0"
os.environ["AEGIS_DISABLE_EMBEDDINGS"] = "1"
os.environ["AEGIS_MEMORY_PERSIST"] = "0"

# Ensure project root is importable
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture(scope="session")
def client():
    import main  # noqa: WPS433

    main._warm_llm_once = lambda: None
    main.start_background_warmup = lambda: None
    return TestClient(main.app)


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(autouse=True)
def isolate_project_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    upload_root = tmp_path / "uploads"
    upload_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(project_store, "UPLOAD_ROOT", upload_root)
    monkeypatch.setattr(project_store, "STORE_FILE", upload_root / ".aegis_projects.json")


@pytest.fixture(autouse=True)
def isolate_crypto_prediction_logs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    log_root = tmp_path / "crypto_pred_logs"
    log_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(crypto_prediction_log, "LOG_DIR", log_root)
    monkeypatch.setattr(crypto_prediction_log, "LOG_FILE", log_root / "predictions.jsonl")
    monkeypatch.setattr(crypto_prediction_log, "OUTCOME_FILE", log_root / "prediction_outcomes.jsonl")
