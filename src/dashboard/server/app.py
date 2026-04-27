"""FastAPI application factory with lifespan management."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

from dashboard.server import deps
from dashboard.server.routes import (
    activity,
    agents,
    health,
    metrics,
    pipeline,
    process,
    specs,
    summary,
    tasks,
)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Initialize adapters on startup."""
    repo_path = Path(app.state.repo_path)
    deps.init(repo_path)
    yield


def create_app(repo_path: str = ".") -> FastAPI:
    """Create and configure the FastAPI application.

    Args:
        repo_path: Path to the target git repository.

    Returns:
        Configured FastAPI application with all routes registered.
    """
    app = FastAPI(title="Hyperloop Dashboard", lifespan=lifespan)
    app.state.repo_path = repo_path
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )
    app.include_router(activity.router)
    app.include_router(agents.router)
    app.include_router(health.router)
    app.include_router(metrics.router)
    app.include_router(pipeline.router)
    app.include_router(process.router)
    app.include_router(specs.router)
    app.include_router(tasks.router)
    app.include_router(summary.router)
    return app
