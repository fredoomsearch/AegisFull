# TODO_FIX_ISSUES Implementation Plan

## Current Status: 5/5 DONE ✅

| Issue | Status | Notes |
|-------|-------|-------|
| #1 Geography/Time | ✅ DONE | chat.py - _TIME_QUESTION_PREFIXES, _decide_source_plan() returns web_only |
| #2 URL Validation | ✅ DONE | input_normalizer.py - validate_url_format() with scheme/netloc |
| #3 Output Guards | ✅ DONE | validation_layer.py - _GENERIC_REFUSAL_PATTERNS, _LEAK_WEB_PATTERNS |
| #4 Stale Cache | ✅ DONE | web_search.py - _modify_query_for_retry(), _should_retry_with_modified_query() |
| #5 Truncation | ✅ DONE | chat.py - _truncate_response() used in 9+ locations |

---

## Issue #1 Implementation: Geography/Time Detection in _decide_source_plan()

### Problem
- Uses local_only mode for geography/time questions with hardcoded facts
- Should force web_only for location/time queries

### Files to Modify
- `app/api/chat.py` - `_decide_source_plan()` function

### Implementation Plan
1. Add time question detection function `_looks_like_time_question()`
2. Add detection for recall/memory queries ("recuerdas", "do you remember", etc.)
3. Modify `_decide_source_plan()` to return "web_only" for time/geography/recall questions

### Code Changes Needed
```python
# Add to chat.py - Time detection prefixes
_TIME_QUESTION_PREFIXES = (
    "what time is it",
    "what's the time",
    "que hora es",
    "dime la hora",
    "current time",
    "hora actual",
)

# Add to _decide_source_plan() - detect time/recall
def _decide_source_plan(...):
    # Existing code...
    
    # NEW: Force web for time/geography/recall questions
    if _looks_like_time_question(routing_message) or \
       _looks_like_recall_question(routing_message):
        return "web_only"
```

---

## Issue #3 Implementation: Enhanced Output Guards

### Problem
- Pattern-based detection leaks through for web queries
- Generic responses bypass guards

### Files to Modify
- `app/services/validation_layer.py`
- `app/api/chat.py`

### Implementation Plan
Enhanced web response guard detection - identify when responses are:
- Generic patterns ("no information available")
- Out-of-context for the query type

---

## Issue #4 Implementation: Web Cache Retry Logic

### Problem
- Returns stale data without attempting fresh search
- Falls back to local too quickly

### Files to Modify
- `app/services/web_search.py`

### Implementation Plan
1. Detect stale cache usage
2. Retry with modified query on stale cache
3. Add retry_count parameter

---

# Root Cause Analysis: Your Memory Errors

Based on your conversation, here are the specific causes:

## Conversation Issue #1: "RECUERDAS LA PRIMERA QUERY?"
- **Expected**: Should search conversation history/durable_memory
- **Actual**: "No hay información adicional disponible" 
- **Cause**: `_decide_source_plan()` treats this as local_only, but there's no local recall mechanism

## Conversation Issue #2: "NECESITO SABER TECNICAS PARA MEJORAR..."
- **Expected**: Web search should work or retry on stale cache
- **Actual**: "No pude obtener evidencia web suficiente"
- **Cause**: No retry logic in web_search.py (Issue #4)

## Implementation Priority

1. **Issue #1** - MOST URGENT
   - Fixes routing to prevent "local_only" mode misuse
   - Prevents incorrect geography/time responses
   - **ADD**: Recall/memory query detection

2. **Issue #4** - HIGH PRIORITY  
   - Improves web search reliability
   - Fixes "No web evidence" responses - Add retry logic

3. **Issue #3** - MEDIUM PRIORITY
   - Guards for output quality
   - Prevents generic response leaks
