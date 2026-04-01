from __future__ import annotations

import glob
import json
import logging
import os
import re
import shutil
import threading
from datetime import UTC, datetime
from typing import Any, Dict, List, Optional, TypedDict

from dotenv import load_dotenv

from app.services.input_normalizer import normalize_user_input, strip_attachment_context
from app.utils.runtime_helpers import now_ms as _now_ms

logger = logging.getLogger(__name__)
load_dotenv()

DATA_DIR = os.getenv("AEGIS_DATA_DIR", "data")
DURABLE_MEMORY_FILE = os.path.join(DATA_DIR, "durable_memory.json")
MAX_BACKUPS = int(os.getenv("AEGIS_DURABLE_MEMORY_MAX_BACKUPS", "5"))
PERSIST = (os.getenv("AEGIS_DURABLE_MEMORY_PERSIST", "1") or "1").lower() in {"1", "true", "yes", "on"}
MAX_ITEMS = int(os.getenv("AEGIS_DURABLE_MEMORY_MAX_NOTES", "24"))
MAX_SUMMARY_CHARS = int(os.getenv("AEGIS_DURABLE_MEMORY_MAX_SUMMARY_CHARS", "900"))


class DurableMemoryProfile(TypedDict):
    subject: str
    facts: List[str]
    preferences: List[str]
    notes: List[str]
    created_at_ms: int
    updated_at_ms: int


_lock = threading.RLock()
profiles: Dict[str, DurableMemoryProfile] = {}


def _ensure_dir() -> None:
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to ensure durable memory dir %s: %s", DATA_DIR, exc)


def _backup(path: str) -> None:
    if MAX_BACKUPS <= 0 or not os.path.exists(path):
        return
    stamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    backup = f"{path}.{stamp}.bak"
    try:
        shutil.copy2(path, backup)
        old = sorted(glob.glob(f"{path}.*.bak"), reverse=True)
        for item in old[MAX_BACKUPS:]:
            try:
                os.remove(item)
            except Exception:
                pass
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to backup durable memory file %s: %s", path, exc)


def _load_file(path: str) -> Dict[str, DurableMemoryProfile]:
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to load durable memory file %s: %s", path, exc)
        return {}
    if not isinstance(raw, dict):
        return {}
    result: Dict[str, DurableMemoryProfile] = {}
    for subject, payload in raw.items():
        if not isinstance(subject, str) or not isinstance(payload, dict):
            continue
        subj = subject.strip().lower() or "anonymous"
        result[subj] = {
            "subject": subj,
            "facts": [str(x).strip() for x in (payload.get("facts") or []) if str(x).strip()][:MAX_ITEMS],
            "preferences": [str(x).strip() for x in (payload.get("preferences") or []) if str(x).strip()][:MAX_ITEMS],
            "notes": [str(x).strip() for x in (payload.get("notes") or []) if str(x).strip()][:MAX_ITEMS],
            "created_at_ms": int(payload.get("created_at_ms") or _now_ms()),
            "updated_at_ms": int(payload.get("updated_at_ms") or _now_ms()),
        }
    return result


def _save_file(path: str, data: Dict[str, DurableMemoryProfile]) -> bool:
    if not PERSIST:
        return True
    _ensure_dir()
    tmp = f"{path}.tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        _backup(path)
        os.replace(tmp, path)
        return True
    except Exception as exc:  # noqa: BLE001
        logger.exception("Failed to persist durable memory file %s: %s", path, exc)
        return False


def _normalize_subject(subject: Optional[str]) -> str:
    raw = re.sub(r"\s+", " ", str(subject or "").strip().lower())
    return raw[:120] or "anonymous"


def _dedupe_extend(target: List[str], additions: List[str]) -> List[str]:
    out = [item for item in target if item]
    for item in additions:
        value = str(item or "").strip()
        if not value:
            continue
        out = [x for x in out if x != value]
        out.append(value)
    return out[-MAX_ITEMS:]


def _extract_notes(user_msg: str, session_state: Optional[Dict[str, Any]] = None) -> tuple[list[str], list[str], list[str]]:
    clean = strip_attachment_context(normalize_user_input(user_msg or ""))
    text = re.sub(r"\s+", " ", clean).strip()
    if not text:
        return [], [], []
    lower = text.lower()

    facts: list[str] = []
    preferences: list[str] = []
    notes: list[str] = []

    name_match = re.search(r"\b(?:call me|my name is|me llamo|ll[áa]mame)\s+([A-Za-z][A-Za-z0-9_\-]{1,40})\b", text, re.IGNORECASE)
    if name_match:
        facts.append(f"name: {name_match.group(1).strip()}")

    if re.search(r"\b(i prefer|prefiero)\b.*\b(concise|brief|short|succinct)\b", text, re.IGNORECASE):
        preferences.append("prefers concise answers")
    if re.search(r"\b(i prefer|prefiero)\b.*\b(detailed|verbose|thorough)\b", text, re.IGNORECASE):
        preferences.append("prefers detailed answers")
    if re.search(r"\b(i prefer|prefiero)\b.*\b(step[- ]?by[- ]?step|steps)\b", text, re.IGNORECASE):
        preferences.append("prefers step-by-step answers")
    if re.search(r"\b(i prefer|prefiero)\b.*\b(spanish|espa[nñ]ol)\b", text, re.IGNORECASE):
        preferences.append("prefers Spanish replies")
    if re.search(r"\b(i prefer|prefiero)\b.*\b(english|ingl[eé]s)\b", text, re.IGNORECASE):
        preferences.append("prefers English replies")

    for prefix, label in (("remember that", "remember"), ("recuerda que", "remember"), ("i work with", "domain"), ("trabajo con", "domain"), ("i use", "domain"), ("uso", "domain")):
        if prefix in lower:
            tail = text.split(prefix, 1)[-1].strip(" :-")
            if tail:
                notes.append(f"{label}: {tail[:240]}")

    if "remember" in lower or "recuerda" in lower:
        notes.append(text[:240])

    answer_style = (session_state or {}).get("answer_style") if isinstance(session_state, dict) else None
    if isinstance(answer_style, dict):
        if answer_style.get("concise"):
            preferences.append("prefers concise answers")
        if answer_style.get("include_steps"):
            preferences.append("prefers step-by-step answers")

    return facts, preferences, notes


def load_durable_memory() -> Dict[str, DurableMemoryProfile]:
    with _lock:
        return _load_file(DURABLE_MEMORY_FILE)


def save_durable_memory(data: Dict[str, DurableMemoryProfile]) -> bool:
    with _lock:
        return _save_file(DURABLE_MEMORY_FILE, data)


profiles = load_durable_memory() or {}


def get_durable_memory(subject: Optional[str]) -> DurableMemoryProfile:
    normalized = _normalize_subject(subject)
    with _lock:
        profile = profiles.get(normalized)
        if profile is None:
            ts = _now_ms()
            profile = {
                "subject": normalized,
                "facts": [],
                "preferences": [],
                "notes": [],
                "created_at_ms": ts,
                "updated_at_ms": ts,
            }
            profiles[normalized] = profile
        return {
            "subject": profile["subject"],
            "facts": list(profile.get("facts") or []),
            "preferences": list(profile.get("preferences") or []),
            "notes": list(profile.get("notes") or []),
            "created_at_ms": int(profile.get("created_at_ms") or _now_ms()),
            "updated_at_ms": int(profile.get("updated_at_ms") or _now_ms()),
        }


def get_durable_memory_summary(subject: Optional[str], *, max_chars: int = MAX_SUMMARY_CHARS) -> str:
    profile = get_durable_memory(subject)
    parts: list[str] = []
    if profile["facts"]:
        parts.append("Facts: " + "; ".join(profile["facts"][:4]))
    if profile["preferences"]:
        parts.append("Preferences: " + "; ".join(profile["preferences"][:4]))
    if profile["notes"]:
        parts.append("Notes: " + "; ".join(profile["notes"][:3]))
    summary = "\n".join(parts).strip()
    if len(summary) > max_chars:
        summary = summary[: max_chars - 3] + "..."
    return summary


def update_durable_memory(
    subject: Optional[str],
    user_msg: str,
    assistant_msg: str = "",
    *,
    session_state: Optional[Dict[str, Any]] = None,
    mode: str = "",
    active_project_id: Optional[str] = None,
) -> DurableMemoryProfile:
    normalized = _normalize_subject(subject)
    facts, preferences, notes = _extract_notes(user_msg, session_state=session_state)
    if active_project_id:
        notes.append(f"active_project: {active_project_id}")
    if mode:
        notes.append(f"mode: {mode}")
    if assistant_msg and any(token in user_msg.lower() for token in ("remember", "recuerda")):
        notes.append(str(assistant_msg).strip()[:240])

    with _lock:
        profile = profiles.get(normalized)
        if profile is None:
            ts = _now_ms()
            profile = {
                "subject": normalized,
                "facts": [],
                "preferences": [],
                "notes": [],
                "created_at_ms": ts,
                "updated_at_ms": ts,
            }
        profile["facts"] = _dedupe_extend(list(profile.get("facts") or []), facts)
        profile["preferences"] = _dedupe_extend(list(profile.get("preferences") or []), preferences)
        profile["notes"] = _dedupe_extend(list(profile.get("notes") or []), notes)
        profile["updated_at_ms"] = _now_ms()
        profiles[normalized] = profile
        save_durable_memory(profiles)
        return {
            "subject": profile["subject"],
            "facts": list(profile.get("facts") or []),
            "preferences": list(profile.get("preferences") or []),
            "notes": list(profile.get("notes") or []),
            "created_at_ms": int(profile.get("created_at_ms") or _now_ms()),
            "updated_at_ms": int(profile.get("updated_at_ms") or _now_ms()),
        }


def snapshot() -> Dict[str, Any]:
    with _lock:
        return {"path": DURABLE_MEMORY_FILE, "subject_count": len(profiles), "subjects": sorted(profiles.keys())[:20]}


__all__ = [
    "DURABLE_MEMORY_FILE",
    "get_durable_memory",
    "get_durable_memory_summary",
    "load_durable_memory",
    "save_durable_memory",
    "snapshot",
    "update_durable_memory",
]
