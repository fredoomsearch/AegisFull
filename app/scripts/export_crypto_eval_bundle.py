from __future__ import annotations

"""
Export a trained/demo crypto evaluation bundle from local runtime stats.

What it does:
- Generates JSON, CSV, and Markdown evaluation artifacts in one output folder.

Why it exists:
- Provide a repeatable portfolio/demo evidence pack without manual UI export steps.
"""

import argparse
import json
from pathlib import Path

from app.api import crypto as crypto_api


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export crypto evaluation bundle.")
    parser.add_argument("--symbol", default="BTCUSDT", help="Symbol filter (default: BTCUSDT).")
    parser.add_argument(
        "--engine",
        default="trained",
        choices=["trained", "demo", "all"],
        help="Engine scope (default: trained).",
    )
    parser.add_argument("--limit", type=int, default=200, help="Outcome sample limit (default: 200).")
    parser.add_argument("--horizon-minutes", type=int, default=0, help="Optional horizon filter in minutes.")
    parser.add_argument("--regime", default="", help="Optional regime filter (example: bull_high_vol).")
    parser.add_argument("--fee-bps", type=float, default=10.0, help="Fee bps per side (default: 10).")
    parser.add_argument("--slippage-bps", type=float, default=5.0, help="Slippage bps per side (default: 5).")
    parser.add_argument(
        "--out-dir",
        default="artifacts/crypto_eval",
        help="Directory for the exported bundle (default: artifacts/crypto_eval).",
    )
    return parser.parse_args()


def _write_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)


def main() -> int:
    args = parse_args()
    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    json_resp = crypto_api.export_prediction_stats(
        limit=args.limit,
        symbol=args.symbol,
        engine=args.engine,
        horizon_minutes=(args.horizon_minutes or None),
        regime=(args.regime or None),
        format="json",
        fee_bps=args.fee_bps,
        slippage_bps=args.slippage_bps,
    )
    csv_resp = crypto_api.export_prediction_stats(
        limit=args.limit,
        symbol=args.symbol,
        engine=args.engine,
        horizon_minutes=(args.horizon_minutes or None),
        regime=(args.regime or None),
        format="csv",
        fee_bps=args.fee_bps,
        slippage_bps=args.slippage_bps,
    )
    md_resp = crypto_api.export_prediction_stats(
        limit=args.limit,
        symbol=args.symbol,
        engine=args.engine,
        horizon_minutes=(args.horizon_minutes or None),
        regime=(args.regime or None),
        format="md",
        fee_bps=args.fee_bps,
        slippage_bps=args.slippage_bps,
    )
    stats = crypto_api.prediction_stats(
        limit=args.limit,
        symbol=args.symbol,
        engine=args.engine,
        horizon_minutes=(args.horizon_minutes or None),
        regime=(args.regime or None),
        fee_bps=args.fee_bps,
        slippage_bps=args.slippage_bps,
    )

    _write_bytes(out_dir / "crypto_eval.json", json_resp.body)
    _write_bytes(out_dir / "crypto_eval.csv", csv_resp.body)
    _write_bytes(out_dir / "crypto_eval.md", md_resp.body)
    (out_dir / "summary.json").write_text(
        json.dumps(
            {
                "symbol": str(args.symbol or "BTCUSDT").upper(),
                "engine": args.engine,
                "limit": args.limit,
                "horizon_minutes": args.horizon_minutes or None,
                "regime": (args.regime or "").strip().lower() or None,
                "fee_bps": args.fee_bps,
                "slippage_bps": args.slippage_bps,
                "stats": stats,
                "files": {
                    "json": "crypto_eval.json",
                    "csv": "crypto_eval.csv",
                    "md": "crypto_eval.md",
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print(
        json.dumps(
            {
                "ok": True,
                "out_dir": str(out_dir),
                "engine": args.engine,
                "symbol": str(args.symbol or "BTCUSDT").upper(),
                "files": [
                    "crypto_eval.json",
                    "crypto_eval.csv",
                    "crypto_eval.md",
                    "summary.json",
                ],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
