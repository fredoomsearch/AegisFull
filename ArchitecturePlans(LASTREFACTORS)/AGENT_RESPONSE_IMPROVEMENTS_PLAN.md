# Agent Response Improvements - Implementation Plan

## Overview
This document outlines a structured plan to improve the agent response logic across three main areas:
1. Input Validation
2. Context Aggregation
3. Memory Management

---

## STAGE 1: Input Validation Improvements (Priority: HIGH)

### 1.1 Input Sanitization
**Objective**: Protect against prompt injection, XSS, and malicious content

| Task | File | Description | Risk |
|-----|------|------------|------|
| T1.1.1 | `app/services/input_normalizer.py` | Add HTML/JS sanitization (strip tags, escape entities) | HIGH |
| T1.1.2 | `app/services/input_normalizer.py` | Add prompt injection detection patterns | HIGH |
| T1.1.3 | `app/schemas.py` | Add `max_length` constraint to ChatRequest.message | MEDIUM |
| T1.1.4 | `app/api/chat.py` | Apply sanitization at entry point | HIGH |

### 1.2 Rate Limiting
**Objective**: Prevent API abuse and spam

| Task | File | Description | Risk |
|-----|------|------------|------|
| T1.2.1 | `app/api/deps.py` | Add rate limiter dependency | HIGH |
| T1.2.2 | `app/api/chat.py` | Apply rate limit to `/chat` endpoint | HIGH |
| T1.2.3 | `app/api/chat.py` | Apply rate limit to agent endpoints | HIGH |

### 1.3 PII Redaction (Optional)
**Objective**: Protect sensitive user data

| Task | File | Description | Risk |
|-----|------|------------|------|
| T1.3.1 | `app/services/input_normalizer.py` | Add PII detection (emails, phones, IDs) | MEDIUM |
| T1.3.2 | `app/services/input_normalizer.py` | Add redaction utility | MEDIUM |

---

## STAGE 2: Context Aggregation Improvements (Priority: MEDIUM)

### 2.1 Context Freshness Scoring
**Objective**: Rank context by recency and quality

| Task | File | Description | Risk |
|-----|------|------------|------|
| T2.1.1 | `app/services/context_scorer.py` (NEW) | Create freshness scoring module | MEDIUM |
| T2.1.2 | `app/api/chat.py` | Apply scores in `_build_response_context()` | MEDIUM |
| T2.1.3 | `app/services/session_state.py` | Integrate freshness into planner | MEDIUM |

### 2.2 Conflict Resolution
**Objective**: Handle local vs web evidence conflicts

| Task | File | Description | Risk |
|-----|------|------------|------|
| T2.2.1 | `app/services/context_scorer.py` | Add conflict detection logic | MEDIUM |
| T2.2.2 | `app/api/chat.py` | Implement resolution strategy (web-first for facts, local-first for code) | MEDIUM |
| T2.2.3 | `app/services/context_scorer.py` | Add evidence ranking by source quality | MEDIUM |

### 2.3 Context Compression (Optional)
**Objective**: Reduce prompt size for large contexts

| Task | File | Description | Risk |
|-----|------|------------|------|
| T2.3.1 | `app/services/context_compressor.py` (NEW) | Create compression utility | LOW |
| T2.3.2 | `app/models/llm_utils.py` | Apply before LLM calls | LOW |

---

## STAGE 3: Memory Management Improvements (Priority: HIGH)

### 3.1 Memory Encryption
**Objective**: Secure data at rest

| Task | File | Description | Risk |
|-----|------|------------|------|
| T3.1.1 | `app/memory.py` | Add encryption utility (Fernet/cryptography) | HIGH |
| T3.1.2 | `app/memory.py` | Encrypt before write, decrypt after read | HIGH |
| T3.1.3 | `app/core/config.py` | Add encryption key config | HIGH |

### 3.2 Memory Prioritization
**Objective**: Priority-based conversation retention

| Task | File | Description | Risk |
|-----|------|------------|------|
| T3.2.1 | `app/services/memory_manager.py` (NEW) | Create priority scoring | MEDIUM |
| T3.2.2 | `app/memory.py` | Implement weighted eviction | MEDIUM |
| T3.2.3 | `app/services/memory_manager.py` | Add cleanup for orphan conversations | LOW |

### 3.3 Memory Integrity Verification
**Objective**: Validate memory integrity

| Task | File | Description | Risk |
|-----|------|------------|------|
| T3.3.1 | `app/services/memory_manager.py` | Add checksum validation | LOW |
| T3.3.2 | `app/memory.py` | Verify on load | LOW |

---

## Implementation Order

```
Stage 1 (Weeks 1-2)
├── T1.1.1 → T1.1.2 → T1.1.3 → T1.1.4
├── T1.2.1 → T1.2.2 → T1.2.3
└── T1.3.1 → T1.3.2 (optional)

Stage 2 (Weeks 2-3)
├── T2.1.1 → T2.1.2 → T2.1.3
├── T2.2.1 → T2.2.2 → T2.2.3
└── T2.3.1 → T2.3.2 (optional)

Stage 3 (Weeks 3-4)
├── T3.1.1 → T3.1.2 → T3.1.3
├── T3.2.1 → T3.2.2 → T3.2.3
└── T3.3.1 → T3.3.2
```

---

## Dependencies

- **Stage 1** has no dependencies
- **Stage 2** depends on Stage 1 completion (for sanitized input)
- **Stage 3** depends on Stage 1 completion (for secure storage)

---

## Testing Strategy

Each task should include:
1. Unit tests in `tests/test_input_validation.py`
2. Unit tests in `tests/test_context_aggregation.py`
3. Unit tests in `tests/test_memory_management.py`
4. Integration tests in `tests/test_agent_response.py`

---

## Files to Create

| File | Purpose |
|------|--------|
| `app/services/context_scorer.py` | Freshness and conflict scoring |
| `app/services/context_compressor.py` | Context compression |
| `app/services/memory_manager.py` | Priority and integrity management |

---

## Files to Modify

| File | Changes |
|------|---------|
| `app/services/input_normalizer.py` | Add sanitization, PII redaction |
| `app/schemas.py` | Add max_length constraints |
| `app/api/deps.py` | Add rate limiter |
| `app/api/chat.py` | Apply all validations |
| `app/memory.py` | Add encryption, priority |
| `app/services/session_state.py` | Add freshness scoring |
| `app/core/config.py` | Add encryption key config |

---

## Configuration Additions

```bash
# Environment variables to add
AEGIS_ENCRYPTION_KEY=aes-256-gcm-key  # For memory encryption
AEGIS_RATE_LIMIT_REQUESTS=100          # Per minute
AEGIS_RATE_LIMIT_WINDOW=60             # Seconds
AEGIS_MAX_MESSAGE_LENGTH=8000         # Characters
AEGIS_CONTEXT_FRESHNESS_WEIGHT=0.3     # Weight for recency in scoring
```

---

## Backward Compatibility

All changes must maintain:
- API response format compatibility
- Existing conversation format compatibility
- Configuration-driven feature flags for gradual rollout
- Fallback to original behavior when new features disabled
