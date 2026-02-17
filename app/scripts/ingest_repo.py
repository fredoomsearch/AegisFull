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
DEFAULT_MANIFEST_MAX_FILES = int(os.getenv("AEGIS_INGEST_MANIFEST_MAX_FILES", "4000"))
MAX_EXTRACT_CHARS = int(os.getenv("AEGIS_INGEST_MAX_EXTRACT_CHARS", "200000"))
MAX_EXTRACT_PAGES = int(os.getenv("AEGIS_INGEST_MAX_EXTRACT_PAGES", "30"))
MAX_EXTRACT_ROWS = int(os.getenv("AEGIS_INGEST_MAX_EXTRACT_ROWS", "2000"))

try:
    from pypdf import PdfReader  # type: ignore
except Exception:
    PdfReader = None  # type: ignore

try:
    from docx import Document  # type: ignore
except Exception:
    Document = None  # type: ignore

try:
    from openpyxl import load_workbook  # type: ignore
except Exception:
    load_workbook = None  # type: ignore

try:
    from pptx import Presentation  # type: ignore
except Exception:
    Presentation = None  # type: ignore

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
    ".csv",
    ".tsv",
    ".xml",
    ".conf",
    ".cfg",
    ".properties",
    ".rst",
    ".mdx",
    ".sh",
    ".bash",
    ".zsh",
    ".go",
    ".rs",
    ".java",
    ".kt",
    ".php",
    ".pdf",
    ".docx",
    ".xlsx",
    ".pptx",
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


def _truncate_text(text: str, limit: int = MAX_EXTRACT_CHARS) -> str:
    if not text:
        return ""
    if limit <= 0 or len(text) <= limit:
        return text
    return text[:limit]


def _read_pdf(path: Path) -> str:
    if PdfReader is None:
        return ""
    try:
        reader = PdfReader(str(path))
    except Exception:
        return ""

    chunks: List[str] = []
    pages = reader.pages[: max(1, MAX_EXTRACT_PAGES)]
    for page in pages:
        try:
            txt = page.extract_text() or ""
        except Exception:
            txt = ""
        if txt.strip():
            chunks.append(txt.strip())
        if sum(len(c) for c in chunks) >= MAX_EXTRACT_CHARS:
            break
    return _truncate_text("\n\n".join(chunks))


def _read_docx(path: Path) -> str:
    if Document is None:
        return ""
    try:
        doc = Document(str(path))
    except Exception:
        return ""
    chunks: List[str] = []
    for p in doc.paragraphs:
        txt = (p.text or "").strip()
        if txt:
            chunks.append(txt)
        if sum(len(c) for c in chunks) >= MAX_EXTRACT_CHARS:
            break
    return _truncate_text("\n".join(chunks))


def _read_xlsx(path: Path) -> str:
    if load_workbook is None:
        return ""
    try:
        wb = load_workbook(str(path), read_only=True, data_only=True)
    except Exception:
        return ""

    chunks: List[str] = []
    row_budget = max(1, MAX_EXTRACT_ROWS)
    seen_rows = 0
    try:
        for ws in wb.worksheets:
            chunks.append(f"# Sheet: {ws.title}")
            for row in ws.iter_rows(values_only=True):
                values = [str(v).strip() for v in row if v is not None and str(v).strip()]
                if values:
                    chunks.append(" | ".join(values))
                seen_rows += 1
                if seen_rows >= row_budget or sum(len(c) for c in chunks) >= MAX_EXTRACT_CHARS:
                    break
            if seen_rows >= row_budget or sum(len(c) for c in chunks) >= MAX_EXTRACT_CHARS:
                break
    finally:
        try:
            wb.close()
        except Exception:
            pass
    return _truncate_text("\n".join(chunks))


def _read_pptx(path: Path) -> str:
    if Presentation is None:
        return ""
    try:
        prs = Presentation(str(path))
    except Exception:
        return ""
    chunks: List[str] = []
    for idx, slide in enumerate(prs.slides[: max(1, MAX_EXTRACT_PAGES)], start=1):
        chunks.append(f"# Slide {idx}")
        for shape in slide.shapes:
            txt = getattr(shape, "text", "") or ""
            txt = txt.strip()
            if txt:
                chunks.append(txt)
            if sum(len(c) for c in chunks) >= MAX_EXTRACT_CHARS:
                break
        if sum(len(c) for c in chunks) >= MAX_EXTRACT_CHARS:
            break
    return _truncate_text("\n".join(chunks))


def _read_text(path: Path) -> str:
    try:
        suffix = path.suffix.lower()
        if suffix == ".pdf":
            return _read_pdf(path)
        if suffix == ".docx":
            return _read_docx(path)
        if suffix == ".xlsx":
            return _read_xlsx(path)
        if suffix == ".pptx":
            return _read_pptx(path)
        return _truncate_text(path.read_text(encoding="utf-8", errors="ignore"))
    except Exception:
        return ""


def ingest(root: Path, max_files: int, max_file_bytes: int, max_total_bytes: int) -> int:
    """Walk files, chunk text, embed, and write to the FAISS index."""
    docs: List[Tuple[str, str]] = []
    manifest_lines: List[str] = []
    total_bytes = 0
    scanned_files = 0
    ingested_files = 0
    last_report = 0
    total_added = 0
    embedding_started = False
    skipped_ext = 0
    skipped_large = 0
    skipped_empty = 0
    skipped_quota = 0
    manifest_truncated = False

    for path in _iter_files(root):
        if not path.is_file():
            continue
        scanned_files += 1

        try:
            size = path.stat().st_size
        except OSError:
            continue

        rel = str(path.relative_to(root))
        if len(manifest_lines) < DEFAULT_MANIFEST_MAX_FILES:
            manifest_lines.append(f"{rel}\t{size}")
        else:
            manifest_truncated = True

        if ingested_files >= max_files:
            skipped_quota += 1
            continue

        ext = path.suffix.lower()
        if DEFAULT_EXTS and ext not in DEFAULT_EXTS:
            skipped_ext += 1
            continue

        if max_file_bytes and size > max_file_bytes:
            skipped_large += 1
            continue
        if max_total_bytes and total_bytes + size > max_total_bytes:
            skipped_quota += 1
            break

        text = _read_text(path)
        if not text.strip():
            skipped_empty += 1
            continue

        # Namespace sources by ingest root folder to avoid cross-project collisions
        # when different uploads share the same relative paths (e.g. app/api.py).
        source = f"{root.name}/{rel}"
        docs.append((source, text))
        total_bytes += size
        ingested_files += 1
        if ingested_files - last_report >= 200:
            print(f"[ingest] scanned={scanned_files} kept={ingested_files} bytes={total_bytes}", flush=True)
            last_report = ingested_files

        if DEFAULT_BATCH_FILES > 0 and len(docs) >= DEFAULT_BATCH_FILES:
            if not embedding_started:
                print("[ingest] embedding + indexing...", flush=True)
                embedding_started = True
            total_added += add_documents(docs)
            docs.clear()

    if manifest_lines:
        summary_lines = [
            f"ROOT_PATH: {root}",
            f"SCANNED_FILES: {scanned_files}",
            f"INGESTED_TEXT_FILES: {ingested_files}",
            f"SKIPPED_EXT: {skipped_ext}",
            f"SKIPPED_FILE_SIZE: {skipped_large}",
            f"SKIPPED_EMPTY: {skipped_empty}",
            f"SKIPPED_QUOTA_OR_LIMIT: {skipped_quota}",
            "",
            "FILE_INVENTORY (REL_PATH<TAB>SIZE_BYTES):",
            *manifest_lines,
        ]
        if manifest_truncated:
            summary_lines.append(f"... (manifest truncated at {DEFAULT_MANIFEST_MAX_FILES} files)")
        docs.append((f"{root.name}/__manifest__/files.tsv", "\n".join(summary_lines)))

    if not docs and total_added == 0:
        print("No files ingested (nothing matched filters or root is empty).")
        return 0

    if docs:
        print(f"[ingest] collected text_files={ingested_files} bytes={total_bytes}", flush=True)
        if not embedding_started:
            print("[ingest] embedding + indexing...", flush=True)
            embedding_started = True
        total_added += add_documents(docs)
        docs.clear()

    print(
        f"[ingest] summary scanned={scanned_files} text_files={ingested_files} "
        f"skipped_ext={skipped_ext} skipped_size={skipped_large} "
        f"skipped_empty={skipped_empty} skipped_quota={skipped_quota}",
        flush=True,
    )
    print(f"[ingest] done files={ingested_files} chunks={total_added}", flush=True)
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
