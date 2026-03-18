from __future__ import annotations

import app.tools as tools


def test_tools_all_exports_resolve() -> None:
    missing = [name for name in tools.__all__ if not hasattr(tools, name)]
    assert missing == []


def test_legacy_tools_wrappers_removed() -> None:
    assert not hasattr(tools, "duckduckgo_search_html_structured")
    assert not hasattr(tools, "browser_search_scrape_structured")
    assert not hasattr(tools, "TOOLS")
    assert not hasattr(tools, "tool")


def test_parse_cors_origins_normalizes_values() -> None:
    parsed = tools.parse_cors_origins(" https://a.com/ , https://b.com, https://a.com ")
    assert parsed == ["https://a.com", "https://b.com"]


def test_parse_cors_origins_wildcard_wins() -> None:
    parsed = tools.parse_cors_origins("https://a.com, * , https://b.com")
    assert parsed == ["*"]
