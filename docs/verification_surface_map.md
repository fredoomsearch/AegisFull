# AEGIS Verification Surface Map

Date: 2026-03-31

This file defines what is actually proved today by gates, tests, and runtime checks.

## Startup / Strict Chain

The main live chain is:

1. host prereq
2. pytest smoke
3. agent evals
4. host E2E
5. `/system/readyz`
6. UI contract
7. hard contract
8. no-loop stress
9. browser smoke

Primary orchestrator:
- `app/scripts/start_with_preflight.py`

Extended orchestrator:
- `app/scripts/verify_full.py`

## What Is Explicitly Proved

### Conversation / Comp

- chat routing and fast paths
- planner/session state behavior
- semantic act contract in session state
- source policy visibility
- project continuity
- turn persistence
- response safety

Main proof files:
- `tests/test_session_context.py`
- `tests/test_chat_fast_turn_paths.py`
- `tests/test_chat_output_safety.py`
- `tests/test_chat_project_binding.py`
- `tests/test_conversation_routes_memory_mode.py`
- `tests/test_conversation_turns.py`

### Memory

- DB-backed conversation state
- fallback memory behavior
- durable memory persistence

Main proof files:
- `tests/test_conversation_state_db.py`
- `tests/test_durable_memory.py`

### Grounding / Files / Retrieval

- `/files/*` surface
- upload / ingest
- project manifest and scoped lookup
- retrieval and symbol lookup

Main proof files:
- `tests/test_files_project_surface.py`
- `tests/test_files_workspace_ingest.py`
- `tests/test_ingest_repo_incremental.py`
- `tests/test_retrieval_project_scope.py`
- `tests/test_project_services.py`

### Web / Image / Crypto / Auth

- web search metadata and fallback
- image reference flow
- crypto prediction and policy surface
- auth/token behavior

Main proof files:
- `tests/test_web_search_meta.py`
- `tests/test_image_reference_generation.py`
- `tests/test_crypto_predict_engine.py`
- `tests/test_crypto_trade_safety.py`
- `tests/test_auth_scope_hardening.py`

### Governance / Quantitative Layer

- readiness/snapshot
- runtime metrics
- route confidence exposure
- model competition distribution
- hard contract thresholds

Main proof files:
- `tests/test_system_readyz_status.py`
- `tests/test_runtime_metrics_service.py`
- `tests/test_system_metrics_runtime.py`
- `tests/test_hard_contract_check.py`
- `tests/test_hard_contract_routing.py`

### UI / Browser

- static DOM contract
- browser smoke on core UI path
- output safety and project identity behavior

Main proof files:
- `tests/test_ui_js_syntax.py`
- `tests/test_ui_output_safety.py`
- `tests/test_ui_project_identity.py`
- `tests/test_browser_smoke_compiles.py`

## What Is Partial, Not Fully Closed

- `app/api/notifications.py`
  - health router is now exercised in host E2E
  - email delivery path itself is still not end-to-end verified

- `app/api/data.py`
  - DB health is now exercised in host E2E
  - still remains a diagnostic surface, not a major product flow

- extended browser proofs
  - project/files deep UI
  - URL mode
  - image mode
  - upload + ingest in browser
  - available, but not part of the slim strict default

- long-run model promotion
  - competition metrics exist
  - fully automatic promotion/demotion policy is still limited

## Verification Read

The current repo has:
- strong coverage on the primary conversational architecture
- strong coverage on memory + grounding + routing
- good coverage on governance and quantitative policy
- partial coverage on peripheral APIs and optional UI surfaces

Use this with:
- [Architecture Map](./architecture_map.md)
- [Core Hole Scan](./core_hole_scan.md)
- [Release Board](./release_board.md)
