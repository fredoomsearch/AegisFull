#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from typing import Iterable

import requests
from app.utils.runtime_helpers import print_json as _print


REQUIRED_IDS = [
    "msg",
    "sendBtn",
    "chat",
    "chatBtn",
    "imgBtn",
    "modeIndicator",
    "activeProjectBadge",
    # Compact image mode wiring (chat-integrated image flow)
    "attachBtn",
    "imageQuickBar",
    "imageModeGuide",
    "imgInput",
]

REQUIRED_ASSETS = [
    "/ui/app.js",
    "/ui/styles.css",
]

_CONTENT_TYPE_HINTS: dict[str, tuple[str, ...]] = {
    "/ui/app.js": ("javascript",),
    "/ui/styles.css": ("text/css", "css"),
}


def _missing_ids(html: str, required: Iterable[str]) -> list[str]:
    text = html or ""
    missing: list[str] = []
    for rid in required:
        # Keep it simple and fast (no heavy HTML parser in gate).
        if f'id="{rid}"' not in text and f"id='{rid}'" not in text:
            missing.append(rid)
    return missing


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="UI contract check (no browser required).")
    p.add_argument("--base-url", default="http://127.0.0.1:8000")
    p.add_argument("--timeout", type=int, default=8)
    return p.parse_args()


def main() -> int:
    args = parse_args()
    base = (args.base_url or "").rstrip("/") or "http://127.0.0.1:8000"

    try:
        r = requests.get(f"{base}/", timeout=max(3, int(args.timeout)))
    except Exception as exc:  # noqa: BLE001
        _print({"ok": False, "reason": f"ui_index_request_failed:{exc}"})
        return 1

    if r.status_code != 200:
        _print({"ok": False, "reason": f"ui_index_status:{r.status_code}"})
        return 1

    html = r.text or ""
    missing = _missing_ids(html, REQUIRED_IDS)
    if missing:
        _print({"ok": False, "reason": "ui_missing_dom_ids", "missing_ids": missing})
        return 1

    asset_status: dict[str, int] = {}
    asset_ctypes: dict[str, str] = {}
    for path in REQUIRED_ASSETS:
        try:
            rr = requests.get(f"{base}{path}", timeout=max(3, int(args.timeout)))
            asset_status[path] = int(rr.status_code)
            asset_ctypes[path] = str(rr.headers.get("content-type") or "")
        except Exception:  # noqa: BLE001
            asset_status[path] = 0
            asset_ctypes[path] = ""

    bad_assets = [p for p, s in asset_status.items() if s != 200]
    if bad_assets:
        _print(
            {
                "ok": False,
                "reason": "ui_assets_missing",
                "asset_status": asset_status,
                "asset_content_type": asset_ctypes,
            }
        )
        return 1

    # Help catch cases where browsers refuse to execute due to nosniff + wrong MIME type.
    bad_ct = []
    for path, hints in _CONTENT_TYPE_HINTS.items():
        ct = asset_ctypes.get(path, "").lower()
        if not ct:
            continue
        if not any(h in ct for h in hints):
            bad_ct.append({"path": path, "content_type": asset_ctypes.get(path, "")})
    if bad_ct:
        _print({"ok": False, "reason": "ui_assets_bad_content_type", "bad": bad_ct, "asset_content_type": asset_ctypes})
        return 1

    _print({"ok": True, "missing_ids": [], "asset_status": asset_status})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
