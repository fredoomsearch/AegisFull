# Project Panel Close Fix - Implementation Plan

## Problem Statement
When the user closes the project panel (eye icon with slash), project mode stays active but the panel becomes hidden. The user wants:
1. Functions to deactivate project mode when pushing the close button
2. Or auto-detection of what project mode was closed and returning to chat mode

## Current State Analysis

### From `ui/app.js`:
- `setMode(mode)` - switches between CHAT, WEB, URL, CRYPTO, IMAGE, AUTO modes
- `showFilesPanelFromToolbar()` - shows the files panel and switches to chat mode
- `toggleSidebarVisibility()` - toggles sidebar visibility
- `setActiveProject(projectId)` - sets the active project

### From `app/services/session_state.py`:
- `SessionState` TypedDict contains:
  - `last_mode: str`
  - `previous_mode: str`
  - `mode_changed: bool`
- `default_session_state()` creates baseline state with empty mode fields
- `update_session_state()` tracks mode transitions

### From `app/services/input_normalizer.py`:
- `_MODE_ALIASES` maps "project" to "project" mode
- `_MODE_PREFIX_RE` regex extracts mode from input like "project: do something"

## Implementation Plan

### Stage 1: Extend Session State Tracking (app/services/session_state.py)
Add tracking for previous mode before project was activated:
```python
# Add to SessionState TypedDict:
previous_mode_before_project: Optional[str]
project_panel_was_visible: bool
```

Add helper function `get_previous_mode_before_project()` that returns the mode user was in before entering project mode.

### Stage 2: UI Enhancement (ui/app.js)
Modify `showFilesPanelFromToolbar()` and `toggleSidebarVisibility()` to:
1. Track current mode before hiding panel
2. Optionally switch to chat mode when closing project panel
3. Or just clear active project context

New function `deactivateProjectMode()`:
```javascript
function deactivateProjectMode() {
  const prevMode = state.previousModeBeforeProject || MODES.CHAT;
  setActiveProject("");
  if (state.mode === MODES.PROJECT) {
    setMode(prevMode);
  }
  // Clear project context
  state.activeProjectId = "";
  localStorage.removeItem("aegis_active_project_id");
}
```

### Stage 3: Mode Switch on Panel Close
Modify the eye icon button handler to optionally trigger mode switch:

Option A (Explicit): Clicking eye icon → switch to chat mode
Option B (Auto-detect): Detect previous mode and restore it

### Stage 4: Similar Error Detection
Search for other modes that may have similar issues:
- Crypto panel close → mode stays in CRYPTO
- Image panel close → mode stays in IMAGE  
- Web panel close → mode stays in WEB

## Files to Modify
1. `app/services/session_state.py` - Add mode tracking
2. `ui/app.js` - Add `deactivateProjectMode()` and modify close handlers
3. `app/api/chat.py` - Optional: Add endpoint for explicit mode switch

## Testing Checklist
- [ ] Closing project panel with eye icon returns to chat mode
- [ ] Active project is cleared when returning to chat
- [ ] Previous mode is tracked correctly
- [ ] No brain unification breakage (project context cleared properly)
- [ ] Similar modes (crypto, image) don't have same issue

## Questions/Clarifications Needed
1. Should closing the panel explicitly switch to chat mode OR just clear project and stay in current mode?
2. Should this behavior apply to crypto/image panels as well?
