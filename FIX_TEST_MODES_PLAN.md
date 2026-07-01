# FIX_TEST_MODES_PLAN.md

## Information Gathered

### Current State Analysis

1. **test_all_modes_comprehensive.py has indentation errors** - file cannot be parsed by Python, preventing any tests from running
   - Line 38: `def test_web_mode_requires_query` - missing 4-space indent
   - Line 47: `def test_url_mode_requires_valid_url` - extra indent (8 spaces instead of 4)
   - Line 61: `def test_url_mode_accepts_valid_url` - extra indent (8 spaces instead of 4)
   - Line 68: `# Should not return 422` - inconsistent indentation

2. **test_input_normalizer_mode_contract.py: 33 tests PASS** - all output quality guard tests currently pass

### Failed Tests Analysis (from User Task)

| Test | Expected | Actual | Fix Required |
|------|----------|--------|------------|
| test_url_mode_requires_valid_url | 400/422 status | 200 OK | Update validation to return 400/422 for invalid URL |
| test_long_message_truncated | 200 or 413 | 422 Unprocessable Entity | Fix truncation logic to return 413 or 200 |
| test_output_quality_guard_blocks_generic_greeting_for_release_notes_query | "random answer" in response | Returns greeting | Update guard to detect mismatch |
| test_output_quality_guard_blocks_unrelated_short_world_question | "random answer" | Returns unrelated answer | Update guard to detect mismatch |
| test_output_quality_guard_blocks_project_summary_leak | "local repo context" | Returns project summary | Update guard for leak prevention |
| test_output_quality_guard_blocks_file_excerpt_leak | "local repo context" | Returns file excerpt | Update guard for leak prevention |

## Plan

### Step 1: Fix Test File Syntax Errors
- Fix indentation in test_all_modes_comprehensive.py
- Ensure all test methods have proper 4-space indentation inside class

### Step 2: Fix URL Validation
- Update `app/services/input_normalizer.py` or `app/api/chat.py`
- Make `validate_url_format` function reject invalid URLs
- Return 400/422 status for invalid URL in URL mode

### Step 3: Fix Long Message Truncation
- Update context compressor or chat API
- Handle 10000 char messages gracefully
- Return 200 with truncated content OR 413 (Payload Too Large)

### Step 4: Enhance Output Quality Guard
- Update `_apply_output_quality_guard` in `app/api/chat.py` to detect:
  - Generic greeting response for non-greeting prompt (mismatch)
  - Unrelated question answered (e.g., capital of Japan for release notes)
  - Project summary leak when not requested
  - File excerpt leak in general prompts

## Dependent Files to Edit

1. `/home/h/Documents/python/whioutoKn/tests/test_all_modes_comprehensive.py` - fix indentation
2. `/home/h/Documents/python/whioutoKn/app/services/input_normalizer.py` - update URL validation
3. `/home/h/Documents/python/whioutoKn/app/api/chat.py` - update output quality guard
4. `/home/h/Documents/python/whioutoKn/app/services/context_compressor.py` - fix truncation handling

## Followup Steps After Edit

1. Run `pytest tests/test_all_modes_comprehensive.py -v` to verify tests parse
2. Run `pytest tests/test_input_normalizer_mode_contract.py -v` to verify existing tests pass
3. Run the full test suite to confirm fixes work
