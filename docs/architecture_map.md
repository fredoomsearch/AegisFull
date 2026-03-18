# AEGIS Architecture Map (Canonical vs Legacy)

This is a quick “what lives where” map so future-you doesn’t have to re-learn the repo.
Primary reference remains `docs/canonical_map.md`.

## Control plane (startup + validation)
- Launchers:
  - `./start_aegis.sh` (full gate + uvicorn)
  - `./start_demo.sh` (fast demo defaults)
  - `./start_standard.sh` (forces `AEGIS_RUNTIME_PROFILE=standard`)
  - `./start_strict.sh` (forces `AEGIS_RUNTIME_PROFILE=strict`)
  - `./stop_aegis.sh` (best-effort stop)
- Gate orchestration: `app/scripts/start_with_preflight.py`
- Host E2E checks: `app/scripts/e2e_flow_check.py`
- Hard contract + soak/no-loop strict checks: `app/scripts/hard_contract_check.py`, `app/scripts/soak_gate.py`, `app/scripts/no_loop_stress_check.py`
- Browser smoke (best-effort by default): `app/scripts/browser_smoke.py`
- Extended verification tier: `app/scripts/verify_full.py`
- Strict go/no-go wrapper: `./go_strict.sh`

## Runtime status (single source of truth)
- Readiness: `GET /system/readyz` → `app/api/system.py`
- Snapshot (debug UI): `GET /system/snapshot` → `app/api/system.py`
- Capabilities registry: `GET /system/capabilities` → `app/api/system.py` + `app/services/capabilities_service.py`
- API surfaces status: `GET /system/snapshot` → `api_surfaces` block

## Conversation plane (agent-ish orchestration)
- Main chat router: `POST /chat` → `app/api/chat.py`
  - tool-first routing: project/manifest/files/symbols/logs before LLM
  - hybrid web routing: local-only vs local+web vs web-only
  - response context metadata: `context.source_plan`, `context.source_origin`, etc.
- Session state (“planner hints”): `app/services/session_state.py`
- Turn/items/events tracing:
  - turns: `app/services/conversation_turns.py` + `/chat/{id}/turns`
  - events: `app/services/conversation_events.py` + `/chat/{id}/events`

## Project plane (ZIP/repo ingest + project tools)
- Canonical project API: `app/api/files.py` (`/files/*`)
  - upload ZIP, clone, register root, ingest jobs
  - project manifest summary + architecture + dependencies/entrypoints/configs
  - scoped file search, symbol search, excerpts
- Project registry: `app/services/project_store.py`
- Manifest: `app/services/project_manifest.py`
- Introspection (fuzzy file search, symbol scan fallback): `app/services/project_introspection.py`
- Ingest pipeline: `app/scripts/ingest_repo.py`
- Retrieval/index: `app/services/retrieval_service.py` (project-scoped)
- Legacy `/tools/*` is not a project API path anymore (deprecation shim only).

## Knowledge plane (LLM + embeddings + web)
- Local LLM backend: `app/llm_client_offload.py` (llama.cpp GGUF)
- Embeddings: `app/services/embedding_service.py`
- Web search (canonical): `app/services/web_search.py` (+ cache/meta/status)
- URL fetch + SSRF guards + text sanitizers + browser binary discovery: `app/tools.py`
- Library-to-code map: `docs/dependencies_map.md`

## Security/ops
- Auth guards + scopes (API key/JWT): `app/api/deps.py`
- Antivirus service (ClamAV): `app/services/antivirus_service.py` + `/files/av/*`
- Image backend + fallback visibility + checkpoint resolver metadata: `app/api/image.py` (`/image/checkpoints`)

## UI plane (single-file frontend)
- UI entry: `ui/index.html`
- UI logic: `ui/app.js`
- Styles: `ui/styles.css`
  - source origin pills, runtime badges, turns view

## Legacy / compatibility surfaces
- `/tools/*` API: `app/api/toolssupport.py` (mounted only as deprecation shim, always `410 Gone`)
- Detailed explanation: `docs/legacy_experiments.md`

## Canonical integrity checklist

- Project lifecycle goes through `/files/*` only.
- Conversation runtime truth goes through `/chat*` + `/system/readyz`.
- Legacy surfaces are explicit and non-operational (`410`), not silently active.
