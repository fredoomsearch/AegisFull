# AEGIS Docs Index (Canonical)

This folder is the canonical documentation entrypoint for backend/runtime architecture.

## Read Order

1. [Canonical Map](./canonical_map.md)
2. [Architecture Map](./architecture_map.md)
3. [Tier-1 Call Flow (API -> Service -> Storage/Tool)](./tier1_call_flow.md)
4. [Function Usage Map (API -> Services)](./function_usage_map.md)
5. [Design Patterns (FastAPI + UI)](./design_patterns_fastapi_ui.md)
6. [Config Reference](./config_reference.md)
7. [Dependencies Map](./dependencies_map.md)
8. [File Inventory Map (By File/Role)](./file_inventory_map.md)
9. [Modules Inventory (All Imports)](./modules_inventory.md)
10. [Legacy / Experimental Surfaces](./legacy_experiments.md)
11. [Hard Contract Gate](./hard_contract.md)
12. [Function Duplication Audit](./function_duplication_audit.md)
13. [Release Board (GO / NO-GO)](./release_board.md)
14. [Commercial Pack (Claim/Tiers/DoD)](./commercial_pack.md)
15. [SLO Contract](./slo_contract.md)
16. [Known Limits](./known_limits.md)
17. [Demo Checklist](./demo_checklist.md)
18. [Unified Strict Closure](./full_strict_closure.md)

## Trust Contract

- Canonical project surface is `/files/*`.
- Legacy `/tools/*` remains mounted only as a deterministic deprecation shim (`410 Gone`).
- Runtime truth for operational status is `/system/readyz` (+ `/system/snapshot` for debugging detail).
- Startup/verification gates are:
  - `app/scripts/start_with_preflight.py`
  - `app/scripts/verify_full.py`
  - `app/scripts/hard_contract_check.py`
  - `app/scripts/adversarial_eval_check.py`
  - `app/scripts/soak_gate.py`
  - `app/scripts/no_loop_stress_check.py`
- `go_strict.sh` (strict host-level go/no-go wrapper)
- Launcher shortcuts: `start_standard.sh` / `start_strict.sh`
- Installer shortcut: `install_local.sh` (env bootstrap + doctor)

## Canonical Coverage Matrix

| Plane | Canonical Truth |
|---|---|
| Project lifecycle | `/files/*` + `app/services/project_*` |
| Conversation/agent runtime | `/chat*` + `app/services/session_state.py` + `app/services/conversation_turns.py` |
| Runtime capability status | `/system/readyz` + `/system/snapshot` |
| Web retrieval | `app/services/web_search.py` |
| Validation flow | `start_with_preflight.py` + `verify_full.py` (+ strict browser smoke in strict profile) |

## Tier-1 Documentation Contract

- Architecture truth is docs-first, centered on [Tier-1 Call Flow](./tier1_call_flow.md).
- Inline comments in Tier-1 code are concise pointers, not full architecture replicas.
- "Called from -> Calls ->" traceability must be updated in Tier-1 docs when orchestration changes.

## Dependency Learning Path

- Use [Dependencies Map](./dependencies_map.md) for architecture-plane view (API/auth/DB/LLM/image/browser).
- Use [Modules Inventory](./modules_inventory.md) for the complete module list used by canonical architecture code (`stdlib`, third-party, and internal `app.*` modules) with purpose and usage locations.
- Use [Function Usage Map](./function_usage_map.md) to learn which endpoint function calls which service function in canonical flows.

## Frontend Note

- The current UI is implemented as vanilla HTML/CSS/JS (`ui/index.html`, `ui/styles.css`, `ui/app.js`).
- Angular is not currently used in runtime architecture.

### Non-canonical (intentional)
- `/tools/*`: legacy compatibility surface, always `410`.
- Optional surfaces (disabled or host-dependent): `/meta/*`, in-process E2E, browser runtime, external image backend.

## Code Signalization

Canonical modules now include concise inline signalization:
- module headers describe **why** the component exists
- section markers identify the role of each block
- key functions/endpoints include short “why” docstrings

Coverage status:
- `main.py` is signalized.
- All files under `app/api/*.py` are signalized.
- All files under `app/services/*.py` are signalized.

## Production-like Validation Flow

1. Start backend with startup gates:
   - `./start_aegis.sh`
2. Run strict verification on a host with browser runtime + real image backend:
   - `./go_strict.sh --base-url http://127.0.0.1:8000`

If strict gate is green on that host, architecture + runtime are aligned with the strict DoD.

## Commercial Readiness Check

Use doctor diagnostics after installation:

```bash
./install_local.sh --track core
python -m app.scripts.doctor --track core --base-url http://127.0.0.1:8000
python -m app.scripts.doctor --track full --base-url http://127.0.0.1:8000
```
