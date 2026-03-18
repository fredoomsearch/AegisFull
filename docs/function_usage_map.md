# AEGIS Function Usage Map (Canonical)

This document maps runtime endpoints to the main function handlers and service calls.
Use it to understand "which def does what" in the current architecture.

Scope:
- API handlers in `app/api/*.py`
- Core service orchestrators in `app/services/*.py`
- Key UI event handlers in `ui/app.js`

Not in scope:
- Every private helper in every file
- Legacy `/tools/*` behavior (covered in `docs/legacy_experiments.md`)

## 1) Chat And Agent Flow

### `POST /chat` -> `app/api/chat.py::chat(...)`

Main calls in order:
- quick time answer: `maybe_answer_time_question(...)`
- upload summary fast-path: `_maybe_local_upload_summary_response(...)`
- routing decision: `_decide_source_plan(...)`
- response context: `_build_response_context(...)`
- local project evidence path: `_maybe_project_file_response(...)`
- web evidence path: `_build_web_context(...)`
- LLM synthesis: `generate_response(...)` (from `app/models/llm_client.py`)
- safety and anti-leak: `_sanitize_and_repair_llm_output(...)`, `_finalize_user_response(...)`
- continuity persistence:
  - `_record_turn_state(...)`
  - `update_session_state(...)` / `replan_session_state(...)` as needed

Storage/tracing calls:
- conversation events: `record_event(...)`
- turns trace: `start_turn(...)`, `append_turn_item(...)`, `finish_turn(...)`

### `POST /chat/{id}/agent_step` -> `app/api/chat.py::agent_step(...)`

Main calls:
- plan build: `_build_turn_plan(...)`
- local evidence from project:
  - `get_project(...)`
  - `load_project_manifest(...)`
  - `summarize_manifest(...)`
  - `summarize_architecture(...)`
  - `list_project_symbols(...)` (retrieval)
  - `scan_project_symbols(...)` (fallback)
- optional web evidence: `_build_web_context(...)`
- optional synthesis: `generate_response(...)` + safety sanitizers
- turn trace: `start_turn(...)`, `append_turn_item(...)`, `finish_turn(...)`

### `POST /chat/{id}/agent_run` -> `app/api/chat.py::agent_run(...)`

Main calls:
- same primitives as `agent_step`, but in a bounded loop:
  - `max_iterations`
  - `max_total_tool_calls`
  - retry policy (`max_tool_retries`, `tool_retry_backoff_ms`)
- replanning after each iteration:
  - `_replan_conversation_state(...)`
  - `replan_session_state(...)`
- emits loop telemetry in response context and turn items.

### `POST /chat/{id}/execute_tool` -> `app/api/chat.py::execute_tool(...)`

Main calls:
- allowlist and approval gate checks
- executes a specific tool action and records output
- can chain to continue (`continue_after=true`) through `agent_continue(...)`

### Conversation state endpoints

- `GET /chat/{id}/events` -> `list_conversation_events(...)`
- `GET /chat/{id}/turns` -> `list_conversation_turns(...)`
- `GET /chat/{id}/turns/{turn_id}` -> `get_conversation_turn(...)`
- `POST /chat/{id}/project` -> `bind_conversation_project(...)` -> `_set_conversation_state(...)`
- `GET /chat/{id}/state` -> `_load_conversation_state(...)`

## 2) Project And Files Flow

### `POST /files/upload-zip` -> `app/api/files.py::upload_zip(...)`

Main calls:
- path and filename safety helpers:
  - `ensure_under_upload_root(...)`
  - `_ensure_within_root(...)`
- AV scan and recording:
  - `_av_scan_path(...)`
  - `record_av_event(...)`
- upload summary memory:
  - `remember_last_upload(...)`
  - `inspect_upload_tree(...)`
  - `format_upload_summary(...)`
- project registration:
  - `register_project(...)`
  - `update_project(...)`

### `POST /files/ingest` -> `app/api/files.py::ingest_path(...)`

Main calls:
- project resolution and guardrails:
  - `_project_root_from_query(...)`
  - `_resolve_registered_project_root(...)`
- job orchestration:
  - `start_job(...)`, `start_stage(...)`, `finish_stage(...)`
- ingestion runtime:
  - internal `_run_ingest(...)` (calls ingest script and updates project metadata)

### Manifest/introspection endpoints

- `GET /files/projects/{id}` -> `project_detail(...)`
  - `load_project_manifest(...)`
  - `summarize_manifest(...)`
  - `summarize_architecture(...)`
- `GET /files/projects/{id}/entrypoints` -> `project_entrypoints(...)`
- `GET /files/projects/{id}/dependencies` -> `project_dependencies(...)`
- `GET /files/projects/{id}/configs` -> `project_configs(...)`
- `GET /files/projects/{id}/architecture` -> `project_architecture(...)`

### File/symbol evidence endpoints

- `GET /files/tree` -> `project_tree(...)` -> `_build_tree_node(...)`
- `GET /files/content` -> `project_content(...)` (path traversal protected)
- `GET /files/projects/{id}/files` -> `project_files(...)` -> `fuzzy_search_project_files(...)`
- `GET /files/projects/{id}/symbols` -> `project_symbols(...)`
  - `list_project_symbols(...)` (retrieval)
  - `scan_project_symbols(...)` fallback
- `GET /files/projects/{id}/excerpt` -> `project_excerpt(...)`

## 3) Runtime Truth And Health

### `GET /system/readyz` -> `app/api/system.py::readyz(...)`

Main calls:
- runtime capabilities: `collect_runtime_capabilities(...)`
- summary state: `summarize_runtime_capabilities(...)`
- metrics snapshot: `runtime_metrics.snapshot(...)`
- validation history: `validation_runtime_snapshot(...)`

### `GET /system/snapshot` -> `app/api/system.py::system_snapshot(...)`

Main calls:
- same capability pipeline as `readyz`
- jobs and runtime resources:
  - `job_manager.list_jobs(...)`
  - `_resources_snapshot(...)`
- prediction/pnl snapshots:
  - `crypto_prediction_log.pair_predictions_with_outcomes(...)`
  - `_pnl_snapshot(...)`

### `GET /system/capabilities` -> `app/api/system.py::capabilities(...)`

Main calls:
- `collect_runtime_capabilities(...)`
- `summarize_runtime_capabilities(...)`

### `GET /system/metrics` -> `app/api/system.py::runtime_metrics_snapshot(...)`

Main call:
- `runtime_metrics.snapshot(...)`

## 4) Core Service Functions (High Impact)

### Session continuity (`app/services/session_state.py`)

Main functions:
- `default_session_state()`
- `normalize_session_state(raw)`
- `update_session_state(...)`
- `replan_session_state(...)`
- focus lifecycle:
  - `_touch_focus(...)`
  - `_apply_focus_decay(...)`
  - `_should_clear_focus_on_topic_switch(...)`

### Turn tracing (`app/services/conversation_turns.py`)

Main functions:
- `start_turn(...)`
- `append_turn_item(...)`
- `finish_turn(...)`
- `list_turns(...)`
- `get_turn(...)`

### Project manifest/introspection

- `app/services/project_manifest.py`
  - `build_project_manifest(...)`
  - `save_project_manifest(...)`
  - `load_project_manifest(...)`
  - `summarize_manifest(...)`
  - `infer_file_focus(...)`
- `app/services/project_introspection.py`
  - `scan_project_symbols(...)`
  - `fuzzy_search_project_files(...)`
  - `build_architecture_profile(...)`
  - `summarize_architecture(...)`

### Retrieval and web

- `app/services/retrieval_service.py`
  - `add_documents(...)`
  - `query(...)`
  - `list_project_symbols(...)`
  - `remove_project_documents(...)`
- `app/services/web_search.py`
  - `web_search_structured_with_meta(...)`
  - provider path (`_search_with_brave_html`, `_search_with_ddgs`, etc.)

## 5) UI Handler Map (Vanilla JS)

UI stack is plain JS (`ui/app.js`), not Angular.

Key bindings:
- mode buttons:
  - `#chatBtn` -> `setMode(MODES.CHAT)`
  - `#webBtn` -> `setMode(MODES.WEB)`
  - `#urlBtn` -> `setMode(MODES.URL)`
  - `#cryptoBtn` -> `setMode(MODES.CRYPTO)`
  - `#imgBtn` -> `setMode(MODES.IMAGE)`
- chart actions:
  - `#chartRefresh` -> `loadChartData(...)`
  - `[data-chart-range]` -> `setChartRangePreset(...)`
  - `#chartResetZoom` -> `resetChartZoom(...)`
  - `#priceChart` wheel -> `handleChartWheel(...)`
  - `#priceChart` double-click -> `resetChartZoom(...)`
- runtime status:
  - `#snapshotBtn` -> `loadSnapshot(...)`
  - `#debugTraceToggle` -> `setDebugTraceEnabled(...)`

## 6) How To Use This Map

For bug hunting:
1. Start from endpoint handler function in `app/api/*`.
2. Follow calls listed here to the service layer.
3. Validate continuity state (`session_state`) and trace (`conversation_turns`).
4. Confirm runtime truth in `/system/readyz` and `/system/snapshot`.

For feature changes:
1. Update handler + service.
2. Add/adjust tests in `tests/`.
3. Update this map and `docs/dependencies_map.md` if call graph/dependencies changed.
