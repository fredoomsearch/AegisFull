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
