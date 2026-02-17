from __future__ import annotations

import json
import os
import threading
import time
from collections import defaultdict, deque
from pathlib import Path
from typing import Deque, Dict, List

_lock = threading.Lock()
_counters: Dict[str, int] = defaultdict(int)
_errors: Deque[dict] = deque(maxlen=50)
_persist_path = Path(os.getenv("HEALTH_STATE_FILE", "data/health_state.json"))


def record(event: str, detail: str | None = None) -> None:
    ts = int(time.time())
    with _lock:
        _counters[event] += 1
        _errors.appendleft({"event": event, "detail": detail, "ts": ts})
        try:
            _persist_path.parent.mkdir(parents=True, exist_ok=True)
            _persist_path.write_text(json.dumps({"counters": _counters, "errors": list(_errors)}))
        except Exception:
            pass


def snapshot() -> dict:
    with _lock:
        return {
            "counters": dict(_counters),
            "recent_errors": list(_errors),
        }

