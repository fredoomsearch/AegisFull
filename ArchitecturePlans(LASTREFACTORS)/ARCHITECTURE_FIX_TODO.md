# Architecture Fixes TODO

## Issues to Fix
1. Geography/Time Queries (local_only) - Force web_only for location/time
2. URL Mode Validation - Invalid URLs accepted 
3. Output Guards Leak - Generic responses leak through for web queries
4. Web Search Stale Cache - No retry with modified queries
5. Long Messages Return 422 - No truncation

## Progress
- [x] Issue #2: URL Validation - Already enhanced in input_normalizer.py and integrated in chat.py
- [ ] Issue #1: Geography/Time - Need to force web_only routing
- [ ] Issue #3: Output Guards - Strengthen in validation_layer.py
- [ ] Issue #4: Web Cache Retry - Add retry in web_search.py
- [ ] Issue #5: Message Truncation - Add truncation in chat.py

## Implementation Notes
- Geography/Time: Modify _decide_source_plan() to force web_only for location queries
- URL: Already done - validate_url_format() added to input_normalizer.py
- Output Guards: Add web query detection in validation patterns
- Web Cache: Add retry with modified query on stale cache
- Truncation: Add _truncate_response() call before Pydantic validation
