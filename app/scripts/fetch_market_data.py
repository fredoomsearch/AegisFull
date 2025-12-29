from __future__ import annotations

"""
Fetch live crypto market data into a CSV for training.

Default source: CoinGecko markets API.

Usage (from project root):
  python -m app.scripts.fetch_market_data \
      --out data/crypto_data.csv \
      --per-page 200 \
      --pages 1

Notes:
- CoinGecko allows up to 250 per_page; be mindful of rate limits when paging.
- The output schema matches the columns expected by train_models.py
  (current_price, high_24h, low_24h, total_volume, market_cap, etc.).
"""




import argparse
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import List

import pandas as pd
import requests

log = logging.getLogger("fetch_market_data")
logging.basicConfig(level=logging.INFO, format="[fetch] %(message)s")


COINGECKO_URL = os.getenv(
    "COINGECKO_MARKETS_URL",
    "https://api.coingecko.com/api/v3/coins/markets",
)


def fetch_coingecko_markets(
    *,
    per_page: int = 200,
    pages: int = 1,
    vs_currency: str = "usd",
    timeout: float = 12.0,
) -> List[dict]:
    per_page = max(1, min(per_page, 250))
    pages = max(1, pages)

    all_items: List[dict] = []
    for page in range(1, pages + 1):
        params = {
            "vs_currency": vs_currency,
            "order": "market_cap_desc",
            "per_page": per_page,
            "page": page,
            "sparkline": "false",
        }
        log.info("Fetching CoinGecko page %s (per_page=%s)...", page, per_page)
        resp = requests.get(COINGECKO_URL, params=params, timeout=timeout)
        resp.raise_for_status()
        batch = resp.json()
        if not batch:
            break
        all_items.extend(batch)
    return all_items


def normalize_to_dataframe(items: List[dict]) -> pd.DataFrame:
    if not items:
        return pd.DataFrame()

    df = pd.DataFrame(items)
    keep = [
        "id",
        "symbol",
        "name",
        "current_price",
        "high_24h",
        "low_24h",
        "total_volume",
        "market_cap",
        "price_change_percentage_24h",
        "last_updated",
    ]
    df = df[[c for c in keep if c in df.columns]].copy()
    df["timestamp"] = datetime.now(timezone.utc).isoformat()
    return df


def save_csv(df: pd.DataFrame, out_path: Path) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_path, index=False)
    return out_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Fetch crypto market snapshot to CSV")
    parser.add_argument("--out", type=Path, default=Path("data/crypto_data.csv"))
    parser.add_argument("--per-page", type=int, default=200, help="Items per page (max 250)")
    parser.add_argument("--pages", type=int, default=1, help="Number of pages to fetch")
    parser.add_argument("--vs-currency", type=str, default="usd", help="Fiat currency (usd, eur, etc.)")
    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)

    items = fetch_coingecko_markets(
        per_page=args.per_page,
        pages=args.pages,
        vs_currency=args.vs_currency,
    )

    if not items:
        log.warning("No market data fetched; CSV not written.")
        return

    df = normalize_to_dataframe(items)
    path = save_csv(df, args.out)
    log.info("Wrote %d rows to %s", len(df), path)


if __name__ == "__main__":
    main()
