# AegisChat (local)
Setup, keys, embeddings/RAG, crypto lab, y comandos diarios para correr localmente (sin claves reales aquí).

---
## Estado rápido
- ✅ Chat + memoria, LLM local (WizardCoder gguf); fallback OpenAI opcional.
- ✅ Ingesta + embeddings (MiniLM) + retrieval para código.
- ✅ UI de Archivos/Jobs/Logs, `/tools/tree`, `/tools/content`, panel de snapshot.
- ✅ Crypto lab (demo): predicción/trade/stats/P&L, comparación post-horizonte, admin refresh.
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

export AEGIS_SEARCH_PROVIDERS=ddgs,ddg_html,startpage_html
export AEGIS_SEARCH_TIMEOUT=6
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

---
## Ingesta + embeddings (RAG)
1) Sube ZIP en Files o `POST /files/upload-zip`, luego `POST /files/ingest`.
2) Estado/logs: `/files/ingest/status?job_id=…`, `/files/ingest/log?job_id=…`.
3) Árbol/contenido: `/tools/tree?root=<abs|rel>`, `/tools/content?path=…`.
4) Embeddings: `/tools/embeddings/status?ensure_loaded=true`, `/tools/embeddings/prepare`.
Retrieval activo salvo que `AEGIS_DISABLE_RETRIEVAL=1`.

---
## Snapshot (auto/manual)
- Botón en Sources. ON: se refresca tras ingest y predicciones/stats/P&L. OFF: pausa hasta click.
- Muestra: roots de ingest, últimos jobs, estado de embeddings, predicciones/outcomes/stats/P&L.

---
## Crypto (demo si no hay feed live)
- Endpoints: `/crypto/predict`, `/crypto/ohlcv`, `/crypto/trade`, `/crypto/predictions`, `/crypto/predictions/stats`, `/crypto/pnl`, `/crypto/predictions/evaluate`.
- Admin refresh: `POST /admin/refresh-crypto` (ADMIN key); logs en `/admin/refresh-log?path=logs/refresh_<id>.log`.
- Borrar históricos: botón en Fuentes o `DELETE /crypto/predictions` y `DELETE /crypto/trades`.
- Regla: BUY si p>0.63, SELL si p<0.37, HOLD en otro caso. Post-horizonte compara base vs actual tras H.
- Live prices/news: demo si no apuntas a feed real (p.ej. Binance/CoinGecko + RSS). Restart tras configurar.

---
## Web search (egreso OK)
```bash
export AEGIS_SEARCH_PROVIDERS=ddgs,ddg_html,startpage_html
export AEGIS_SEARCH_TIMEOUT=6
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
- Precio vivo robusto (fallback CoinGecko u otro si falla Binance).
- CI/tests + hardening (HTTPS final, secrets, monitoreo, DB/CORS estrictos).

---
## License
Add your license text here (MIT, Apache-2.0, proprietary, etc.).
