"""GET /api/health — liveness check with adapter info."""

from __future__ import annotations

from fastapi import APIRouter

from dashboard.server.deps import get_repo_path
from dashboard.server.models import HealthResponse

router = APIRouter()


@router.get("/api/health")
def health(repo: str | None = None) -> HealthResponse:
    """Return health status and configured adapter types."""
    return HealthResponse(
        status="ok",
        repo_path=str(get_repo_path()),
        state_store="git",
        spec_source="git",
    )
