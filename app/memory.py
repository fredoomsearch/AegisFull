from __future__ import annotations

"""
Lightweight JSON-backed conversation memory (fallback when DB is unavailable).

- Keeps conversations in a dict[str, Conversation].
- Persists to disk atomically (CONV_FILE).
- Trims old messages and merges them into a summary.
- Optional encryption at rest using Fernet (cryptography).
"""

import base64
import glob
import hashlib
import json
import logging
import os
import shutil
import threading
import uuid
from datetime import UTC, datetime
from typing import Any, Dict, List, Optional, TypedDict

from dotenv import load_dotenv
from app.services.session_state import default_session_state, normalize_session_state, update_session_state
from app.utils.runtime_helpers import now_ms as _now_ms

logger = logging.getLogger(__name__)

# Try to import cryptography for encryption
try:
    from cryptography.fernet import Fernet
    _ENCRYPTION_AVAILABLE = True
except Exception:
    _ENCRYPTION_AVAILABLE = False
    Fernet = None

# ============================================================
# LOCAL CONFIG (decoupled from llm_client_offload)
# ============================================================

load_dotenv()

DATA_DIR: str = os.getenv("AEGIS_DATA_DIR", "data")
CONV_FILE: str = os.path.join(DATA_DIR, "conversations.json")
MAX_MEMORY_BACKUPS: int = int(os.getenv("AEGIS_MEMORY_MAX_BACKUPS", "5"))
PERSIST_MEMORY: bool = (os.getenv("AEGIS_MEMORY_PERSIST", "1") or "1").lower() in {"1", "true", "yes", "on"}

# How many turns we keep before trimming (user+assistant pairs -> *2 messages)
MAX_HISTORY_TURNS: int = int(os.getenv("AEGIS_MAX_HISTORY_TURNS", "20"))

# Max chars allowed in the summary field
MAX_SUMMARY_CHARS: int = int(os.getenv("AEGIS_MAX_SUMMARY_CHARS", "1400"))
# Max chars per stored message to prevent runaway JSON growth
MAX_MESSAGE_CHARS: int = int(os.getenv("AEGIS_MAX_MESSAGE_CHARS", "4000"))

# Encryption key (32 bytes base64-encoded for Fernet)
_ENCRYPTION_KEY: Optional[bytes] = None
_fernet: Optional[Fernet] = None

def _init_encryption() -> None:
    """Initialize encryption if key is provided."""
    global _ENCRYPTION_KEY, _fernet
    
    key_str = os.getenv("AEGIS_ENCRYPTION_KEY", "").strip()
    if not key_str:
        logger.debug("No encryption key provided; memory encryption disabled.")
        return
    
    if not _ENCRYPTION_AVAILABLE:
        logger.warning("cryptography not installed; memory encryption unavailable.")
        return
    
    try:
        # Accept raw 32-byte key or base64-encoded
        if len(key_str) == 44 and key_str.endswith("="):  # Likely base64
            _ENCRYPTION_KEY = key_str.encode()
        else:
            # Hash password to get 32 bytes
            _ENCRYPTION_KEY = base64.urlsafe_b64encode(hashlib.sha256(key_str.encode()).digest())
        
        _fernet = Fernet(_ENCRYPTION_KEY)
        logger.info("Memory encryption initialized.")
    except Exception as e:
        logger.warning(f"Failed to initialize encryption: {e}")
        _ENCRYPTION_KEY = None
        _fernet = None


def _encrypt(data: str) -> str:
    """Encrypt string data. Returns original if encryption unavailable."""
    if not _fernet or not data:
        return data
    try:
        return _fernet.encrypt(data.encode()).decode()
    except Exception:
        return data


def _decrypt(data: str) -> str:
    """Decrypt string data. Returns original if not encrypted or encryption unavailable."""
    if not _fernet or not data:
        return data
    try:
        return _fernet.decrypt(data.encode()).decode()
    except Exception:
        # Not encrypted or wrong key; return as-is
        return data


class Message(TypedDict):
    role: str
    content: str


class Conversation(TypedDict):
    summary: str
    messages: List[Message]
    state: Dict[str, Any]
    archived: bool
    created_at_ms: int
    updated_at_ms: int


_lock = threading.RLock()
conversations: Dict[str, Conversation] = {}


def _normalize_message(role: str, content: str) -> Message:
    content_str = "" if content is None else str(content)
    if len(content_str) > MAX_MESSAGE_CHARS:
        content_str = content_str[:MAX_MESSAGE_CHARS] + " … [truncated]"
    return {"role": str(role) if role is not None else "user", "content": content_str}


def _ensure_data_dir() -> None:
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to ensure DATA_DIR %s: %s", DATA_DIR, exc)


def _backup_memory_file(path: str) -> None:
    if MAX_MEMORY_BACKUPS <= 0 or not os.path.exists(path):
        return
    ts = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    backup_path = f"{path}.{ts}.bak"
    try:
        shutil.copy2(path, backup_path)
        _prune_old_backups(path)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to backup memory file %s: %s", path, exc)


def _prune_old_backups(path: str) -> None:
    pattern = f"{path}.*.bak"
    backups = sorted(glob.glob(pattern), reverse=True)
    for old in backups[MAX_MEMORY_BACKUPS:]:
        try:
            os.remove(old)
        except Exception:
            logger.debug("Failed to remove old backup %s", old, exc_info=True)


def _safe_json_load(path: str) -> Dict[str, Conversation]:
    if not os.path.exists(path):
        logger.debug("Memory file not found at %s; starting with empty store.", path)
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw_str = f.read()
        
        # Decrypt if needed
        if _fernet and raw_str.startswith("g"):
            raw_str = _decrypt(raw_str)
        
        raw = json.loads(raw_str)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to load memory file %s: %s; using empty store.", path, exc)
        return {}
    
    # Handle new format with checksum
    if "_checksum" in raw:
        stored_checksum = raw.get("_checksum", "")
        data = raw.get("conversations", {})
    else:
        data = raw
        stored_checksum = ""
    
    # Verify checksum if present
    if stored_checksum:
        computed = _compute_checksum(data)
        if computed != stored_checksum:
            logger.warning("Memory integrity check failed for %s; data may be corrupted.", path)
    
    if not isinstance(data, dict):
        logger.warning("Memory file %s did not contain a dict root; using empty store.", path)
        return {}

    result: Dict[str, Conversation] = {}
    for conv_id, conv in data.items():
        if not isinstance(conv_id, str) or not isinstance(conv, dict):
            continue
        summary = conv.get("summary", "") if isinstance(conv.get("summary"), str) else ""
        msgs_raw = conv.get("messages") or []
        msgs: List[Message] = []
        if isinstance(msgs_raw, list):
            for m in msgs_raw:
                if not isinstance(m, dict):
                    continue
                msgs.append(_normalize_message(m.get("role", "user"), m.get("content", "")))
        state = normalize_session_state(conv.get("state") or {})
        archived = bool(conv.get("archived", False))
        created_at_ms = int(conv.get("created_at_ms") or state.get("focus_last_touch_ms") or _now_ms())
        updated_at_ms = int(conv.get("updated_at_ms") or state.get("focus_last_touch_ms") or created_at_ms)
        result[conv_id] = {
            "summary": summary,
            "messages": msgs,
            "state": state,
            "archived": archived,
            "created_at_ms": created_at_ms,
            "updated_at_ms": updated_at_ms,
        }
    return result


def _compute_checksum(data: Dict[str, Conversation]) -> str:
    """Compute SHA-256 checksum for integrity verification."""
    try:
        serialized = json.dumps(data, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(serialized.encode()).hexdigest()[:16]
    except Exception:
        return ""


def _safe_json_write(path: str, data: Dict[str, Conversation]) -> bool:
    if not PERSIST_MEMORY:
        return True
    _ensure_data_dir()
    tmp_file = f"{path}.tmp"
    try:
        # Add checksum for integrity verification
        payload = {
            "_checksum": _compute_checksum(data),
            "conversations": data,
        }
        json_str = json.dumps(payload, ensure_ascii=False, indent=2)
        
        # Encrypt if enabled
        if _fernet:
            json_str = _encrypt(json_str)
        
        with open(tmp_file, "w", encoding="utf-8") as f:
            f.write(json_str)
            f.flush()
            os.fsync(f.fileno())
        _backup_memory_file(path)
        os.replace(tmp_file, path)
        return True
    except Exception as exc:  # noqa: BLE001
        logger.exception("Failed to persist memory file %s: %s", path, exc)
        return False


def load_conversations() -> Dict[str, Conversation]:
    with _lock:
        return _safe_json_load(CONV_FILE)


def save_conversations(data: Dict[str, Conversation]) -> bool:
    with _lock:
        return _safe_json_write(CONV_FILE, data)


conversations = load_conversations() or {}

# Initialize encryption at module load
_init_encryption()


def get_or_create_conversation(conversation_id: Optional[str] = None) -> str:
    global conversations
    with _lock:
        if conversation_id and conversation_id in conversations:
            return conversation_id
        new_id = str(uuid.uuid4())
        ts = _now_ms()
        conversations[new_id] = {
            "summary": "",
            "messages": [],
            "state": default_session_state(),
            "archived": False,
            "created_at_ms": ts,
            "updated_at_ms": ts,
        }
        if not save_conversations(conversations):
            logger.warning("Failed to persist new conversation %s to disk.", new_id)
        logger.debug("Created new in-memory conversation %s", new_id)
        return new_id


def get_conversation_state(conversation_id: str) -> Dict[str, Any]:
    with _lock:
        conv = conversations.get(conversation_id)
        if not conv:
            return default_session_state()
        return normalize_session_state(conv.get("state") or {})


def set_conversation_state(conversation_id: str, state: Dict[str, Any]) -> Dict[str, Any]:
    global conversations
    with _lock:
        conv = conversations.get(conversation_id)
        if conv is None:
            ts = _now_ms()
            conv = {
                "summary": "",
                "messages": [],
                "state": default_session_state(),
                "archived": False,
                "created_at_ms": ts,
                "updated_at_ms": ts,
            }
            conversations[conversation_id] = conv
        conv["state"] = normalize_session_state(state)
        conv["updated_at_ms"] = _now_ms()
        conversations[conversation_id] = conv
        save_conversations(conversations)
        return conv["state"]


def set_conversation_state_fields(conversation_id: str, **fields: Any) -> Dict[str, Any]:
    global conversations
    with _lock:
        conv = conversations.get(conversation_id)
        if conv is None:
            ts = _now_ms()
            conv = {
                "summary": "",
                "messages": [],
                "state": default_session_state(),
                "archived": False,
                "created_at_ms": ts,
                "updated_at_ms": ts,
            }
            conversations[conversation_id] = conv
        state = normalize_session_state(conv.get("state") or {})
        for key, value in fields.items():
            if value is None:
                state[key] = None
            elif isinstance(value, str):
                state[key] = value.strip()
            else:
                state[key] = value
        conv["state"] = normalize_session_state(state)
        conv["updated_at_ms"] = _now_ms()
        conversations[conversation_id] = conv
        save_conversations(conversations)
        return conv["state"]


def list_conversations(limit: int = 20, include_archived: bool = False) -> List[Dict[str, Any]]:
    with _lock:
        rows: List[Dict[str, Any]] = []
        for conv_id, conv in conversations.items():
            archived = bool(conv.get("archived", False))
            if archived and not include_archived:
                continue
            rows.append(
                {
                    "id": conv_id,
                    "summary": str(conv.get("summary") or "").strip(),
                    "archived": archived,
                    "created_at_ms": int(conv.get("created_at_ms") or 0),
                    "updated_at_ms": int(conv.get("updated_at_ms") or 0),
                }
            )
    rows.sort(key=lambda row: int(row.get("updated_at_ms") or 0), reverse=True)
    return rows[: max(1, limit)]


def set_conversation_archived(conversation_id: str, archived: bool = True) -> bool:
    global conversations
    with _lock:
        conv = conversations.get(conversation_id)
        if conv is None:
            return False
        conv["archived"] = bool(archived)
        conv["updated_at_ms"] = _now_ms()
        conversations[conversation_id] = conv
        save_conversations(conversations)
        return True


def delete_conversation(conversation_id: str) -> bool:
    """
    Remove a conversation from the JSON memory store.
    """
    global conversations
    with _lock:
        if conversation_id not in conversations:
            return False
        conversations.pop(conversation_id, None)
        if not save_conversations(conversations):
            logger.warning("Failed to persist deletion for conv_id=%s.", conversation_id)
        return True


def summarize_old_messages(old_messages: List[Message]) -> str:
    """
    Convert a set of messages into a compact summary using the LLM.
    Currently unused by update_memory; kept for compatibility.
    """
    if not old_messages:
        return ""

    text = "\n".join(f"{m['role']}: {m['content']}" for m in old_messages)
    try:
        from app.llm_client_offload import generate_response  # type: ignore
    except Exception as exc:  # noqa: BLE001
        logger.warning("summarize_old_messages: LLM unavailable (%s); returning empty summary.", exc)
        return ""

    try:
        summary = generate_response(
            [
                {"role": "system", "content": "Summarize the following dialog for long-term memory."},
                {"role": "user", "content": text},
            ],
            max_new_tokens=200,
        )
        summary = summary.strip() if isinstance(summary, str) else str(summary).strip()
        if len(summary) > MAX_SUMMARY_CHARS:
            summary = summary[-MAX_SUMMARY_CHARS:]
        return summary
    except Exception as exc:  # noqa: BLE001
        logger.warning("summarize_old_messages failed: %s", exc)
        return ""


def update_memory(
    conv_id: str,
    user_msg: str,
    assistant_msg: str,
    *,
    sources: Optional[List[Dict[str, Any]]] = None,
    web_query: str = "",
    mode: str = "",
    active_project_id: Optional[str] = None,
) -> None:
    """
    Add messages to the conversation, trim history, and maintain summaries.
    """
    global conversations

    user_message = _normalize_message("user", user_msg)
    assistant_message = _normalize_message("assistant", assistant_msg)

    with _lock:
        conv = conversations.get(conv_id)
        if conv is None:
            ts = _now_ms()
            conv = {
                "summary": "",
                "messages": [],
                "state": default_session_state(),
                "archived": False,
                "created_at_ms": ts,
                "updated_at_ms": ts,
            }
            conversations[conv_id] = conv

        conv["messages"].append(user_message)
        conv["messages"].append(assistant_message)

        msgs = conv["messages"]
        max_msgs = MAX_HISTORY_TURNS * 2  # user+assistant pairs → 2 messages per turn
        if len(msgs) > max_msgs:
            older = msgs[:-max_msgs]
            keep = msgs[-max_msgs:]

            older_text = " ".join(f"{m['role']}: {m['content']}" for m in older)
            merged_summary = f"{conv.get('summary', '')} {older_text}".strip()
            if len(merged_summary) > MAX_SUMMARY_CHARS:
                merged_summary = merged_summary[-MAX_SUMMARY_CHARS:]

            conv["summary"] = merged_summary
            conv["messages"] = keep

        conv["state"] = update_session_state(
            conv.get("state") or {},
            user_msg,
            assistant_msg,
            web_query=web_query,
            sources=sources,
            mode=mode,
            active_project_id=active_project_id,
        )
        conv["updated_at_ms"] = _now_ms()
        conversations[conv_id] = conv
        if not save_conversations(conversations):
            logger.warning(
                "Failed to persist memory update for conv_id=%s (messages=%d).",
                conv_id,
                len(conv["messages"]),
            )
        logger.debug(
            "Updated memory for conv_id=%s (messages=%d, summary_len=%d, goal=%r)",
            conv_id,
            len(conv["messages"]),
            len(conv.get("summary", "")),
            (conv.get("state") or {}).get("goal"),
        )
