from __future__ import annotations

from app.api import toolssupport


def test_tools_router_has_hard_410_gate_dependency():
    deps = [d.dependency for d in toolssupport.router.dependencies]
    assert toolssupport._legacy_tools_gate in deps


def test_tools_router_exposes_legacy_paths_for_explicit_migration():
    paths = {route.path for route in toolssupport.router.routes}
    assert "/tools/tree" in paths
    assert "/tools/content" in paths
    assert "/tools/docs/summary" in paths
    assert "/tools/upload_project" in paths
    assert "/tools/delete_project" in paths
    assert "/tools/embeddings/status" in paths
    assert "/tools/embeddings/prepare" in paths
    assert "/tools/{path:path}" in paths
