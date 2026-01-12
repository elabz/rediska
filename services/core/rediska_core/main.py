"""Rediska Core API - Main Application."""

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from rediska_core.api.middleware.onboarding import OnboardingGateMiddleware
from rediska_core.api.routes import accounts as accounts_routes
from rediska_core.api.routes import attachment as attachment_routes
from rediska_core.api.routes import audit as audit_routes
from rediska_core.api.routes import auth as auth_routes
from rediska_core.api.routes import conversation as conversation_routes
from rediska_core.api.routes import directory as directory_routes
from rediska_core.api.routes import identity as identity_routes
from rediska_core.api.routes import leads as leads_routes
from rediska_core.api.routes import metrics as metrics_routes
from rediska_core.api.routes import ops as ops_routes
from rediska_core.api.routes import reddit_oauth as reddit_oauth_routes
from rediska_core.api.routes import search as search_routes
from rediska_core.api.routes import setup as setup_routes
from rediska_core.api.routes import sources as sources_routes
from rediska_core.config import get_settings


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan handler."""
    # Startup
    settings = get_settings()
    app.state.settings = settings
    yield
    # Shutdown


app = FastAPI(
    title="Rediska Core API",
    description="Local-first conversation management and lead discovery system",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS configuration for local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://rediska.local", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Onboarding gate middleware (blocks access until identity is created)
app.add_middleware(OnboardingGateMiddleware)

# Include API routers
app.include_router(accounts_routes.router)
app.include_router(attachment_routes.router)
app.include_router(audit_routes.router)
app.include_router(auth_routes.router)
app.include_router(conversation_routes.router)
app.include_router(directory_routes.router)
app.include_router(identity_routes.router)
app.include_router(leads_routes.router)
app.include_router(metrics_routes.router)
app.include_router(ops_routes.router)
app.include_router(reddit_oauth_routes.router)
app.include_router(search_routes.router)
app.include_router(setup_routes.router)
app.include_router(sources_routes.router)


@app.get("/healthz")
async def health_check() -> dict:
    """Health check endpoint."""
    return {"ok": True, "service": "rediska-core"}


@app.get("/")
async def root() -> dict:
    """Root endpoint."""
    return {
        "name": "Rediska Core API",
        "version": "0.1.0",
        "status": "running",
    }
