# AEGIS Core Hole Scan

Date: 2026-03-31

This is the current honest gap list after the architecture repass.

## Closed Core Areas

These areas are not holes anymore:

- semantic act classification
- source-policy-aware routing
- local vs Groq model routing
- durable memory across sessions
- comp snapshot in prompt/runtime context
- quantitative route signal
- crypto adaptive policy and gating
- model competition metrics

## Confirmed Remaining Holes

### 1. Notifications Delivery Depth

Files:
- `app/api/notifications.py`
- `app/services/email_service.py`

Status:
- router health is now covered in the host E2E path
- actual email delivery remains outside the strict proof chain

Impact:
- low for core chat correctness
- medium if outbound email is treated as a core product feature

### 2. Extended UI Surfaces

Status:
- browser smoke covers the core UI path
- extended proofs remain optional

Still partial:
- deep project/files browser proof
- URL mode proof
- image mode proof
- upload + ingest proof from browser

Impact:
- medium for full UI confidence
- low for backend correctness

### 3. Automatic Model Promotion

Status:
- competition metrics exist
- alternative provider is tracked
- quantitative routing exists

Still partial:
- long-run automatic champion promotion/demotion logic

Impact:
- low for correctness
- medium for long-run optimization and adaptive quality

## Indirectly Covered But Not First-Class

These modules are exercised by higher-level flows but are not strong standalone proof targets:

- `app/services/http_client.py`
- `app/services/jsonl_log_utils.py`
- `app/services/web_snippets.py`
- `app/services/proxy_pool.py`
- `app/services/crypto_trade_log.py`
- `app/services/crypto_news_service.py`

This is acceptable as long as they remain support plumbing and not primary product surfaces.

## Bottom Line

The repo is not missing a core architecture layer anymore.

The remaining holes are:
- optional UI proofs
- long-run adaptive promotion logic
- notifications delivery beyond health-level coverage

That is why the architecture reads as high-confidence but not `100%`.
