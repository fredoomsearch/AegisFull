# AEGIS Config Reference (Env Vars)

This is a curated reference for the env vars that matter most in practice.
For a “legacy vs experimental” map, see `docs/legacy_experiments.md`.

## Auth / keys
- `AEGIS_AUTH_MODE` = `on` | `off` | `local`
- `AEGIS_API_KEY` = main API keys (comma-separated allowed)
- `FILES_API_KEY` = file/ingest API keys (can reuse `AEGIS_API_KEY`)
- `ADMIN_API_KEY` = admin API keys
- `AEGIS_RUNTIME_PROFILE` = `standard` | `strict`
- `AEGIS_PRODUCT_TRACK` = `core` | `full` (default `core`)
- JWT:
  - `AEGIS_JWT_SECRET` (defaults to first token of `AEGIS_API_KEY` if unset)
  - `AEGIS_JWT_ALG` (default `HS256`)
  - `AEGIS_JWT_ALLOWED_SCOPES` (default `chat files crypto`; `admin` is blocked for self-issued tokens)
  - `AEGIS_JWT_DEFAULT_SCOPES` (optional scopes when `/auth/token` request omits scopes)

Security posture vars (recommended for strict/prod-like):
- `AEGIS_CORS_ORIGINS` (avoid `*` in strict/prod)
- `AEGIS_HSTS_SECONDS` (set `>0` behind HTTPS reverse proxy)
- `FILES_AV_FAIL_OPEN=0` (fail-closed upload scanning)

## Startup gates
- `AEGIS_ENABLE_INPROCESS_E2E` = `1` to enable in-process E2E (opt-in)
- Full evidence doctor stability knobs:
  - `AEGIS_DOCTOR_TIMEOUT_SECONDS` (default `20`)
  - `AEGIS_DOCTOR_ATTEMPTS` (default `2`)
- Browser smoke:
  - `./start_aegis.sh --strict-browser-smoke` to force strict browser gating
  - default strict behavior is track-aware:
    - `strict+full` => blocking
    - `strict+core`/`standard` => best-effort
- Shutdown endpoint (local demo only):
  - `AEGIS_ENABLE_SHUTDOWN_ENDPOINT=1` enables `POST /system/shutdown`

## Projects / files / ingest
- `FILES_UPLOAD_ROOT` (default `data/uploads`)
- `FILES_MAX_UPLOAD_BYTES` (default 50MB)
- `FILES_INGEST_TIMEOUT` (seconds; ingest job timeout)
- AV scan:
  - `FILES_AV_SCAN` = `0/1`
  - `FILES_AV_TIMEOUT` (seconds)
  - `FILES_AV_FAIL_OPEN` = `0/1` (dev default is fail-open)
- `FILES_ALLOW_ROOT_PARAM` = `1` to allow `root=` query (workspace mode)

Database:
- `DATABASE_URL` (canonical)
- or `POSTGRES_HOST`, `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_PORT`
- `AEGIS_DISABLE_DB=1` for DB-less local mode

## Web search (canonical: `app/services/web_search.py`)
- `AEGIS_SEARCH_PROVIDERS` (comma list) e.g. `brave_html,startpage_html,qwant_html`
- `AEGIS_SEARCH_TIMEOUT` (seconds)
- `AEGIS_WEB_SNIPPETS_MAX_PAGES` (default small)
- `AEGIS_SEARCH_CACHE_TTL` (in-memory TTL seconds, 0 disables)
- `AEGIS_SEARCH_CACHE_DISK_TTL` (disk TTL seconds, 0 disables)
- Readyz probing (optional):
  - `AEGIS_READYZ_PROBE_WEB=1`
  - `AEGIS_READYZ_WEB_QUERY="python fastapi"`
  - `AEGIS_READYZ_INCLUDE_WEB_DEGRADED=1` (include web in degraded reasons)

Browser runtime (for browser-smoke and strict profile):
- `AEGIS_BROWSER_BINARY` (absolute path to chrome/chromium/brave binary)

## Local LLM (llama.cpp GGUF)
- `AEGIS_MODEL_PATH` (GGUF path)
- `AEGIS_FAST_MODE=1` to reduce default ctx/threads/batch
- `AEGIS_LLAMA_CTX` (context length)
- `AEGIS_LLAMA_THREADS` (CPU threads)
- `AEGIS_N_GPU_LAYERS` (GPU layers)
- `AEGIS_LLAMA_BATCH` (batch size)
- `AEGIS_MAX_NEW_TOKENS` (max generation tokens)
- `LLM_MAX_CALL_SECONDS` (0 disables timeouts)

## Embeddings / retrieval (RAG)
- `AEGIS_EMBED_MODEL` (default `sentence-transformers/all-MiniLM-L6-v2`)
- `AEGIS_DISABLE_EMBEDDINGS=1` to disable embedding loads
- `AEGIS_EMBED_BATCH_SIZE`
- `AEGIS_EMBED_HARD_TIMEOUT`, `AEGIS_EMBED_ENCODE_TIMEOUT`
- `AEGIS_EMBED_LOCAL_ONLY=1` (no downloads)

## Image backend
- `AEGIS_IMAGE_ENDPOINT` (ComfyUI prompt endpoint)
- `AEGIS_IMAGE_CKPT` (checkpoint filename)
- `AEGIS_IMAGE_TIMEOUT` (seconds)
- `AEGIS_IMAGE_PYTHON` (optional ComfyUI venv Python for torch CUDA diagnostics in full evidence precheck)
- `AEGIS_REQUIRE_IMAGE_TORCH_CUDA=1` (optional strict/full precheck: fail when torch CUDA is unavailable in `AEGIS_IMAGE_PYTHON`)
- `AEGIS_REQUIRE_NVIDIA_SMI=1` (optional strict/full precheck: fail when `nvidia-smi` is unavailable or reports zero GPUs)
- Runtime check endpoint: `GET /image/checkpoints` (configured/selected/available ckpt + fallback flag)

## Crypto (demo-safe defaults)
- `BINANCE_LIVE` = `1` enables live price/news fetches (read-only)
- `BINANCE_LIVE_TRADING` = `1` required to allow live orders (otherwise simulated)
- `BINANCE_API_KEY`, `BINANCE_API_SECRET`

## Misc
- `AEGIS_DEMO_MODE=1` reduces heavy warmups
- `AEGIS_LLM_WARMUP=0/1`, `AEGIS_WEB_WARMUP=0/1`
- `AEGIS_DISABLE_DB=1` for DB-less mode (memory fallback)
- Memory persistence (JSON fallback store):
  - `AEGIS_MEMORY_PERSIST=0/1` (default `1`; set `0` in tests/CI to avoid disk I/O)
- Secret redaction (best-effort, prompt/log safety):
  - `AEGIS_REDACT_SECRETS=0/1` (default `1`)
