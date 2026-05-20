from __future__ import annotations

import main


def test_security_policy_includes_csp_sources():
    csp = main._content_security_policy()
    assert "default-src 'self'" in csp
    assert "script-src 'self' https://cdn.jsdelivr.net" in csp
    assert "style-src 'self' 'unsafe-inline' https://cdnjs.cloudflare.com https://fonts.googleapis.com" in csp
    assert "frame-ancestors 'none'" in csp
    assert "object-src 'none'" in csp
