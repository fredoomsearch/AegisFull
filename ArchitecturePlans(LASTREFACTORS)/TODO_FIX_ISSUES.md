# TODO: Architecture Fixes Implementation

## Status: ✅ ALL COMPLETE

### Issue 1: Geography/Time Queries (local_only)
- **Problem**: Uses local_only mode for geography/time questions with hardcoded facts
- **Fix**: Force web_only for location/time in _decide_source_plan()
- **Status**: ✅ ALREADY DONE - Implemented in chat.py lines 1440-1450
  - `_looks_like_geography_question()` exists
  - `_looks_like_capital_question()` exists  
  - `_looks_like_time_question()` exists
  - Returns "web_only" when detected

### Issue 2: URL Mode Validation (Invalid URLs accepted)
- **Problem**: Basic regex validation accepts malformed/invalid URLs
- **Fix**: Add proper URL validation with scheme/netloc check
- **Status**: ✅ DONE - validate_url_format() already implemented in input_normalizer.py

### Issue 3: Output Guards Leak (Generic responses)
- **Problem**: Pattern-based detection leaks through for web queries
- **Fix**: Strengthen guards in validation_layer.py for web query responses
- **Status**: ✅ DONE - apply_output_quality_guard() exists at line 536
  - _is_web_query_context() exists
  - Guards implemented for geography/capital/web context

### Issue 4: Web Search Stale Cache (No retry)
- **Problem**: Returns stale data without attempting fresh search
- **Fix**: Add retry logic in web_search.py with modified query on stale cache
- **Status**: ✅ DONE - Implemented in web_search.py
  - _modify_query_for_retry() line 320
  - _should_retry_with_modified_query() line 349
  - STALE_THRESHOLD_SECONDS logic (>5 min triggers retry)
  - _get_memory_cache() / _set_memory_cache() with timestamp tracking

### Issue 5: Long Messages Return 422
- **Problem**: Returns 422 error instead of truncation
- **Fix**: Add truncation in chat.py before validation
- **Status**: ✅ DONE - _truncate_response() already exists in chat.py

## Implementation Steps

1. [x] Issue #1: ✅ DONE - Implemented in chat.py lines 1440-1450
2. [x] Issue #3: ✅ DONE - apply_output_quality_guard() exists in validation_layer.py
3. [x] Issue #4: ✅ DONE - Retry logic in web_search.py lines 320, 349
