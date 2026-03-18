# Tier-1 Call Flow (Canonical)

Date: 2026-03-11
Scope: high-impact runtime orchestration paths only.

## 1) Chat Runtime

- `POST /chat` (`app/api/chat.py::chat`)
  - Calls -> `session_state.update_session_state` for planner continuity
  - Calls -> local project tools (`/files/*` service helpers) when project-bound
  - Calls -> `web_search` service when plan selects `web_only` or `local+web`
  - Calls -> LLM synthesis + output sanitizers
  - Writes -> conversation/messages state via `db/crud_conversation.py`

- `POST /chat/{id}/agent_run` (`app/api/chat.py::agent_run`)
  - Calls -> plan/execute/verify loop with tool budget + retries
  - Calls -> project and web evidence collection
  - Calls -> optional synthesis step
  - Writes -> turn items/events and final assistant response

- `POST /chat/{id}/agent_step` (`app/api/chat.py::agent_step`)
  - Calls -> deterministic one-step planner + tool candidate selection
  - Calls -> local project tools first, optional web context, optional synthesis
  - Writes -> turn items/events and planner hints for next step

- `POST /chat/{id}/agent_continue` (`app/api/chat.py::agent_continue`)
  - Calls -> conversation state seed resolution (`next_step`/`current_subtask`/etc.)
  - Calls -> forwards into `agent_run` with continuation budget
  - Guard -> falls back to `"continue"` when no seed is present

- `POST /chat/{id}/execute_tool` (`app/api/chat.py::execute_tool`)
  - Calls -> allowlisted project/ops tools with one-shot execution
  - Calls -> approval token flow for sensitive actions (e.g. delete project)
  - Writes -> tool turn traces + approval state in conversation session

- `POST /chat/{id}/project` (`app/api/chat.py::bind_conversation_project`)
  - Calls -> project registry validation
  - Calls -> conversation state update + focus reset
  - Guard -> rejects non-existing project ids

## 2) Project/Files Runtime

- `POST /files/upload-zip` (`app/api/files.py::upload_zip`)
  - Calls -> zip-slip validation + extraction
  - Calls -> optional AV scan
  - Writes -> upload directory + project registry entry

- `POST /files/clone` (`app/api/files.py::clone_repo`)
  - Calls -> guarded git clone with host/branch/depth controls
  - Calls -> optional AV scan
  - Writes -> upload directory + project registry entry

- `POST /files/ingest` (`app/api/files.py::ingest_path`)
  - Calls -> `app/scripts/ingest_repo.py` subprocess
  - Calls -> manifest loader + project registry updater
  - Writes -> manifest/index references and ingest job state

- `POST /files/register-root` (`app/api/files.py::register_root`)
  - Calls -> workspace/upload root guards
  - Calls -> project registry binding without upload/clone
  - Writes -> canonical project metadata for local folders

- `POST /files/delete_project` (`app/api/files.py::delete_project_endpoint`)
  - Calls -> project registry lookup/delete
  - Calls -> guarded filesystem removal for upload-backed projects
  - Guard -> disallows deletions outside allowed roots

- `GET /files/projects/{id}` (`app/api/files.py::project_detail`)
  - Calls -> project registry + project manifest load
  - Calls -> architecture summary formatter

## 3) Crypto Runtime

- `POST /crypto/predict` (`app/api/crypto.py::predict`)
  - Calls -> market data fetch + lightweight prediction logic
  - Calls -> news enrichment + sentiment adjustment
  - Calls -> prediction/outcome log writers
  - Writes -> prediction telemetry for stats and outcomes

- `POST /crypto/trade` (`app/api/crypto.py::trade`)
  - Calls -> spot price + optional signed Binance request
  - Calls -> trade log writer
  - Guard -> defaults to simulation unless live-trading flag is enabled

## 4) System/Readiness Runtime

- `GET /system/snapshot` (`app/api/system.py::system_snapshot`)
  - Calls -> capability probe + readiness summary
  - Calls -> runtime metrics + validation flow snapshot
  - Calls -> prediction/trade snapshot aggregators

- `GET /system/readyz` (`app/api/system.py::readyz`)
  - Calls -> capability probe + readiness summary
  - Calls -> runtime metrics alert thresholds
  - Used by -> startup gates, strict verification, and operational checks

## 5) Startup/Strict Gates

- `app/scripts/start_with_preflight.py::main`
  - Flow -> host prereqs -> pytest smoke -> agent evals -> health/readyz -> E2E -> contracts -> no-loop -> browser smoke -> start uvicorn
  - Fails closed under strict profile for required gates

- `app/scripts/verify_full.py::main`
  - Flow -> full pytest -> strict E2E -> readyz -> agent evals -> UI contract -> hard contract -> no-loop stress -> browser smoke
  - Used for post-start strict validation

- `app/scripts/hard_contract_check.py::main`
  - Flow -> adversarial eval -> runtime metric thresholds -> optional soak + no-loop stress
  - Produces -> machine-readable go/no-go payload for release gates

## 6) Conversation Persistence and ORM

- `app/db/crud_conversation.py`
  - Entry points -> `create_conversation`, `append_message`, `get_conversation_state`, `set_conversation_state`
  - Used by -> chat and agent endpoints for canonical conversation storage

- `app/db/models.py`
  - Canonical entities -> `Conversation`, `Message`, `Embedding`
  - Used by -> CRUD layer and SQLAlchemy sessions for runtime persistence
