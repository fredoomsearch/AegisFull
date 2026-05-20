from __future__ import annotations

import pytest

from app.api import chat as chat_api
from app.services import input_normalizer


@pytest.mark.parametrize(
    ("raw", "expected_substring"),
    [
        ("where's colombia?", "where is colombia"),
        ("wheres colombia", "where is colombia"),
        ("where s colombia", "where is colombia"),
        ("what's a login?", "what is a login"),
        ("dondes colombia", "donde es colombia"),
    ],
)
def test_normalize_for_routing_handles_contractions_and_typos(raw: str, expected_substring: str):
    normalized = input_normalizer.normalize_for_routing(raw)
    assert expected_substring in normalized


def test_split_mode_prefix_extracts_mode_and_payload():
    mode, payload = input_normalizer.split_mode_prefix("  web:   where is colombia? ")
    assert mode == "web"
    assert payload == "where is colombia?"


def test_split_mode_prefix_extracts_local_mode_and_payload():
    mode, payload = input_normalizer.split_mode_prefix("  local:   latest python release notes ")
    assert mode == "local"
    assert payload == "latest python release notes"


def test_normalize_user_input_strips_null_and_control_chars():
    normalized = input_normalizer.normalize_user_input("hello\x00world\x07\nnext")
    assert normalized == "hello world next"
    assert "\x00" not in normalized


def test_normalize_for_routing_strips_attachment_context():
    normalized = input_normalizer.normalize_for_routing(
        "what u can tell me about active project ?\n\n"
        "[Attachment context image: trust1.png]\n"
        "Local visual analysis (no external services):\n"
        "For programming questions: produce COMPLETE runnable code."
    )
    assert "attachment context" not in normalized
    assert "complete runnable code" not in normalized
    assert normalized.startswith("what u can tell me about active project")


@pytest.mark.parametrize(
    ("mode_value", "expected_source_plan"),
    [
        ("web", "web_only"),
        ("url", "web_only"),
        ("crypto", "local_only"),
        ("project", "local_only"),
        ("image", "local_only"),
    ],
)
def test_mode_contract_matrix_forces_expected_source_plan(mode_value: str, expected_source_plan: str):
    source_plan = chat_api._decide_source_plan(
        "latest python release notes",
        mode_value=mode_value,
        force_web=False,
        is_crypto_mode=False,
        has_active_project=False,
        session_state={},
    )
    assert source_plan == expected_source_plan


@pytest.mark.parametrize(
    "prompt",
    [
        "where is colombia?",
        "wheres colombia",
        "where's colombia",
        "donde esta colombia",
        "dónde está colombia",
    ],
)
def test_geography_prompt_variants_route_web_first_in_chat_mode(prompt: str):
    source_plan = chat_api._decide_source_plan(
        prompt,
        mode_value="chat",
        force_web=False,
        is_crypto_mode=False,
        has_active_project=False,
        session_state={},
    )
    assert source_plan == "web_only"


def test_local_only_request_phrase_forces_local_plan():
    source_plan = chat_api._decide_source_plan(
        "responde con local: latest python release notes",
        mode_value="chat",
        force_web=False,
        force_local=False,
        is_crypto_mode=False,
        has_active_project=False,
        session_state={},
    )
    assert source_plan == "local_only"


def test_validate_turn_inputs_requires_web_query():
    payload = chat_api._validate_turn_inputs(
        message="",
        mode_value="web",
        lang="en",
        active_project_id=None,
    )
    assert payload is not None
    assert payload["tool_kind"] == "validation_web_query"


def test_validate_turn_inputs_requires_valid_url_in_url_mode():
    payload = chat_api._validate_turn_inputs(
        message="please open docs",
        mode_value="url",
        lang="en",
        active_project_id=None,
    )
    assert payload is not None
    assert payload["tool_kind"] == "validation_url"


def test_validate_turn_inputs_requires_active_project_in_project_mode():
    payload = chat_api._validate_turn_inputs(
        message="explain this repo",
        mode_value="project",
        lang="en",
        active_project_id=None,
    )
    assert payload is not None
    assert payload["tool_kind"] == "validation_project"


def test_validate_turn_inputs_requires_crypto_symbol_for_prediction_like_queries():
    payload = chat_api._validate_turn_inputs(
        message="give me a prediction now",
        mode_value="crypto",
        lang="en",
        active_project_id=None,
    )
    assert payload is not None
    assert payload["tool_kind"] == "validation_crypto_symbol"


def test_web_evidence_exhausted_local_plus_web_without_project_has_deterministic_local_reason():
    payload = chat_api._maybe_web_evidence_exhausted_response(
        "latest python release notes",
        "en",
        {"next_tool": "web_search", "last_web_query": "latest python release notes"},
        source_plan="local+web",
        web_meta={"status": "unavailable", "source": "none", "attempted": True},
        raw_sources=[],
        has_active_project=False,
        web_query="latest python release notes",
    )
    assert payload is not None
    assert payload["tool_kind"] == "web_evidence_exhausted"
    assert "local-only context" in payload["response"].lower()


def test_web_evidence_exhausted_geography_returns_local_fact_when_known_place():
    payload = chat_api._maybe_web_evidence_exhausted_response(
        "where is colombia?",
        "en",
        {"next_tool": "web_search", "last_web_query": "where is colombia"},
        source_plan="web_only",
        web_meta={"status": "unavailable", "source": "none", "attempted": True},
        raw_sources=[],
        has_active_project=False,
        web_query="where is colombia",
    )
    assert payload is not None
    assert payload["tool_kind"] == "web_evidence_exhausted"
    response = payload["response"].lower()
    assert "colombia is in the northwest of south america" in response
    assert "web evidence was unavailable" in response


def test_output_quality_guard_blocks_off_topic_code_for_geography_prompt():
    guarded = chat_api._apply_output_quality_guard(
        user_message="where is colombia?",
        response_text=(
            "```python\n"
            "from flask import Flask\n"
            "app = Flask(__name__)\n"
            "@app.route('/login')\n"
            "def login():\n"
            "    return 'ok'\n"
            "```"
        ),
        lang="en",
        source_plan="web_only",
        web_meta={"status": "unavailable", "source": "none"},
    )
    assert "colombia is" in guarded.lower()
    assert "flask" not in guarded.lower()
    assert "off-topic" in guarded.lower()


def test_output_quality_guard_blocks_generic_greeting_for_release_notes_query():
    guarded = chat_api._apply_output_quality_guard(
        user_message="latest python 3.12 release notes",
        response_text="Hello, I'm AEGIS. What can I help you with today?",
        lang="en",
        source_plan="web_only",
        web_meta={"status": "live", "source": "live"},
    )

    assert "random answer" in guarded.lower()
    assert "hello, i'm aegis" not in guarded.lower()


def test_output_quality_guard_blocks_unrelated_short_world_question():
    guarded = chat_api._apply_output_quality_guard(
        user_message="latest python 3.12 release notes",
        response_text="What is the capital of Japan?",
        lang="en",
        source_plan="web_only",
        web_meta={"status": "live", "source": "live"},
    )

    assert "random answer" in guarded.lower()
    assert "capital of japan" not in guarded.lower()


def test_output_quality_guard_keeps_legitimate_capital_answer_when_on_topic():
    guarded = chat_api._apply_output_quality_guard(
        user_message="what is the capital of japan?",
        response_text="The capital of Japan is Tokyo.",
        lang="en",
        source_plan="local_only",
        web_meta={"status": "not-used", "source": "none"},
    )

    assert guarded == "The capital of Japan is Tokyo."


def test_output_quality_guard_blocks_project_summary_leak_for_release_notes_query():
    guarded = chat_api._apply_output_quality_guard(
        user_message="latest python 3.12 release notes",
        response_text=(
            "Project summary: detected layers api/ui. "
            "Entrypoints: app/main.py. Config files: Dockerfile, render.yml."
        ),
        lang="en",
        source_plan="web_only",
        web_meta={"status": "live", "source": "live"},
    )

    assert "local repo context" in guarded.lower()
    assert "app/main.py" not in guarded.lower()


def test_output_quality_guard_blocks_file_excerpt_leak_for_general_prompt():
    guarded = chat_api._apply_output_quality_guard(
        user_message="hello",
        response_text=(
            "File app/service.py:\n"
            "def login():\n"
            "    return 'ok'\n\n"
            "Project impact: /auth/login"
        ),
        lang="en",
        source_plan="local_only",
        web_meta={"status": "not-used", "source": "none"},
    )

    assert "local repo context" in guarded.lower()
    assert "file app/service.py" not in guarded.lower()


def test_output_quality_guard_keeps_project_summary_when_project_was_requested():
    response = (
        "Project summary: detected layers api/ui. "
        "Entrypoints: app/main.py. Config files: Dockerfile, render.yml."
    )
    guarded = chat_api._apply_output_quality_guard(
        user_message="what can you tell me about this repo?",
        response_text=response,
        lang="en",
        source_plan="local_only",
        web_meta={"status": "not-used", "source": "none"},
    )

    assert guarded == response
