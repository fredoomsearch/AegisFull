# AEGIS Canonical Map (Backend)

This document is the “source of truth” map for how the backend is organized and how the main flows connect.
For doc navigation, see `docs/README.md`.

Canonical status rule: if a flow is not listed in this map as a core plane, treat it as optional/legacy until proven otherwise.

Code signalization rule:
- Canonical modules include short headers/docstrings that explain **why** each component exists.
- This is intended to reduce architecture drift and onboarding confusion.

## Control Plane (startup + validation)

- `start_aegis.sh`: production-ish launcher (runs `start_with_preflight.py`, then uvicorn).
- `start_demo.sh`: demo launcher (disables heavy warmups for faster interviews).
- `start_standard.sh`: shortcut launcher (`AEGIS_RUNTIME_PROFILE=standard`).
- `start_strict.sh`: shortcut launcher (`AEGIS_RUNTIME_PROFILE=strict`).
- `stop_aegis.sh --clean`: detiene procesos + limpia artefactos runtime (imágenes/logs/turn traces/validation state).
- `app/scripts/start_with_preflight.py`: startup gate (host-prereq → pytest-smoke → agent-evals → preflight-e2e(optional) → healthz → host e2e → readyz → ui-contract → hard-contract → no-loop-stress → browser-smoke).  
  Runtime profile controls strictness: `--runtime-profile strict|standard` (also `AEGIS_RUNTIME_PROFILE`).
- `app/scripts/ui_contract_check.py`: UI contract gate (no browser): checks `/` HTML + required DOM ids + `/ui/*` assets.
- `app/scripts/e2e_flow_check.py`: API-level end-to-end smoke (host mode is the main signal).
  Limpia artefactos de su corrida por defecto (imagenes/logs/turn traces/conversation memory entry); usa `--keep-artifacts` si quieres conservarlos para debugging.
- `app/scripts/cleanup_runtime_artifacts.py`: limpieza explícita de artefactos runtime para demos/tests.
- `app/api/system.py`: runtime reporting (`/system/snapshot`, `/system/readyz`, `/system/capabilities`) + optional `/system/shutdown`.

## Router Composition (actual runtime wiring)

- `main.py` mounts static surfaces:
  - `/ui/*` from `ui/`
  - `/data/*` from `data/` (read-only static serving for generated assets)
- `main.py` includes routers in this order:
  1. `app/api/files.py` router (`/files/*`) with `require_files_api_key`
  2. aggregate `app/api/__init__.py` router (chat/crypto/data/system/admin/auth/image/notifications)
- In `app/api/__init__.py`, optional routers are env-flag driven (`AEGIS_ENABLE_*`), but:
  - legacy `app.api.toolssupport` is always mounted intentionally as deprecation shim (`/tools/* -> 410`)

## Conversation Plane (chat + agent runtime)

- `app/api/chat.py`
  - `POST /chat`: main chat endpoint (tool-first for deterministic answers when possible).
    Incluye guardas anti-leak de salida (`_sanitize_and_repair_llm_output` + `_finalize_user_response`) para evitar exponer prompt interno/trazas.
  - `POST /chat/{id}/agent_step`: 1-step tool-first planner/executor (plan → tools → verify → optional LLM).
  - `POST /chat/{id}/agent_run`: multi-iteration tool-first loop (replans inside one call) with explicit tool budgets (`max_iterations`, `max_total_tool_calls`) and retry policy (`max_tool_retries`, `tool_retry_backoff_ms`).
  - `POST /chat/{id}/agent_continue`: continue from session-state hints (`next_step` / task focus) without retyping.
  - `POST /chat/{id}/execute_tool`: allowlisted tools with approval gate for sensitive actions.
    Tras ejecutar, devuelve contexto replanned (`tool_candidates`, `actions`, `next_step`) y soporta `continue_after=true`
    para encadenar `agent_continue` server-side en una sola llamada.
    Si no hay plan de continuación disponible, devuelve `continue_result.reason=no-continue-plan`.
  - `GET /chat/{id}/turns`: turn/item trace for debugging.
- `app/services/conversation_turns.py`: turn/item storage for traces (plan/tool/web/llm events).
- `app/services/session_state.py`: structured session state (goal/task/subtask/focus/missing_evidence).
- `app/memory.py`: fallback memory store when DB is disabled.
- `app/db/crud_conversation.py` + `app/db/models.py`: persisted conversations/messages + persisted `session_state_json`.

## Project Plane (uploads → project_id → manifest → tools)

- `app/api/files.py`: canonical project API surface (`/files/*`), including:
  - upload/clone/register-root
  - ingest
  - manifest + architecture + entrypoints/dependencies/configs
  - project-scoped file tree/content and symbol search
- `app/services/project_store.py`: project registry (project_id → root_path, manifest_path, status).
- `app/services/project_manifest.py`: manifest generation and summaries (“what’s inside this zip?” deterministically).
- `app/scripts/ingest_repo.py`: ingest driver (chunking + indexing).
- `app/services/retrieval_service.py`: project-scoped retrieval/index metadata.
- Project identity contract:
  - operational id is `active_project_id`
  - manual root input is auxiliary; it is not the canonical project identity

## Fresh Context Plane (web)

- `app/services/web_search.py`: provider orchestration + cache + meta (“live/cache/unavailable”).
- `app/api/chat.py`: contextual query rewrite via `_prepare_web_query(..., session_state=...)`.
- `/websearch` never explodes: if all providers fail it returns `meta.status="unavailable"` (UI muestra “Web off → sigo con local/cache”).
- Readiness: `/system/readyz` incluye bloque `web_search` con estado `ready/degraded/cooldown`.

## Security & Ops Plane

- `app/api/deps.py`: API key auth (main/files/admin scopes).
- `app/services/antivirus_service.py`: ClamAV status + recent events (`/files/av/*` + snapshot).
- `app/services/redaction.py`: best-effort secret redaction before sending prompts to LLMs.
- Browser gate: `app/scripts/browser_smoke.py` usa Chromium/Chrome/Brave headless.
  En `runtime-profile=strict`, browser smoke es obligatorio (falla real si runtime no está disponible).

## Data Persistence Contract

- Canonical DB mode: PostgreSQL via `DATABASE_URL` or `POSTGRES_*` (`app/db/base.py`).
- `AEGIS_DISABLE_DB=1` enables controlled fallback mode for local demo/tests.
- Conversation continuity uses DB when available, with memory fallback in DB-disabled mode.

## UI Plane (single-file frontend)

- `ui/index.html` + `ui/app.js` + `ui/styles.css`
  - Web status badges (live/cache/off)
  - Active project badge + manifest summaries
  - Turn/trace viewer for debugging
  - Agent button: click = `agent_step`, shift+click = `agent_run`
  - Agent suggested actions: backend returns `plan.actions` (typed tool + args + risk), UI renders 1-click buttons
    (executes `/execute_tool` and can auto-call `/agent_continue` when `next_step` exists).
  - Respuesta visible saneada: `sanitizeAssistantAnswerText(...)` evita mostrar en bubbles trazas internas o fugas de prompt.
- Web modo: si `/websearch` falla, UI muestra “Web no disponible; sigo con local/caché” en vez de “Network error”.
- Imagen: panel Imagen permite OCR local (`/analyze_image`), usar imagen de referencia + OCR opcional (`/image/generate_with_reference`) y generar (`/image/generate`). Si backend SD no está, se usa placeholder y se etiqueta como fallback.
  Checkpoint activo/configurado/backend disponibles: `/image/checkpoints` (útil para diagnosticar errores `ckpt_name not in list`).

## Evidence Contract (what “tool-first” means here)

Order of evidence for agent answers:

1. Project manifest summaries (deterministic inventory + architecture)
2. Local tools (files/symbols/excerpts/logs)
3. Optional web search (for freshness/external docs)
4. LLM synthesis (only after evidence exists, unless explicitly requested)

## Startup & Validación (gates por nivel)

- Startup gate (`start_with_preflight.py`): `host-prereq` → `pytest-smoke` → `agent-evals` → `preflight-e2e(optional)` → `healthz` → `host e2e` → `/system/readyz` → `ui_contract` → `hard_contract` → `no_loop_stress` → `browser_smoke`.
  Con `runtime-profile=strict` exige browser usable + capacidades core en `ready`.
- `verify_full.py`: verificación extendida (host-prereq/healthz + pytest full + e2e strict + agent evals + ui_contract + hard_contract + no_loop_stress + browser smoke).
  En `strict`, requiere `--base-url` y bloquea skips de checks core (`pytest`, `e2e`, `ui_contract`).
- Runtime badges en UI: `RUN`, `WEB`, `image`, `llm` usan `/system/readyz` para mostrar `ready/degraded/fallback`.
  En la tarjeta de capacidades también se muestra `browser_runtime` (clave para strict profile).

## Legacy Policy

- `/tools/*` permanece montado solo como superficie de deprecación y responde `410 Gone`.
- El dominio canónico de proyecto es `/files/*` (tree/content/delete/manifest/introspection).

## Librerías clave

- FastAPI, Uvicorn, SQLAlchemy, Pydantic
- Retrieval: FAISS + `sentence-transformers/all-MiniLM-L6-v2`
- LLM local: llama.cpp + WizardCoder GGUF (offload client)
- Web: requests + BeautifulSoup; opcional Selenium (si hay navegador)
- Imagen: ComfyUI/SD vía HTTP; fallback Pillow placeholder
- OCR: pytesseract (ES/EN)

For full library mapping (`library -> implementation files`), see `docs/dependencies_map.md`.
