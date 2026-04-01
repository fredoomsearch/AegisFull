# AEGIS Architecture Map

Date: 2026-03-31

This is the canonical architecture doc for the repo.

## Tree Architecture

```text
AegisChat
├── Control Plane
│   ├── start_aegis.sh
│   ├── app/scripts/start_with_preflight.py
│   ├── app/scripts/verify_full.py
│   └── app/api/system.py
├── Conversation / Comp Plane
│   ├── app/api/chat.py
│   ├── app/services/session_state.py
│   ├── app/models/llm_client.py
│   └── app/models/llm_utils.py
├── Grounding Plane
│   ├── app/api/files.py
│   ├── app/services/project_store.py
│   ├── app/services/project_manifest.py
│   ├── app/services/project_introspection.py
│   ├── app/services/retrieval_service.py
│   ├── app/services/web_search.py
│   ├── app/services/time_service.py
│   └── app/tools.py
├── Memory Plane
│   ├── app/services/session_state.py
│   ├── app/services/conversation_turns.py
│   ├── app/services/durable_memory.py
│   ├── app/memory.py
│   └── app/db/*
├── Execution Plane
│   ├── app/api/chat.py
│   ├── app/api/files.py
│   ├── app/api/image.py
│   ├── app/api/crypto.py
│   └── execute_tool / agent paths
├── Governance Plane
│   ├── app/api/system.py
│   ├── app/services/capabilities_service.py
│   ├── app/services/runtime_metrics.py
│   ├── quantitative routing in app/models/llm_client.py
│   └── adaptive crypto policy in app/api/crypto.py
└── UI Plane
    ├── ui/index.html
    ├── ui/app.js
    └── ui/styles.css
```

## Layer Contract

### 1. Control Plane

Purpose:
- start the runtime
- verify the runtime
- expose readiness and snapshot truth

Main files:
- `start_aegis.sh`
- `app/scripts/start_with_preflight.py`
- `app/scripts/verify_full.py`
- `app/api/system.py`

### 2. Conversation / Comp Plane

Purpose:
- detect the conversational act
- track subject and follow-up context
- choose source policy
- choose provider/tool route

Main files:
- `app/api/chat.py`
- `app/services/session_state.py`
- `app/models/llm_client.py`
- `app/models/llm_utils.py`

Implemented semantic contract:
- `act`
- `subject`
- `source_policy`
- `web_required`
- `allow_run`
- `override_memory`

### 3. Grounding Plane

Purpose:
- prefer local operational truth first
- use web only when needed and allowed
- avoid unsupported answers with no evidence

Main files:
- `app/api/files.py`
- `app/services/project_manifest.py`
- `app/services/project_introspection.py`
- `app/services/retrieval_service.py`
- `app/services/web_search.py`
- `app/services/time_service.py`
- `app/tools.py`

Source order:
1. local project truth
2. local runtime/helpers
3. web context
4. LLM synthesis

### 4. Memory Plane

Purpose:
- keep turn continuity
- preserve active project/focus
- carry durable user facts/preferences across sessions

Main files:
- `app/services/session_state.py`
- `app/services/conversation_turns.py`
- `app/services/durable_memory.py`
- `app/memory.py`
- `app/db/*`

### 5. Execution Plane

Purpose:
- execute bounded actions safely
- keep agent/tool use explicit and observable

Main files:
- `app/api/chat.py`
- `app/api/files.py`
- `app/api/image.py`
- `app/api/crypto.py`

Key execution paths:
- `POST /chat`
- `POST /chat/{id}/agent_step`
- `POST /chat/{id}/agent_run`
- `POST /chat/{id}/agent_continue`
- `POST /chat/{id}/execute_tool`

### 6. Governance Plane

Purpose:
- measure runtime quality
- route by quantitative signal
- expose adaptive policy
- support champion/challenger observation

Main files:
- `app/api/system.py`
- `app/services/runtime_metrics.py`
- `app/models/llm_client.py`
- `app/api/crypto.py`

Current governance features:
- readiness and snapshot
- quantitative route signal for model selection
- crypto adaptive thresholds and scope fallback
- model competition distribution metrics

### 7. UI Plane

Purpose:
- expose the runtime without hiding status
- keep mode and source behavior visible

Main files:
- `ui/index.html`
- `ui/app.js`
- `ui/styles.css`

## What Is Complete

- semantic routing is real, not just prompt text
- durable memory exists and is prompt-visible
- local vs Groq routing exists
- quantitative routing exists
- crypto adaptive policy exists
- comp snapshot exists in prompt and runtime snapshot
- release verification surfaces are strong

## What Is Still Partial

- `app/api/notifications.py` is not part of the core verification chain
- `app/api/data.py` remains diagnostic rather than a primary release gate
- extended browser proofs are available but not in the slim strict default
- model competition is measured, but automatic long-run promotion policy is still limited
