from __future__ import annotations

"""
Fetch Binance OHLCV candles into a training CSV for crypto models.

Why this exists:
- `train_models.py` expects a time-series dataset, not a one-shot market snapshot.
- This script produces a repeatable local CSV using public Binance klines.
"""

import argparse
import json
import logging
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd
import requests


logging.basicConfig(level=logging.INFO, format="[ohlcv-fetch] %(message)s")
log = logging.getLogger("fetch_ohlcv_training_data")

BINANCE_KLINES_URL = "https://api.binance.com/api/v3/klines"
MAX_BATCH = 1000


def _fetch_symbol_klines(
    *,
    symbol: str,
    interval: str,
    candles: int,
    timeout: float,
    pause_seconds: float,
) -> List[list[Any]]:
    remaining = max(1, candles)
    end_time: int | None = None
    collected: List[list[Any]] = []

    while remaining > 0:
        limit = min(MAX_BATCH, remaining)
        params: Dict[str, Any] = {
            "symbol": symbol.upper(),
            "interval": interval,
            "limit": limit,
        }
        if end_time is not None:
            params["endTime"] = end_time

        resp = requests.get(BINANCE_KLINES_URL, params=params, timeout=timeout)
        resp.raise_for_status()
        batch = resp.json()
        if not isinstance(batch, list) or not batch:
            break

        collected = batch + collected
        remaining -= len(batch)
        earliest_open_ms = int(batch[0][0])
        end_time = earliest_open_ms - 1
        if len(batch) < limit:
            break
        if remaining > 0 and pause_seconds > 0:
            time.sleep(pause_seconds)

    collected.sort(key=lambda row: int(row[0]))
    return collected[-candles:]


def _rows_from_klines(symbol: str, klines: List[list[Any]]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for item in klines:
        try:
            open_ms = int(item[0])
            rows.append(
                {
                    "timestamp": datetime.fromtimestamp(open_ms / 1000.0, tz=UTC).isoformat(),
                    "symbol": symbol.upper(),
                    "binance_symbol": symbol.upper(),
                    "open": float(item[1]),
                    "high": float(item[2]),
                    "low": float(item[3]),
                    "close": float(item[4]),
                    "current_price": float(item[4]),
                    "high_24h": float(item[2]),
                    "low_24h": float(item[3]),
                    "total_volume": float(item[5]),
                    "quote_volume": float(item[7]),
                    "trade_count": int(item[8]),
                    "market_cap": None,
                }
            )
        except Exception:
            continue
    return rows


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Fetch Binance OHLCV candles into a training CSV.")
    parser.add_argument(
        "--symbols",
        default="BTCUSDT",
        help="Comma-separated Binance symbols (default: BTCUSDT).",
    )
    parser.add_argument(
        "--interval",
        default="5m",
        help="Binance interval, for example 1m, 5m, 15m, 1h (default: 5m).",
    )
    parser.add_argument(
        "--candles",
        type=int,
        default=1500,
        help="Candles per symbol to fetch (default: 1500).",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("data/crypto_ohlcv_training.csv"),
        help="Output CSV path.",
    )
    parser.add_argument("--timeout", type=float, default=10.0, help="Per-request timeout seconds.")
    parser.add_argument("--pause-seconds", type=float, default=0.15, help="Pause between paged requests.")
    return parser


def main(argv: List[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    symbols = [part.strip().upper() for part in str(args.symbols or "").split(",") if part.strip()]
    if not symbols:
        raise SystemExit("No symbols provided")

    all_rows: List[Dict[str, Any]] = []
    for symbol in symbols:
        log.info("Fetching %s candles for %s (%s)...", args.candles, symbol, args.interval)
        klines = _fetch_symbol_klines(
            symbol=symbol,
            interval=args.interval,
            candles=max(1, args.candles),
            timeout=max(1.0, float(args.timeout)),
            pause_seconds=max(0.0, float(args.pause_seconds)),
        )
        rows = _rows_from_klines(symbol, klines)
        log.info("Collected %s rows for %s", len(rows), symbol)
        all_rows.extend(rows)

    df = pd.DataFrame(all_rows)
    if df.empty:
        raise SystemExit("No OHLCV rows fetched")
    df = df.sort_values(["timestamp", "binance_symbol"]).reset_index(drop=True)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(args.out, index=False)

    summary = {
        "ok": True,
        "rows": int(len(df)),
        "symbols": symbols,
        "interval": args.interval,
        "candles_per_symbol": int(args.candles),
        "out": str(args.out),
    }
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
