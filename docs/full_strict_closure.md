# AEGIS Unified Strict Closure

Date: 2026-03-16  
Canonical strict-closure source: this file (`docs/full_strict_closure.md`).

This file consolidates:
- strict phase/sprint status,
- post-install acceptance checklist,
- core + full strict closure runbooks,
- latest repass status and blocker ledger.

## 0) What "100%" Means

- `100%` means **100% pass of a bounded release contract** (tests + gates + soak thresholds).
- It does not mean universal bug-free behavior for every possible LLM prompt.
- Confidence comes from deterministic gates:
  - `verify_full`,
  - hard-contract checks,
  - adversarial evals,
  - no-loop stress,
  - soak thresholds,
  - readiness/snapshot observability.

## 1) Current Completion Snapshot

### By Phase

| Phase | Scope | Status |
|---|---|---|
| Phase 1 | Source of truth + legacy cleanup | **99.5%** |
| Phase 2 | Operational flow (tool-first routing) | **98.0%** |
| Phase 3 | Observability + validation | **99.9%** |
| Phase 4 | UX + product cleanup | **99.0%** |
| Phase 5 | Codex-like runtime reliability | **94.8%** |

### By Sprint

| Sprint | Focus | Main phases | Implemented | Verified |
|---|---|---|---|---|
| Sprint A | UX state (snapshot/messages/panels) | P4 + P3 | **100%** | **95%** |
| Sprint B | Debug + startup health | P3 + P2/P4 | **100%** | **90%** |
| Sprint C | Chart readability (Google-like) | P4 | **100%** | **100%** |
| Sprint D | Docs architecture/functions/dependencies | P1 + P4 | **100%** | **96%** |
| Sprint E | Codex parity runtime | P5 + P2/P3 | **99.0%** | **98.4%** |

### Repass Status (this host/session)

- Full smoke gate: **157/157 passed**.
- Agent eval: **16/16 passed**.
- Adversarial eval: **520/520 passed** (`min_cases=500`).
- Live strict/full startup gate re-run (2026-03-13): **passed**.
  - image generation: backend path (no fallback),
  - `system/readyz`: `ready=True`, `status=ready`,
  - hard-contract: pass,
  - no-loop-stress: pass,
  - browser-smoke: pass.
- Focused regression pack re-run (2026-03-14): **74/74 passed** (routing/mode/image/strict guards).
- Runtime hole scan in `app/`: clean (`NotImplementedError/TODO/FIXME/HACK/XXX` = none).
- Latest complete full evidence bundle remains green:
  - `artifacts/release_evidence/20260312_021853` (`release_summary.ok=true`).
- Newer 72h attempt folders are partial/incomplete (`20260312_023706`, `20260312_023820`) and should not be used as closure evidence.
- Current strict/full closure progress: **99.3%** (single blocker: missing complete 72h soak artifact).
- Important host caveat: a local strict/full boot on `2026-03-16` can still fail if `AEGIS_IMAGE_ENDPOINT` is offline on that host (`127.0.0.1:8188` refused connection). The `99.3%` figure is based on the latest complete green evidence bundle, not on an arbitrary host session with the image backend down.
- Runtime artifact cleanup pass: completed (`cleanup_runtime_artifacts --aggressive`).
- Runtime cleanup now also clears stale 72h control artifacts (`full_72h.pid`, `full_72h.logpath`, `full_72h_*.log`) to avoid false in-progress state.

## 2) Resolved Error Ledger (By Phase/Sprint)

### Phase 1 (Source of Truth + Legacy)

Resolved:
- Canonical project surface consolidated to `/files/*`.
- Legacy `/tools/*` fixed as deterministic deprecation shim (`410 Gone`).
- Canonical maps/docs expanded for architecture/function/dependency traceability.

### Phase 2 (Operational Flow / Routing)

Resolved:
- Tool-first routing and evidence-before-LLM behavior stabilized.
- Planner/session state continuity strengthened (`next_step`, `next_tool`, `missing_evidence`).
- Project-binding contamination fixes:
  - stale task/artifact/web context reset on project switch.
- Generic prompts no longer incorrectly blocked by project missing-evidence.
- Pasted code/log blobs now prefer local/project path over noisy web routing.
- Internal trace-leak stripping strengthened (`localOrigin`, `webData`, `Task`, etc.).

### Phase 3 (Observability + Validation)

Resolved:
- Strict profile wired through startup + verify pipelines.
- Runtime metrics and alert thresholds exposed via `/system/metrics` + `/system/snapshot`.
- Hard-contract now enforces routing confidence/rate thresholds.
- No-loop stress integrated as strict blocking gate.
- Auth-edge no-loop injection support added.
- Doctor and full-evidence fail-fast prechecks improved:
  - image endpoint reachability,
  - browser binary executable/version,
  - checkpoint probe.
- Release evidence summary artifacts standardized (`release_summary.json`).

### Phase 4 (UX + Product Cleanup)

Resolved:
- Main chat output protection from internal trace leakage.
- Debug traces isolated behind debug surfaces.
- Web mode confusion reduced:
  - web button removed from mode controls,
  - web remains automatic fallback or explicit `web:` force.
- Web status/error messaging clarified:
  - explicit "web is automatic / use `web:` to force",
  - backend-unreachable error now states this is a server connectivity issue (not web-mode disablement).
- UI contracts updated accordingly.

### Phase 5 (Codex-like Runtime Reliability)

Resolved:
- Planner -> execute -> verify loop bounded and instrumented.
- Approval model + budgets/retries in place.
- Adversarial suite expanded to strict deterministic set (>=500; current 520).
- Recovery behavior improved for build-intent requests.

Still open:
- long-horizon replan tuning under sustained multi-step load,
- full 72h strict soak closure on target host profile.

## 3) Open Blockers (Current)

1. Full-track 72h soak artifact remains required for final Full GO closure.
2. Incomplete partial 72h folders must be replaced by one final complete bundle (`release_summary.json` + `soak_gate.json` green).
3. Long-horizon replan tuning remains open for Phase 5 hardening.

## 4) Product-Track Acceptance Checklist (Post-Install)

## Base Runtime

- [ ] `./install_local.sh --track core`
- [ ] venv + dependencies installed
- [ ] `.env` keys configured (`AEGIS_API_KEY`, `FILES_API_KEY`, DB settings)
- [ ] backend starts with `./start_aegis.sh`
- [ ] `GET /healthz` = `200`
- [ ] `GET /system/readyz` matches selected track expectations

## Security Baseline (single-user local)

- [ ] `AEGIS_AUTH_MODE=on`
- [ ] strong keys only (no defaults)
- [ ] `FILES_AV_FAIL_OPEN=0`
- [ ] explicit `AEGIS_CORS_ORIGINS` (no wildcard for strict delivery)
- [ ] host hardening baseline applied (firewall/OS policy)

## Core Track Acceptance

- [ ] `python -m app.scripts.doctor --track core --base-url http://127.0.0.1:8000`
- [ ] doctor passes
- [ ] chat + files + web retrieval validated
- [ ] startup/verify artifacts archived

## Full Track Acceptance

- [ ] image backend online (`AEGIS_IMAGE_ENDPOINT`)
- [ ] browser runtime available for strict smoke
- [ ] `python -m app.scripts.doctor --track full --base-url http://127.0.0.1:8000`
- [ ] `python -m app.scripts.verify_full --runtime-profile strict --base-url http://127.0.0.1:8000 --api-key <key> --files-api-key <key>`
- [ ] `./run_full_release_evidence.sh --base-url http://127.0.0.1:8000 --duration-hours 72`
- [ ] strict/full artifacts archived

## Reliability Evidence

- [ ] hard-contract output saved
- [ ] no-loop stress output saved
- [ ] runtime metrics snapshot exported
- [ ] release board updated with GO/NO-GO

## 5) Core Strict Closure Runbook

Use this to close Milestone A (Core-track evidence).

Preconditions:
- backend reachable
- `AEGIS_RUNTIME_PROFILE=strict`
- `AEGIS_PRODUCT_TRACK=core`
- keys configured

Command:

```bash
./run_core_release_evidence.sh \
  --base-url http://127.0.0.1:8000 \
  --out-dir artifacts/release_evidence_core
```

Optional:

```bash
./run_core_release_evidence.sh --base-url http://127.0.0.1:8000 --run-soak --duration-hours 4
./run_core_release_evidence.sh --base-url http://127.0.0.1:8000 --precheck-only
```

Core GO criteria:
- `doctor_core.json` -> `ok: true`
- `verify_full_core.log` strict/core pass
- `hard_contract_core.log` -> `ok: true`
- `system_readyz.json` -> `ready=true` and status in `{ready,degraded,fallback-only}`

## 6) Full Strict Closure Runbook

Use this to close Step 7 (Full-track GO/NO-GO).

Preconditions:
- backend reachable
- `AEGIS_RUNTIME_PROFILE=strict`
- `AEGIS_PRODUCT_TRACK=full`
- real image backend reachable
- browser runtime available
- full doctor passes

Command:

```bash
./run_full_release_evidence.sh \
  --base-url http://127.0.0.1:8000 \
  --duration-hours 72 \
  --out-dir artifacts/release_evidence
```

Optional:

```bash
./run_full_release_evidence.sh --base-url http://127.0.0.1:8000 --duration-hours 72 --skip-doctor
./run_full_release_evidence.sh --base-url http://127.0.0.1:8000 --precheck-only
```

Fail-fast probes included:
- doctor full checks (readyz/security/image/browser)
- `python -m app.scripts.image_backend_probe --require-checkpoint`

Optional diagnostics:
- `AEGIS_IMAGE_PYTHON` (torch/cuda diagnostics runtime)
- `AEGIS_REQUIRE_IMAGE_TORCH_CUDA=1`
- `AEGIS_REQUIRE_NVIDIA_SMI=1`
- `AEGIS_DOCTOR_TIMEOUT_SECONDS` / `AEGIS_DOCTOR_ATTEMPTS`

Full GO criteria:
- `verify_full.log` strict/full pass
- `hard_contract.log` -> `ok: true`
- `soak_gate.json` -> `ok: true` with thresholds green
- `system_readyz.json` -> `ready=true` and `status=ready`
- evidence bundle linked in `docs/release_board.md`

## 7) Strict Completion Criteria (Release Gate)

- strict `verify_full` pass
- `/tools/*` remains `410 Gone`
- hard contract suite pass at configured threshold
- adversarial suite pass at configured threshold
- no-loop stress pass
- soak rates within configured budgets:
  - wrong-route
  - safety fallback
  - polling/auth noise

Track semantics:
- core strict: image/browser may be non-blocking
- full strict: image/backend + browser smoke are blocking

## 8) Update Protocol (Locked)

On every completion slice, update:
1. `docs/release_board.md` (canonical board + blockers)
2. `docs/full_strict_closure.md` (this unified strict closure status)

Keep percentages synchronized before external reporting.
