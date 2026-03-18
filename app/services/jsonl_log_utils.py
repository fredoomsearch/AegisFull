from __future__ import annotations

"""
Shared helpers for append-only JSONL log stores.

Why this module exists:
- Avoid duplicated low-level file iteration/initialization logic.
- Keep trade and prediction logs consistent across services.
"""

import os
from pathlib import Path
from typing import Iterator


def ensure_log_dir(path: Path) -> None:
    """Create the log directory if it does not exist yet."""
    path.mkdir(parents=True, exist_ok=True)


def iter_recent_lines(path: Path) -> Iterator[str]:
    """
    Yield file lines from newest to oldest without loading full file in memory.

    This is intentionally generic and used by both prediction and trade logs.
    """
    if not path.exists():
        return iter(())

    chunk_size = 8192

    def _generator() -> Iterator[str]:
        with path.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            pos = handle.tell()
            buffer = b""
            while pos > 0:
                read_size = min(chunk_size, pos)
                pos -= read_size
                handle.seek(pos)
                chunk = handle.read(read_size)
                buffer = chunk + buffer
                lines = buffer.splitlines()
                if pos > 0:
                    buffer = lines[0] if lines else buffer
                    lines = lines[1:] if lines else []
                else:
                    buffer = b""
                for line in reversed(lines):
                    yield line.decode("utf-8", errors="replace")
            if buffer:
                yield buffer.decode("utf-8", errors="replace")

    return _generator()
