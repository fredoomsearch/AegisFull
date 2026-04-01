from __future__ import annotations

import asyncio
import json
import os

from app.api import system as system_api


def test_readyz_reports_fallback_only_when_core_ready(monkeypatch):
    monkeypatch.setenv("AEGIS_RUNTIME_PROFILE", "standard")
    monkeypatch.setattr(
        system_api,
        "collect_runtime_capabilities",
        lambda **_kwargs: {
            "embeddings": {"status": "loaded"},
            "retrieval": {"status": "loaded"},
            "llm": {"status": "ready", "available": True, "model_exists": False, "loaded": False, "provider": "groq", "effective_provider": "groq", "remote_ready": True, "model": "llama-3.1-70b-versatile"},
            "web_search": {"status": "ready", "provider_count": 2},
            "image": {"status": "fallback-only", "images_dir_exists": True, "fallback_only": True, "backend_reachable": False},
            "clamav": {"status": "missing"},
            "project_tools": {"status": "ready", "available": True},
        },
    )
    monkeypatch.setattr(system_api, "validation_runtime_snapshot", lambda: {"last_updated_ms": 123, "flows": {"startup_gate": {"status": "passed"}}})

    data = asyncio.run(system_api.readyz())
    assert data["ready"] is True
    assert data["status"] == "degraded"
    assert data["process"]["pid"] == os.getpid()
    assert data["process"]["hostname"]
    assert data["process"]["uptime_s"] >= 0
    assert "image:fallback-only" in data["degraded_reasons"]
    assert "clamav:missing" in data["degraded_reasons"]
    assert data["checks"]["project_tools"] is True
    assert "host-prereq" in data["validation"]["startup_gate"]
    assert "browser-smoke" in data["validation"]["startup_gate"]
    assert "no-loop-stress" in data["validation"]["startup_gate"]
    assert "host-prereq" in data["validation"]["verify_full"]
    assert "ui-contract" in data["validation"]["verify_full"]
    assert "no-loop-stress" in data["validation"]["verify_full"]
    assert data["validation"]["browser_smoke_default"] is True
    assert data["validation"]["browser_smoke_strict_default"] is False
    assert "agent-evals" in data["validation"]["verify_full"]
    assert data["validation"]["last_runs"]["startup_gate"]["status"] == "passed"


def test_snapshot_exposes_validation_tiers(monkeypatch):
    monkeypatch.setenv("AEGIS_RUNTIME_PROFILE", "standard")
    monkeypatch.setattr(
        system_api,
        "collect_runtime_capabilities",
        lambda **_kwargs: {
            "embeddings": {"status": "loaded"},
            "retrieval": {"status": "loaded"},
            "llm": {"status": "ready", "available": True, "model_exists": False, "loaded": False, "provider": "groq", "effective_provider": "groq", "remote_ready": True, "model": "llama-3.1-70b-versatile"},
            "web_search": {"status": "ready", "provider_count": 2},
            "image": {"status": "ready", "images_dir_exists": True, "fallback_only": False, "backend_reachable": True},
            "clamav": {"status": "ready"},
            "project_tools": {"status": "ready", "available": True},
        },
    )
    monkeypatch.setattr(system_api.job_manager, "list_jobs", lambda limit=5: [])
    monkeypatch.setattr(system_api.crypto_prediction_log, "pair_predictions_with_outcomes", lambda limit=10: [])
    monkeypatch.setattr(system_api.crypto_prediction_log, "recent_stats", lambda limit=200: {})
    monkeypatch.setattr(system_api, "_pnl_snapshot", lambda: {})
    monkeypatch.setattr(system_api.health_state, "snapshot", lambda: {})
    monkeypatch.setattr(
        system_api,
        "validation_runtime_snapshot",
        lambda: {
            "last_updated_ms": 456,
            "flows": {
                "startup_gate": {"status": "passed"},
                "verify_full": {"status": "running"},
            },
        },
    )

    data = asyncio.run(system_api.system_snapshot())
    assert isinstance(data.get("resources"), dict)
    assert isinstance(data.get("agent_profile"), dict)
    assert isinstance(data.get("durable_memory"), dict)
    assert "subject_count" in data["durable_memory"]
    assert data["resources"]["llm_config"]["provider"] == "groq"
    assert data["resources"]["llm_config"]["effective_provider"] == "groq"
    assert data["resources"]["llm_config"]["remote_ready"] is True
    assert data["resources"]["llm_config"]["model"] == "llama-3.1-70b-versatile"
    assert data["resources"]["llm_config"]["contract"]["contract_version"]
    assert data["resources"]["llm_config"]["contract"]["prompt_version"]
    assert data["resources"]["llm_config"]["contract"]["policy_version"]
    assert "act" in data["resources"]["llm_config"]["contract"]["semantic_fields"]
    assert data["resources"]["comp"]["controller"] == "comp"
    assert data["resources"]["comp"]["route_mode"] == "local"
    assert data["resources"]["comp"]["quantitative"]["gate"] == "escalate"
    assert data["resources"]["comp"]["quantitative"]["confidence_bucket"] == "low"
    assert data["process"]["pid"] == os.getpid()
    assert data["process"]["hostname"]
    assert "pytest-smoke" in data["validation"]["startup_gate"]
    assert "host-prereq" in data["validation"]["startup_gate"]
    assert "host-prereq" in data["validation"]["verify_full"]
    assert "pytest-full" in data["validation"]["verify_full"]
    assert "agent-evals" in data["validation"]["verify_full"]
    assert "ui-contract" in data["validation"]["verify_full"]
    assert "no-loop-stress" in data["validation"]["verify_full"]
    assert data["validation"]["scripts"]["start_with_preflight"] is True
    assert data["validation"]["scripts"]["verify_full"] is True
    assert data["validation"]["scripts"]["agent_eval_check"] is True
    assert data["validation"]["scripts"]["no_loop_stress_check"] is True
    assert data["validation"]["last_runs"]["verify_full"]["status"] == "running"
    assert data["validation"]["last_updated_ms"] == 456


def test_validation_snapshot_reflects_strict_runtime_profile(monkeypatch):
    monkeypatch.setenv("AEGIS_RUNTIME_PROFILE", "strict")
    monkeypatch.setenv("AEGIS_PRODUCT_TRACK", "full")
    monkeypatch.setenv("AEGIS_START_CONTRACT_MODE", "strict")
    data = system_api._validation_snapshot()
    assert data["runtime_profile_default"] == "strict"
    assert data["browser_smoke_strict_default"] is True
    assert data["contract_mode_default"] == "strict"


class _FakeGroqResponse:
    def __init__(self, payload: dict[str, object], status_code: int = 200):
        self._payload = payload
        self.status_code = status_code
        self.text = json.dumps(payload)

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise __import__("requests").HTTPError(self.text, response=self)


def test_llm_status_reports_groq_provider(monkeypatch):
    from app import llm_client_offload as llm_offload

    monkeypatch.setenv("AEGIS_LLM_PROVIDER", "groq")
    monkeypatch.setenv("AEGIS_GROQ_API_KEY", "groq-test-key")
    monkeypatch.setenv("AEGIS_GROQ_MODEL", "llama-3.1-70b-versatile")
    monkeypatch.setenv("AEGIS_GROQ_BASE_URL", "https://api.groq.com/openai/v1")
    monkeypatch.setattr(llm_offload, "_llama", None)
    monkeypatch.setattr(llm_offload, "_get_llama_class", lambda: None)
    monkeypatch.setattr(llm_offload, "MODEL_PATH", "/tmp/nonexistent-local-model.gguf", raising=False)

    status = llm_offload.llm_status()
    assert status["provider"] == "groq"
    assert status["effective_provider"] == "groq"
    assert status["remote_ready"] is True
    assert status["available"] is True
    assert status["status"] == "ready"
    assert status["model"] == "llama-3.1-70b-versatile"


def test_generate_response_uses_groq_when_configured(monkeypatch):
    from app import llm_client_offload as llm_offload

    monkeypatch.setenv("AEGIS_LLM_PROVIDER", "groq")
    monkeypatch.setenv("AEGIS_GROQ_API_KEY", "groq-test-key")
    monkeypatch.setenv("AEGIS_GROQ_MODEL", "llama-3.1-70b-versatile")
    monkeypatch.setenv("AEGIS_GROQ_BASE_URL", "https://api.groq.com/openai/v1")
    monkeypatch.setattr(llm_offload, "_llama", None)
    monkeypatch.setattr(llm_offload, "_get_llama_class", lambda: None)

    def fake_post(url, json=None, headers=None, timeout=None):
        body = {
            "choices": [
                {"message": {"content": "groq answer"}}
            ]
        }
        assert headers and headers.get("User-Agent")
        return _FakeGroqResponse(body)

    monkeypatch.setattr(llm_offload.requests, "post", fake_post)

    answer = llm_offload.generate_response([{"role": "user", "content": "hello"}], max_new_tokens=32)
    assert answer == "groq answer"


def test_llm_provider_state_reports_options(monkeypatch):
    monkeypatch.setenv("AEGIS_LLM_PROVIDER", "groq")

    def fake_caps(**kwargs):
        return {
            "llm": {
                "ctx": 2048,
                "threads": 4,
                "gpu_layers": 0,
                "batch": 256,
                "max_new_tokens": 512,
                "model_path": "./models/local.gguf",
                "model": "llama-3.1-70b-versatile",
                "provider": "groq",
                "effective_provider": "groq",
                "remote_ready": True,
            }
        }

    monkeypatch.setattr(system_api, "collect_runtime_capabilities", fake_caps)
    payload = asyncio.run(system_api.llm_provider_state())
    assert payload["configured_provider"] == "groq"
    assert payload["effective_provider"] == "groq"
    assert any(opt["id"] == "cloud" for opt in payload["options"])


def test_set_llm_provider_accepts_cloud_alias(monkeypatch):
    monkeypatch.setenv("AEGIS_LLM_PROVIDER", "local")

    def fake_caps(**kwargs):
        provider = os.getenv("AEGIS_LLM_PROVIDER", "local")
        effective = provider if provider != "auto" else "local"
        return {
            "llm": {
                "ctx": 2048,
                "threads": 4,
                "gpu_layers": 0,
                "batch": 256,
                "max_new_tokens": 512,
                "model_path": "./models/local.gguf",
                "model": "llama-3.1-70b-versatile" if effective == "groq" else "./models/local.gguf",
                "provider": provider,
                "effective_provider": effective,
                "remote_ready": True,
            }
        }

    monkeypatch.setattr(system_api, "collect_runtime_capabilities", fake_caps)
    payload = asyncio.run(system_api.set_llm_provider(system_api.LLMProviderUpdateRequest(provider="cloud")))
    assert os.getenv("AEGIS_LLM_PROVIDER") == "groq"
    assert payload["updated"] is True
    assert payload["configured_provider"] == "groq"


def test_llm_status_fail_closed_when_groq_not_ready(monkeypatch):
    from app import llm_client_offload as llm_offload

    monkeypatch.setenv("AEGIS_LLM_PROVIDER", "groq")
    monkeypatch.delenv("AEGIS_GROQ_API_KEY", raising=False)
    monkeypatch.setenv("AEGIS_GROQ_MODEL", "llama-3.1-70b-versatile")
    monkeypatch.setattr(llm_offload, "_llama", None)
    monkeypatch.setattr(llm_offload, "_get_llama_class", lambda: object())
    monkeypatch.setattr(llm_offload, "MODEL_PATH", "/tmp/existing-local-model.gguf", raising=False)
    monkeypatch.setattr(llm_offload.os.path, "exists", lambda _path: True)

    status = llm_offload.llm_status()
    assert status["provider"] == "groq"
    assert status["effective_provider"] == "groq"
    assert status["remote_ready"] is False
    assert status["available"] is False
    assert status["fallback_available"] is False
    assert status["status"] == "error"
    assert status["model"] == "llama-3.1-70b-versatile"


def test_generate_response_fail_closed_when_groq_not_ready(monkeypatch):
    from app import llm_client_offload as llm_offload

    monkeypatch.setenv("AEGIS_LLM_PROVIDER", "groq")
    monkeypatch.delenv("AEGIS_GROQ_API_KEY", raising=False)
    monkeypatch.setenv("AEGIS_GROQ_MODEL", "llama-3.1-70b-versatile")

    local_called = {"value": False}

    def fake_local(*args, **kwargs):
        local_called["value"] = True
        return "local-used"

    monkeypatch.setattr(llm_offload, "_generate_local_response", fake_local)

    answer = llm_offload.generate_response([{"role": "user", "content": "hello"}], max_new_tokens=16)
    assert local_called["value"] is False
    assert "groq" in answer.lower()
