# AEGIS Module Inventory (Canonical Architecture)

Generated from real imports on: 2026-03-08 06:51 UTC

Scope: `main.py`, `app/api/*.py`, `app/services/*.py`, `app/db/*.py`, `app/models/*.py`, `app/core/*.py`.

This is the complete module-level dependency inventory for the architecture layer, with purpose and usage locations.

## Standard Library Modules

| Module | Why it is used | Used in files | Sample locations |
|---|---|---:|---|
| `__future__` | Forward-compatibility imports (annotations and typing behavior). | 56 | `app/api/__init__.py, app/api/auth.py, app/api/chat.py, app/api/crypto.py, +52 more` |
| `asyncio` | Async coordination for non-blocking endpoint flows and retries. | 1 | `app/api/chat.py` |
| `collections` | Counters/defaultdict/deques for in-memory state and stats. | 7 | `app/services/crypto_prediction_log.py, app/services/crypto_trade_log.py, app/services/health_state.py, app/services/project_introspection.py, +3 more` |
| `concurrent.futures` | ThreadPool execution for blocking/offloaded tasks. | 1 | `app/api/chat.py` |
| `contextlib` | Context managers for resource-safe lifecycle handling. | 4 | `app/db/base.py, app/services/proxy_pool.py, app/services/web_snippets.py, main.py` |
| `dataclasses` | Lightweight structured runtime models. | 1 | `app/services/job_manager.py` |
| `datetime` | Timestamps, UTC handling, and time windows. | 12 | `app/api/chat.py, app/core/meta.py, app/db/crud_conversation.py, app/db/kb_news.py, +8 more` |
| `email.message` | SMTP message construction. | 1 | `app/services/email_service.py` |
| `functools` | Helper decorators/utilities. | 1 | `app/core/meta.py` |
| `hashlib` | Stable hashing for keys, IDs, and dedupe. | 5 | `app/api/crypto.py, app/services/embedding_service.py, app/services/news_store.py, app/services/retrieval_service.py, +1 more` |
| `hmac` | Signed request support for exchange APIs. | 1 | `app/api/crypto.py` |
| `html` | Escaping/unescaping text from web sources. | 1 | `app/services/web_search.py` |
| `importlib` | Dynamic feature-router loading. | 1 | `app/api/__init__.py` |
| `io` | Bytes/text stream handling for files/images. | 2 | `app/api/files.py, app/services/ocr_service.py` |
| `json` | Serialization for API payloads, state files, and logs. | 16 | `app/api/chat.py, app/api/image.py, app/core/meta.py, app/db/crud_conversation.py, +12 more` |
| `logging` | Structured runtime and operational logging. | 23 | `app/api/__init__.py, app/api/chat.py, app/api/crypto.py, app/api/files.py, +19 more` |
| `math` | Numeric helpers in scoring/prediction logic. | 2 | `app/api/crypto.py, app/services/crypto_service_legacy.py` |
| `os` | Environment configuration and process/runtime controls. | 38 | `app/api/__init__.py, app/api/auth.py, app/api/chat.py, app/api/crypto.py, +34 more` |
| `pathlib` | Safe filesystem path handling. | 25 | `app/api/chat.py, app/api/files.py, app/api/image.py, app/api/system.py, +21 more` |
| `random` | Non-critical randomized seeds/sampling. | 1 | `app/api/crypto.py` |
| `re` | Pattern matching for parsing, routing hints, and sanitization. | 13 | `app/api/chat.py, app/api/crypto.py, app/api/files.py, app/models/llm_utils.py, +9 more` |
| `shutil` | Filesystem operations and binary discovery. | 5 | `app/api/chat.py, app/api/files.py, app/services/antivirus_service.py, app/services/capabilities_service.py, +1 more` |
| `signal` | Process signal handling (shutdown/kill flows). | 1 | `app/api/system.py` |
| `smtplib` | SMTP transport for email notifications. | 1 | `app/services/email_service.py` |
| `sqlite3` | Lightweight local state/cache persistence. | 1 | `app/services/search_state.py` |
| `subprocess` | External command execution (git, checks, scripts). | 4 | `app/api/files.py, app/core/admin.py, app/services/antivirus_service.py, main.py` |
| `sys` | Interpreter/runtime introspection. | 2 | `app/api/files.py, app/core/admin.py` |
| `threading` | Background workers and thread-safe locks. | 16 | `app/api/crypto.py, app/api/system.py, app/core/admin.py, app/services/antivirus_service.py, +12 more` |
| `time` | Durations, timeouts, and epoch timestamps. | 28 | `app/api/auth.py, app/api/chat.py, app/api/crypto.py, app/api/data.py, +24 more` |
| `traceback` | Debug trace capture in exception paths. | 1 | `app/api/chat.py` |
| `typing` | Type hints for architecture contracts. | 50 | `app/api/auth.py, app/api/chat.py, app/api/crypto.py, app/api/deps.py, +46 more` |
| `urllib.parse` | URL parsing/normalization and query building. | 8 | `app/api/chat.py, app/api/crypto.py, app/api/files.py, app/services/conversation_services.py, +4 more` |
| `urllib.robotparser` | robots.txt policy checks for snippet fetches. | 1 | `app/services/web_snippets.py` |
| `uuid` | Stable unique IDs for jobs/turns/resources. | 9 | `app/api/chat.py, app/api/files.py, app/api/image.py, app/core/admin.py, +5 more` |
| `xml.etree.ElementTree` | Lightweight XML feed parsing. | 1 | `app/services/crypto_news_service.py` |
| `zipfile` | ZIP upload extraction in file ingestion. | 1 | `app/api/files.py` |
| `zoneinfo` | Timezone conversion for time-answer helpers. | 1 | `app/services/time_service.py` |

## Third-Party Modules

| Module | Why it is used | Used in files | Sample locations |
|---|---|---:|---|
| `PIL` | Image generation/fallback/OCR image handling. | 2 | `app/api/image.py, app/services/ocr_service.py` |
| `bs4` | HTML parsing for web search/snippets. | 1 | `app/services/web_search.py` |
| `duckduckgo_search` | Optional DDGS provider adapter. | 1 | `app/services/web_search.py` |
| `faiss` | Vector index backend for retrieval. | 1 | `app/services/retrieval_service.py` |
| `fastapi` | HTTP API framework and request/response models. | 14 | `app/api/__init__.py, app/api/auth.py, app/api/chat.py, app/api/crypto.py, +10 more` |
| `fastapi.middleware.cors` | CORS policy middleware. | 1 | `main.py` |
| `fastapi.responses` | Typed HTTP responses and static-file responses. | 1 | `main.py` |
| `fastapi.staticfiles` | Static UI/data asset serving. | 1 | `main.py` |
| `jinja2` | HTML email template rendering. | 1 | `app/services/email_service.py` |
| `joblib` | Model artifact loading/cache helpers. | 1 | `app/core/meta.py` |
| `jwt` | JWT signing/verification (PyJWT). | 2 | `app/api/auth.py, app/api/deps.py` |
| `numpy` | Vector/numeric utilities in retrieval/analytics. | 2 | `app/core/meta.py, app/services/retrieval_service.py` |
| `openai` | Optional remote model client integration. | 1 | `app/models/llm_client.py` |
| `pandas` | Dataframe processing in crypto/meta flows. | 3 | `app/api/crypto.py, app/core/meta.py, app/services/crypto_service.py` |
| `pandas_ta` | Technical analysis indicators. | 1 | `app/core/meta.py` |
| `pdf2image` | PDF page rendering for OCR. | 1 | `app/services/ocr_service.py` |
| `psutil` | System resource telemetry for snapshot. | 1 | `app/api/system.py` |
| `pydantic` | Request/response data validation models. | 8 | `app/api/auth.py, app/api/chat.py, app/api/crypto.py, app/api/files.py, +4 more` |
| `pydantic_settings` | Settings management from environment. | 1 | `app/core/config.py` |
| `pytesseract` | OCR text extraction from images. | 1 | `app/services/ocr_service.py` |
| `pytz` | Timezone compatibility helpers. | 1 | `app/services/time_service.py` |
| `requests` | HTTP client for web/image/crypto providers. | 10 | `app/api/crypto.py, app/api/image.py, app/core/meta.py, app/services/conversation_services.py, +6 more` |
| `requests.adapters` | HTTP retry adapter wiring. | 1 | `app/core/meta.py` |
| `sentence_transformers` | Embedding model runtime. | 1 | `app/services/embedding_service.py` |
| `sklearn.metrics` | Model/eval metrics utilities. | 1 | `app/core/meta.py` |
| `sqlalchemy` | ORM/queries/sessions for PostgreSQL persistence. | 6 | `app/api/data.py, app/db/base.py, app/db/crud_conversation.py, app/db/kb_news.py, +2 more` |
| `sqlalchemy.engine` | Engine typing/hooks. | 1 | `app/db/base.py` |
| `sqlalchemy.engine.url` | Database URL parsing helpers. | 1 | `app/db/base.py` |
| `sqlalchemy.exc` | DB exception handling. | 3 | `app/db/crud.py, app/db/crud_conversation.py, app/db/crud_summary.py` |
| `sqlalchemy.orm` | Session and mapping APIs. | 10 | `app/api/chat.py, app/api/data.py, app/db/base.py, app/db/crud.py, +6 more` |
| `sqlalchemy.pool` | Engine pool tuning. | 1 | `app/db/base.py` |
| `torch` | Runtime checks for GPU/model capabilities. | 1 | `app/api/system.py` |
| `urllib3.util.retry` | Retry policy model for resilient requests. | 1 | `app/core/meta.py` |
| `vaderSentiment.vaderSentiment` | Sentiment scoring helper. | 1 | `app/core/meta.py` |

## Internal AEGIS Modules

| Module | Why it is used | Used in files | Sample locations |
|---|---|---:|---|
| `app` | Top-level AEGIS package namespace used by internal imports. | 1 | `app/models/llm_client.py` |
| `app.api` | Canonical API router package mounted by the main app entrypoint. | 1 | `main.py` |
| `app.api.crypto` | Crypto/market HTTP surface used by chat and standalone API calls. | 1 | `app/api/chat.py` |
| `app.api.deps` | Shared auth/API-key/JWT dependency guards for all protected routes. | 10 | `app/api/auth.py, app/api/chat.py, app/api/crypto.py, app/api/data.py, +6 more` |
| `app.api.files` | Canonical project/files endpoints (`/files/*`) for ingest and inspection. | 1 | `main.py` |
| `app.api.image` | Image generation and analysis API surface with backend/fallback handling. | 1 | `app/services/capabilities_service.py` |
| `app.core` | Core shared package for cross-cutting utilities and types. | 1 | `app/api/crypto.py` |
| `app.core.config` | Environment settings loader and runtime configuration source. | 1 | `app/db/base.py` |
| `app.core.meta` | Optional analytics/meta feature engineering and model helper utilities. | 1 | `app/services/crypto_service.py` |
| `app.core.types` | Shared typed contracts (for example `WebSearchResult`) across services. | 1 | `app/services/web_search.py` |
| `app.db` | Database package namespace for CRUD and persistence helpers. | 4 | `app/api/chat.py, app/db/crud.py, app/db/crud_conversation.py, app/db/crud_summary.py` |
| `app.db.base` | SQLAlchemy engine/session bootstrap and DB lifecycle wiring. | 4 | `app/api/chat.py, app/db/deps.py, app/services/news_store.py, main.py` |
| `app.db.deps` | FastAPI dependency helpers that provide DB sessions per request. | 2 | `app/api/chat.py, app/api/data.py` |
| `app.db.kb_news` | News persistence model/access layer for knowledge-base style records. | 1 | `app/services/news_store.py` |
| `app.db.models` | Canonical SQLAlchemy models for conversations, turns, and related entities. | 2 | `app/db/base.py, main.py` |
| `app.llm_client_offload` | Local GGUF/llama.cpp runtime loader used for on-device inference. | 3 | `app/models/llm_client.py, app/services/capabilities_service.py, main.py` |
| `app.memory` | JSON/file fallback memory store for conversation state continuity. | 2 | `app/api/chat.py, app/models/llm_utils.py` |
| `app.models.llm_client` | Model invocation router used by chat generation paths. | 1 | `app/api/chat.py` |
| `app.models.llm_utils` | Prompt building, routing heuristics, and output safety helpers. | 1 | `app/api/chat.py` |
| `app.models.ml.ensemble` | Ensemble prediction logic used by crypto forecasting flows. | 1 | `app/services/crypto_service.py` |
| `app.models.ml.models` | ML data structures and model wrappers for crypto features. | 1 | `app/api/crypto.py` |
| `app.schemas` | Pydantic request/response schemas shared across API surfaces. | 2 | `app/api/chat.py, app/services/crypto_service.py` |
| `app.scripts.agent_eval_check` | Agent quality/eval harness reused by runtime validation endpoints. | 1 | `app/api/system.py` |
| `app.services` | Services package namespace for business/runtime logic modules. | 6 | `app/api/chat.py, app/api/system.py, app/services/capabilities_service.py, app/services/proxy_pool.py, +2 more` |
| `app.services.antivirus_service` | ClamAV integration for upload scanning and AV status reporting. | 3 | `app/api/chat.py, app/api/files.py, app/services/capabilities_service.py` |
| `app.services.capabilities_service` | Runtime capability summary builder powering ready/snapshot views. | 1 | `app/api/system.py` |
| `app.services.conversation_events` | Persistence/retrieval of per-conversation event timelines. | 1 | `app/api/chat.py` |
| `app.services.conversation_turns` | Persistence/retrieval of turn items and conversation traces. | 1 | `app/api/chat.py` |
| `app.services.crypto_ml_service` | Crypto ML feature prep/inference helper service. | 1 | `app/services/crypto_service_legacy.py` |
| `app.services.crypto_news_service` | Crypto news fetching/normalization from external providers. | 2 | `app/api/crypto.py, app/services/crypto_service_legacy.py` |
| `app.services.crypto_prediction_log` | Append/read prediction outputs for observability and UI. | 3 | `app/api/chat.py, app/api/crypto.py, app/services/crypto_service_legacy.py` |
| `app.services.crypto_service_legacy` | Legacy crypto service compatibility shim and fallback behavior. | 1 | `app/services/crypto_service.py` |
| `app.services.crypto_trade_log` | Trade action logging for simulated/live crypto operations. | 2 | `app/api/chat.py, app/api/crypto.py` |
| `app.services.email_service` | Email notification rendering and SMTP delivery service. | 1 | `app/api/notifications.py` |
| `app.services.embedding_service` | Embedding model lifecycle (load/encode/dimension checks). | 1 | `app/services/retrieval_service.py` |
| `app.services.job_manager` | In-process async job registry/execution state tracking. | 2 | `app/api/chat.py, app/api/files.py` |
| `app.services.news_store` | Database-backed storage/retrieval helpers for news entries. | 1 | `app/api/crypto.py` |
| `app.services.project_introspection` | Project scan/introspection for symbols, entrypoints, configs. | 3 | `app/api/chat.py, app/api/files.py, app/services/project_manifest.py` |
| `app.services.project_manifest` | Manifest generation and project architecture summary extraction. | 2 | `app/api/chat.py, app/api/files.py` |
| `app.services.project_store` | Project registration, root mapping, and active-project lookup. | 3 | `app/api/chat.py, app/api/files.py, app/services/capabilities_service.py` |
| `app.services.redaction` | Secret/token redaction filters for safe logging and responses. | 1 | `app/models/llm_utils.py` |
| `app.services.retrieval_service` | FAISS index loading/search with project-scoped retrieval. | 3 | `app/api/chat.py, app/api/files.py, app/models/llm_utils.py` |
| `app.services.search_state` | Provider cooldown/cache/rate state used by web search flows. | 3 | `app/services/proxy_pool.py, app/services/web_search.py, app/services/web_snippets.py` |
| `app.services.session_state` | Conversation session/planner memory state for deterministic continuation. | 3 | `app/api/chat.py, app/db/crud_conversation.py, app/models/llm_utils.py` |
| `app.services.time_service` | Localized time-question helper (timezone-aware answer path). | 1 | `app/api/chat.py` |
| `app.services.upload_inspector` | Upload payload inspection/normalization before ingest pipeline. | 2 | `app/api/chat.py, app/api/files.py` |
| `app.services.validation_state` | Startup/verify gate result persistence and status lookup. | 1 | `app/api/system.py` |
| `app.services.web_search` | Multi-provider web search orchestration with cache/cooldown metadata. | 3 | `app/api/chat.py, app/services/capabilities_service.py, main.py` |
| `app.services.web_snippets` | Snippet/page fetch sanitization for evidence enrichment. | 1 | `app/api/chat.py` |
| `app.tools` | Legacy/compat utility surface for web fetch/search helper functions. | 4 | `app/api/chat.py, app/models/llm_client.py, app/services/capabilities_service.py, app/services/web_snippets.py` |
| `app.vision_client` | Vision/OCR helper client used by chat and image APIs. | 2 | `app/api/chat.py, app/api/image.py` |

