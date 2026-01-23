# app/services/crypto_prediction_log.py
from __future__ import annotations

import json
import os
import threading
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, DefaultDict, Dict, List, Optional

LOG_DIR = Path(os.getenv("CRYPTO_PRED_LOG_DIR", "logs"))
LOG_FILE = LOG_DIR / "predictions.jsonl"
OUTCOME_FILE = LOG_DIR / "prediction_outcomes.jsonl"
_lock = threading.Lock()


def _ensure_log_dir() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)


def _iter_recent_lines(path: Path):
    if not path.exists():
        return []
    chunk_size = 8192
    with path.open("rb") as f:
        f.seek(0, os.SEEK_END)
        pos = f.tell()
        buffer = b""
        while pos > 0:
            read_size = min(chunk_size, pos)
            pos -= read_size
            f.seek(pos)
            chunk = f.read(read_size)
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


def log_prediction(entry: Dict[str, Any]) -> str:
    _ensure_log_dir()
    entry = dict(entry)
    entry.setdefault("id", f"pred_{int(time.time()*1e6)}")
    entry.setdefault("ts", int(time.time()))
    with _lock:
        with LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry["id"]


def list_predictions(limit: int = 50, symbol: Optional[str] = None) -> List[Dict[str, Any]]:
    _ensure_log_dir()
    if not LOG_FILE.exists():
        return []
    out: List[Dict[str, Any]] = []
    sym = symbol.upper() if symbol else None
    for line in _iter_recent_lines(LOG_FILE):
        try:
            item = json.loads(line)
        except Exception:
            continue
        if sym and (item.get("symbol") or "").upper() != sym:
            continue
        out.append(item)
        if len(out) >= limit:
            break
    out.sort(key=lambda x: x.get("ts") or 0, reverse=True)
    return out


def get_prediction(pid: str) -> Optional[Dict[str, Any]]:
    for p in list_predictions(limit=500):
        if p.get("id") == pid:
            return p
    return None


def log_outcome(entry: Dict[str, Any]) -> str:
    _ensure_log_dir()
    entry = dict(entry)
    entry.setdefault("id", f"out_{int(time.time()*1e6)}")
    entry.setdefault("ts", int(time.time()))
    with _lock:
        with OUTCOME_FILE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry["id"]


def list_outcomes(limit: int = 50, symbol: Optional[str] = None) -> List[Dict[str, Any]]:
    _ensure_log_dir()
    if not OUTCOME_FILE.exists():
        return []
    out: List[Dict[str, Any]] = []
    sym = symbol.upper() if symbol else None
    for line in _iter_recent_lines(OUTCOME_FILE):
        try:
            item = json.loads(line)
        except Exception:
            continue
        if sym and (item.get("symbol") or "").upper() != sym:
            continue
        out.append(item)
        if len(out) >= limit:
            break
    out.sort(key=lambda x: x.get("ts") or 0, reverse=True)
    return out


def recent_stats(limit: int = 100) -> Dict[str, Any]:
    outs = list_outcomes(limit=limit)
    if not outs:
        return {"count": 0, "accuracy": None, "avg_delta_pct": None, "per_model": {}}

    hits = [o for o in outs if o.get("hit") is True]
    acc = len(hits) / len(outs) if outs else None
    deltas = [o.get("delta_pct") for o in outs if isinstance(o.get("delta_pct"), (int, float))]
    avg_delta = sum(deltas) / len(deltas) if deltas else None

    per_model: DefaultDict[str, Dict[str, Any]] = defaultdict(lambda: {"count": 0, "hits": 0})
    for o in outs:
        model = o.get("model") or "unknown"
        per_model[model]["count"] += 1
        if o.get("hit") is True:
            per_model[model]["hits"] += 1

    per_model_stats = {
        m: {"count": v["count"], "accuracy": (v["hits"] / v["count"] if v["count"] else None)}
        for m, v in per_model.items()
    }

    return {
        "count": len(outs),
        "accuracy": acc,
        "avg_delta_pct": avg_delta,
        "per_model": per_model_stats,
    }


def pair_predictions_with_outcomes(limit: int = 50, symbol: Optional[str] = None) -> List[Dict[str, Any]]:
    preds = list_predictions(limit=limit, symbol=symbol)
    outs = list_outcomes(limit=limit * 2, symbol=symbol)
    out_map = {o.get("log_id"): o for o in outs if o.get("log_id")}
    merged: List[Dict[str, Any]] = []
    for p in preds:
        out = out_map.get(p.get("id"))
        merged.append({**p, "outcome": out} if out else p)
    return merged


def clear_predictions_and_outcomes() -> None:
    _ensure_log_dir()
    with _lock:
        if LOG_FILE.exists():
            LOG_FILE.unlink()
        if OUTCOME_FILE.exists():
            OUTCOME_FILE.unlink()
