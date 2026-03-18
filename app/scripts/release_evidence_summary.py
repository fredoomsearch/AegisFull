#!/usr/bin/env python3
from __future__ import annotations

"""
Release evidence summary checker (Core/Full artifact bundles).

What it does:
- Validates required evidence artifacts and derives pass/fail per gate.
- Emits machine-readable status with actionable failing checks.

Why it exists:
- Avoid manual log interpretation when deciding GO/NO-GO.
- Keep final release decision deterministic from archived artifacts.
"""

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


@dataclass(frozen=True)
class GateCheck:
    name: str
    ok: bool
    detail: str


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _load_json(path: Path) -> Tuple[bool, Dict[str, Any], str]:
    try:
        payload = json.loads(_read_text(path))
    except Exception as exc:  # noqa: BLE001
        return False, {}, str(exc)
    if not isinstance(payload, dict):
        return False, {}, "json-root-not-object"
    return True, payload, "ok"


def _load_last_json_object(path: Path) -> Tuple[bool, Dict[str, Any], str]:
    text = _read_text(path)
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    for line in reversed(lines):
        if not (line.startswith("{") and line.endswith("}")):
            continue
        try:
            payload = json.loads(line)
        except Exception:
            continue
        if isinstance(payload, dict):
            return True, payload, "ok"
    return False, {}, "no-json-object-found"


def _check_doctor(path: Path) -> GateCheck:
    if not path.exists():
        return GateCheck("doctor_full", False, "missing")
    ok, payload, detail = _load_json(path)
    if not ok:
        return GateCheck("doctor_full", False, f"invalid-json ({detail})")
    if bool(payload.get("ok")):
        return GateCheck("doctor_full", True, "ok")
    failed = int(payload.get("failed") or 0)
    return GateCheck("doctor_full", False, f"failed_checks={failed}")


def _check_image_probe(path: Path) -> GateCheck:
    if not path.exists():
        return GateCheck("image_backend_probe", False, "missing")
    ok, payload, detail = _load_json(path)
    if not ok:
        return GateCheck("image_backend_probe", False, f"invalid-json ({detail})")
    if bool(payload.get("ok")):
        count = int(payload.get("checkpoint_count") or 0)
        return GateCheck("image_backend_probe", True, f"checkpoints={count}")
    err = str(payload.get("error") or "probe-failed").strip()
    return GateCheck("image_backend_probe", False, err[:180])


def _check_verify_log(path: Path) -> GateCheck:
    if not path.exists():
        return GateCheck("verify_full", False, "missing")
    text = _read_text(path)
    if "[ok] verify-full checks passed." in text:
        return GateCheck("verify_full", True, "ok")
    return GateCheck("verify_full", False, "missing-success-sentinel")


def _check_hard_contract(path: Path) -> GateCheck:
    if not path.exists():
        return GateCheck("hard_contract", False, "missing")
    ok, payload, detail = _load_last_json_object(path)
    if not ok:
        return GateCheck("hard_contract", False, f"invalid-json ({detail})")
    if bool(payload.get("ok")):
        return GateCheck("hard_contract", True, "ok")
    return GateCheck("hard_contract", False, "ok=false")


def _check_soak_json(path: Path) -> GateCheck:
    if not path.exists():
        return GateCheck("soak_gate", False, "missing")
    ok, payload, detail = _load_json(path)
    if not ok:
        return GateCheck("soak_gate", False, f"invalid-json ({detail})")
    if bool(payload.get("ok")):
        return GateCheck("soak_gate", True, "ok")
    return GateCheck("soak_gate", False, "ok=false")


def _check_readyz(path: Path) -> GateCheck:
    if not path.exists():
        return GateCheck("system_readyz", False, "missing")
    ok, payload, detail = _load_json(path)
    if not ok:
        return GateCheck("system_readyz", False, f"invalid-json ({detail})")
    ready = bool(payload.get("ready"))
    status = str(payload.get("status") or "").strip().lower()
    if ready and status == "ready":
        return GateCheck("system_readyz", True, "ready=true status=ready")
    return GateCheck("system_readyz", False, f"ready={ready} status={status or 'unknown'}")


def summarize_full_bundle(bundle_dir: Path) -> Dict[str, Any]:
    checks: List[GateCheck] = [
        _check_doctor(bundle_dir / "doctor_full.json"),
        _check_image_probe(bundle_dir / "image_backend_probe.json"),
        _check_verify_log(bundle_dir / "verify_full.log"),
        _check_hard_contract(bundle_dir / "hard_contract.log"),
        _check_soak_json(bundle_dir / "soak_gate.json"),
        _check_readyz(bundle_dir / "system_readyz.json"),
    ]
    failed = [c for c in checks if not c.ok]
    return {
        "ok": not failed,
        "bundle_dir": str(bundle_dir),
        "total_checks": len(checks),
        "passed_checks": len(checks) - len(failed),
        "failed_checks": len(failed),
        "checks": [asdict(c) for c in checks],
    }


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Summarize release evidence bundle gates.")
    p.add_argument("--bundle-dir", required=True, help="Path to evidence bundle directory.")
    p.add_argument("--json", action="store_true", help="Emit JSON only.")
    return p.parse_args()


def _print_text(payload: Dict[str, Any]) -> None:
    print(f"ok={payload.get('ok')} bundle={payload.get('bundle_dir')}")
    print(f"checks: {payload.get('passed_checks')}/{payload.get('total_checks')} passed")
    for chk in payload.get("checks", []):
        status = "ok" if chk.get("ok") else "fail"
        print(f"[{status}] {chk.get('name')}: {chk.get('detail')}")


def main() -> int:
    args = parse_args()
    bundle_dir = Path(args.bundle_dir).resolve()
    if not bundle_dir.exists() or not bundle_dir.is_dir():
        raise SystemExit(f"Invalid --bundle-dir: {bundle_dir}")
    payload = summarize_full_bundle(bundle_dir)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        _print_text(payload)
    return 0 if bool(payload.get("ok")) else 2


if __name__ == "__main__":
    raise SystemExit(main())
