# Legacy & Experimental Surfaces (AEGIS)

This doc explains what can look “disconnected” in AEGIS and why it still exists.

## Stable core (current truth)
- Project lifecycle: `/files/*` (project registry, ingest, manifest, scoped retrieval tools)
- Chat orchestration: `/chat` (tool-first routing, session state, turn tracing)
- Runtime status: `/system/readyz`, `/system/snapshot`, `/system/capabilities`
- Startup gate: `./start_aegis.sh` → `app/scripts/start_with_preflight.py`
- Libraries/dependencies map: `docs/dependencies_map.md`

## Legacy surfaces (kept for compatibility)

### `/tools/*` API (legacy project surface)
- Code: `app/api/toolssupport.py`
- Status: **deprecated, always `410 Gone`**
- Why it exists: older UI/workflows used `/tools/tree`, `/tools/content`, `/tools/delete_project`.
- Current replacement: `/files/tree`, `/files/content`, `/files/delete_project` + `/files/projects/*`.
- Removal plan: keep only as a deprecation shim (`410`) until all external clients migrate.

### `app/tools.py` (canonical runtime utilities)
- What it is: a focused utilities module with SSRF-safe fetch, text sanitizers, and browser binary discovery.
- What is currently used:
  - URL fetch helpers + sanitizers (used by chat and URL mode)
  - Browser binary discovery flags (used by `app/scripts/browser_smoke.py` and readiness checks)
- What was removed:
  - legacy web search compatibility wrappers and unused tool-registry helpers.
- Canonical search path remains `app/services/web_search.py`.

## Experimental / opt-in features

### In-process E2E (`--inprocess`)
- Flag: `AEGIS_ENABLE_INPROCESS_E2E=1`
- Status: **opt-in only**
- Why: ASGI TestClient in-process runs can be flaky depending on environment; host-level E2E is the real signal.

### Meta API (`/meta/*`)
- Surface: `app/core/meta.py`
- Gate: `AEGIS_ENABLE_META_API=1`
- Status: **optional analytics surface**, disabled by default.
- Why: depends on extra data/ML stack (`numpy/pandas/pandas_ta/sklearn/vaderSentiment`) and is not part of core strict runtime DoD.

### Browser smoke gate
- Script: `app/scripts/browser_smoke.py`
- `runtime-profile=standard`: best-effort (can skip if runtime unavailable)
- `runtime-profile=strict`: required (fails if browser runtime unavailable)
- Why: headless Chrome often fails on some machines/containers; best-effort preserves demo reliability.

### Shutdown endpoint
- Endpoint: `POST /system/shutdown`
- Guard: `AEGIS_ENABLE_SHUTDOWN_ENDPOINT=1` + `ADMIN_API_KEY`/admin scope
- Why: local demo convenience; disabled by default for safety.

### Offline mode flag
- Flag: `AEGIS_OFFLINE_MODE=1`
- Status: **informational** (reported in snapshot profile; not a hard enforcement switch)
- Why: kept as a “design hook” for future policy enforcement; safe to ignore for now.

## How to decide “remove now vs later”
- Remove now if:
  - it creates user confusion (exposed in UI/README as active when it isn’t),
  - it causes security risk by being enabled by default,
  - it blocks tests/gates.
- Keep for later if:
  - it is disabled by default and low risk,
  - it provides compatibility for older clients,
  - it’s a useful hook for future features (but document it clearly as opt-in/experimental).
