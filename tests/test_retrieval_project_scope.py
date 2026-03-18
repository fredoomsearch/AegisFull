from __future__ import annotations

from pathlib import Path

from app.services import retrieval_service


def _reset_retrieval_state(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(retrieval_service, "INDEX_DIR", tmp_path / "faiss_index")
    monkeypatch.setattr(retrieval_service, "INDEX_FILE", retrieval_service.INDEX_DIR / "index.faiss")
    monkeypatch.setattr(retrieval_service, "META_FILE", retrieval_service.INDEX_DIR / "metadata.json")
    monkeypatch.setattr(retrieval_service, "faiss", None)
    monkeypatch.setattr(retrieval_service, "np", None)
    monkeypatch.setattr(retrieval_service, "_index", None)
    monkeypatch.setattr(retrieval_service, "_meta", {"ids": [], "meta": {}})
    monkeypatch.setattr(retrieval_service, "_state_loaded", False)


def test_project_scoped_retrieval_and_symbol_listing(tmp_path: Path, monkeypatch):
    _reset_retrieval_state(tmp_path, monkeypatch)

    added = retrieval_service.add_documents(
        [
            {
                "project_id": "proj_a",
                "rel_path": "app/auth.py",
                "source": "proj_a/app/auth.py",
                "text": "def login(user):\n    return user\n",
                "language": "python",
                "chunk_type": "symbol",
                "symbol": "login",
                "line_start": 1,
                "line_end": 2,
                "prechunked": True,
            },
            {
                "project_id": "proj_b",
                "rel_path": "app/users.py",
                "source": "proj_b/app/users.py",
                "text": "def register(user):\n    return user\n",
                "language": "python",
                "chunk_type": "symbol",
                "symbol": "register",
                "line_start": 1,
                "line_end": 2,
                "prechunked": True,
            },
        ]
    )

    assert added == 2
    assert retrieval_service.count_project_chunks("proj_a") == 1

    results = retrieval_service.query("login", top_k=5, project_id="proj_a")
    assert results
    assert results[0]["project_id"] == "proj_a"
    assert results[0]["rel_path"] == "app/auth.py"
    assert results[0]["chunk_type"] == "symbol"

    symbols = retrieval_service.list_project_symbols("proj_a")
    assert symbols == [
        {
            "symbol": "login",
            "path": "app/auth.py",
            "language": "python",
            "line_start": 1,
            "line_end": 2,
        }
    ]

    removed = retrieval_service.remove_project_documents("proj_a", rel_paths={"app/auth.py"})
    assert removed == 1
    assert retrieval_service.count_project_chunks("proj_a") == 0
    assert retrieval_service.query("login", top_k=5, project_id="proj_a") == []
