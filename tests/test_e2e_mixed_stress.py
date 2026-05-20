from __future__ import annotations

from dataclasses import dataclass

from app.scripts import e2e_mixed_stress as stress


@dataclass
class _Ctx:
    conversation_id: str = "conv-1"
    uploaded_project_id: str = "proj-1"


def test_build_stress_plan_uses_local_chat_prompts_when_cloud_is_not_ready():
    plan = stress.build_stress_plan(_Ctx(), cloud_ready=False)
    names = [spec.name for spec in plan]
    assert "chat_time" in names
    assert "websearch" in names
    assert "fetch_url" in names
    assert "image_generate" in names
    assert "ingest_jobs" in names
    assert "chat_cloud_reasoning" not in names
    assert len(plan) >= 40
    assert any(spec.files_scope for spec in plan if spec.name.startswith("files_"))


def test_build_stress_plan_uses_cloud_chat_prompt_when_cloud_is_ready():
    plan = stress.build_stress_plan(_Ctx(), cloud_ready=True)
    names = [spec.name for spec in plan]
    assert "chat_cloud_reasoning" in names
    assert "chat_time" not in names
    assert "websearch" in names
    assert "fetch_url" in names
    assert len(plan) >= 40
    assert any(spec.category == "crypto" for spec in plan)
