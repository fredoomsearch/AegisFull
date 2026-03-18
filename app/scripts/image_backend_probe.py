#!/usr/bin/env python3
from __future__ import annotations

"""
Image backend probe for strict/full release closure.

What it does:
- Probes configured image backend endpoint health and checkpoint visibility.
- Emits machine-readable JSON for evidence bundles.

Why it exists:
- Full strict closure depends on host image backend readiness.
- Gives deterministic fail reasons before long verify/soak runs.
"""

import argparse
import json
import subprocess
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional, Tuple

import requests
from app.services.image_backend_helpers import (
    extract_checkpoint_choices,
    normalize_checkpoint_values,
    normalize_prompt_url,
    split_prompt_url,
)
from app.utils.network_helpers import probe_tcp_url


def _normalize_prompt_url(raw: str) -> str:
    return normalize_prompt_url(raw)


def _split_urls(prompt_url: str) -> Tuple[str, str]:
    return split_prompt_url(prompt_url)


def _tcp_reachable(url: str, timeout: float = 2.0) -> Tuple[bool, str]:
    return probe_tcp_url(url, timeout=max(0.5, float(timeout)))


def _normalize_checkpoint_values(raw: Any) -> List[str]:
    return normalize_checkpoint_values(raw)


def _extract_checkpoint_choices(payload: Any) -> List[str]:
    return extract_checkpoint_choices(payload)


@dataclass(frozen=True)
class ProbeResult:
    ok: bool
    endpoint: str
    base_url: str
    tcp_ok: bool
    tcp_detail: str
    root_status: int
    object_info_status: int
    checkpoints: List[str]
    nvidia_probe_attempted: bool
    nvidia_probe_ok: bool
    nvidia_gpu_count: int
    nvidia_detail: str
    torch_probe_attempted: bool
    torch_probe_ok: bool
    torch_cuda_available: Optional[bool]
    torch_detail: str
    error: str


def _probe_torch_runtime(python_bin: str, timeout: float = 8.0) -> Tuple[bool, Optional[bool], str]:
    py = str(python_bin or "").strip()
    if not py:
        return False, None, "python-bin-missing"
    cmd = [
        py,
        "-c",
        (
            "import json, torch; "
            "print(json.dumps({'cuda_available': bool(torch.cuda.is_available()), "
            "'device_count': int(torch.cuda.device_count())}))"
        ),
    ]
    try:
        res = subprocess.run(
            cmd,
            check=False,
            capture_output=True,
            text=True,
            timeout=max(1.0, float(timeout)),
        )
    except Exception as exc:  # noqa: BLE001
        return False, None, str(exc)

    out = (res.stdout or "").strip()
    err = (res.stderr or "").strip()
    if res.returncode != 0:
        detail = f"exit={res.returncode}"
        if err:
            detail += f" {err[:180]}"
        return False, None, detail
    try:
        payload = json.loads(out) if out else {}
        cuda_available = bool(payload.get("cuda_available"))
        device_count = int(payload.get("device_count") or 0)
        return True, cuda_available, f"cuda_available={cuda_available} device_count={device_count}"
    except Exception as exc:  # noqa: BLE001
        detail = f"parse-error ({exc})"
        if out:
            detail += f" out={out[:180]}"
        return False, None, detail


def _probe_nvidia_smi(timeout: float = 5.0) -> Tuple[bool, int, str]:
    cmd = ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"]
    try:
        res = subprocess.run(
            cmd,
            check=False,
            capture_output=True,
            text=True,
            timeout=max(1.0, float(timeout)),
        )
    except Exception as exc:  # noqa: BLE001
        return False, 0, str(exc)

    out = (res.stdout or "").strip()
    err = (res.stderr or "").strip()
    if res.returncode != 0:
        detail = f"exit={res.returncode}"
        if err:
            detail += f" {err[:180]}"
        return False, 0, detail
    gpu_lines = [line.strip() for line in out.splitlines() if line.strip()]
    return bool(gpu_lines), len(gpu_lines), f"gpu_count={len(gpu_lines)}"


def probe_backend(
    *,
    endpoint: str,
    timeout: float = 4.0,
    require_checkpoint: bool = False,
    python_bin: str = "",
    require_torch_cuda: bool = False,
    require_nvidia_smi: bool = False,
) -> ProbeResult:
    prompt_url, base_url = _split_urls(endpoint)
    tcp_ok, tcp_detail = _tcp_reachable(prompt_url, timeout=min(timeout, 3.0))

    if not tcp_ok:
        return ProbeResult(
            ok=False,
            endpoint=prompt_url,
            base_url=base_url,
            tcp_ok=False,
            tcp_detail=tcp_detail,
            root_status=0,
            object_info_status=0,
            checkpoints=[],
            nvidia_probe_attempted=False,
            nvidia_probe_ok=False,
            nvidia_gpu_count=0,
            nvidia_detail="not-run",
            torch_probe_attempted=False,
            torch_probe_ok=False,
            torch_cuda_available=None,
            torch_detail="not-run",
            error=tcp_detail,
        )

    root_status = 0
    object_info_status = 0
    checkpoints: List[str] = []
    nvidia_probe_attempted = False
    nvidia_probe_ok = False
    nvidia_gpu_count = 0
    nvidia_detail = "not-run"
    torch_probe_attempted = False
    torch_probe_ok = False
    torch_cuda_available: Optional[bool] = None
    torch_detail = "not-run"
    err = ""
    try:
        root = requests.get(f"{base_url}/", timeout=max(1.0, float(timeout)))
        root_status = int(root.status_code)
    except Exception as exc:  # noqa: BLE001
        err = f"root probe failed ({exc})"

    try:
        info = requests.get(
            f"{base_url}/object_info/CheckpointLoaderSimple",
            timeout=max(1.0, float(timeout)),
        )
        object_info_status = int(info.status_code)
        if object_info_status >= 400:
            err = err or f"object_info status={object_info_status}"
        else:
            payload = info.json() if info.content else {}
            checkpoints = _extract_checkpoint_choices(payload)
    except Exception as exc:  # noqa: BLE001
        err = err or f"object_info probe failed ({exc})"

    ok = object_info_status == 200
    if require_checkpoint:
        ok = ok and bool(checkpoints)
        if ok is False and not err and object_info_status == 200:
            err = "no-checkpoints-found"

    if require_nvidia_smi:
        nvidia_probe_attempted = True
        nvidia_probe_ok, nvidia_gpu_count, nvidia_detail = _probe_nvidia_smi(timeout=min(timeout, 5.0))
        if not nvidia_probe_ok:
            ok = False
            if not err:
                err = f"nvidia-smi-required ({nvidia_detail})"

    selected_python = str(python_bin or "").strip()
    if selected_python:
        torch_probe_attempted = True
        torch_probe_ok, torch_cuda_available, torch_detail = _probe_torch_runtime(selected_python)
        if require_torch_cuda and not bool(torch_cuda_available):
            ok = False
            if not err:
                err = f"torch-cuda-required ({torch_detail})"
    elif require_torch_cuda:
        ok = False
        err = err or "torch-cuda-required (python-bin-missing)"

    return ProbeResult(
        ok=bool(ok),
        endpoint=prompt_url,
        base_url=base_url,
        tcp_ok=tcp_ok,
        tcp_detail=tcp_detail,
        root_status=root_status,
        object_info_status=object_info_status,
        checkpoints=checkpoints,
        nvidia_probe_attempted=nvidia_probe_attempted,
        nvidia_probe_ok=nvidia_probe_ok,
        nvidia_gpu_count=nvidia_gpu_count,
        nvidia_detail=nvidia_detail,
        torch_probe_attempted=torch_probe_attempted,
        torch_probe_ok=torch_probe_ok,
        torch_cuda_available=torch_cuda_available,
        torch_detail=torch_detail,
        error=err,
    )


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Probe image backend readiness for strict/full runs.")
    p.add_argument("--endpoint", default="", help="Image backend /prompt endpoint.")
    p.add_argument("--timeout", type=float, default=4.0, help="HTTP/TCP timeout seconds.")
    p.add_argument("--require-checkpoint", action="store_true", help="Fail if backend reports zero checkpoints.")
    p.add_argument(
        "--python-bin",
        default="",
        help="Optional Python binary for torch CUDA diagnostics (e.g., ComfyUI venv python).",
    )
    p.add_argument("--require-torch-cuda", action="store_true", help="Fail if torch CUDA is unavailable in --python-bin runtime.")
    p.add_argument("--require-nvidia-smi", action="store_true", help="Fail if `nvidia-smi` is unavailable or reports zero GPUs.")
    p.add_argument("--json", action="store_true", help="Print JSON payload.")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    result = probe_backend(
        endpoint=args.endpoint,
        timeout=max(1.0, float(args.timeout)),
        require_checkpoint=bool(args.require_checkpoint),
        python_bin=str(args.python_bin or "").strip(),
        require_torch_cuda=bool(args.require_torch_cuda),
        require_nvidia_smi=bool(args.require_nvidia_smi),
    )
    payload: Dict[str, Any] = asdict(result)
    payload["checkpoint_count"] = len(result.checkpoints)
    payload["checkpoint_preview"] = list(result.checkpoints[:5])
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"ok={result.ok} endpoint={result.endpoint}")
        print(f"tcp={result.tcp_ok} detail={result.tcp_detail}")
        print(
            "http: "
            f"root_status={result.root_status} "
            f"object_info_status={result.object_info_status} "
            f"checkpoint_count={len(result.checkpoints)}"
        )
        if result.nvidia_probe_attempted:
            print(
                "nvidia: "
                f"probe_ok={result.nvidia_probe_ok} "
                f"gpu_count={result.nvidia_gpu_count} "
                f"detail={result.nvidia_detail}"
            )
        if result.torch_probe_attempted:
            print(
                "torch: "
                f"probe_ok={result.torch_probe_ok} "
                f"cuda_available={result.torch_cuda_available} "
                f"detail={result.torch_detail}"
            )
        if result.error:
            print(f"error={result.error}")
    return 0 if result.ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
