from __future__ import annotations

import pytest

from app.services import retrieval_service


class _FakeMatrix(list):
    @property
    def shape(self) -> tuple[int, int]:
        rows = len(self)
        cols = len(self[0]) if self and self[0] else 0
        return (rows, cols)


class _FakeIndex:
    def __init__(self, dim: int) -> None:
        self.d = dim
        self.rows: list[list[float]] = []

    def add(self, rows) -> None:  # type: ignore[no-untyped-def]
        self.rows.extend(list(rows))


def _reset_state(monkeypatch: pytest.MonkeyPatch, *, embed_batch_size: int) -> None:
    monkeypatch.setattr(retrieval_service, "_load_index", lambda: None)
    monkeypatch.setattr(retrieval_service, "_save_index", lambda: None)
    monkeypatch.setattr(retrieval_service, "_get_faiss", lambda: object())
    monkeypatch.setattr(retrieval_service, "np", object())
    monkeypatch.setattr(retrieval_service, "EMBED_BATCH_SIZE", embed_batch_size)
    monkeypatch.setattr(
        retrieval_service,
        "_normalize",
        lambda vecs: _FakeMatrix([list(map(float, row)) for row in vecs]),
    )
    monkeypatch.setattr(
        retrieval_service,
        "_embed_texts_safe",
        lambda texts: [[0.25] * 256 for _ in texts],
    )
    monkeypatch.setattr(
        retrieval_service,
        "_create_index",
        lambda: _FakeIndex(int(retrieval_service._current_dim() or 0)),
    )
    monkeypatch.setattr(retrieval_service, "_index", _FakeIndex(384))
    monkeypatch.setattr(retrieval_service, "EMBEDDING_DIM", 384)
    monkeypatch.setattr(
        retrieval_service,
        "_meta",
        {
            "ids": ["old-doc"],
            "meta": {
                "old-doc": {
                    "project_id": "proj",
                    "rel_path": "app/old.py",
                    "source": "proj/app/old.py",
                    "text": "def old_login():\n    return True\n",
                }
            },
            "dim": 384,
        },
    )


@pytest.mark.parametrize("embed_batch_size", [0, 1])
def test_add_documents_rebuilds_index_on_dimension_mismatch(
    monkeypatch: pytest.MonkeyPatch,
    embed_batch_size: int,
) -> None:
    _reset_state(monkeypatch, embed_batch_size=embed_batch_size)

    added = retrieval_service.add_documents(
        [
            {
                "project_id": "proj",
                "rel_path": "app/new.py",
                "source": "proj/app/new.py",
                "text": "def new_login():\n    return True\n",
                "prechunked": True,
                "chunk_type": "symbol",
                "symbol": "new_login",
                "line_start": 1,
                "line_end": 2,
            }
        ]
    )

    assert added == 1
    assert retrieval_service._index is not None
    assert retrieval_service._index.d == 256
    assert retrieval_service._meta["dim"] == 256
    assert len(retrieval_service._meta["ids"]) == 2
