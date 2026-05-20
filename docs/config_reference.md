# AEGIS Config Reference

This is the current concise env reference.

## Runtime Profile

- `AEGIS_RUNTIME_PROFILE=standard|strict`
- `AEGIS_PRODUCT_TRACK=core|full`
- `AEGIS_AUTH_MODE=on|off|local`

## Keys

- `AEGIS_API_KEY`
- `FILES_API_KEY`
- `ADMIN_API_KEY`

JWT-related:
- `AEGIS_JWT_SECRET`
- `AEGIS_JWT_ALG`
- `AEGIS_JWT_ALLOWED_SCOPES`
- `AEGIS_JWT_DEFAULT_SCOPES`

## Security Posture

- `AEGIS_CORS_ORIGINS`
- `AEGIS_HSTS_SECONDS`
- `FILES_AV_FAIL_OPEN=0`
- `AEGIS_ENABLE_SHUTDOWN_ENDPOINT=1` for local/demo only

## Database

Canonical:
- `DATABASE_URL`

Alternative split vars:
- `POSTGRES_HOST`
- `POSTGRES_DB`
- `POSTGRES_USER`
- `POSTGRES_PASSWORD`
- `POSTGRES_PORT`

Fallback mode:
- `AEGIS_DISABLE_DB=1`

## Local LLM

- `AEGIS_LLM_PROVIDER=local|groq|auto`
- `AEGIS_MODEL_PATH`
- `AEGIS_FAST_MODE=1`
- `AEGIS_LLAMA_CTX`
- `AEGIS_LLAMA_THREADS`
- `AEGIS_N_GPU_LAYERS`
- `AEGIS_LLAMA_BATCH`
- `AEGIS_MAX_NEW_TOKENS`
- `LLM_MAX_CALL_SECONDS`

## Groq / Cloud LLM

- `AEGIS_GROQ_API_KEY`
- `GROQ_API_KEY`
- `AEGIS_GROQ_MODEL`
- `AEGIS_GROQ_BASE_URL`
- `AEGIS_GROQ_TIMEOUT_SECONDS`

## Memory

Fallback memory:
- `AEGIS_MEMORY_PERSIST=0|1`
- `AEGIS_MEMORY_MAX_BACKUPS`

Durable memory:
- `AEGIS_DURABLE_MEMORY_PERSIST=0|1`
- `AEGIS_DURABLE_MEMORY_MAX_BACKUPS`
- `AEGIS_DURABLE_MEMORY_MAX_NOTES`
- `AEGIS_DURABLE_MEMORY_MAX_SUMMARY_CHARS`

## Files / Ingest

- `FILES_UPLOAD_ROOT`
- `FILES_MAX_UPLOAD_BYTES`
- `FILES_INGEST_TIMEOUT`
- `FILES_ALLOW_ROOT_PARAM=1`
- `FILES_AV_SCAN=0|1`
- `FILES_AV_TIMEOUT`
- `FILES_AV_FAIL_OPEN=0|1`

## Web Search

- `AEGIS_SEARCH_PROVIDERS`
- `AEGIS_SEARCH_TIMEOUT`
- `AEGIS_WEB_SNIPPETS_MAX_PAGES`
- `AEGIS_SEARCH_CACHE_TTL`
- `AEGIS_SEARCH_CACHE_DISK_TTL`

Optional readyz probing:
- `AEGIS_READYZ_PROBE_WEB=1`
- `AEGIS_READYZ_WEB_QUERY`
- `AEGIS_READYZ_INCLUDE_WEB_DEGRADED=1`

## Browser

- `AEGIS_BROWSER_BINARY`

## Embeddings / Retrieval

- `AEGIS_EMBED_MODEL`
- `AEGIS_DISABLE_EMBEDDINGS=1`
- `AEGIS_EMBED_BATCH_SIZE`
- `AEGIS_EMBED_HARD_TIMEOUT`
- `AEGIS_EMBED_ENCODE_TIMEOUT`
- `AEGIS_EMBED_LOCAL_ONLY=1`

## Image

- `AEGIS_IMAGE_ENDPOINT`
- `AEGIS_IMAGE_CKPT`
- `AEGIS_IMAGE_TIMEOUT`
- `AEGIS_IMAGE_PYTHON`
- `AEGIS_REQUIRE_IMAGE_TORCH_CUDA=1`
- `AEGIS_REQUIRE_NVIDIA_SMI=1`

## Crypto

- `BINANCE_EXECUTION_MODE=simulated|testnet|live`
- `BINANCE_LIVE=1`
- `BINANCE_LIVE_TRADING=1`
- `BINANCE_API_KEY`
- `BINANCE_API_SECRET`

### One-Symbol Testnet Rehearsal

- Keep `BINANCE_EXECUTION_MODE=testnet`.
- Provide `BINANCE_API_KEY` and `BINANCE_API_SECRET` for Binance testnet only.
- Keep `BINANCE_LIVE_TRADING=0` so live order placement stays disabled.
- Run one symbol and one horizon at a time; use the crypto preview first and only confirm after the risk gate is green.
- If the preview is blocked with calibration sizing guidance, use the suggested lower qty path before retrying the order.
- To include this lane inside the full release evidence bundle, set `AEGIS_RUN_CRYPTO_TESTNET_REHEARSAL=1` before running `run_full_release_evidence.sh`.
- Optional: set `AEGIS_CRYPTO_REHEARSAL_SUBMIT=1` to allow `/crypto/trade` submission when the preview remains allowed in effective testnet mode.
- Optional: set `AEGIS_SYNC_RELEASE_BOARD=1` to refresh `docs/release_board.md` from the latest full evidence bundle after `release_summary.json` is written.
- The same `AEGIS_SYNC_RELEASE_BOARD=1` flag can also be used with `run_core_release_evidence.sh`; the board sync now updates both the latest full and latest core snapshot blocks.

Example:

```bash
venv/bin/python app/scripts/crypto_testnet_rehearsal.py \
	--base-url http://127.0.0.1:8000 \
	--symbol BTCUSDT \
	--side BUY \
	--quantity 0.001 \
	--horizon-minutes 15 \
	--execution-mode testnet \
	--submit-if-allowed
```

- The script archives JSON and Markdown evidence under `artifacts/release_evidence/crypto_testnet_rehearsal/`.
- If Binance testnet credentials are missing, the preview will record the effective fallback mode instead of pretending the rehearsal was real testnet execution.
- When the rehearsal is archived under a full evidence bundle, `app.scripts.release_evidence_summary` will include it automatically.
- `python -m app.scripts.release_board_sync --print-only` shows the generated board snapshot without editing the markdown file.
- `python -m app.scripts.release_board_sync --track core --print-only` prints only the generated core snapshot block.

## Startup / Verification

- `AEGIS_START_CONTRACT_MODE=full|strict|none`
- `AEGIS_ENABLE_INPROCESS_E2E=1`
- `AEGIS_DOCTOR_TIMEOUT_SECONDS`
- `AEGIS_DOCTOR_ATTEMPTS`
- `AEGIS_LLM_WARMUP=0|1`
- `AEGIS_WEB_WARMUP=0|1`
- `AEGIS_DEMO_MODE=1`
