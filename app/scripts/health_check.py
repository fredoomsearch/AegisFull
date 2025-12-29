from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path
from typing import Tuple


def _print_status(name: str, ok: bool, detail: str = "") -> bool:
    status = "ok" if ok else "fail"
    suffix = f": {detail}" if detail else ""
    print(f"[{status}] {name}{suffix}")
    return ok


def _check_llm() -> Tuple[bool, str]:
    try:
        from app.llm_client_offload import generate_response
    except Exception as exc:  # noqa: BLE001
        return False, f"import failed: {exc}"

    try:
        resp = generate_response(
            [
                {"role": "system", "content": "You are AEGIS."},
                {"role": "user", "content": "ping"},
            ],
            max_new_tokens=8,
        )
    except Exception as exc:  # noqa: BLE001
        return False, f"call failed: {exc}"

    text = (resp or "").strip()
    if not text:
        return False, "empty response"

    bad_markers = (
        "Local LLM backend is not available",
        "took too long",
        "couldn't generate a response",
    )
    if any(m in text for m in bad_markers):
        return False, text[:160]
    return True, text[:160]


def _check_embeddings() -> Tuple[bool, str]:
    try:
        from app.services.embedding_service import prepare_embeddings
    except Exception as exc:  # noqa: BLE001
        return False, f"import failed: {exc}"

    try:
        status = prepare_embeddings()
    except Exception as exc:  # noqa: BLE001
        return False, f"prepare failed: {exc}"

    mode = status.get("mode") or "unknown"
    err = status.get("error")
    detail = f"mode={mode}"
    if err:
        detail = f"{detail}, error={err}"
    return True, detail


def _check_ingest() -> Tuple[bool, str]:
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "sample_repo"
            root.mkdir(parents=True, exist_ok=True)
            (root / "hello.txt").write_text("hello world", encoding="utf-8")

            # Use an isolated FAISS index directory for the health check.
            os.environ["AEGIS_INDEX_DIR"] = str(Path(tmpdir) / "faiss_index")

            from app.scripts import ingest_repo

            added = ingest_repo.ingest(
                root,
                max_files=5,
                max_file_bytes=5000,
                max_total_bytes=20000,
            )
            if added <= 0:
                return False, "no chunks added"
            return True, f"chunks={added}"
    except Exception as exc:  # noqa: BLE001
        return False, f"ingest failed: {exc}"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="AEGIS health check (LLM + embeddings + ingest)")
    parser.add_argument("--skip-llm", action="store_true", help="Skip LLM check")
    parser.add_argument("--skip-embeddings", action="store_true", help="Skip embeddings check")
    parser.add_argument("--skip-ingest", action="store_true", help="Skip ingest check")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    ok = True
    if not args.skip_llm:
        ok = _print_status("llm", *_check_llm()) and ok
    if not args.skip_embeddings:
        ok = _print_status("embeddings", *_check_embeddings()) and ok
    if not args.skip_ingest:
        ok = _print_status("ingest", *_check_ingest()) and ok

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
