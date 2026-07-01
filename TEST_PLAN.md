# Comprehensive Test Plan: All Modes & Functions (Excluding Image Mode)

## Overview

This document specifies a comprehensive test plan for all routing modes and core service functions in AegisChat, excluding image mode. The plan is organized by test architecture, phases, and execution scripts.

---

## 1. Test Architecture & Infrastructure

### 1.1 Test Folder Structure

```
tests/
├── conftest.py                              # Test fixtures and setup
├── test_all_modes_comprehensive.py          # Main comprehensive test file
├── test_input_normalizer_mode_contract.py   # Mode contract tests
├── test_e2e_flow_guards.py                  # E2E guard tests
├── test_chat_output_safety.py                # Output safety tests
├── test_auth_scope_hardening.py             # Auth scope tests
├── test_admin_scope_hardening.py              # Admin scope tests
├── test_crypto_runtime.py                   # Crypto mode tests
├── test_crypto_trade_safety.py              # Crypto trade safety
├── test_crypto_predict_engine.py             # Crypto prediction engine
├── test_conversation_state_db.py               # Conversation state
├── test_conversation_turns.py                # Conversation turns
├── test_durable_memory.py                    # Durable memory tests
├── test_chat_project_binding.py              # Project binding tests
├── test_retrieval_project_scope.py          # Project retrieval
├── test_agent_run.py                       # Agent run tests
├── test_agent_step.py                       # Agent step tests
├── test_agent_continue.py                  # Agent continue tests
├── test_agent_eval_check.py                 # Agent eval tests
├── test_api_smoke.py                       # API smoke tests
├── test_redaction.py                       # Redaction tests
├── test_session_context.py                   # Session context tests
└── run_all_tests_except_image.sh            # Runner script
```

### 1.2 Test Execution Scripts

```bash
# Main runner script
./run_all_tests_except_image.sh

# Alternative execution
cd /home/h/Documents/python/whioutoKn
source venv/bin/activate
pytest tests/test_all_modes_comprehensive.py -v --tb=short
```

---

## 2. Test Phases

### Phase 1: Unit Tests (Priority HIGH)

#### 1.1 input_normalizer.py Functions (8/8)

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

**New Tests to Add:**

```python
# Test 5: looks_like_url_candidate
- test_looks_like_url_candidate_valid_urls
- test_looks_like_url_candidate_invalid_urls
- test_looks_like_url_candidate_ip_addresses

# Test 8: detect_pii
- test_detect_pii_finds_email
- test_detect_pii_finds_phone
- test_detect_pii_finds_ssn
- test_detect_pii_finds_credit_card
- test_detect_pii_handles_empty_input
```

#### 1.2 context_scorer.py Functions (3/3)

| # | Function | Test Name | Priority | Status |
|---|----------|-----------|----------|--------|
| 1 | `compute_freshness_score` | test_compute_freshness_score | HIGH | ✓ Complete |
| 2 | `rank_sources` | test_rank_sources | HIGH | ✓ Complete |
| 3 | `detect_conflicts` | test_detect_conflicts | MEDIUM | ⚠ Add Tests |

**New Tests to Add:**

```python
# Test 3: detect_conflicts
- test_detect_conflicts_finds_contradiction
- test_detect_conflicts_handles_no_common_keywords
- test_detect_conflicts_returns_empty_for_no_conflicts
- test_detect_conflicts_with_affirmative_and_negative
```

#### 1.3 context_compressor.py Functions (5/5)

| # | Function | Test Name | Priority | Status |
|---|----------|-----------|----------|--------|
| 1 | `compress_messages` | test_compress_messages | HIGH | ✓ Complete |
| 2 | `compress_context` | test_compress_context | MEDIUM | ✓ Complete |
| 3 | `compress_sources` | test_compress_sources | MEDIUM | ⚠ Enhance |
| 4 | `truncate_for_llm` | test_truncate_for_llm | HIGH | ✓ Complete |
| 5 | `estimate_tokens` | test_estimate_tokens | LOW | ✓ Complete |

**New Tests to Add:**

```python
# Test 3: compress_sources
- test_compress_sources_limits_count
- test_compress_sources_truncates_snippets
```

#### 1.4 memory_manager.py Functions (5/5)

| # | Function | Test Name | Priority | Status |
|---|----------|-----------|----------|--------|
| 1 | `compute_priority_score` | test_compute_priority_score | HIGH | ✓ Complete |
| 2 | `rank_conversations_for_eviction` | test_rank_conversations_for_eviction | MEDIUM | ⚠ Add Tests |
| 3 | `find_orphan_conversations` | test_find_orphan_conversations | MEDIUM | ⚠ Add Tests |
| 4 | `cleanup_conversations` | test_cleanup_conversations | MEDIUM | ⚠ Add Tests |
| 5 | `verify_integrity` | test_verify_integrity | HIGH | ✓ Complete |

**New Tests to Add:**

```python
# Test 2: rank_conversations_for_eviction
- test_eviction_ranks_by_priority
- test_eviction_returns_correct_count

# Test 3: find_orphan_conversations
- test_orphan_finds_idle_conversations
- test_orphan_finds_archived_old

# Test 4: cleanup_conversations
- test_cleanup_dry_run
- test_cleanup_identifies_orphans
```

---

### Phase 2: Mode Routing Tests (Priority HIGH)

#### 2.1 Mode List (9 modes)

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

#### 2.2 Mode Test Matrix

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

### Phase 3: Security Tests (Priority HIGH)

#### 3.1 Input Sanitization Tests

```
TestInputSanitization:
├── test_html_sanitization
├── test_prompt_injection_blocked
├── test_pii_detection
└── test_long_message_truncated
```

#### 3.2 Response Safety Tests

```
TestResponseSafety:
├── test_internal_prompt_leak_prevented
└── test_trace_blob_prevention
```

---

### Phase 4: Integration Tests (Priority MEDIUM)

#### 4.1 Crypto Mode Tests

```
TestCryptoMode:
├── test_crypto_prediction
└── test_crypto_price
```

#### 4.2 Project Mode Tests

```
TestProjectMode:
├── test_project_bind_requires_active
└── test_project_files_query
```

#### 4.3 Agent Mode Tests

```
TestAgentMode:
├── test_agent_step
├── test_agent_run
└── test_agent_continue
```

#### 4.4 Memory/Conversation Tests

```
TestMemoryManagement:
├── test_conversation_creation
├── test_conversation_history
├── test_conversation_list
└── test_memory_encryption
```

---

## 3. Test Execution Order

### 3.1 Quick Verification

```bash
# Single command to run all except image
cd /home/h/Documents/python/whioutoKn && ./run_all_tests_except_image.sh
```

### 3.2 Manual Step-by-Step

```bash
# 1. Unit tests - Guard Functions
pytest tests/test_all_modes_comprehensive.py::TestGuardFunctions -v --tb=short

# 2. Unit tests - Context Scoring
pytest tests/test_all_modes_comprehensive.py::TestContextScoring -v --tb=short

# 3. Unit tests - Memory Management
pytest tests/test_all_modes_comprehensive.py::TestMemoryManagement -v --tb=short

# 4. Mode routing tests
pytest tests/test_all_modes_comprehensive.py::TestModeRouting -v --tb=short

# 5. Security tests
pytest tests/test_all_modes_comprehensive.py::TestInputSanitization -v --tb=short

# 6. All comprehensive
pytest tests/test_all_modes_comprehensive.py -v --tb=short

# 7. Input normalizer mode contract
pytest tests/test_input_normalizer_mode_contract.py -v --tb=short
```

---

## 4. Test Coverage Targets

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

## 5. Environment Setup

### 5.1 Virtual Environment

```bash
cd /home/h/Documents/python/whioutoKn
python -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

### 5.2 Environment Variables

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

## 6. Expected Outcomes

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

## 7. Implementation Steps

### Step 1: Update TEST_SPECIFICATION.md
- Document all test functions
- Update test coverage matrix

### Step 2: Add Missing Tests
- Add tests for looks_like_url_candidate
- Add tests for detect_pii
- Add tests for detect_conflicts
- Add tests for rank_conversations_for_eviction
- Add tests for find_orphan_conversations
- Add tests for cleanup_conversations

### Step 3: Run Tests
- Execute test suite
- Analyze results
- Fix any failures

### Step 4: Verify Coverage
- Check test coverage
- Ensure all functions are covered

---

## 8. File Structure Summary

```
/home/h/Documents/python/whioutoKn/
├── TEST_SPECIFICATION.md      # Original test specification
├── TEST_PLAN.md             # This test plan
├── run_all_tests_except_image.sh  # Runner script
├── tests/
│   ├── conftest.py          # Test fixtures
│   ├── test_all_modes_comprehensive.py  # Main test file
│   └── test_input_normalizer_mode_contract.py  # Mode contract tests
└── app/services/
    ├── input_normalizer.py  # Functions to test
    ├── context_scorer.py   # Functions to test
    ├── context_compressor.py  # Functions to test
    └── memory_manager.py    # Functions to test
```

---

## Status: READY FOR EXECUTION

This test plan is based on thorough analysis of:
- TEST_SPECIFICATION.md (original)
- tests/test_all_modes_comprehensive.py
- tests/test_input_normalizer_mode_contract.py
- tests/conftest.py
- Service modules: input_normalizer.py, context_scorer.py, context_compressor.py, memory_manager.py

**Required Actions:**
1. Update TEST_SPECIFICATION.md with this plan
2. Add missing test functions
3. Run tests to verify coverage
4. Fix any failures
