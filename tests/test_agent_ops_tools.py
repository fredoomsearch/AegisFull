import uuid

import pytest


@pytest.mark.anyio
async def test_agent_step_can_report_clamav_status_without_llm():
    import httpx
    import main

    conv_id = str(uuid.uuid4())
    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        r = await client.post(
            f"/chat/{conv_id}/agent_step",
            json={
                "message": "show clamav status",
                "use_web": False,
                "max_tool_calls": 2,
                "synthesize": False,
                "lang": "en",
            },
        )
        assert r.status_code == 200
        payload = r.json()
        assert payload.get("ok") is True
        text = (payload.get("response") or "").lower()
        assert "clamav" in text


@pytest.mark.anyio
async def test_agent_step_can_report_ingest_jobs_without_llm():
    import httpx
    import main

    conv_id = str(uuid.uuid4())
    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        r = await client.post(
            f"/chat/{conv_id}/agent_step",
            json={
                "message": "show last ingest log",
                "use_web": False,
                "max_tool_calls": 2,
                "synthesize": False,
                "lang": "en",
            },
        )
        assert r.status_code == 200
        payload = r.json()
        assert payload.get("ok") is True
        text = (payload.get("response") or "").lower()
        assert "jobs" in text

