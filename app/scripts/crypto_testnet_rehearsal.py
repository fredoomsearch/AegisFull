#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.scripts import e2e_flow_check as e2e


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a one-symbol crypto preview/testnet rehearsal and archive evidence.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--api-key", default="")
    parser.add_argument("--files-api-key", default="")
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--skip-auth", action="store_true")
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--side", default="BUY", choices=["BUY", "SELL"])
    parser.add_argument("--quantity", type=float, default=0.001)
    parser.add_argument("--horizon-minutes", type=int, default=15)
    parser.add_argument("--regime", default="")
    parser.add_argument("--execution-mode", default="testnet", choices=["simulated", "testnet"])
    parser.add_argument("--stop-loss-pct", type=float, default=1.0)
    parser.add_argument("--take-profit-pct", type=float, default=2.0)
    parser.add_argument("--max-exposure-quote", type=float, default=100.0)
    parser.add_argument("--max-order-size-pct", type=float, default=15.0)
    parser.add_argument(
        "--submit-if-allowed",
        action="store_true",
        help="Send /crypto/trade only when preview is allowed and effective mode matches the requested mode.",
    )
    parser.add_argument(
        "--out-dir",
        default="artifacts/release_evidence/crypto_testnet_rehearsal",
        help="Directory where the timestamped rehearsal evidence folder will be written.",
    )
    args = parser.parse_args()
    if args.quantity <= 0:
        parser.error("--quantity must be > 0")
    if args.horizon_minutes <= 0:
        parser.error("--horizon-minutes must be > 0")
    return args


def _normalize_symbol(value: str) -> str:
    return str(value or "BTCUSDT").strip().upper() or "BTCUSDT"


def _optional_positive(value: Optional[float]) -> Optional[float]:
    if value is None:
        return None
    number = float(value)
    return number if number > 0 else None


def _request_json(
    ctx: e2e.ClientCtx,
    method: str,
    path: str,
    *,
    json_body: Optional[dict[str, Any]] = None,
    params: Optional[dict[str, Any]] = None,
) -> tuple[int, Any]:
    response = ctx.request(method, path, json_body=json_body, params=params)
    return response.status_code, e2e._json_or_text(response)


def _build_order_payload(args: argparse.Namespace) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "symbol": _normalize_symbol(args.symbol),
        "side": str(args.side or "BUY").strip().upper() or "BUY",
        "quantity": float(args.quantity),
        "test": True,
        "execution_mode": str(args.execution_mode or "testnet").strip().lower() or "testnet",
    }
    optional_fields = {
        "stop_loss_pct": _optional_positive(args.stop_loss_pct),
        "take_profit_pct": _optional_positive(args.take_profit_pct),
        "max_exposure_quote": _optional_positive(args.max_exposure_quote),
        "max_order_size_pct": _optional_positive(args.max_order_size_pct),
    }
    for key, value in optional_fields.items():
        if value is not None:
            payload[key] = value
    return payload


def _build_params(args: argparse.Namespace) -> dict[str, Any]:
    params: dict[str, Any] = {"horizon_minutes": int(args.horizon_minutes)}
    regime = str(args.regime or "").strip().lower()
    if regime:
        params["regime"] = regime
    return params


def _extract_calibration_summary(risk_gate: Any) -> dict[str, Any]:
    gate = risk_gate if isinstance(risk_gate, dict) else {}
    controls = gate.get("calibration_controls") if isinstance(gate.get("calibration_controls"), dict) else {}
    operator_guidance = gate.get("operator_guidance") if isinstance(gate.get("operator_guidance"), dict) else {}
    return {
        "allowed": bool(gate.get("allowed")) if isinstance(gate.get("allowed"), bool) else None,
        "reason": str(gate.get("reason") or "").strip() or None,
        "operator_status": str(operator_guidance.get("status") or "").strip() or None,
        "operator_action": str(operator_guidance.get("action") or "").strip() or None,
        "max_order_notional": controls.get("max_order_notional"),
        "max_quantity": controls.get("max_quantity"),
        "recommended_reduction_pct": controls.get("recommended_reduction_pct"),
        "sizing_basis": str(controls.get("sizing_basis") or "").strip() or None,
        "blocked_checks": list(gate.get("blocked_checks") or []) if isinstance(gate.get("blocked_checks"), list) else [],
    }


def _markdown_for_payload(payload: dict[str, Any]) -> str:
    request = payload.get("request") if isinstance(payload.get("request"), dict) else {}
    preview = payload.get("preview") if isinstance(payload.get("preview"), dict) else {}
    preview_body = preview.get("body") if isinstance(preview.get("body"), dict) else {}
    preview_calibration = preview.get("calibration") if isinstance(preview.get("calibration"), dict) else {}
    trade = payload.get("trade") if isinstance(payload.get("trade"), dict) else {}
    trade_body = trade.get("body") if isinstance(trade.get("body"), dict) else {}
    decision = payload.get("decision") if isinstance(payload.get("decision"), dict) else {}
    recent_trades = payload.get("recent_trades") if isinstance(payload.get("recent_trades"), dict) else {}
    recent_items = recent_trades.get("body") if isinstance(recent_trades.get("body"), list) else []

    lines = [
        "# Crypto Testnet Rehearsal",
        "",
        "## Request",
        "",
        f"- Symbol: {request.get('symbol')}",
        f"- Side: {request.get('side')}",
        f"- Quantity: {request.get('quantity')}",
        f"- Horizon minutes: {request.get('horizon_minutes')}",
        f"- Regime: {request.get('regime') or 'none'}",
        f"- Requested execution mode: {request.get('execution_mode')}",
        f"- Submit if allowed: {bool(request.get('submit_if_allowed'))}",
        "",
        "## Preview",
        "",
        f"- HTTP status: {preview.get('status_code')}",
        f"- Effective execution mode: {preview_body.get('execution_mode') or 'unknown'}",
        f"- Risk gate allowed: {preview_calibration.get('allowed')}",
        f"- Risk gate reason: {preview_calibration.get('reason') or 'ok'}",
        f"- Operator guidance: {preview_calibration.get('operator_status') or 'none'}",
        f"- Operator action: {preview_calibration.get('operator_action') or 'none'}",
        f"- Max order notional: {preview_calibration.get('max_order_notional')}",
        f"- Max quantity: {preview_calibration.get('max_quantity')}",
        f"- Recommended reduction pct: {preview_calibration.get('recommended_reduction_pct')}",
        f"- Sizing basis: {preview_calibration.get('sizing_basis') or 'none'}",
        f"- Execution note: {preview_body.get('execution_note') or 'none'}",
        "",
        "## Submission",
        "",
        f"- Attempt requested: {bool(decision.get('submit_requested'))}",
        f"- Attempt performed: {bool(decision.get('submit_attempted'))}",
        f"- Skip reason: {decision.get('submit_skipped_reason') or 'none'}",
        f"- Trade HTTP status: {trade.get('status_code')}",
        f"- Trade status: {trade_body.get('status') or 'not-submitted'}",
        f"- Trade execution mode: {trade_body.get('execution_mode') or 'not-submitted'}",
        f"- Trade message: {trade_body.get('message') or 'none'}",
        "",
        "## Evidence",
        "",
        f"- State before status: {payload.get('state_before', {}).get('status_code') if isinstance(payload.get('state_before'), dict) else 'n/a'}",
        f"- State after status: {payload.get('state_after', {}).get('status_code') if isinstance(payload.get('state_after'), dict) else 'n/a'}",
        f"- Recent trade rows fetched: {len(recent_items)}",
        f"- Overall ok: {bool(payload.get('ok'))}",
    ]
    return "\n".join(lines) + "\n"


def _write_artifacts(run_dir: Path, payload: dict[str, Any]) -> dict[str, str]:
    run_dir.mkdir(parents=True, exist_ok=True)
    summary_json = run_dir / "summary.json"
    summary_md = run_dir / "summary.md"
    summary_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    summary_md.write_text(_markdown_for_payload(payload), encoding="utf-8")
    return {
        "summary_json": str(summary_json),
        "summary_md": str(summary_md),
    }


def main() -> int:
    args = parse_args()
    symbol = _normalize_symbol(args.symbol)
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    run_dir = (ROOT / str(args.out_dir)).resolve() / f"{stamp}_{symbol.lower()}_{str(args.execution_mode).lower()}"
    ctx = e2e.ClientCtx(
        base_url=str(args.base_url),
        timeout=float(args.timeout),
        api_key=str(args.api_key or ""),
        files_api_key=str(args.files_api_key or args.api_key or ""),
        transport=e2e.RequestsTransport(),
        cleanup_artifacts=False,
    )

    payload: dict[str, Any] = {
        "ok": False,
        "ts": stamp,
        "base_url": str(args.base_url),
        "request": {
            "symbol": symbol,
            "side": str(args.side or "BUY").upper(),
            "quantity": float(args.quantity),
            "horizon_minutes": int(args.horizon_minutes),
            "regime": str(args.regime or "").strip().lower() or None,
            "execution_mode": str(args.execution_mode or "testnet").strip().lower() or "testnet",
            "submit_if_allowed": bool(args.submit_if_allowed),
        },
        "decision": {
            "submit_requested": bool(args.submit_if_allowed),
            "submit_attempted": False,
            "submit_skipped_reason": None,
        },
    }

    health_ok = e2e.check_health(ctx)
    payload["health_ok"] = bool(health_ok)
    if not health_ok:
        payload["error"] = "healthz_failed"
        payload["artifacts"] = _write_artifacts(run_dir, payload)
        print(json.dumps(payload, ensure_ascii=False))
        return 2

    auth_ok = True
    if not args.skip_auth:
        auth_ok = e2e.check_auth_token(ctx)
    payload["auth_ok"] = bool(auth_ok)
    payload["cookie_auth"] = bool(ctx.cookie_auth)
    if not auth_ok:
        payload["error"] = "auth_failed"
        payload["artifacts"] = _write_artifacts(run_dir, payload)
        print(json.dumps(payload, ensure_ascii=False))
        return 2

    params = _build_params(args)
    order_payload = _build_order_payload(args)

    state_before_status, state_before_body = _request_json(
        ctx,
        "GET",
        "/crypto/state",
        params={
            "symbol": symbol,
            "horizon_minutes": int(args.horizon_minutes),
            "execution_mode": str(args.execution_mode or "testnet").strip().lower() or "testnet",
            **({"regime": params["regime"]} if params.get("regime") else {}),
        },
    )
    payload["state_before"] = {"status_code": state_before_status, "body": state_before_body}

    preview_status, preview_body = _request_json(
        ctx,
        "POST",
        "/crypto/trade/preview",
        json_body=order_payload,
        params=params,
    )
    preview_calibration = _extract_calibration_summary(
        preview_body.get("risk_gate") if isinstance(preview_body, dict) else None
    )
    payload["preview"] = {
        "status_code": preview_status,
        "body": preview_body,
        "calibration": preview_calibration,
    }
    if preview_status != 200 or not isinstance(preview_body, dict):
        payload["error"] = "preview_failed"
        payload["artifacts"] = _write_artifacts(run_dir, payload)
        print(json.dumps(payload, ensure_ascii=False))
        return 2

    requested_mode = str(args.execution_mode or "testnet").strip().lower() or "testnet"
    effective_preview_mode = str(preview_body.get("execution_mode") or "").strip().lower() or None
    preview_allowed = bool(preview_calibration.get("allowed")) if isinstance(preview_calibration.get("allowed"), bool) else False
    payload["decision"]["preview_allowed"] = preview_allowed
    payload["decision"]["effective_preview_mode"] = effective_preview_mode
    payload["decision"]["preview_reason"] = preview_calibration.get("reason")

    trade_status = None
    trade_body: Any = None
    if args.submit_if_allowed:
        if not preview_allowed:
            payload["decision"]["submit_skipped_reason"] = "preview_blocked"
        elif effective_preview_mode != requested_mode:
            payload["decision"]["submit_skipped_reason"] = f"effective_mode={effective_preview_mode or 'unknown'}"
        else:
            payload["decision"]["submit_attempted"] = True
            trade_status, trade_body = _request_json(
                ctx,
                "POST",
                "/crypto/trade",
                json_body=order_payload,
                params=params,
            )
    payload["trade"] = {"status_code": trade_status, "body": trade_body}

    recent_trades_status, recent_trades_body = _request_json(
        ctx,
        "GET",
        "/crypto/trades",
        params={"limit": 5, "symbol": symbol},
    )
    payload["recent_trades"] = {"status_code": recent_trades_status, "body": recent_trades_body}

    state_after_status, state_after_body = _request_json(
        ctx,
        "GET",
        "/crypto/state",
        params={
            "symbol": symbol,
            "horizon_minutes": int(args.horizon_minutes),
            "execution_mode": requested_mode,
            **({"regime": params["regime"]} if params.get("regime") else {}),
        },
    )
    payload["state_after"] = {"status_code": state_after_status, "body": state_after_body}

    payload["ok"] = True
    payload["artifacts"] = _write_artifacts(run_dir, payload)
    print(
        json.dumps(
            {
                "ok": True,
                "out_dir": str(run_dir),
                "symbol": symbol,
                "requested_mode": requested_mode,
                "effective_preview_mode": effective_preview_mode,
                "preview_allowed": preview_allowed,
                "submit_attempted": bool(payload["decision"].get("submit_attempted")),
                "submit_skipped_reason": payload["decision"].get("submit_skipped_reason"),
                "trade_status": (trade_body or {}).get("status") if isinstance(trade_body, dict) else None,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())