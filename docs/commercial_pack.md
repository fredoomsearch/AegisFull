# AEGIS Commercial Pack (Draft v1)

Date: 2026-03-11

This document defines the first sellable package for AEGIS as a local, self-hosted product.

## 1) Positioning Claim

Primary claim:
- **Local AI assistant for developers (privacy-first, self-hosted).**

Operational meaning:
- Runs on customer machine/network.
- No mandatory multi-tenant cloud backend.
- Core value is evidence-first chat + project tools + web retrieval.

## 2) Product Tracks

## Core Track (recommended first sale)

Includes:
- Chat runtime (`/chat`)
- Project/files surface (`/files/*`)
- Web retrieval (`app/services/web_search.py`)
- Deterministic routing/contract checks

Does not require:
- Image backend to be reachable
- Browser runtime as a strict blocker

Target user:
- Solo developer/operator on a local workstation.

## Full Track

Includes Core + hard-required host dependencies:
- Image backend online and reachable
- Browser runtime strict validation
- Full strict host-level reliability gates

Target user:
- Demo/ops environments that require all capabilities green.

## 3) Legal and Safety Limits (Customer-Facing)

- No financial advice: crypto outputs are informational/simulated unless explicitly configured.
- No guarantee of universal correctness for all LLM inputs.
- Security responsibility is shared:
  - AEGIS provides app-level controls and runtime checks.
  - Customer must maintain host hardening, patching, and key handling.
- Optional modules may degrade independently (especially image/backend dependencies).

## 4) Packaging and Delivery Model

Initial model:
- ZIP delivery after transfer.
- Customer receives:
  - source + runtime scripts
  - env template
  - install steps
  - post-install checklist
  - doctor diagnostics command

Required operator artifacts:
- `.env` values set
- successful `doctor` output
- startup gate output archived
- `install_local.sh` log/output archived for handoff

## 5) Pricing Tiers (Starter Proposal)

## Tier A: Core Local Pack

Scope:
- Install + configure core track
- verify startup and core doctor checks
- basic handoff session

DoD:
- Core doctor = pass
- `start_aegis.sh` startup gates pass for core profile
- customer can run chat + files + web flows

## Tier B: Full Runtime Pack

Scope:
- Tier A + image backend + strict browser/runtime alignment
- strict verification and hard-contract review

DoD:
- Full doctor = pass
- strict verify run archived
- runtime status green for full profile

## Tier C: Reliability Add-on

Scope:
- Long-horizon soak and threshold tuning
- route/fallback/no-loop threshold hardening
- release evidence bundle

DoD:
- Soak profile completed with agreed thresholds
- release board marked GO for agreed track

## 6) Definition Of Done by Track

## Core Track DoD

- `/files/*` is canonical surface, `/tools/*` remains `410 Gone`.
- Adversarial suite passes configured minimum case count.
- Wrong-route/fallback/no-loop thresholds within contract.
- Core doctor passes.

## Full Track DoD

- Core DoD + strict browser smoke pass.
- Image backend healthy (`/system/readyz` with required full checks green).
- Strict verify artifact archived for target host profile.

## 7) Known Limits (Explicit)

- Full strict reliability depends on host dependencies (browser/image backend).
- LLM output remains probabilistic; safeguards reduce but do not eliminate unexpected outputs.
- Multi-user/tenant security model is not the default local single-user model.

## 8) Required Companion Docs

- [Release Board (GO / NO-GO)](./release_board.md)
- [SLO Contract](./slo_contract.md)
- [Unified Strict Closure](./full_strict_closure.md)
- [Known Limits](./known_limits.md)
- [Demo Checklist](./demo_checklist.md)
