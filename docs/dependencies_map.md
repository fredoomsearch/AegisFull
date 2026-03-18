# AEGIS Dependencies Map (Library -> Implementation)

This map documents where key libraries are implemented in code and whether they are core or optional.
For the complete import-level list (including standard library and internal `app.*` modules), see [modules_inventory.md](./modules_inventory.md).

## Dependencies Session (by architecture plane)

- API/runtime plane: `fastapi`, `uvicorn`, `pydantic`, `requests`
- Auth/security plane: `PyJWT`, `python-multipart`, ClamAV binaries
- Persistence plane: `sqlalchemy`, `psycopg2-binary`
- LLM/retrieval plane: `llama-cpp-python`, `sentence-transformers`, `faiss-cpu`
- Image/OCR plane: `Pillow`, `pytesseract`, ComfyUI backend
- Browser/web validation plane: `selenium`, `chromedriver-autoinstaller`, browser binary
- Optional analytics plane: `pandas`, `pandas_ta`, `scikit-learn`, `vaderSentiment`

## Core API / Runtime

| Library | Purpose | Implemented in | Required |
|---|---|---|---|
| `fastapi` | API framework + routing | `main.py`, `app/api/*.py`, `app/core/admin.py` | Yes |
| `uvicorn` | ASGI server runtime | launcher/scripts (`start_aegis.sh`, uvicorn command) | Yes |
| `pydantic` / `pydantic_settings` | schemas + env config | `app/schemas.py`, `app/core/config.py`, API request models | Yes |
| `requests` | HTTP clients (web/image/health checks/providers) | `app/services/web_search.py`, `app/tools.py`, `app/api/image.py`, scripts | Yes |
| `beautifulsoup4` (`bs4`) | HTML parsing for web search/fetch sanitization | `app/services/web_search.py`, `app/tools.py` | Yes |

## Auth / Security

| Library | Purpose | Implemented in | Required |
|---|---|---|---|
| `PyJWT` (`jwt`) | access/refresh token signing + verification | `app/api/auth.py`, `app/api/deps.py` | Yes (when auth mode is `on`) |
| `python-multipart` | file/form payload parsing | file/image/chat endpoints | Yes for upload/image endpoints |
| ClamAV binaries (`clamscan`/`clamdscan`) | AV scanning of uploads | `app/services/antivirus_service.py`, `app/api/files.py` | Optional at host level (service degrades if missing) |

## Database / Persistence

| Library | Purpose | Implemented in | Required |
|---|---|---|---|
| `sqlalchemy` | ORM + engine/session + CRUD | `app/db/base.py`, `app/db/models.py`, `app/db/crud_*.py`, `app/services/news_store.py` | Yes for DB mode |
| `psycopg2-binary` | PostgreSQL driver | used by `DATABASE_URL` in `app/db/base.py` | Yes for PostgreSQL mode |

Notes:
- Canonical DB backend is PostgreSQL.
- `AEGIS_DISABLE_DB=1` enables memory/fallback paths for local demos/tests.

## LLM / Retrieval

| Library | Purpose | Implemented in | Required |
|---|---|---|---|
| `llama-cpp-python` | local GGUF inference backend | `app/llm_client_offload.py` | Required for local LLM |
| `sentence-transformers` | embedding model inference | `app/services/embedding_service.py` | Optional (hash fallback exists) |
| `faiss-cpu` | vector index for retrieval | `app/services/retrieval_service.py` | Optional (lexical fallback exists) |
| `numpy` | retrieval/math + meta analytics | `app/services/retrieval_service.py`, `app/core/meta.py` | Optional in some features |

## Image / OCR

| Library | Purpose | Implemented in | Required |
|---|---|---|---|
| `Pillow` | image processing + placeholder image ops | `app/vision_client.py`, `app/services/ocr_service.py` | Optional (required for OCR/image helpers) |
| `pytesseract` | OCR extraction | `app/vision_client.py`, `app/services/ocr_service.py` | Optional (OCR disabled if missing) |
| ComfyUI HTTP backend | image generation backend | `app/api/image.py` via `AEGIS_IMAGE_ENDPOINT` | Host dependency for real image generation |

## Web / Browser Runtime

| Library | Purpose | Implemented in | Required |
|---|---|---|---|
| `selenium` | browser smoke automation | `app/scripts/browser_smoke.py` | Optional in standard profile, required in strict gate |
| `chromedriver-autoinstaller` | driver bootstrap for smoke | `app/scripts/browser_smoke.py`, `app/tools.py` flags | Optional in standard profile |
| `duckduckgo_search` (`DDGS`) | optional provider for web search | `app/services/web_search.py` | Optional (HTTP providers fallback) |
| browser binary (Chrome/Chromium/Brave) | headless browser runtime | discovered via `app/tools.py::find_brave_binary` | Host dependency for strict browser gate |

## Crypto / Analytics (optional surfaces)

| Library | Purpose | Implemented in | Required |
|---|---|---|---|
| `pandas` | OHLCV shaping + analytics | `app/services/crypto_service.py`, `app/core/meta.py`, scripts | Optional for crypto/meta |
| `pandas_ta` | technical indicators (meta analytics) | `app/core/meta.py` | Optional |
| `scikit-learn` | calibration/metrics in meta analytics + training scripts | `app/core/meta.py`, `app/scripts/train_models.py` | Optional (meta API off by default) |
| `vaderSentiment` | sentiment scoring for meta/news analytics | `app/core/meta.py` | Optional |

## Operational Scripts Dependencies

| Script | Main dependencies |
|---|---|
| `app/scripts/start_with_preflight.py` | `requests`, `pytest`, subprocess tooling |
| `app/scripts/verify_full.py` | `requests`, subprocess tooling |
| `app/scripts/no_loop_stress_check.py` | `requests` |
| `app/scripts/e2e_flow_check.py` | `requests` |
| `app/scripts/production_profile_check.py` | stdlib + `app.tools` browser detection |
| `app/scripts/browser_smoke.py` | `selenium`, `chromedriver_autoinstaller`, browser binary |

## Canonical vs Optional Rule

- Canonical architecture does not require every optional dependency to be installed.
- Optional dependencies are acceptable when the runtime:
  - degrades explicitly (`readyz.status=degraded/fallback-only`), and
  - does not fake success.
- Strict runtime/profile requires host capabilities (browser runtime + image backend reachable) in addition to code correctness.
