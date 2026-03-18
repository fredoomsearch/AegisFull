from __future__ import annotations

"""
Legacy `/tools/*` compatibility shim.

Project lifecycle is canonical under `/files/*`.
This module intentionally keeps the old `/tools/*` paths mounted, but all of them
return HTTP 410 (Gone) with a migration hint.

Why this module exists:
- Preserve deterministic compatibility behavior for old clients.
- Prevent silent legacy behavior by hard-failing with migration hints.
"""

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import require_api_key


def _legacy_tools_gate() -> None:
    """
    Hard gate for legacy /tools surface.
    `/tools/*` is permanently deprecated in favor of `/files/*`.
    """
    raise HTTPException(
        status_code=410,
        detail="Legacy /tools endpoints are disabled. Use /files/* project endpoints instead.",
    )


router = APIRouter(
    prefix="/tools",
    tags=["tools"],
    dependencies=[Depends(require_api_key), Depends(_legacy_tools_gate)],
)


@router.get("/tree")
async def tree_legacy_disabled() -> dict[str, str]:
    return {"detail": "Use /files/tree"}


@router.get("/content")
async def content_legacy_disabled() -> dict[str, str]:
    return {"detail": "Use /files/content"}


@router.post("/docs/summary")
async def docs_summary_legacy_disabled() -> dict[str, str]:
    return {"detail": "Use /files/projects/{id}/architecture or /files/content"}


@router.post("/upload_project")
async def upload_project_legacy_disabled() -> dict[str, str]:
    return {"detail": "Use /files/upload-zip"}


@router.post("/delete_project")
async def delete_project_legacy_disabled() -> dict[str, str]:
    return {"detail": "Use /files/delete_project"}


@router.get("/embeddings/status")
async def embeddings_status_legacy_disabled() -> dict[str, str]:
    return {"detail": "Use /system/readyz and /system/capabilities"}


@router.post("/embeddings/prepare")
async def embeddings_prepare_legacy_disabled() -> dict[str, str]:
    return {"detail": "Use startup/verify flows (embeddings handled by runtime)"}


@router.api_route("/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"])
async def legacy_catchall_disabled(path: str) -> dict[str, str]:
    return {"detail": f"Legacy /tools/{path} disabled. Use /files/* endpoints."}
