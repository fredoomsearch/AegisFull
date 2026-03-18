# Function Duplication Audit

Date: 2026-03-11  
Scope: `app/**/*.py`

## Objective
Remove unsafe exact helper clones, keep behavior stable, and document canonical ownership (`used from -> where`).

## Canonical AST Command

Script:
- `app/scripts/ast_dup_audit.py`

Run:
- `venv/bin/python -m app.scripts.ast_dup_audit --root app`
- `venv/bin/python -m app.scripts.ast_dup_audit --root app --json`

## Current Result (After Consolidation)

- `TOTAL_TOP_LEVEL_FUNCTIONS: 801`
- `EXACT_CLONE_GROUPS: 0`
- `SAME_NAME_GROUPS: 26` (expected script entrypoints and intentionally different implementations)

## Canonical Helper Ownership (Used From -> Where)

### Runtime/env/text helpers
- Module: `app/utils/runtime_helpers.py`
- Functions:
  - `first_csv_token`
  - `runtime_profile_default`
  - `env_int`
  - `print_json`
  - `now_ms`
  - `now_ts`
  - `utcnow_naive`
  - `utcnow_db`
  - `compact`
  - `proxies_enabled`

Used from:
- Scripts: `start_with_preflight.py`, `verify_full.py`, `production_profile_check.py`, `browser_smoke.py`, `ui_contract_check.py`
- API: `api/deps.py`, `api/chat.py`
- DB: `db/models.py`, `db/crud_conversation.py`, `db/kb_news.py`
- Services: `conversation_events.py`, `conversation_turns.py`, `runtime_metrics.py`, `validation_state.py`, `project_store.py`, `antivirus_service.py`, `web_search.py`, `web_snippets.py`, `session_state.py`
- Models: `models/llm_utils.py`

### ML fallback helpers
- Module: `app/utils/ml_helpers.py`
- Functions:
  - `sentiment_score`
  - `hash_embed`

Used from:
- `api/crypto.py`
- `services/news_store.py`
- `services/embedding_service.py`
- `services/retrieval_service.py`

## Why Same-Name Groups Still Exist

These are not exact clones and should remain separate:
- `main` and `parse_args` across scripts (different CLI behavior).
- `_check_readyz` in `start_with_preflight` vs `verify_full` (different strict semantics).
- `_print_text` in `doctor` vs `ast_dup_audit` (different output contracts).
- `_http_get` in `web_search` vs `web_snippets` (different request flow and logging intent).
- `get_conversation_state` / `set_conversation_state*` in memory vs DB modules (different storage backends).

## Verification

- `venv/bin/python -m py_compile` on touched modules -> pass
- `venv/bin/python -m pytest -q tests/test_start_with_preflight_defaults.py tests/test_verify_full_profile.py tests/test_production_profile_check.py tests/test_system_readyz_status.py tests/test_api_smoke.py tests/test_chat_tool_first.py tests/test_hard_contract_check.py tests/test_no_loop_stress_check.py tests/test_web_search_meta.py` -> pass
- `venv/bin/python -m app.scripts.ast_dup_audit --root app` -> `TOTAL_TOP_LEVEL_FUNCTIONS: 801`, `EXACT_CLONE_GROUPS: 0`, `SAME_NAME_GROUPS: 26`
