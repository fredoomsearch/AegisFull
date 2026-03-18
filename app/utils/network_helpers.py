from __future__ import annotations

import socket
from typing import Tuple
from urllib.parse import urlparse


def probe_tcp_host_port(host: str, port: int, timeout: float = 2.5) -> Tuple[bool, str]:
    clean_host = str(host or "").strip()
    if not clean_host:
        return False, "invalid-host"
    try:
        with socket.create_connection((clean_host, int(port)), timeout=max(0.5, float(timeout))):
            return True, f"tcp://{clean_host}:{int(port)} ok"
    except Exception as exc:  # noqa: BLE001
        return False, f"tcp://{clean_host}:{int(port)} failed ({exc})"


def probe_tcp_url(url: str, timeout: float = 2.0) -> Tuple[bool, str]:
    parsed = urlparse(str(url or "").strip())
    host = str(parsed.hostname or "").strip()
    if not host:
        return False, "invalid-url"
    port = int(parsed.port or (443 if parsed.scheme == "https" else 80))
    return probe_tcp_host_port(host, port, timeout=max(0.5, float(timeout)))
