# Testing TODO - AegisChat Comprehensive Test Plan

## Overview
Execute comprehensive automated tests for all AegisChat components including:
- Mode routing (9 modes)
- Guard functions (input_normalizer.py, context_scorer.py, context_compressor.py, memory_manager.py)
- Security tests
- Integration tests

## Execution Plan

### Step 1: Check Environment & Dependencies
- [x] Verify venv exists with pytest, fastapi, httpx
- [x] Verify Python 3.12+ available 
- [x] Verify conftest.py sets correct env vars

### Step 2: Run Core Test Modules
- [ ] Run test_all_modes_comprehensive.py
- [ ] Run test_input_normalizer_mode_contract.py
- [ ] Run test_chat_output_safety.py

### Step 3: Run Category Tests
- [ ] Run auth scope tests (test_auth_scope_hardening.py, test_admin_scope_hardening.py)
- [ ] Run crypto mode tests (test_crypto_runtime.py, test_crypto_trade_safety.py, test_crypto_predict_engine.py)
- [ ] Run conversation/memory tests (test_conversation_state_db.py, test_conversation_turns.py, test_durable_memory.py)
- [ ] Run project mode tests (test_chat_project_binding.py, test_retrieval_project_scope.py)
- [ ] Run agent mode tests (test_agent_run.py, test_agent_step.py, test_agent_continue.py, test_agent_eval_check.py)

### Step 4: Run Additional Tests
- [ ] Run test_api_smoke.py
- [ ] Run test_redaction.py
- [ ] Run test_session_context.py

### Step 5: Verify Coverage
- [ ] Verify all 8 input_normalizer.py functions tested
- [ ] Verify all 3 context_scorer.py functions tested
- [ ] Verify all 5 context_compressor.py functions tested
- [ ] Verify all 5 memory_manager.py functions tested
- [ ] Verify all 9 routing modes tested

### Step 6: Report Results
- [ ] Document pass/fail status for each test
- [ ] Identify any gaps or missing tests
- [ ] Provide recommendations for improvements

## Test Functions Mapping

### input_normalizer.py (8 functions)
| # | Function | Test File | Status |
|---|----------|----------|--------|
| 1 | strip_attachment_context | test_all_modes_comprehensive.py | ✓ |
| 2 | normalize_user_input | test_all_modes_comprehensive.py | ✓ |
| 3 | normalize_for_routing | test_all_modes_comprehensive.py | ✓ |
| 4 | split_mode_prefix | test_all_modes_comprehensive.py | ✓ |
| 5 | looks_like_url_candidate | test_all_modes_comprehensive.py | ✓ |
| 6 | sanitize_html | test_all_modes_comprehensive.py | ✓ |
| 7 | detect_prompt_injection | test_all_modes_comprehensive.py | ✓ |
| 8 | detect_pii | test_all_modes_comprehensive.py | ✓ |

### context_scorer.py (3 functions)
| # | Function | Test File | Status |
|---|----------|----------|--------|
| 1 | compute_freshness_score | test_all_modes_comprehensive.py | ✓ |
| 2 | rank_sources | test_all_modes_comprehensive.py | ✓ |
| 3 | detect_conflicts | test_all_modes_comprehensive.py | ✓ |

### context_compressor.py (5 functions)
| # | Function | Test File | Status |
|---|----------|----------|--------|
| 1 | compress_messages | test_all_modes_comprehensive.py | ✓ |
| 2 | compress_CONTEXT | test_all_modes_comprehensive.py | ✓ |
| 3 | compress_sources | test_all_modes_comprehensive.py | ✓ |
| 4 | truncate_for_llm | test_all_modes_comprehensive.py | ✓ |
| 5 | estimate_tokens | test_all_modes_comprehensive.py | ✓ |

### memory_manager.py (5 functions)
| # | Function | Test File | Status |
|---|----------|----------|--------|
| 1 | compute_priority_score | test_all_modes_comprehensive.py | ✓ |
| 2 | rank_conversations_for_eviction | test_all_modes_comprehensive.py | ✓ |
| 3 | find_orphan_conversations | test_all_modes_comprehensive.py | ✓ |
| 4 | cleanup_conversations | test_all_modes_comprehensive.py | ✓ |
| 5 | verify_integrity | test_all_modes_comprehensive.py | ✓ |

## Routing Modes (9 modes)
| Mode | Test Status |
|------|-------------|
| general | ✓ |
| chat | ✓ |
| code | ✓ |
| web | ✓ |
| url | ✓ |
| crypto | ✓ |
| project | ✓ |
| agent | ✓ |
| auto | ✓ |

## Execution Command
```bash
cd /home/h/Documents/python/whioutoKn
source venv/bin/activate
pytest tests/test_all_modes_comprehensive.py -v --tb=short
```

## Alternative: Use Test Runner Script
```bash
cd /home/h/Documents/python/whioutoKn
./run_all_tests_except_image.sh
