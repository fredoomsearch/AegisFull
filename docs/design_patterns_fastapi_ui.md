# AEGIS Design Patterns (FastAPI + UI)

This guide explains how current functions are designed and why.
It is focused on practical architecture rules used in this repo.

Important stack note:
- Backend: FastAPI + service modules + SQLAlchemy.
- Frontend: vanilla JS (`ui/app.js`), not Angular at the moment.

## 1) Architectural Shape

Current shape is layered:
1. API handlers (`app/api/*.py`) define HTTP contracts.
2. Services (`app/services/*.py`) implement domain/runtime behavior.
3. Persistence (`app/db/*.py`) stores durable state.
4. Runtime scripts (`app/scripts/*.py`) enforce preflight and release gates.

Rule:
- Handlers should orchestrate.
- Services should decide/compute.
- DB modules should persist.

## 2) SOLID In Current Code

### S: Single Responsibility Principle

Examples:
- `app/api/chat.py`: chat/agent HTTP orchestration only.
- `app/services/session_state.py`: planner/session continuity logic only.
- `app/services/conversation_turns.py`: turn trace persistence only.
- `app/services/web_search.py`: provider search orchestration only.

Practical check:
- If a function touches unrelated concerns (routing + file IO + auth + formatting), split it.

### O: Open/Closed Principle

Examples:
- web providers in `app/services/web_search.py` are added as new provider functions without rewriting chat endpoint contracts.
- runtime feature flags (`AEGIS_ENABLE_*`, runtime profile flags) extend behavior without changing all call sites.

Practical check:
- Add new provider/tool via extension points, not by editing core decision code in many places.

### L: Liskov Substitution Principle

Examples:
- capability collectors in `app/services/capabilities_service.py` return stable dict shapes even when degraded.
- fallback paths (hash embeddings, placeholder image) preserve endpoint response contracts.

Practical check:
- fallback implementation must keep response schema compatible.

### I: Interface Segregation Principle

Examples:
- auth dependencies split by scope:
  - `require_api_key`
  - `require_files_api_key`
  - `require_admin_api_key`
- endpoints are separated by surface (`/chat`, `/files`, `/system`, `/crypto`) instead of one generic interface.

Practical check:
- do not force callers to provide broader permissions than needed.

### D: Dependency Inversion Principle

Examples:
- FastAPI dependency injection (`Depends(...)`) for auth/session boundaries.
- handlers depend on service functions rather than raw provider internals.
- runtime truth reads from capability services (`collect_runtime_capabilities`) instead of each endpoint re-implementing checks.

Practical check:
- handler should call a service API, not external provider code directly.

## 3) Core Patterns In Use

### Router + DTO pattern

- FastAPI router functions define request/response shape with Pydantic models.
- Example: `AgentRunRequest` -> `agent_run(...)` -> `AgentRunResponse`.

### Strategy pattern (search providers)

- `app/services/web_search.py` selects providers (`brave_html`, `ddgs`, etc.) based on availability/cooldown.
- Provider-specific implementation stays isolated.

### State machine style (agent/session)

- `session_state` stores planner hints: `next_step`, `next_tool`, focus state, missing evidence.
- agent endpoints run bounded loops (`plan -> execute -> verify -> replan`).

### Pipeline pattern (validation)

- startup/verification scripts run deterministic ordered checks.
- release gating uses explicit pass/fail criteria.

### Facade pattern (runtime truth)

- `app/services/capabilities_service.py` aggregates many subsystems.
- `/system/readyz` and `/system/snapshot` expose one consistent runtime view.

## 4) UI Function Design Pattern

`ui/app.js` follows a single-store event-driven style:
- `state` object = runtime UI truth.
- `cacheDom()` = one-time DOM references.
- `wireUI()` = event binding.
- render/update functions read state and mutate DOM.

Why this works:
- predictable event flow
- easier debugging with explicit handlers
- lower coupling to backend response shape changes

Recent chart pattern additions:
- range preset controls (`setChartRangePreset`)
- manual zoom/pan state (`handleChartWheel`, `resetChartZoom`)
- chart rendering remains deterministic via `renderChart(state.lastPoints)`

## 5) If You Migrate To Angular Later

Suggested mapping:
- `state` -> Angular services + RxJS store
- `wireUI` handlers -> component outputs/actions
- render helpers -> pure pipes/view-model methods
- polling/runtime status -> dedicated data services with interceptors

Migration rule:
- keep backend contracts unchanged; replace UI implementation layer only.

## 6) Function Design Checklist

When adding a new function:
1. Declare one responsibility.
2. Keep input/output explicit (typed where possible).
3. Put business logic in service module, not endpoint body.
4. Preserve response contract under fallback/degraded paths.
5. Emit trace/metrics when function affects runtime behavior.
6. Add tests for happy path and failure mode.

When changing existing behavior:
1. Update endpoint/service docs map (`docs/function_usage_map.md`).
2. Update dependency docs if a new library is introduced.
3. Run UI/API contract tests plus strict gates relevant to the change.
