from __future__ import annotations

"""
Model Router - Smart provider selection for LLM calls.

Why this module exists:
- Route between local (llama.cpp) and remote (Groq) based on task requirements
- Provide intelligent fallback chains
- Enable hybrid reasoning modes

Integration:
- Used by llm_client_offload.py for smart routing
- Used by chat endpoints for provider selection
- Used by tools for model selection
"""

import os
from typing import Any, Dict, List, Optional

# Import from existing llm_client_offload
from app.llm_client_offload import (
    _configured_provider,
    _remote_api_key,
    _remote_model_name,
    generate_response as _generate_local_response,
    llm_status,
)


class ModelRouter:
    """
    Smart router for LLM provider selection.
    
    Features:
    - Task-based routing (speed, context, code, privacy)
    - Automatic fallback chains
    - Provider status awareness
    - Hybrid mode support
    """
    
    def __init__(
        self,
        default_provider: str = "auto",
        prefer_remote: bool = False,
    ):
        self.default_provider = default_provider
        self.prefer_remote = prefer_remote
        self._status = llm_status()
    
    @property
    def status(self) -> Dict[str, Any]:
        """Get current provider status."""
        self._status = llm_status()
        return self._status
    
    @property
    def local_available(self) -> bool:
        """Check if local provider is available."""
        return bool(self._status.get("local_ready"))
    
    @property
    def remote_available(self) -> bool:
        """Check if remote (Groq) provider is available."""
        return bool(self._status.get("remote_ready"))
    
    def analyze_requirements(self, messages: List[Dict[str, str]]) -> Dict[str, Any]:
        """
        Analyze message content to determine routing requirements.
        
        Returns:
            Dict with requirement flags:
            - requires_speed: favor fast responses
            - requires_big_context: need larger context window
            - requires_code_reasoning: code analysis tasks
            - requires_privacy: sensitive data, local only
            - short_query: quick answer expected
        """
        combined = " ".join(
            str(m.get("content") or "") for m in messages
        ).lower()
        
        # Analyze requirements
        requires_speed = any(
            token in combined
            for token in (
                "rápido", "rápida", "fast", "quick", "inmediato", "immediate",
                "ahora", "now", "pronto", "soon"
            )
        )
        requires_big_context = any(
            token in combined
            for token in (
                "analiza", "analyze", "explica", "explain", "detalle",
                "detailed", "completo", "complete", "full"
            )
        ) or len(combined) > 3000
        requires_code_reasoning = any(
            token in combined
            for token in (
                "código", "code", "function", "class", "debug", "error", "bug",
                "implementa", "implementation", "refactor", "review",
                "inspect", "symbol", "class", "method"
            )
        )
        requires_privacy = any(
            token in combined
            for token in (
                "privado", "private", "confidencial", "confidential",
                "sensitive", "secreto", "secret"
            )
        )
        short_query = len(combined) < 200
        
        return {
            "requires_speed": requires_speed or short_query,
            "requires_big_context": requires_big_context,
            "requires_code_reasoning": requires_code_reasoning,
            "requires_privacy": requires_privacy,
            "short_query": short_query,
            "combined_length": len(combined),
        }
    
    def determine_route(
        self,
        messages: List[Dict[str, str]],
        preferred_provider: Optional[str] = None,
    ) -> List[str]:
        """
        Determine optimal provider route based on requirements.
        
        Args:
            messages: Chat messages to analyze
            preferred_provider: Explicit provider preference
            
        Returns:
            List of providers to try in order (fallback chain)
        """
        requirements = self.analyze_requirements(messages)
        
        # Explicit provider takes priority
        if preferred_provider and preferred_provider not in {"auto", "hybrid"}:
            return [preferred_provider]
        
        # Privacy requirement forces local
        if requirements.get("requires_privacy"):
            return ["local"]
        
        # Build fallback chain based on requirements
        chain: List[str] = []
        
        if requirements.get("requires_speed") and self.remote_available:
            # Speed requirement → Groq first
            chain.append("groq")
            if self.local_available:
                chain.append("local")
        elif requirements.get("requires_code_reasoning"):
            # Code reasoning → local (better for code)
            chain.append("local")
            if self.remote_available:
                chain.append("groq")
        elif requirements.get("requires_big_context") and self.remote_available:
            # Big context → Groq (larger context window)
            chain.append("groq")
            chain.append("local")
        elif self.prefer_remote and self.remote_available:
            # Remote preference
            chain.append("groq")
            chain.append("local")
        else:
            # Default: local first, then remote fallback
            if self.local_available:
                chain.append("local")
            if self.remote_available:
                chain.append("groq")
        
        # If no providers available, return empty chain
        if not chain:
            # At least try one based on env
            if self._status.get("provider"):
                return [self._status.get("provider")]
            return ["local"]  # Default attempt
        
        return chain
    
    def generate(
        self,
        messages: List[Dict[str, str]],
        max_new_tokens: Optional[int] = None,
        temperature: float = 0.2,
        top_p: float = 0.95,
        preferred_provider: Optional[str] = None,
    ) -> str:
        """
        Generate response with smart routing.
        
        This is the main entry point that replaces direct llm_client_offload calls
        when you want intelligent routing.
        """
        from app.llm_client_offload import (
            _generate_groq_response,
            _looks_like_local_failure,
            _looks_like_remote_failure,
            sanitize_messages,
        )
        
        route = self.determine_route(messages, preferred_provider)
        max_tokens = max_new_tokens or 1800
        
        messages = sanitize_messages(messages)
        
        last_error = ""
        for provider in route:
            try:
                if provider == "groq":
                    text = _generate_groq_response(messages, max_tokens, temperature, top_p)
                    if _looks_like_remote_failure(text):
                        last_error = text
                        continue
                    return text
                
                # local provider
                text = _generate_local_response(messages, max_tokens, temperature, top_p)
                if _looks_like_local_failure(text):
                    last_error = text
                    continue
                return text
            except Exception as e:
                last_error = str(e)
                continue
        
        # All providers failed
        return last_error or "No LLM provider available"
    
    def get_available_providers(self) -> List[Dict[str, Any]]:
        """Get list of available providers with status."""
        providers = []
        
        if self.local_available:
            providers.append({
                "name": "local",
                "status": "ready",
                "model": self._status.get("model"),
            })
        elif self._status.get("provider") == "local":
            providers.append({
                "name": "local",
                "status": "configured" if self._status.get("model_exists") else "error",
                "model": self._status.get("model"),
            })
        
        if self.remote_available:
            providers.append({
                "name": "groq",
                "status": "ready",
                "model": self._status.get("remote_model"),
            })
        elif self._status.get("provider") == "groq":
            providers.append({
                "name": "groq",
                "status": "configured",
                "model": self._status.get("remote_model"),
            })
        
        return providers


# ============================================================
# Global Router Instance
# ============================================================

_router: Optional[ModelRouter] = None


def get_model_router() -> ModelRouter:
    """Get global router instance."""
    global _router
    if _router is None:
        provider = _configured_provider()
        prefer_remote = provider == "groq"
        _router = ModelRouter(
            default_provider=provider,
            prefer_remote=prefer_remote,
        )
    return _router


def smart_generate(
    messages: List[Dict[str, str]],
    max_new_tokens: Optional[int] = None,
    temperature: float = 0.2,
    top_p: float = 0.95,
    preferred_provider: Optional[str] = None,
) -> str:
    """Convenience function for smart LLM generation."""
    router = get_model_router()
    return router.generate(
        messages,
        max_new_tokens=max_new_tokens,
        temperature=temperature,
        top_p=top_p,
        preferred_provider=preferred_provider,
    )
