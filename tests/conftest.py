import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


os.environ["DATABASE_URL"] = "postgresql+psycopg2://postgres:postgres@localhost:5432/test_aegis"
os.environ["AEGIS_SEARCH_WARMUP_ON_START"] = "0"
os.environ["AEGIS_SEARCH_WARMUP_INTERVAL"] = "0"
os.environ["AEGIS_AUTH_MODE"] = "off"
os.environ["AEGIS_DISABLE_DB"] = "1"
os.environ["AEGIS_DISABLE_RETRIEVAL"] = "1"
os.environ["AEGIS_LLM_WARMUP"] = "0"
os.environ["AEGIS_DISABLE_EMBEDDINGS"] = "1"

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
