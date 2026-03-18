# AEGIS Demo Checklist

Date: 2026-03-11

Use this to run repeatable demos and produce evidence artifacts.

## 1) Pre-demo setup

- Set `AEGIS_AUTH_MODE=on` and strong keys (`AEGIS_API_KEY`, `FILES_API_KEY`, `ADMIN_API_KEY`).
- Select track:
  - Core: `AEGIS_PRODUCT_TRACK=core`
  - Full: `AEGIS_PRODUCT_TRACK=full`
- Start with gates: `./start_aegis.sh`.

## 2) Core demo flow (required)

- Ask generic chat question and verify normal response.
- Bind/upload a project, ask project-specific question, verify project-scoped answer.
- Ask explicit web question (`web:` prompt), verify source meta shows live/cache/local status.
- Run doctor:
  - `python -m app.scripts.doctor --track core --base-url http://127.0.0.1:8000`

## 3) Full demo flow (optional, host-dependent)

- Confirm image backend reachable via `/system/readyz` (`image_backend=true`).
- Run image generation from UI and verify non-fallback backend response.
- Run strict browser smoke:
  - `./verify_full_strict.sh --base-url http://127.0.0.1:8000`
- Run doctor:
  - `python -m app.scripts.doctor --track full --base-url http://127.0.0.1:8000`

## 4) Capture artifacts

- Save startup gate output.
- Save verify-full output.
- Save hard-contract and no-loop outputs (if run separately).
- Save `/system/metrics` snapshot.
- Update `docs/release_board.md` with GO/NO-GO per track.
