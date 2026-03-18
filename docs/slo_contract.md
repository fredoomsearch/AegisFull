# AEGIS SLO Contract (Core vs Full)

Date: 2026-03-11

This is the measurable reliability contract used for release decisions.

## 1) Scope

- Track-specific SLOs:
  - Core track (default commercial baseline)
  - Full track (all dependencies required)
- Time window:
  - short gate (strict checks)
  - long soak (production-like run)

## 2) Core Track SLOs

- Startup success:
  - `start_with_preflight` exits success for core profile.
- Routing quality:
  - wrong-route rate <= `0.5%`.
- Safety fallback:
  - safety fallback rate <= configured threshold (default `3%`).
- Polling auth noise:
  - poll 401 rate <= configured threshold (default `2%`).
- No-loop guarantee:
  - no-loop stress gate passes with configured failure budget.
- Adversarial quality:
  - strict adversarial suite passes 100% for configured minimum case count.

## 3) Full Track SLOs

Full track includes all Core SLOs plus:
- Browser runtime:
  - strict browser smoke passes (no skip).
- Image backend:
  - backend reachable and not degraded in strict readiness path.
- Strict verify:
  - `verify_full` strict passes on target host profile.
- Long soak:
  - agreed soak duration completes with thresholds green.

## 4) Operational Metrics (Runtime)

Primary metrics:
- `wrong_route_rate`
- `safety_fallback_rate`
- `poll_401_rate`
- `ambiguous_route_rate`
- `low_confidence_route_rate`

Primary source:
- `/system/metrics` and strict gate outputs (`hard_contract_check`, `soak_gate`, `no_loop_stress_check`).

## 5) Release Gate Policy

GO requires:
1. All required SLOs for selected track are green.
2. Release evidence artifacts archived.
3. No blocker severity issues open for selected track.

NO-GO if any required SLO is red.

## 6) Evidence Bundle (Required)

- strict verify output
- hard-contract output
- no-loop stress output
- runtime metrics snapshot
- release board snapshot
