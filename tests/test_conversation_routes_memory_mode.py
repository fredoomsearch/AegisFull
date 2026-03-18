from __future__ import annotations

import pytest


@pytest.mark.anyio
async def test_memory_mode_conversation_routes_stay_available():
    import httpx
    import main

    transport = httpx.ASGITransport(app=main.app)
    created_conv_id = None
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            created = await client.post("/chat/new")
            assert created.status_code == 200
            created_conv_id = str(created.json().get("conversation_id") or "")
            assert created_conv_id

            listing = await client.get("/chat/list")
            assert listing.status_code == 200
            ids = [str(item.get("id") or "") for item in (listing.json().get("items") or [])]
            assert created_conv_id in ids

            archived = await client.post(f"/chat/{created_conv_id}/archive")
            assert archived.status_code == 200
            assert archived.json().get("archived") is True

            archived_listing = await client.get("/chat/list", params={"include_archived": "true"})
            archived_rows = archived_listing.json().get("items") or []
            target = next((row for row in archived_rows if row.get("id") == created_conv_id), None)
            assert target is not None
            assert target.get("archived") is True

            unarchived = await client.post(f"/chat/{created_conv_id}/unarchive")
            assert unarchived.status_code == 200
            assert unarchived.json().get("archived") is False
    finally:
        if created_conv_id:
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
                await client.delete(f"/chat/{created_conv_id}")
