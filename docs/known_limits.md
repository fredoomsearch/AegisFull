# AEGIS Known Limits

Date: 2026-03-31

## Product Scope

- The default delivery model is still local-first.
- Multi-tenant cloud isolation is not the base product assumption.

## Reliability

- LLM output remains probabilistic.
- The verification stack reduces risk; it does not eliminate all failure modes.
- Full strict confidence still depends on host capabilities such as browser runtime and image backend availability.

## Evidence

- Local project truth is stronger than web context for internal facts.
- Web providers can degrade or rate-limit.
- If evidence is weak, the correct behavior is bounded uncertainty, not invention.

## Execution

- The system supports bounded execution and approval-aware tool use.
- It is not designed for uncontrolled autonomous action.

## Quantitative Governance

- Quantitative routing and crypto gating exist.
- Automatic long-run model promotion is still limited; current competition metrics are mainly for observation and controlled policy use.
