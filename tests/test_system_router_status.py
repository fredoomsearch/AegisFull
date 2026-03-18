from __future__ import annotations


def test_api_surfaces_snapshot_reflects_router_mount_state():
    from app.api import system as system_api

    payload = system_api._api_surfaces_snapshot()

    assert "router_status" in payload
    router_status = payload["router_status"]
    assert isinstance(router_status, dict)
    assert "chat" in router_status
    assert payload["chat_api"] is bool((router_status.get("chat") or {}).get("mounted"))
