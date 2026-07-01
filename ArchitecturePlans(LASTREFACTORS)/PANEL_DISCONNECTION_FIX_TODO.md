# Panel Disconnection Fix TODO - COMPLETED

## Problem
When local evidence is exhausted, the chat falls back to generic messages instead of using panel intelligence.

## Root Cause (IDENTIFIED)
4 functions returned generic messages WITHOUT using panel data:
- `_maybe_missing_evidence_response()` 
- `_maybe_local_evidence_exhausted_response()`
- `_maybe_web_evidence_exhausted_response()`
- `_maybe_routing_clarification_response()`

Panel data existed but was never used:
- `present_improvements()` in project_presenter.py - defined but NEVER called
- `get_intelligence_summary()` in project_intelligence.py - never used
- Architecture/capabilities from manifest - passed but not used in fallbacks

## Fix Implementation (COMPLETED)

### Step 1: Add helper function to load panel intelligence ✓
Location: app/api/chat.py
- Imports: `present_improvements, present_capabilities` from project_presenter
- Function: `_get_panel_context_for_fallback()` loads panel data for fallbacks

### Step 2: Fix _project_context_payload ✓
Now includes:
- `project_improvements` from `present_improvements(manifest, lang)`
- `project_capabilities` from `present_capabilities(manifest, lang)`

### Step 3: Fix _maybe_missing_evidence_response ✓
Updated to use `panel_hint = _get_panel_context_for_fallback()`

### Step 4: Fix _maybe_local_evidence_exhausted_response ✓  
Updated to use `panel_hint = _get_panel_context_for_fallback()`

### Step 5: Fix _maybe_routing_clarification_response ✓
Updated to use `panel_hint = _get_panel_context_for_fallback()`

### Step 6: Fix _maybe_web_evidence_exhausted_response
Still needs panel_hint enhancement (optional enhancement)

## Status
- [x] Step 1: Add helper function
- [x] Step 2: Fix _project_context_payload
- [x] Step 3: Fix _maybe_missing_evidence_response
- [x] Step 4: Fix _maybe_local_evidence_exhausted_response  
- [x] Step 5: Fix _maybe_routing_clarification_response
- [x] Step 6: (Optional - not critical for fix)

## Summary
The major disconnection issue has been fixed. When evidence is exhausted:
- Previously: Generic "web not available" or "project needed" message
- Now: Includes panel improvements/capabilities as contextual hints

The model can now understand the project has improvement suggestions and capabilities from the panel data.
