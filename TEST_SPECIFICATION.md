# Test Specification: All Modes & Functions (Excluding Image Mode)

## Overview

This document specifies comprehensive tests for all routing modes and core service functions, excluding image mode as requested.

---

## 1. MODES TO TEST

### 1.1 Mode List (9 modes)

| Mode | Description | Priority | Existing Tests |
|------|-------------|----------|----------------|
| `general` | Default fallback mode | HIGH | ✓ |
| `chat` | Standard chat mode | HIGH | ✓ |
| `code` | Code generation mode | MEDIUM | Partial |
| `web` | Web search mode | HIGH | ✓ |
| `url` | URL analysis mode | HIGH | ✓ |
| `crypto` | Crypto prediction mode | MEDIUM | ✓ |
| `project` | Project context mode | HIGH | ✓ |
| `agent` | Agent orchestration mode | MEDIUM | ✓ |
| `auto` | Auto-detection mode | MEDIUM | Partial |

### 1.2 Mode Test Matrix

```
Test Mode Routing:
├── test_mode_prefix_routing[general]
├── test_mode_prefix_routing[chat]
├── test_mode_prefix_routing[code]
├── test_mode_prefix_routing[web]
├── test_mode_prefix_routing[url]
├── test_mode_prefix_routing[crypto]
├── test_mode_prefix_routing[project]
├── test_mode_prefix_routing[agent]
├── test_mode_prefix_routing[auto]
├── test_web_mode_requires_query
├── test_url_mode_requires_valid_url
├── test_url_mode_accepts_valid_url
└── test_crypto_mode_validation
```

---

## 2. FUNCTION TESTS BY SERVICE MODULE

### 2.1 input_normalizer.py (8 functions)

| # | Function | Test Name | Priority | Status |
|---|----------|-----------|----------|--------|
| 1 | `strip_attachment_context` | test_strip_attachment_context | HIGH | ✓ Complete |
| 2 | `normalize_user_input` | test_normalize_user_input | HIGH | ✓ Complete |
| 3 | `normalize_for_routing` | test_normalize_for_routing | HIGH | ✓ Complete |
| 4 | `split_mode_prefix` | test_split_mode_prefix | HIGH | ✓ Complete |
| 5 | `looks_like_url_candidate` | test_looks_like_url_candidate | MEDIUM | ⚠ Add Tests |
| 6 | `sanitize_html` | test_sanitize_html | HIGH | ✓ Complete |
| 7 | `detect_prompt_injection` | test_detect_prompt_injection | HIGH | ✓ Complete |
| 8 | `detect_pii` | test_detect_pii | MEDIUM | ⚠ Add Tests |

#### Detailed Function Tests:

```python
# Test 5: looks_like_url_candidate
- test_looks_like_url_candidate_valid_urls
- test_looks_like_url_candidate_invalid_urls
- test_looks_like_url_candidate_ip_addresses

# Test 6: sanitize_html
test_sanitize_html_removes_script_tags
test_sanitize_html_escapes_entities
test_sanitize_html_preserves_safe_content

# Test 7: detect_prompt_injection
test_detect_prompt_injection_ignores_previous_instructions
test_detect_prompt_injection_blocks_jailbreak
test_detect_prompt_injection_allows_legitimate_questions

# Test 8: detect_pii
test_detect_pii_finds_email
test_detect_pii_finds_phone
test_detect_pii_finds_ssn
test_detect_pii_finds_credit_card
test_detect_pii_handles_empty_input
```

### 2.2 context_scorer.py (3 functions)

| # | Function | Test Name | Priority | Status |
|---|----------|-----------|----------|--------|
| 1 | `compute_freshness_score` | test_compute_freshness_score | HIGH | ✓ Complete |
| 2 | `rank_sources` | test_rank_sources | HIGH | ✓ Complete |
| 3 | `detect_conflicts` | test_detect_conflicts | MEDIUM | ⚠ Add Tests |

#### Detailed Function Tests:

```python
# Test 1: compute_freshness_score
test_freshness_score_returns_1_for_recent
test_freshness_score_returns_0_for_stale
test_freshness_score_returns_05_for_unknown
test_freshness_score_handles_invalid_input

# Test 2: rank_sources
test_rank_sources_sorts_by_score
test_rank_sources_handles_empty_list
test_rank_sources_applies_freshness_weight
test_rank_sources_prefers_web_for_facts

# Test 3: detect_conflicts
test_detect_conflicts_finds_contradiction
test_detect_conflicts_handles_no_common_keywords
test_detect_conflicts_returns_empty_for_no_conflicts
test_detect_conflicts_with_affirmative_and_negative
```

### 2.3 context_compressor.py (5 functions)

| # | Function | Test Name | Priority | Status |
|---|----------|-----------|----------|--------|
| 1 | `compress_messages` | test_compress_messages | HIGH | ✓ Complete |
| 2 | `compress_context` | test_compress_context | MEDIUM | ✓ Complete |
| 3 | `compress_sources` | test_compress_sources | MEDIUM | ⚠ Enhance |
| 4 | `truncate_for_llm` | test_truncate_for_llm | HIGH | ✓ Complete |
| 5 | `estimate_tokens` | test_estimate_tokens | LOW | ✓ Complete |

#### Detailed Function Tests:

```python
# Test 1: compress_messages
test_compress_messages_preserves_system
test_compress_messages_respects_max_tokens
test_compress_messages_work_backwards

# Test 2: compress_context
test_compress_context_limits_items
test_compress_context_truncates_long_text

# Test 3: compress_sources
test_compress_sources_limits_count
test_compress_sources_truncates_snippets

# Test 4: truncate_for_llm
test_truncate_for_llm_simple_mode
test_truncate_for_llm_smart_mode
test_truncate_for_llm_paragraph_mode
test_truncate_for_llm_handles_short_text
```

### 2.4 memory_manager.py (5 functions)

| # | Function | Test Name | Priority | Status |
|---|----------|-----------|----------|--------|
| 1 | `compute_priority_score` | test_compute_priority_score | HIGH | ✓ Complete |
| 2 | `rank_conversations_for_eviction` | test_rank_conversations_for_eviction | MEDIUM | ⚠ Add Tests |
| 3 | `find_orphan_conversations` | test_find_orphan_conversations | MEDIUM | ⚠ Add Tests |
| 4 | `cleanup_conversations` | test_cleanup_conversations | MEDIUM | ⚠ Add Tests |
| 5 | `verify_integrity` | test_verify_integrity | HIGH | ✓ Complete |

#### Detailed Function Tests:

```python
# Test 1: compute_priority_score
test_priority_recent_conversation
test_priority_older_conversation
test_priority_archived_older_than_max
test_priority_boosts_for_message_count

# Test 2: rank_conversations_for_eviction
test_eviction_ranks_by_priority
test_eviction_returns_correct_count

# Test 3: find_orphan_conversations
test_orphan_finds_idle_conversations
test_orphan_finds_archived_old

# Test 4: cleanup_conversations
test_cleanup_dry_run
test_cleanup_identifies_orphans

# Test 5: verify_integrity
test_verify_integrity_returns_true_for_valid
test_verify_integrity_returns_false_for_invalid
test_verify_integrity_detects_future_timestamp
```

---

## 3. INTEGRATION TEST CATEGORIES

### 3.1 Security Tests

```
TestInputSanitization:
├── test_html_sanitization
├── test_prompt_injection_blocked
├── test_pii_detection
└── test_long_message_truncated

TestResponseSafety:
├── test_internal_prompt_leak_prevented
└── test_trace_blob_prevention
```

### 3.2 Mode-Specific Tests

```
TestCryptoMode:
├── test_crypto_prediction
└── test_crypto_price

TestProjectMode:
├── test_project_bind_requires_active
└── test_project_files_query

TestAgentMode:
├── test_agent_step
├── test_agent_run
└── test_agent_continue
```

### 3.3 Memory/Conversation Tests

```
TestMemoryManagement:
├── test_conversation_creation
├── test_conversation_history
├── test_conversation_list
└── test_memory_encryption

TestContextScoring:
├── test_freshness_score_calculation
└── test_source_ranking
```

---

## 4. TEST EXECUTION ORDER

### 4.1 Phase 1: Unit Tests (Priority HIGH)

```bash
# Run input_normalizer tests
pytest tests/ -k "input_normalizer" -v

# Run context_scorer tests  
pytest tests/ -k "context_scorer" -v

# Run context_compressor tests
pytest tests/ -k "context_compressor" -v

# Run memory_manager tests
pytest tests/ -k "memory_manager" -v
```

### 4.2 Phase 2: Mode Routing Tests (Priority HIGH)

```bash
pytest tests/test_all_modes_comprehensive.py::TestModeRouting -v
pytest tests/test_input_normalizer_mode_contract.py -v
```

### 4.3 Phase 3: Integration Tests (Priority MEDIUM)

```bash
# Run full comprehensive test suite (excluding image)
pytest tests/test_all_modes_comprehensive.py -v
```

### 4.4 Phase 4: Full Test Run via Script

```bash
# Use existing script
./run_all_tests_except_image.sh
```

---

## 5. TEST COVERAGE TARGETS

| Category | Target | Current | Gap |
|----------|--------|---------|-----|
| Input Normalizer Functions | 8/8 | 6/8 | 2 |
| Context Scorer Functions | 3/3 | 2/3 | 1 |
| Context Compressor Functions | 5/5 | 4/5 | 1 |
| Memory Manager Functions | 5/5 | 2/5 | 3 |
| Mode Routing | 9/9 | 9/9 | 0 |
| Security Guards | 6/6 | 6/6 | 0 |
| Integration Tests | 15+ | 15+ | 0 |

---

## 6. EXPECTED OUTCOMES

### 6.1 Success Criteria

- All 9 modes route correctly (excluding image)
- All service functions pass their unit tests
- Integration tests pass without critical errors
- No test timeouts or hangs

### 6.2 Known Issues to Handle

- Potential missing mock fixtures
- Environment variable dependencies
- Async function test patterns
- Database/stateful test cleanup

---

## 7. EXECUTION COMMANDS

### 7.1 Quick Verification

```bash
# Single command to run all except image
cd /home/h/Documents/python/whioutoKn && ./run_all_tests_except_image.sh
```

### 7.2 Manual Step-by-Step

```bash
# 1. Unit tests
pytest tests/test_all_modes_comprehensive.py::TestGuardFunctions -v --tb=short

# 2. Mode routing tests  
pytest tests/test_all_modes_comprehensive.py::TestModeRouting -v --tb=short

# 3. Security tests
pytest tests/test_all_modes_comprehensive.py::TestInputSanitization -v --tb=short

# 4. All comprehensive
pytest tests/test_all_modes_comprehensive.py -v --tb=short
```

---

## 8. FILE STRUCTURE

```
tests/
├── conftest.py                              # Test fixtures and setup
├── test_all_modes_comprehensive.py              # Main comprehensive test file
├── test_input_normalizer_mode_contract.py      # Mode contract tests
├── test_e2e_flow_guards.py                # E2E guard tests
├── test_chat_output_safety.py               # Output safety tests
├── test_auth_scope_hardening.py           # Auth scope tests
├── test_crypto_runtime.py               # Crypto mode tests
├── test_crypto_trade_safety.py          # Crypto trade safety
├── test_crypto_predict_engine.py      # Crypto prediction engine
├── test_conversation_state_db.py    # Conversation state
├── test_conversation_turns.py      # Conversation turns
├── test_durable_memory.py            # Durable memory tests
├── test_chat_project_binding.py    # Project binding tests
├── test_retrieval_project_scope.py  # Project retrieval
├── test_agent_run.py             # Agent run tests
├── test_agent_step.py           # Agent step tests
├── test_agent_continue.py    # Agent continue tests
├── test_agent_eval_check.py    # Agent eval tests
├── test_api_smoke.py          # API smoke tests
├── test_redaction.py        # Redaction tests
├── test_session_context.py    # Session context tests
├── test_start_aegis_bootstrap.py  # Startup tests
├── test_start_with_preflight_defaults.py  # Preflight tests
└── run_all_tests_except_image.sh  # Runner script
```

---

## 9. ENVIRONMENT SETUP

### 9.1 Virtual Environment

```bash
cd /home/h/Documents/python/whioutoKn
python -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

### 9.2 Environment Variables

```bash
export DATABASE_URL="postgresql+psycopg2://postgres:postgres@localhost:5432/test_aegis"
export AEGIS_SEARCH_WARMUP_ON_START="0"
export AEGIS_AUTH_MODE="off"
export AEGIS_DISABLE_DB="1"
export AEGIS_DISABLE_RETRIEVAL="1"
export AEGIS_LLM_WARMUP="0"
export AEGIS_DISABLE_EMBEDDINGS="1"
export AEGIS_MEMORY_PERSIST="0"
```

---

## 10. IMPLEMENTATION STEPS

### Step 1: Add Missing Tests to TestGuardFunctions

Update `test_all_modes_comprehensive.py` with the following new test functions:

1. **test_input_normalizer_functions** - Add tests for looks_like_url_candidate and detect_pii
2. **test_context_scorer_functions** - Enhance with detect_conflicts tests
3. **test_context_compressor_functions** - Add compress_sources tests
4. **test_memory_manager_functions** - Add rank_conversations_for_eviction, find_orphan_conversations, cleanup_conversations tests

### Step 2: Run Tests

Execute the test suite to verify current coverage:

```bash
cd /home/h/Documents/python/whioutoKn
source venv/bin/activate
pytest tests/test_all_modes_comprehensive.py -v --tb=short
```

### Step 3: Fix Failures

Analyze and fix any test failures that occur.

---

## 11. SUMMARY

This specification covers:
- ✅ 9 modes to test (excluding image)
- ✅ 21 core service functions across 4 modules
- ✅ Complete test execution plan
- ✅ Expected outcomes and success criteria

Run with: `./run_all_tests_except_image.sh` or specific pytest commands above.

---

## 12. ADDITIONAL NOTES

### Crypto Mode Testing (Missing 15-20%)

Based on the original task requirements, the following crypto tests are needed:

- **Crypto/demo/analysis**: Missing 3-4%
- **Crypto para testnet serio**: Missing 10-12%
- **Crypto para live real con Binance**: Missing 15-20%
- **Seguridad/auth actual del sistema**: Missing 5-8%

### Test Architecture

```
test_all_modes_comprehensive.py structure:
├── TestModeRouting              # Mode routing tests (9 modes)
├── TestInputSanitization     # Input sanitization tests
├── TestRateLimiting       # Rate limiting tests
├── TestAuthentication    # Auth tests
├── TestResponseSafety   # Response safety tests
├── TestContextScoring   # Context scoring tests
├── TestMemoryManagement # Memory management tests
├── TestCryptoMode     # Crypto mode tests
├── TestProjectMode   # Project mode tests
├── TestAgentMode   # Agent mode tests
└── TestGuardFunctions  # Guard function tests (21 functions)
