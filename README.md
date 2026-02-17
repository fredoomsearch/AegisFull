# AegisChat (local)
Setup, keys, embeddings/RAG, crypto lab, y comandos diarios para correr localmente (sin claves reales aquí).

---
## Estado rápido
- ✅ Chat + memoria, LLM local (WizardCoder gguf); fallback OpenAI opcional.
- ✅ Ingesta + embeddings (MiniLM) + retrieval para código.
- ✅ Fallback de retrieval léxico cuando FAISS/numpy no están disponibles (no bloquea ingest).
- ✅ UI de Archivos/Jobs/Logs, `/tools/tree`, `/tools/content`, panel de snapshot.
- ✅ Crypto lab (demo): predicción/trade/stats/P&L, comparación post-horizonte, admin refresh, badge de fuente de precio y pill de contexto cripto en UI.
- ⚠️ Precios/noticias siguen demo si no apuntas a feeds vivos.

---
## Quick start
```bash
# venv + deps
python -m venv venv && source venv/bin/activate
pip install --upgrade pip && pip install -r requirements.txt

# Postgres (demo)
docker run --name aegis-postgres -p 5432:5432 \
  -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=aegis -d postgres:15
docker start aegis-postgres

# Env (mismo shell que uvicorn)
export BINANCE_LIVE=1                    # prod; testnet si lo desactivas
export BINANCE_API_KEY=""                # deja vacío si no tradearás real
export BINANCE_API_SECRET=""
export DATABASE_URL="postgresql+psycopg2://postgres:postgres@127.0.0.1:5432/aegis"

export AEGIS_SEARCH_PROVIDERS=brave_html,startpage_html,qwant_html   # Brave primero; sin DDG
export AEGIS_SEARCH_TIMEOUT=8
export AEGIS_WEB_SNIPPETS_MAX_PAGES=1
export AEGIS_SEARCH_CACHE_TTL=0
export AEGIS_SEARCH_CACHE_DISK_TTL=0

export ADMIN_API_KEY="my-secret-key"
export AEGIS_API_KEY="my-secret-key"
export FILES_API_KEY="my-secret-key"

export AEGIS_EMBED_MODEL=sentence-transformers/all-MiniLM-L6-v2
export AEGIS_EMBED_CACHE_DIR=./models/embeddings
export AEGIS_EMBED_LOCAL_ONLY=1
export AEGIS_EMBED_HARD_TIMEOUT=45
export AEGIS_EMBED_ENCODE_TIMEOUT=45
export AEGIS_EMBED_BATCH_SIZE=32

uvicorn main:app --reload
```
Abre `http://127.0.0.1:8000` y pon la misma key en el prompt.

---
## Keys (auth ON por defecto)
- `AEGIS_API_KEY` – chat/tools.
- `FILES_API_KEY` – uploads/ingest/tree/content.
- `ADMIN_API_KEY` – crypto refresh, cancel-all.
Ponlas en el diálogo de keys de la UI; las peticiones reutilizan esas claves.
La UI ahora muestra estado `Auth` en el panel de estado (scope, código 401/403 y detalle corto) para depurar credenciales sin abrir DevTools.

---
## Conciencia / snapshot / contexto
- Snapshot backend: `GET /system/snapshot` devuelve raíces ingeridas recientes, jobs, estado de embeddings/retrieval/image, últimas predicciones/outcomes, stats y P&L.
- Readiness rápido: `GET /system/readyz` (checks de embeddings, retrieval e image).
- Snapshot UI: botón 🛰 en Fuentes; auto-snapshot está ON por defecto (se refresca en segundo plano tras ingest/preds) y puedes pausarlo allí mismo.
- Conciencia cripto en chat: al detectar modo cripto o símbolo, se inyecta el último signal, hit-rate y P&L del símbolo. En la UI verás:
  - Badge “Price source” (binance / coingecko / cache / demo).
  - Pill de contexto cripto: modelo, horizonte, p, px o la línea de contexto disponible.
- Si no hay datos vivos, el asistente responde en modo demo y lo indica.

---
## Ingesta + embeddings (RAG)
1) Sube ZIP en Files o `POST /files/upload-zip`, luego `POST /files/ingest`.
2) Estado/logs: `/files/ingest/status?job_id=…`, `/files/ingest/log?job_id=…`.
3) Inventario de proyecto subido: `/files/describe?path=<ruta_upload>` (resumen ES/EN + muestra de archivos).
4) Árbol/contenido: `/tools/tree?root=<abs|rel>`, `/tools/content?path=…`.
5) Embeddings: `/tools/embeddings/status?ensure_loaded=true`, `/tools/embeddings/prepare`.
Retrieval activo salvo que `AEGIS_DISABLE_RETRIEVAL=1`.
Si falta FAISS, AEGIS cae a modo léxico (ingesta y búsqueda básica siguen funcionando).
Si `AEGIS_DISABLE_DB=1`, la app usa fallback SQLite en memoria para no romper imports/startup.
Para arrances modulares puedes apagar routers con flags:
`AEGIS_ENABLE_CHAT_API`, `AEGIS_ENABLE_CRYPTO_API`, `AEGIS_ENABLE_DATA_API`,
`AEGIS_ENABLE_NOTIFICATIONS_API`, `AEGIS_ENABLE_TOOLS_API`, `AEGIS_ENABLE_SYSTEM_API`,
`AEGIS_ENABLE_ADMIN_API`, `AEGIS_ENABLE_AUTH_API`, `AEGIS_ENABLE_IMAGE_API`,
`AEGIS_ENABLE_META_API` (default `0`).

---
## E2E smoke check
Con el backend arriba:
```bash
python app/scripts/e2e_flow_check.py \
  --base-url http://127.0.0.1:8000 \
  --api-key my-secret-key \
  --files-api-key my-secret-key
```
Valida en cadena: `healthz`, `auth/token`, `chat`, `image`, `upload+ingest`, `system/snapshot+readyz`, `crypto/*`.

Si no puedes abrir puertos locales (sandbox/CI), usa modo interno:
```bash
python app/scripts/e2e_flow_check.py \
  --inprocess \
  --api-key my-secret-key \
  --files-api-key my-secret-key \
  --skip-chat
```

---
## Snapshot (auto/manual)
- Botón en Sources. ON: se refresca tras ingest y predicciones/stats/P&L (y al cargar). OFF: pausa hasta click.
- Muestra: roots de ingest, últimos jobs, estado de embeddings, predicciones/outcomes/stats/P&L.

---
## Crypto (demo si no hay feed live)
- Endpoints: `/crypto/predict`, `/crypto/ohlcv`, `/crypto/trade`, `/crypto/predictions`, `/crypto/predictions/stats`, `/crypto/pnl`, `/crypto/predictions/evaluate`, `/crypto/models/metrics`.
- Admin refresh: `POST /admin/refresh-crypto` (ADMIN key); logs en `/admin/refresh-log?path=logs/refresh_<id>.log`.
- Borrar históricos: botón en Fuentes o `DELETE /crypto/predictions` y `DELETE /crypto/trades`.
- Regla: BUY si p>0.63, SELL si p<0.37, HOLD en otro caso. Post-horizonte compara base vs actual tras H.
- Live prices: Binance con fallback CoinGecko y cache corto; badge “Price source” en UI. News sigue demo hasta apuntar a feed real.
- Contexto cripto en chat: último signal + hit-rate + P&L se inyectan en el prompt; la pill muestra ese contexto.

---
## Web search (egreso OK)
```bash
export AEGIS_SEARCH_PROVIDERS=brave_html,startpage_html,qwant_html
export AEGIS_SEARCH_TIMEOUT=8
export AEGIS_WEB_SNIPPETS_MAX_PAGES=1
export AEGIS_SEARCH_CACHE_TTL=0
export AEGIS_SEARCH_CACHE_DISK_TTL=0
```
Si no quieres desactivar cache, sube TTLs según tu preferencia.

---
## UI notes
- Modos: chat / web (`web:`) / URL (`url:https://…`) / image / crypto.
- Files tab: árbol, jobs, logs; requiere FILES key.
- Snapshot: toggle de auto-refresh; se muestra estado en la UI.
- Logs panel alterna `/admin/refresh-log` y `/files/ingest/log` según path/job_id.

---
## Security & hardening
- Scope keys (`AEGIS_API_KEY`, `FILES_API_KEY`, `ADMIN_API_KEY`); fija `AEGIS_CORS_ORIGINS`.
- Rate limits: `AEGIS_RATE_LIMIT_PER_MINUTE`, `AEGIS_RATE_LIMITS`.
- Fetch guard: HTTP/HTTPS, redes privadas bloqueadas (`TOOLS_BLOCK_NETS`), redirects limitados.
- Upload guard: `FILES_MAX_UPLOAD_BYTES`, zip-slip protection, AV opcional (clamd).
- Producción: HTTPS, no loguear secretos, usuarios DB de mínimo privilegio.

---
## KB offline versionada (nuevo)
- Esquema: `docs/kb_schema.sql` (tablas `kb_documents`, `kb_versions`, `kb_chunks`, `kb_embeddings`, `kb_topics`).
- Ingest/versionado:  
  `python -m app.scripts.kb_ingest --title "<título>" --topic "<tema>" --year 2026 --lang es --source "manual" --file data/texto.txt`  
  Marca versiones previas como no vigentes (`is_current=false`), crea versión nueva y chunks con hash.
- Embeddings: genera vectores solo para chunks `is_current=true` (filtro por topic/year/lang) y guarda IDs en FAISS/SQLite; `kb_embeddings` es metadata.
- Consulta: filtra siempre `is_current=true`; si procede, `topic`, `chunk_year`, `lang`. Si no hay resultados vigentes, responde que no hay datos actuales.

---
## Health / troubleshooting
- API: `GET /healthz`.
- Embeddings: `GET /tools/embeddings/status?ensure_loaded=true`.
- Jobs: `GET /files/ingest/jobs`.
- Cancelar todo: `POST /admin/cancel-all` (ADMIN key).
- Si el árbol de Files queda en “Loading…”: pon FILES key, refresca el root y prueba `/tools/tree` por curl.

---
## Gaps / next steps
- Sustituir noticias demo por feed real.
- CI/tests + hardening (HTTPS final, secrets, monitoreo, DB/CORS estrictos).

---
## License
Add your license text here (MIT, Apache-2.0, proprietary, etc.).
