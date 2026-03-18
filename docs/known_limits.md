# AEGIS Known Limits

Date: 2026-03-11

This file is customer-facing and should stay explicit.

## Product Model

- Default delivery is single-user local deployment.
- Multi-tenant cloud isolation is out of scope for the base package.

## Runtime / Reliability

- LLM outputs are probabilistic; contract gates reduce risk but do not guarantee universal correctness.
- Full strict reliability depends on host dependencies:
  - reachable image backend
  - working browser runtime for strict smoke
- Web retrieval quality depends on external provider availability.

## Security Model

- App-level controls are included, but host hardening remains operator responsibility.
- Default package assumes trusted local machine usage with strong API keys.
- Admin actions require `ADMIN_API_KEY` (no fallback to `AEGIS_API_KEY`).

## Performance

- Model latency and memory usage depend on local hardware and model size.
- Long-horizon agent runs are bounded but still sensitive to host resource pressure.

## Support Boundaries

- Core support target: chat + files/project tools + web retrieval on local host.
- Full support target: core + image/browser strict dependencies, only when host prerequisites are met.
