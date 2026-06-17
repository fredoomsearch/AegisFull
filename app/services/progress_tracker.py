from __future__ import annotations

from datetime import datetime, timezone
import re
from pathlib import Path
from typing import Dict, Optional


ROOT = Path(__file__).resolve().parents[2]
PROGRESS_FILE = ROOT / "PROGRESO_FASES.md"
SNAPSHOT_START = "<!-- PROGRESS_SNAPSHOT_START -->"
SNAPSHOT_END = "<!-- PROGRESS_SNAPSHOT_END -->"


def read_progress_file(path: Optional[Path] = None) -> str:
    target = Path(path) if path else PROGRESS_FILE
    try:
        return target.read_text(encoding="utf-8")
    except Exception:
        return ""


def write_progress_file(content: str, path: Optional[Path] = None) -> bool:
    target = Path(path) if path else PROGRESS_FILE
    try:
        target.write_text(content, encoding="utf-8")
        return True
    except Exception:
        return False


def update_phase_percentage(phase_label: str, percent: int, note: Optional[str] = None, path: Optional[Path] = None) -> bool:
    """Update or append a phase percentage in the progress markdown file.

    Matches the first heading line where `phase_label` is a substring of the heading.
    """
    content = read_progress_file(path)
    if content is None:
        return False

    lines = content.splitlines()
    changed = False
    out_lines: list[str] = []
    pattern = re.compile(r"^- \*\*(?P<heading>[^*]+)\*\*:\s*(?P<pct>\d+)%(?::(?P<desc>.*))?$")

    timestamp_updated = False
    timestamp_patterns = (
        "Última actualización:",
        "Last updated:",
    )
    for ln in lines:
        if any(ln.startswith(pattern) for pattern in timestamp_patterns):
            updated_ts = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
            prefix = ln.split(":", 1)[0]
            out_lines.append(f"{prefix}: {updated_ts}")
            timestamp_updated = True
            continue
        m = pattern.match(ln)
        if m:
            heading = m.group("heading").strip()
            desc = (m.group("desc") or "").strip()
            if phase_label.lower() in heading.lower():
                desc_text = f" {note.strip()}" if note else (f" {desc}" if desc else "")
                out_lines.append(f"- **{heading}**: {int(percent)}%:{desc_text}")
                changed = True
                continue
        out_lines.append(ln)

    if not timestamp_updated:
        # Insert timestamp after the first line if missing
        if len(out_lines) >= 1 and out_lines[0].startswith("#"):
            updated_ts = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
            out_lines.insert(1, f"Última actualización: {updated_ts}")
        else:
            updated_ts = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
            out_lines.insert(0, f"Última actualización: {updated_ts}")

    if not changed:
        note_text = f": {note.strip() if note else ''}"
        out_lines.append(f"- **{phase_label}**: {int(percent)}%{note_text}")

    new_content = "\n".join(out_lines) + "\n"
    return write_progress_file(new_content, path)


def _update_last_updated_timestamp(content: str) -> str:
    lines = content.splitlines()
    timestamp_patterns = (
        "Última actualización:",
        "Last updated:",
    )
    updated_ts = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    out_lines: list[str] = []
    timestamp_updated = False
    for ln in lines:
        if any(ln.startswith(pattern) for pattern in timestamp_patterns):
            prefix = ln.split(":", 1)[0]
            out_lines.append(f"{prefix}: {updated_ts}")
            timestamp_updated = True
        else:
            out_lines.append(ln)

    if not timestamp_updated:
        if out_lines and out_lines[0].startswith("#"):
            out_lines.insert(1, f"Última actualización: {updated_ts}")
        else:
            out_lines.insert(0, f"Última actualización: {updated_ts}")

    return "\n".join(out_lines)


def update_snapshot_block(block_content: str, path: Optional[Path] = None) -> bool:
    content = read_progress_file(path)
    if content is None:
        return False

    start = SNAPSHOT_START
    end = SNAPSHOT_END
    body = block_content.rstrip()
    replacement = f"{start}\n{body}\n{end}"

    if start in content and end in content:
        before, rest = content.split(start, 1)
        _, after = rest.split(end, 1)
        content = before + replacement + after
    else:
        content = content.rstrip() + "\n\n" + replacement + "\n"

    content = _update_last_updated_timestamp(content)
    return write_progress_file(content, path)


def snapshot_progress(path: Optional[Path] = None) -> Dict[str, int]:
    """Return a mapping of heading -> percent parsed from the progress file."""
    content = read_progress_file(path)
    result: Dict[str, int] = {}
    if not content:
        return result
    pattern = re.compile(r"^- \*\*(?P<heading>[^*]+)\*\*:\s*(?P<pct>\d+)%(?::(?P<desc>.*))?$")
    for ln in content.splitlines():
        m = pattern.match(ln)
        if m:
            heading = m.group("heading").strip()
            pct = int(m.group("pct"))
            result[heading] = pct
    return result


__all__ = [
    "read_progress_file",
    "write_progress_file",
    "update_phase_percentage",
    "snapshot_progress",
    "update_snapshot_block",
]
