FALTA
Crypto/demo/analysis: faltan 3-4%
Crypto para testnet serio: faltan 10-12%
Crypto para live real con Binance: faltan 15-20%
Seguridad/auth actual del sistema: faltan 5-8%


# AegisChat

AegisChat is a local-first conversational runtime with grounded chat, project-aware retrieval, controlled web augmentation, image/OCR flows, and a crypto lab. The runtime supports `standard|strict` profiles and `core|full` product tracks.

## What Lives Here
- Conversational chat with semantic routing, session state, durable memory, and controlled tool usage.
- Grounding through local project context, web search, URL fetch, OCR/image flows, and crypto services.
- Canonical project surface under `/files/*`; legacy `/tools/*` stays deprecated and returns `410 Gone`.
- Validation layers for startup, readiness, E2E, no-loop stress, hard-contract checks, and browser smoke.

## Canonical Docs
- [Docs Index](docs/README.md)
- [Architecture Map](docs/architecture_map.md)
- [Verification Surface Map](docs/verification_surface_map.md)
- [Config Reference](docs/config_reference.md)
- [Release Board](docs/release_board.md)
- [Core Hole Scan](docs/core_hole_scan.md)
- [Known Limits](docs/known_limits.md)

----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
## Quick Start
```bash
python -m venv venv && source venv/bin/activate
pip install --upgrade pip
if [ -f requirements.txt ]; then pip install -r requirements.txt; else pip install -e .; fi
```

Ubuntu OCR deps:
```bash
sudo apt update && sudo apt install -y tesseract-ocr tesseract-ocr-spa tesseract-ocr-eng
```
----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
Local Postgres example:
```bash
docker run --name aegis-postgres -p 5432:5432 \
  -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=aegis -d postgres:15
docker start aegis-postgres
```

Minimal local start:
```bash
./start_aegis.sh
```

Generate/copy the local export block without manually copying from this README:
```bash
python -m app.scripts.readme_exports --copy
python -m app.scripts.readme_exports --write-env-file
```

Startup contract modes:
```bash
# full release-grade startup gates (default)
./start_aegis.sh --contract-mode full

# lighter local contract: skips pytest/E2E/hard-contract/browser-smoke, keeps healthz/readyz/ui-contract
./start_aegis.sh --contract-mode strict

# minimal boot: only security/host prereqs + healthz
./start_aegis.sh --contract-mode none
```

Convenience wrappers:
```bash
./start_contract_strict.sh
./start_no_contract.sh
./start_full_local.sh
```

## Local Strict+Full Runbook
These paths match the current workstation setup. If your repo lives elsewhere, adjust the `cd` paths only.

### Terminal 1: ComfyUI
```bash
cd /home/h/Documents/python/whioutoKn/models/ComfyUI
./.venv/bin/python -m pip install SQLAlchemy
./.venv/bin/python main.py --listen 127.0.0.1 --port 8188

#FIX .VEVN INSTALLATION 
# cd /home/h/Documents/whioutoKn/models/ComfyUI
# source .venv/bin/activate
# python main.py --listen 127.0.0.1 --port 8188
```

## CLEAN START
cd /home/h/Documents/python/whioutoKn
source venv/bin/activate
./start_aegis.sh

### Terminal 2: AEGIS strict+full
```bash
# Terminal B: AEGIS only
cd /home/h/Documents/python/whioutoKn
source venv/bin/activate

export AEGIS_RUNTIME_PROFILE=strict
export AEGIS_PRODUCT_TRACK=full
export AEGIS_AUTH_MODE=on
export AEGIS_START_CONTRACT_MODE=full
export AEGIS_WEB_AUTO_DEFAULT_ON=0
export AEGIS_WEB_AUTO_DEFAULT_ON=false


export AEGIS_LLM_PROVIDER=groq
export AEGIS_GROQ_API_KEY="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"
export AEGIS_GROQ_MODEL="llama-3.1-8b-instant"
export AEGIS_GROQ_BASE_URL="https://api.groq.com/openai/v1"
export AEGIS_GROQ_TIMEOUT_SECONDS=20

export AEGIS_API_KEY="aegis-demo-key-2026-strong"
export FILES_API_KEY="aegis-demo-key-2026-strong"
export ADMIN_API_KEY="aegis-demo-key-2026-strong"

export DATABASE_URL="postgresql+psycopg2://postgres:postgres@127.0.0.1:5432/aegis"
export AEGIS_IMAGE_ENDPOINT="http://127.0.0.1:8188/prompt"
export AEGIS_IMAGE_CKPT="DreamShaper_8_pruned.safetensors"
export AEGIS_IMAGE_TIMEOUT=90
export AEGIS_BROWSER_BINARY="/usr/bin/google-chrome-stable"

export AEGIS_CORS_ORIGINS="http://127.0.0.1:8000"
export FILES_AV_FAIL_OPEN=0
export AEGIS_HSTS_SECONDS=31536000

./start_aegis.sh

###############################################
IF MAYBE FAIL THEN THE START WHIT HARD CONTRACT 
cd /home/h/Documents/whioutoKn
source venv/bin/activate

python -m app.scripts.readme_exports --copy
python -m app.scripts.readme_exports --copy --contract-mode strict
python -m app.scripts.readme_exports --write-env-file --contract-mode none


./start_aegis.sh --contract-mode strict
./start_aegis.sh --contract-mode none
#################################################

----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------

### Doctor checks
```bash
cd /home/h/Documents/whioutoKn
source venv/bin/activate

# precheck
python -m app.scripts.doctor --track core --base-url http://127.0.0.1:8000

# after startup
python -m app.scripts.doctor --track full --base-url http://127.0.0.1:8000
```

### Terminal 3: release evidence / soak
Quick precheck first:
```bash
cd /home/h/Documents/whioutoKn
source venv/bin/activate
export AEGIS_API_KEY="aegis-demo-key-2026-strong"
export FILES_API_KEY="$AEGIS_API_KEY"
export AEGIS_IMAGE_ENDPOINT="http://127.0.0.1:8188/prompt"
export AEGIS_BROWSER_BINARY="/usr/bin/google-chrome-stable"

./run_full_release_evidence.sh --base-url http://127.0.0.1:8000 --precheck-only
```

If precheck is green, launch the real soak:
```bash
./run_full_release_evidence.sh --base-url http://127.0.0.1:8000 --duration-hours 72
```

Inspect the latest artifact:
```bash
ls -1dt artifacts/release_evidence/* | head -n 1
cat artifacts/release_evidence/<timestamp>/release_summary.json
cat artifacts/release_evidence/<timestamp>/soak_gate.json
```

## Operator Notes
- `./start_aegis.sh` is the preferred launcher. It runs the preflight chain and then starts uvicorn.
- `--contract-mode full|strict|none` controls how much startup verification runs before boot.
- `GET /healthz` checks process liveness.
- `GET /system/readyz` is the core runtime readiness signal.
- `GET /system/snapshot` exposes current runtime state and degradation details.
- `frontend/README.md` contains the React/TypeScript demo frontend notes.
- Detailed config belongs in [docs/config_reference.md](docs/config_reference.md).
- Detailed gate and validation coverage belongs in [docs/verification_surface_map.md](docs/verification_surface_map.md).

## Repo Map
- `ui/`: static UI assets.
- `app/api/`: HTTP surfaces for chat, files, crypto, image, system, data, and notifications.
- `app/models/` + `app/llm_client_offload.py`: prompt building, routing, and model backends.
- `app/services/`: retrieval, web search, memory/state, project services, runtime metrics, crypto services.
- `app/scripts/`: startup gates, doctor checks, E2E checks, verify flows, soak/release evidence.
- `docs/`: canonical repo documentation set.

## License
Add your license text here (MIT, Apache-2.0, proprietary, etc.).


### MODELS 

<!-- <!-- Local model

Backend: llama.cpp
Model file: ./models/wizardcoder-python-7b-v1.0.Q5_K_M.gguf
Best for:
short/local/offline answers
fallback when you want the app to keep working without cloud
simple project-context help
Limits:
slower on CPU
weaker on general conversation
more likely to echo prompt/meta if stressed
Cloud model

Backend: Groq
Model ID: whatever you set in AEGIS_GROQ_MODEL
Best for:
normal chat
harder reasoning
long prompts
code/build requests
better response quality and speed
auto mode

The app routes by difficulty.
It prefers cloud for:
code/build prompts
crypto/harder turns
repo-content questions
long or lower-confidence prompts
It keeps local for easier/simple turns when confidence is high.
Important detail:

Some answers use no LLM at all.
Example:
time lookup
capital/country fast paths
project/tool responses
crypto prediction endpoints
So not every reply will hit local or Groq.
Other models in the app are separate:

Image generation: ComfyUI, not local/Groq chat LLM
Embeddings/RAG: sentence-transformers/all-MiniLM-L6-v2
Crypto predictions: trained numeric models, not the chat LLM
How provider selection works now:

AEGIS_LLM_PROVIDER=groq

true LLM replies go to Groq
if Groq is not ready, it now fails closed
it does not silently switch to local
AEGIS_LLM_PROVIDER=local

true LLM replies go local first
if local fails and Groq is ready, current code can still fall through to Groq
AEGIS_LLM_PROVIDER=auto

router chooses local vs Groq per turn -->
 -->
