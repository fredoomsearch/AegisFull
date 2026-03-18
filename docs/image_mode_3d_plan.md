# Image Mode + 3D Roadmap

Date: 2026-03-14

This plan extends the compact image mode to production quality and defines a real 3D path.

## Scope

- Keep one unified chat input flow.
- Upload image -> understand image -> chat with context.
- Generate images from chat commands.
- Add optional 3D generation workflow without reintroducing panel complexity.

## Current baseline (done)

- Compact image mode in chat bar (`imgBtn` + inline upload button).
- Image analysis attaches context into chat.
- Chat command generation:
  - `/img ...`
  - `/img3d ...` (3D-style render prompt preset).
- Generated image previews render directly in chat bubbles.

## Phase A: Quality lock for compact image mode

Target: deterministic, low-confusion behavior.

1. Input contract
- `/img <prompt> [--steps N] [--seed N] [--cfg N] [--width N] [--height N] [--negative "..."]`
- `/img3d <prompt>` same flags as `/img`.
- Natural language parse only when mode is `image`.

2. Validation
- Enforce bounds:
  - `steps` in `[1, 50]`
  - `width/height` in `[256, 1024]`
  - `cfg` in `[1.0, 20.0]`
- Clear user error messages when values are invalid.

3. Output UX
- Always show:
  - concise status bubble,
  - image preview bubble,
  - metadata line (`steps`, `seed`, backend/fallback).
- Never leak internal traces in normal mode.

4. Tests
- Add UI regression tests for parser variants and compact-only contract.
- Add end-to-end test:
  - image mode on,
  - upload image,
  - ask question,
  - run `/img` and assert image path appears in response.

Exit gate:
- New image-mode tests 100% pass in strict profile.

## Phase B: True 3D support (mesh output)

Target: real 3D assets (`.glb`) and chat-first interaction.

1. Backend capability layer
- Add `app/api/image_3d.py` (or extend `app/api/image.py`) with:
  - `POST /image/3d/generate` (text/image -> 3D job)
  - `GET /image/3d/jobs/{id}`
  - `GET /image/3d/recent`
- Add runtime capability key in `/system/readyz`:
  - `image_3d.status` in `{ready,degraded,unavailable}`.

2. Provider abstraction
- Create `app/services/image_3d_service.py`:
  - provider interface,
  - timeout/retry policy,
  - fail-closed metadata validation.
- Support at least one provider at first (config-driven).

3. Artifact handling
- Store generated assets under `data/images3d/`.
- Persist metadata in JSONL (prompt, seed, provider, job id, path, latency, errors).
- Enforce max file size and extension allowlist (`.glb`, `.gltf`).

4. Frontend
- Add chat commands:
  - `/3d <prompt>`
  - `/3d-from-image` when an image attachment exists.
- Render result bubble with:
  - download link,
  - optional inline viewer toggle (Phase C),
  - metadata.

5. Security
- Validate MIME and extension before serving files.
- Optional AV scan of produced artifacts if pipeline permits.
- Signed short-lived URLs if exposed outside localhost.

Exit gate:
- Strict tests for 3D endpoints + contract checks + artifact validation.

## Phase C: 3D viewer and advanced controls

Target: high-end UX without panel sprawl.

1. Inline chat 3D viewer card
- Use a lightweight viewer component for `.glb`.
- Add fallback to download-only mode on unsupported browsers.

2. Quality controls
- Optional flags:
  - polygon/detail profile,
  - texture resolution,
  - generation style preset.

3. Conversation continuity
- Keep latest 3D artifact in conversation state as `last_artifact_kind=3d_asset`.
- Allow follow-up prompts:
  - "make it more metallic"
  - "reduce polycount".

Exit gate:
- Browser smoke includes viewer rendering and fallback path.

## Operational checklist

- Add doctor checks for 3D provider availability.
- Add strict verify checks for 3D endpoints when feature flag is enabled.
- Add soak checks for job completion rate and timeout budget.

## Recommended execution order

1. Finish Phase A tests and strict gating.
2. Ship Phase B minimal provider + file download.
3. Ship Phase C inline viewer and advanced controls.

## GO criteria for "exceptional quality"

- Compact image mode confusion rate near zero in adversarial prompts.
- Deterministic command behavior (`/img`, `/img3d`, natural prompts in image mode).
- 3D pipeline has explicit ready/degraded semantics and reproducible artifacts.
