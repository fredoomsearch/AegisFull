from __future__ import annotations

import json
import os
import threading
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

LOG_DIR = Path(os.getenv("CRYPTO_PRED_LOG_DIR", "logs"))
TRADE_FILE = LOG_DIR / "trades.jsonl"
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


def log_trade(entry: Dict[str, Any]) -> str:
    """
    Append a trade to jsonl log.
    Expected keys: symbol, side (BUY/SELL), quantity, price, test (bool).
    """
    _ensure_log_dir()
    entry = dict(entry)
    entry.setdefault("id", f"trade_{int(time.time() * 1e6)}")
    entry.setdefault("ts", int(time.time()))
    with _lock:
        with TRADE_FILE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return str(entry["id"])


def list_trades(limit: int = 50, symbol: Optional[str] = None) -> List[Dict[str, Any]]:
    _ensure_log_dir()
    if not TRADE_FILE.exists():
        return []
    out: List[Dict[str, Any]] = []
    sym = symbol.upper() if symbol else None
    for line in _iter_recent_lines(TRADE_FILE):
        try:
            item = json.loads(line)
        except Exception:
            continue
        if sym and (item.get("symbol") or "").upper() != sym:
            continue
        out.append(item)
        if len(out) >= limit:
            break
    return out


def _compute_pnl_for_symbol(trades: List[Dict[str, Any]], current_price: float) -> Dict[str, Any]:
    """
    Simple mark-to-market:
      position = sum(signed qty)  (BUY=+qty, SELL=-qty)
      cost = sum(qty_signed * price)
      unrealized = current_price * position - cost
    """
    if not trades:
        return {"position": 0.0, "avg_price": None, "unrealized": 0.0, "count": 0}

    qty_signed = 0.0
    cost = 0.0
    for t in trades:
        qty = float(t.get("quantity") or 0.0)
        price = float(t.get("price") or 0.0)
        side = (t.get("side") or "").upper()
        sign = 1.0 if side == "BUY" else -1.0
        qty_signed += sign * qty
        cost += sign * qty * price

    avg_price = (cost / qty_signed) if qty_signed else None
    unrealized = current_price * qty_signed - cost
    return {"position": qty_signed, "avg_price": avg_price, "unrealized": unrealized, "count": len(trades)}


def compute_pnl(trades: List[Dict[str, Any]], price_lookup: Callable[[str], Optional[float]]) -> Dict[str, Any]:
    """
    Compute P&L by symbol (mark-to-market) and totals.
    price_lookup(symbol: str) -> float | None
    """
    by_symbol = defaultdict(list)
    for t in trades:
        sym = (t.get("symbol") or "").upper()
        if sym:
            by_symbol[sym].append(t)

    results: Dict[str, Any] = {}
    total_unrealized = 0.0
    for sym, ts in by_symbol.items():
        cp = price_lookup(sym)
        if cp is None:
            cp = float(ts[-1].get("price") or 0.0)
        pnl_info = _compute_pnl_for_symbol(ts, float(cp))
        pnl_info["current_price"] = float(cp)
        results[sym] = pnl_info
        total_unrealized += float(pnl_info.get("unrealized") or 0.0)

    return {"per_symbol": results, "total_unrealized": total_unrealized}
