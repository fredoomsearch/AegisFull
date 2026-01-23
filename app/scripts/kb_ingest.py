"""
Quick knowledge-base ingest with versioning and chunk hashing.

Usage (from repo root, venv active):
    python -m app.scripts.kb_ingest --title "Colombia facts" --topic "colombia" --year 2026 --lang es --source "manual" --file data/colombia.txt

What it does:
 - Ensures KB tables exist (see docs/kb_schema.sql).
 - Upserts document, creates a new version, marks previous as not current.
 - Deletes old chunks for that doc, inserts new hashed chunks.

Embedding: This script does NOT embed; call your embedding pipeline afterwards,
using kb_chunks rows (is_current via kb_versions).
"""

from __future__ import annotations

import argparse
import hashlib
import textwrap
from pathlib import Path
from typing import Iterable, List, Tuple

from sqlalchemy import text

from app.db.base import engine

CHUNK_SIZE = 800  # chars


def _read_text(path: Path) -> str:
    data = path.read_text(encoding="utf-8", errors="ignore")
    return data.strip()


def _chunk(text: str, size: int = CHUNK_SIZE, overlap: int = 80) -> Iterable[str]:
    start = 0
    n = len(text)
    while start < n:
        end = min(n, start + size)
        yield text[start:end].strip()
        start = end - overlap
        if start < 0:
            start = 0


def ensure_schema() -> None:
    sql = Path("docs/kb_schema.sql").read_text(encoding="utf-8")
    with engine.begin() as conn:
        conn.execute(text(sql))


def upsert_document(title: str, source: str, topic: str, year: int, lang: str, text_body: str) -> Tuple[int, int]:
    chunks = [c for c in _chunk(text_body) if c]
    if not chunks:
        raise ValueError("No chunks produced from text.")

    with engine.begin() as conn:
        # document
        doc_row = conn.execute(
            text(
                """
                INSERT INTO kb_documents(title, source, topic, year, lang)
                VALUES (:title, :source, :topic, :year, :lang)
                ON CONFLICT (title, source, topic, year, lang)
                DO UPDATE SET updated_at=now()
                RETURNING id
                """
            ),
            dict(title=title, source=source, topic=topic, year=year, lang=lang),
        ).first()
        doc_id = int(doc_row[0])

        # version number
        version_row = conn.execute(
            text("SELECT COALESCE(MAX(version), 0)+1 FROM kb_versions WHERE doc_id=:doc_id"),
            dict(doc_id=doc_id),
        ).first()
        version = int(version_row[0])

        # close previous versions
        conn.execute(
            text(
                """
                UPDATE kb_versions
                   SET is_current = FALSE, valid_to = now()
                 WHERE doc_id = :doc_id AND is_current = TRUE
                """
            ),
            dict(doc_id=doc_id),
        )

        # create version
        version_row = conn.execute(
            text(
                """
                INSERT INTO kb_versions(doc_id, version, is_current)
                VALUES (:doc_id, :version, TRUE)
                RETURNING id
                """
            ),
            dict(doc_id=doc_id, version=version),
        ).first()
        version_id = int(version_row[0])

        # delete old chunks for this doc/version scope
        conn.execute(
            text("DELETE FROM kb_chunks WHERE doc_id = :doc_id AND version_id IN (SELECT id FROM kb_versions WHERE doc_id=:doc_id)"),
            dict(doc_id=doc_id),
        )

        # insert chunks
        for chunk_text in chunks:
            h = hashlib.sha1(chunk_text.encode("utf-8")).hexdigest()
            conn.execute(
                text(
                    """
                    INSERT INTO kb_chunks(doc_id, version_id, chunk_text, chunk_hash, chunk_year, topic, lang)
                    VALUES (:doc_id, :version_id, :chunk_text, :chunk_hash, :chunk_year, :topic, :lang)
                    """
                ),
                dict(
                    doc_id=doc_id,
                    version_id=version_id,
                    chunk_text=chunk_text,
                    chunk_hash=h,
                    chunk_year=year,
                    topic=topic,
                    lang=lang,
                ),
            )
    return doc_id, version


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--title", required=True)
    ap.add_argument("--source", default="manual")
    ap.add_argument("--topic", required=True)
    ap.add_argument("--year", type=int, required=True)
    ap.add_argument("--lang", default="es")
    ap.add_argument("--file", type=Path, required=True)
    args = ap.parse_args()

    ensure_schema()
    body = _read_text(args.file)
    doc_id, version = upsert_document(args.title, args.source, args.topic, args.year, args.lang, body)
    print(f"Upserted doc_id={doc_id} version={version} chunks_size={CHUNK_SIZE}")


if __name__ == "__main__":
    main()

