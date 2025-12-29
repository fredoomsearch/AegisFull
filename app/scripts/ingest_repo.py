#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Iterable, List, Tuple

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

# Defaults (override with env vars or CLI flags).
DEFAULT_MAX_FILES = int(os.getenv("AEGIS_INGEST_MAX_FILES", "1500"))
DEFAULT_MAX_FILE_BYTES = int(os.getenv("AEGIS_INGEST_MAX_FILE_BYTES", "250000"))
DEFAULT_MAX_TOTAL_BYTES = int(os.getenv("AEGIS_INGEST_MAX_TOTAL_BYTES", "7000000"))
DEFAULT_BATCH_FILES = int(os.getenv("AEGIS_INGEST_BATCH_FILES", "200"))

def _apply_thread_env(threads: int) -> None:
    """Allow embedding to use more CPU threads if configured."""
    for var in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
        os.environ.setdefault(var, str(threads))


raw_threads = os.getenv("AEGIS_INGEST_THREADS", "").strip()
if raw_threads.isdigit() and int(raw_threads) > 0:
    _apply_thread_env(int(raw_threads))
else:
    # Default to using most CPU cores to speed up embeddings.
    cpu_count = os.cpu_count() or 1
    _apply_thread_env(max(1, cpu_count - 1))

from app.services.retrieval_service import add_documents  # noqa: E402

DEFAULT_EXTS = {
    ".py",
    ".js",
    ".ts",
    ".tsx",
    ".jsx",
    ".html",
    ".css",
    ".scss",
    ".md",
    ".txt",
    ".json",
    ".yml",
    ".yaml",
    ".toml",
    ".ini",
    ".env",
    ".sql",
    ".sh",
    ".bash",
    ".zsh",
    ".go",
    ".rs",
    ".java",
    ".kt",
    ".php",
}

EXCLUDED_DIRS = {
    ".git",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    "node_modules",
    "venv",
    ".venv",
    "dist",
    "build",
    "data",
    "uploads",
    "logs",
    "artifacts",
}

EXCLUDED_FILES = {
    "aegis.db",
}


def _iter_files(root: Path) -> Iterable[Path]:
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in EXCLUDED_DIRS]
        for fname in filenames:
            if fname in EXCLUDED_FILES:
                continue
            path = Path(dirpath) / fname
            yield path


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""


def ingest(root: Path, max_files: int, max_file_bytes: int, max_total_bytes: int) -> int:
    """Walk files, chunk text, embed, and write to the FAISS index."""
    docs: List[Tuple[str, str]] = []
    total_bytes = 0
    seen_files = 0
    last_report = 0
    total_added = 0
    embedding_started = False

    for path in _iter_files(root):
        if seen_files >= max_files:
            break
        if not path.is_file():
            continue

        ext = path.suffix.lower()
        if DEFAULT_EXTS and ext not in DEFAULT_EXTS:
            continue

        try:
            size = path.stat().st_size
        except OSError:
            continue
        if max_file_bytes and size > max_file_bytes:
            continue
        if max_total_bytes and total_bytes + size > max_total_bytes:
            break

        text = _read_text(path)
        if not text.strip():
            continue

        rel = str(path.relative_to(root))
        docs.append((rel, text))
        total_bytes += size
        seen_files += 1
        if seen_files - last_report >= 200:
            print(f"[ingest] scanned={seen_files} kept={len(docs)} bytes={total_bytes}", flush=True)
            last_report = seen_files

        if DEFAULT_BATCH_FILES > 0 and len(docs) >= DEFAULT_BATCH_FILES:
            if not embedding_started:
                print("[ingest] embedding + indexing...", flush=True)
                embedding_started = True
            total_added += add_documents(docs)
            docs.clear()

    if not docs and total_added == 0:
        print("No files ingested (nothing matched filters).")
        return 0

    if docs:
        print(f"[ingest] collected files={len(docs)} bytes={total_bytes}", flush=True)
        if not embedding_started:
            print("[ingest] embedding + indexing...", flush=True)
            embedding_started = True
        total_added += add_documents(docs)
        docs.clear()

    print(f"[ingest] done files={seen_files} chunks={total_added}", flush=True)
    return total_added


def main() -> int:
    parser = argparse.ArgumentParser(description="Ingest a repo and build FAISS embeddings.")
    parser.add_argument("--root", required=True, help="Root directory to ingest")
    parser.add_argument("--max-files", type=int, default=DEFAULT_MAX_FILES)
    parser.add_argument("--max-file-bytes", type=int, default=DEFAULT_MAX_FILE_BYTES)
    parser.add_argument("--max-total-bytes", type=int, default=DEFAULT_MAX_TOTAL_BYTES)

    args = parser.parse_args()
    root = Path(args.root).resolve()
    if not root.exists() or not root.is_dir():
        print("Invalid root:", root)
        return 1

    try:
        ingest(root, args.max_files, args.max_file_bytes, args.max_total_bytes)
    except Exception as exc:
        print("Ingest failed:", exc)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
