# AEGIS File Inventory Map (Canonical)

This is the per-file inventory requested for architecture learning:
- what each file does,
- key functions/defs,
- main dependencies,
- and where it is used in runtime flows.

Use this together with:
- `docs/function_usage_map.md` (endpoint -> service call graph)
- `docs/dependencies_map.md` (library -> implementation map)
- `docs/modules_inventory.md` (full import-level inventory)

## API Layer (`app/api/*`)

| File | Purpose | Key functions / defs | Main dependencies | Used by |
|---|---|---|---|---|
| `app/api/chat.py` | Chat + agent orchestration surface. | `chat`, `agent_step`, `agent_run`, `agent_continue`, `execute_tool` | FastAPI, session state, conversation turns/events, retrieval/web services, LLM client | `/chat*` routes from UI and E2E scripts |
| `app/api/files.py` | Project ingest and project-scoped file tools. | `upload_zip`, `ingest_path`, `project_detail`, `project_symbols`, `project_excerpt` | FastAPI, project store/manifest/introspection, job manager, AV service | `/files/*` routes + project panel UI |
| `app/api/system.py` | Runtime truth endpoints and capability/snapshot summaries. | `readyz`, `system_snapshot`, `capabilities`, `runtime_metrics_snapshot` | capabilities service, validation state, runtime metrics | status badges, snapshot panel, gates |
| `app/api/crypto.py` | Crypto demo/prediction/trade endpoints. | `predict`, `ohlcv`, `news`, `trade`, `predictions` | crypto services, trade/prediction logs | chart + crypto panel UI |
| `app/api/image.py` | Image generation + checkpoint metadata + fallbacks. | `generate_image`, `generate_with_reference`, `recent_images`, `checkpoints_status` | requests, image/ocr utilities, filesystem | image mode UI + E2E |
| `app/api/auth.py` | JWT token issue/refresh and auth helper endpoints. | `issue_token`, `refresh_token` (names may vary by route) | jwt, auth deps, config | UI token refresh and protected endpoints |
| `app/api/deps.py` | Auth dependencies and scope guards. | `require_api_key`, `require_files_api_key`, `require_admin_api_key` | FastAPI `Depends`, config/auth utils | all protected API surfaces |

## Services Layer (`app/services/*`)

| File | Purpose | Key functions / defs | Main dependencies | Used by |
|---|---|---|---|---|
| `app/services/session_state.py` | Planner/session continuity memory model. | `default_session_state`, `normalize_session_state`, `update_session_state`, `replan_session_state` | stdlib + heuristics | chat/agent routing decisions |
| `app/services/conversation_turns.py` | Turn/item trace persistence. | `start_turn`, `append_turn_item`, `finish_turn`, `list_turns`, `get_turn` | JSON/DB persistence helpers | debug mode + `/chat/{id}/turns` |
| `app/services/conversation_events.py` | Event stream for conversation diagnostics. | `record_event`, `list_events` | persistence helpers | `/chat/{id}/events`, UI event panel |
| `app/services/retrieval_service.py` | Embedding/vector retrieval + project symbol search. | `query`, `add_documents`, `list_project_symbols`, `remove_project_documents` | sentence-transformers, faiss/numpy fallback | chat project evidence, `/files/*` |
| `app/services/web_search.py` | Multi-provider web retrieval with meta/cooldown/cache. | `web_search_structured_with_meta` + provider handlers | requests, bs4, provider rate/cooldown state | `chat.py`, `/websearch` flows |
| `app/services/capabilities_service.py` | Aggregates runtime capabilities and health levels. | `collect_runtime_capabilities`, `summarize_runtime_capabilities` | multiple service probes | `/system/readyz` and `/system/snapshot` |
| `app/services/project_store.py` | Registered project persistence + lookup. | `register_project`, `update_project`, `get_project`, `list_projects` | DB/file persistence | files API + chat project binding |
| `app/services/project_manifest.py` | Manifest build/load/summarization for projects. | `build_project_manifest`, `save_project_manifest`, `load_project_manifest`, `summarize_manifest` | filesystem parsing | files API, chat summaries |
| `app/services/project_introspection.py` | Entrypoints/deps/config/symbol/file search helpers. | `build_architecture_profile`, `summarize_architecture`, `scan_project_symbols`, `fuzzy_search_project_files` | filesystem + parsing helpers | files API + chat local evidence |
| `app/services/validation_state.py` | Tracks startup/verify flow step status. | `start_flow`, `mark_step`, `finish_flow`, `snapshot` (names may vary) | JSON persistence + timestamps | start/verify scripts + system endpoints |
| `app/services/runtime_metrics.py` | Aggregates runtime rates/counters (fallback/poll/auth). | `record_*`, `snapshot` | in-memory/file counters | hard-contract + soak gates + `/system/metrics` |
| `app/services/antivirus_service.py` | Upload AV scan orchestration and event recording. | scan/record status helpers | clamscan/clamdscan integration | files upload/ingest security checks |

## Script/Gate Layer (`app/scripts/*`)

| File | Purpose | Key functions / defs | Main dependencies | Used by |
|---|---|---|---|---|
| `app/scripts/start_with_preflight.py` | Startup gate orchestrator before server handoff. | preflight chain + host E2E + readyz + hard-contract + no-loop-stress + browser smoke | subprocess, pytest, requests | `start_aegis.sh` |
| `app/scripts/verify_full.py` | Extended strict verification pipeline. | verify flow with full pytest/E2E/contract/no-loop/browser checks | subprocess, requests | `verify_full.sh`, `go_strict.sh` |
| `app/scripts/hard_contract_check.py` | Release gate contract checker (routing + runtime rates). | `_run_adversarial`, metrics thresholds, strict fail logic | adversarial suite + `/system/metrics` | startup/verify strict checks |
| `app/scripts/adversarial_eval_check.py` | Deterministic multi-turn adversarial routing suite. | `run_adversarial_eval_cases`, CLI | chat planner functions + session state | CI and hard contract |
| `app/scripts/soak_gate.py` | Long-run traffic soak with threshold assertions. | timed loop, wrong-route/rate checks | requests | production-like reliability gate |
| `app/scripts/no_loop_stress_check.py` | Agent no-loop stress gate under bounded budgets. | repeated `/chat/{id}/agent_run` checks with stop-reason/budget assertions + optional auth-edge injections | requests | strict startup/verify hard blocker |
| `app/scripts/e2e_flow_check.py` | Host-level end-to-end functional check. | auth/chat/image/files/project flow checks | requests + runtime API | startup/verify flows |
| `app/scripts/browser_smoke.py` | Browser runtime smoke against UI contract behavior. | driver setup + UI assertions | selenium + chromedriver/browser | strict profile browser gate |

## Frontend Layer (`ui/*`)

| File | Purpose | Key functions / defs | Main dependencies | Used by |
|---|---|---|---|---|
| `ui/index.html` | DOM structure, toolbars, panels, mode controls. | element IDs used as UI contract | HTML + static asset refs | served at `/` |
| `ui/app.js` | Main UI runtime state machine and API integration. | `setMode`, `onSend`, `renderChart`, `loadSnapshot`, `setDebugTraceEnabled`, project/image/crypto handlers | Fetch API, Chart.js, DOM APIs | interactive frontend behavior |
| `ui/styles.css` | Visual system/layout states and component styling. | classes for modes, chart, sources, toasts, panels | CSS only | frontend presentation |

## Design Notes (SOLID/pattern alignment)

- Single Responsibility:
  - API files orchestrate; service files compute/domain logic; scripts gate/verify.
- Open/Closed:
  - Web providers and tool routing policies are extensible without changing endpoint contracts.
- Interface Segregation:
  - Auth scopes are split (`main/files/admin`) rather than one global guard.
- Dependency Inversion:
  - Handlers call services, not provider internals directly.

## How To Keep This Inventory Up To Date

When adding/changing canonical behavior:

1. Update this file with any new file-level role changes.
2. Update `docs/function_usage_map.md` if call graph changes.
3. Update `docs/dependencies_map.md` if new external libraries are introduced.
4. Run relevant tests/gates and update `docs/full_strict_closure.md` and `docs/release_board.md` percentages.
