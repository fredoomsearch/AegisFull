# AEGIS Release Board (GO / NO-GO)

Date: 2026-03-16  
Canonical source: this file (`docs/release_board.md`).

## 1) Canonical Completion Snapshot

### By Phase

| Phase | Status |
|---|---|
| Phase 1 (source of truth + legacy cleanup) | **99.5%** |
| Phase 2 (operational flow / deterministic routing) | **98.0%** |
| Phase 3 (observability + validation) | **99.9%** |
| Phase 4 (UX + product cleanup) | **99.0%** |
| Phase 5 (Codex-like runtime reliability) | **94.8%** |

### By Sprint

| Sprint | Implemented | Verified |
|---|---:|---:|
| Sprint A (UX state) | **100%** | **95%** |
| Sprint B (debug + startup health) | **100%** | **90%** |
| Sprint C (chart readability) | **100%** | **100%** |
| Sprint D (docs architecture/functions/dependencies) | **100%** | **96%** |
| Sprint E (Codex parity runtime) | **99.0%** | **98.4%** |

### Composite Read

- Implementation average (sprints): **99.8%**
- Verification average (sprints): **95.9%**
- Phase average progress: **98.2%**
- Full strict closure progress (current host): **99.3%** (72h soak pending)

## 2) Product Tracks (Commercial Positioning)

- **Core track**: chat + files/project tools + web retrieval + strict routing/contract.
- **Full track**: Core + image backend hard-required + host browser runtime hard-required in strict.

## 2.1) Commercial Readiness Snapshot

- Core vs Full split: **96%**
- Installer + doctor + checklist: **95%**
- SLO contract: **93%**
- Demo + known-limits pack: **80%**

## 3) GO / NO-GO Board

## Core Track

- [x] Deterministic routing + confidence buckets integrated.
- [x] Adversarial eval strict >= 500 cases at 100% pass (`520/520`).
- [x] Wrong-route contract target (`<= 0.5%`) enforced in strict checks.
- [x] Safety fallback rate threshold enforcement wired.
- [x] Poll 401 spam control + runtime metrics alerts wired.
- [x] No-loop stress gate integrated in strict orchestration.
- [x] `/tools/*` legacy deprecation hard-gated (`410 Gone`).
- [x] AV timeout retry is bounded + fail-closed preserved (reduces transient upload flakes).
- [x] Core evidence runbook + bundle script prepared (`run_core_release_evidence.sh`).
- [x] Host-level strict verify run archived as green artifact for release candidate.
  - Artifact: `artifacts/release_evidence_core/20260312_000239`

**Current decision: GO**  
Reason: strict/core host evidence is archived and green; core release gate is satisfied.

## Full Track

- [x] Browser smoke strict pass on target host (no skip).
- [x] Image backend reachable and healthy in strict (`readyz` not degraded by image).
- [x] `verify_full` strict pass on active target host with real image backend.
- [ ] 72h soak profile complete with thresholds stable.

**Current decision: NO-GO**  
Reason: only the 72h soak artifact is still open.

Latest repass (2026-03-14):
- smoke tests: `157/157` pass
- agent eval: `16/16` pass
- adversarial eval: `520/520` pass
- live strict/full startup gate: pass (`image` ready, `readyz=ready`, hard-contract/no-loop/browser-smoke pass)
- focused mode/routing/image/strict regression pack: pass (`74/74`)
- runtime hole scan markers in `app/`: clean (`NotImplementedError/TODO/FIXME/HACK/XXX` = none)
- runtime cleanup hardened to clear stale 72h control artifacts (`full_72h.pid`, `full_72h.logpath`, `full_72h_*.log`)
- latest complete full bundle still: `artifacts/release_evidence/20260312_021853` (`ok=true`)
- newer folders `20260312_023706` / `20260312_023820` are partial and not closure-grade
- current-host caveat: if the active host loses the real image backend (`AEGIS_IMAGE_ENDPOINT` offline / `127.0.0.1:8188` refused), strict/full startup on that host will fail even though the latest complete archived bundle remains green

Step 7 execution status:
- [x] Evidence runbook + bundle script prepared (`run_full_release_evidence.sh`, fail-fast doctor precheck with actionable failure hints + precheck-only mode).
- [x] Full doctor precheck strengthened (image endpoint reachability + browser binary executable/version).
- [x] Evidence scripts now print doctor blocker details directly on precheck failure.
- [x] Full evidence run now includes fail-fast image backend probe (`image_backend_probe.json`).
- [x] Full image probe supports optional torch CUDA diagnostics (`AEGIS_IMAGE_PYTHON`, `AEGIS_REQUIRE_IMAGE_TORCH_CUDA`).
- [x] Full image probe supports optional NVIDIA hardware guard (`AEGIS_REQUIRE_NVIDIA_SMI`).
- [x] Full evidence bundle now includes deterministic gate summary (`release_summary.json`).
- [x] Host strict/full execution complete (short-cycle strict evidence green).
  - Artifact: `artifacts/release_evidence/20260312_021853`
- [x] Runtime cleanup now removes stale 72h run control files to prevent false “run in progress” state.
- [ ] 72h soak artifact archived and reviewed.

## 4) Trust Bands (Operational)

- **Core trust (current): 88-92%**
- **Full strict trust (current): 84-89%**
- **UI consistency trust (current): 80-86%**

These are operational confidence bands, not a claim of universal bug-free behavior.

## 5) Exit Criteria To Close 100% Strict Board

1. Pass strict host verification with real browser runtime and real image backend.
2. Complete and archive 72h soak run with contract thresholds green.
3. Keep adversarial strict suite at 100% pass for configured minimum case count.
4. Record release artifact bundle:
   - strict verify output
   - hard contract output
   - no-loop stress output
   - runtime metrics snapshot

## 6) Next Actions (Ordered)

1. Execute 72h soak and lock thresholds.
2. Archive 72h soak bundle and release summary.
3. Mark Full track GO after 72h gate is green.

Runbook:
- [Unified Strict Closure (Status + Checklist + Core/Full Runbooks)](./full_strict_closure.md)
