# AEGIS — Unified Brain Architecture Proposal

## Problem Analysis

Based on my analysis of the codebase, I've identified the following architectural issues:

### Current Architecture Problems

1. **Fragmented Context** - Each mode (web, crypto, project, image) maintains its own context handling logic:
   - `chat.py` has ~5200 lines of monolithic routing code
   - Session state in `session_state.py` mixes planning with state management
   - Project introspection is isolated from retrieval

2. **Weak Validation Layer** - The system can "invent" information when retrieval is incomplete:
   - No `Confidence Engine` exists
   - Framework detection in `project_introspection.py` is basic pattern matching
   - No evidence-based validation before responding

3. **Separated Memory Types** - Multiple memory systems that don't share context:
   - `memory.py` for chat history
   - `durable_memory.py` for persistent knowledge
   - Retrieval service has its own vector storage
   - No unified memory layer

4. **Model Routing Too Early** - Routing decisions happen before context building:
   - `_decide_source_plan()` routes first, then builds context
   - Should build context first, then route to appropriate model

5. **Project Understanding as Lookup** - Current approach is file listing, not true analysis:
   - `project_introspection.py` does symbol scanning
   - No knowledge graph relationships between components
   - No architecture inference engine

### What Works Well (To Preserve)

- Fast local shortcuts for geography/capital questions (`chat.py`)
- Crypto prediction flow is well-structured
- Session state tracking for planner continuity
- Source origin tracking in responses
- Validation of conversation IDs

---

## Proposed Architecture

### Target State

```
                    [ FRONTEND CHAT ]
                          │
          ┌───────────────┼───────────────┐
          │               │               │
     [crypto]      [project]      [general]
          │               │               │
          └───────────────┼───────────────┘
                          │
                  [UNIFIED BRAIN]
                          │
          ┌───────────────┼────────────────┐
          │               │                │
     [memory]      [retrieval]      [reasoning]
          │               │                │
          └───────────────┼────────────────┘
                          │
                   [MODEL ROUTER]
                          │
            ┌─────────────┴─────────────┐
            │                           │
        [Groq API]                [Local LLM]
```

---

## Implementation Plan

### Phase 1: Context Aggregator (Priority 1)

**Objective**: Build a unified context before any model call.

**New file**: `app/services/context_aggregator.py`

```
ContextAggregator:
  - build_context(user_query, session_state, mode)
  - add_project_context(manifest, session_state)
  - add_memory_context(conversation_id, limit=5)
  - add_retrieval_context(query, limit=3)
  - add_tool_context(recent_tools)
  - compute_confidence_scores()
  - should_invent_framework() -> bool
```

**Integration**: Replace `_build_response_context()` in `chat.py`.

### Phase 2: Validation Layer Anti-Hallucination (Priority 2)

**Objective**: Never invent frameworks or features that don't exist.

**New file**: `app/services/validation_layer.py`

```
ValidationLayer:
  - validate_response(response, evidence) -> ValidationResult
  - check_framework_exists(framework, manifest) -> bool  
  - check_file_exists(path, root) -> bool
  - check_route_exists(route, manifest) -> bool
  
ConfidenceScore (returned):
  - filesystem: 0.95
  - retrieval: 0.83
  - symbol_match: 0.91
  - framework_detection: 0.21
  - overall: 0.45

Actions when confidence < threshold:
  - NEVER invent
  - Return: "No evidence found for X. Found: Y."
```

**Integration**: Call before `_finalize_user_response()`.

### Phase 3: Project Knowledge Graph (Priority 3)

**Objective**: Build real relationships between code components.

**Enhance**: `app/services/project_introspection.py`

```
ProjectKnowledgeGraph:
  - add_edge(source, target, kind)
  - get_dependents(symbol) -> List[Path]
  - get_usages(symbol) -> List[Path]
  - infer_architecture() -> ArchitectureProfile
  
ArchitectureInferer:
  - detect_frontend_type(manifest) -> FrontendType
    (SSR/Thymeleaf, SPA/React, Hybrid/Next.js)
  - detect_backend_type(manifest) -> BackendType  
  - infer_data_layer(manifest) -> DataLayer
```

**Frontend Detection Logic**:
```python
def detect_frontend_type(manifest) -> str:
    file_tree = manifest.get("file_tree", [])
    
    # Check for Thymeleaf/SSR patterns
    if any("th:" in str(f) for f in file_tree):
        return "thymeleaf"  # SSR
        
    # Check for React/Vue SPA
    if any(f.startswith("src/components") for f in file_tree):
        if any(".tsx" in f for f in file_tree):
            return "react"
        return "vue"
        
    # Check for Next.js/Nuxt
    if any("pages/" in f or "app/" in f for f in file_tree):
        return "nextjs"
        
    # Check for static HTML
    if any(f.endswith(".html") for f in file_tree):
        return "static"
        
    return "unknown"
```

**Integration**: Use in `summarize_project_architecture_deep()`.

### Phase 4: Unified Memory Layer (Priority 4)

**Objective**: Single memory system with typed storage.

**New file**: `app/services/unified_memory.py`

```
UnifiedMemory:
  # Short-term (conversation)
  - get_short_term(conv_id, limit) -> List[Turn]
  - append_short_term(conv_id, turn)
  
  # Working memory (current flow state)
  - get_working() -> Dict
  - set_working(key, value)
  
  # Semantic memory (persistent knowledge)
  - get_semantic(query) -> List[Chunk]
  - add_semantic(key, chunk)
  
  # Project memory (architecture)
  - get_project(project_id) -> ProjectMemory
  - set_project(project_id, analysis)
  
  # Tool memory (cached tool results)
  - get_cached(tool, args) -> Optional[Result]
  - set_cached(tool, args, result, ttl)
```

**Migration**:
- Move chat history from `memory.py`
- Move durable memory from `durable_memory.py`
- Add retrieval chunks as semantic memory

### Phase 5: Hybrid Model Reasoning (Priority 5)

**Objective**: Smart routing between Groq and local models.

**Enhanced**: `app/models/llm_client.py`

```
HybridReasoning:
  def generate(messages, task_type) -> str:
    if task_type == "speed_critical":
        # Use Groq for quick generation
        return groq_generate(messages)
        
    elif task_type == "big_context":
        # Use local for large project context
        return local_generate(messages)
        
    elif task_type == "code_reasoning":
        # Hybrid: local analyzes + Groq synthesizes
        analysis = local_analyze_project(messages)
        synthesis = groq_synthesize(analysis)
        return synthesis
        
    else:
        # Default auto-routing
        return auto_route(messages)
```

### Phase 6: Tool Result Persistence (Priority 6)

**Objective**: Don't re-analyze projects repeatedly.

**New file**: `app/services/tool_cache.py`

```
ToolCache:
  - get_project_analysis(project_id) -> Optional[Analysis]
  - set_project_analysis(project_id, analysis, ttl=3600)
  - get_framework_detection(project_id) -> List[str]
  - invalidate(project_id)
```

**Integration**: Use in project introspection.

---

## File Changes Summary

### New Files to Create

| File | Purpose | Phase |
|------|---------|-------|
| `app/services/context_aggregator.py` | Unified context builder | 1 |
| `app/services/validation_layer.py` | Anti-hallucination | 2 |
| `app/services/unified_memory.py` | Single memory layer | 4 |
| `app/services/tool_cache.py` | Tool result cache | 6 |

### Files to Modify

| File | Changes | Phase |
|--------|--------|-------|
| `app/services/project_introspection.py` | Add knowledge graph | 3 |
| `app/models/llm_client.py` | Add hybrid reasoning | 5 |
| `app/api/chat.py` | Use aggregator + validation | 1,2 |

### Files to Deprecate (After Migration)

| File | Replacement |
|------|------------|
| `app/memory.py` | `unified_memory.py` |
| `app/services/durable_memory.py` | `unified_memory.py` |

---

## Expected Results

### Before (Current)
```
User: does the project have frontend?
System: (no project loaded)
```

### After (Target)
```
User: does the project have frontend?
System: 
Yes. The frontend uses server-side rendering with Thymeleaf.

Evidence:
- src/main/resources/templates/
- *.html files with th:text, th:replace
- Thymeleaf layouts
- Bootstrap CSS classes

No React/Vue/Angular detected.

Views: listar.html, form.html, ver.html
Frontend type: Thymeleaf/SSR (Bootstrap)
```

### Confidence Scores Example
```
confidence = {
  "filesystem": 0.95,    // File tree confirms
  "retrieval": 0.83,     // Retrieval found matches  
  "symbol_match": 0.91,   // Symbols found in code
  "framework_detection": 0.21  // LOW - don't invent
}

response_allowed = overall >= 0.55
if not response_allowed:
  return "No evidence found for framework X. Found: Y"
```

---

## Implementation Order

1. **Create `context_aggregator.py`** - No dependencies
2. **Create `validation_layer.py`** - Uses manifest structure
3. **Enhance `project_introspection.py`** - Add frontend detection
4. **Create `unified_memory.py`** - Uses existing storage
5. **Enhance `llm_client.py`** - Add hybrid mode
6. **Create `tool_cache.py`** - Simple dict cache
7. **Migrate `chat.py`** - Use new components

---

## Risk Mitigation

- **Backward compatibility**: Keep existing APIs working
- **Gradual migration**: One component at a time
- **Feature flags**: AEGIS_UNIFIED_BRAIN=1 to enable
- **Fallback**: Existing logic if new fails

---

## Testing Approach

1. Unit tests for each new component
2. Integration tests for context flow
3. Validation layer tests with fake evidence
4. End-to-end tests for frontend detection

---

## Notes

- The key insight from the proposal is: **"context > model"**
- A perfect context beats a perfect model with bad context
- Mode should ONLY add context/tools/restrictions, not reasoning
- All modes share: memory, retrieval, project understanding, validation, reasoning
