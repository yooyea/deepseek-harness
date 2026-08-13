"""FastAPI entry point for the DeepHarness tenant control plane."""

from __future__ import annotations

from contextlib import asynccontextmanager
import binascii
import hmac
from pathlib import Path
from typing import Any, AsyncIterator

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .capacity import ResourceSampler
from .config import Settings
from .database import Database
from .docker_client import DockerClient
from .service import TenantError, TenantService


settings = Settings.from_env()
database = Database(settings.database_path)
docker = DockerClient(settings.docker_socket)
sampler = ResourceSampler()
service = TenantService(settings, database, docker, sampler)
static_dir = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Initialize durable state and resource sampling."""
    database.initialize()
    sampler.start()
    try:
        yield
    finally:
        sampler.stop()


app = FastAPI(title="DeepHarness Tenant Control Plane", version="0.1.0", lifespan=lifespan)


def _unauthorized() -> Response:
    return Response(status_code=401, headers={"WWW-Authenticate": 'Basic realm="DeepHarness Control Plane"'})


@app.middleware("http")
async def admin_auth(request: Request, call_next: Any) -> Response:
    """Protect every control-plane resource except the health probe."""
    if request.url.path == "/api/health":
        return await call_next(request)
    authorization = request.headers.get("authorization", "")
    if not authorization.startswith("Basic "):
        return _unauthorized()
    import base64

    try:
        username, password = base64.b64decode(authorization[6:]).decode().split(":", 1)
    except (binascii.Error, ValueError, UnicodeDecodeError):
        return _unauthorized()
    if not hmac.compare_digest(username, settings.admin_user) or not hmac.compare_digest(password, settings.admin_password):
        return _unauthorized()
    if request.method not in {"GET", "HEAD", "OPTIONS"} and request.headers.get("x-control-plane-csrf") != "1":
        return JSONResponse({"detail": "missing mutation protection header"}, status_code=403)
    return await call_next(request)


class TenantCreate(BaseModel):
    """New tenant fields accepted from the administrator."""

    name: str = Field(min_length=1, max_length=80)
    slug: str = Field(min_length=3, max_length=32)
    access_username: str = Field(default="admin", min_length=1, max_length=64)


class TenantAction(BaseModel):
    """Allowed tenant runtime operation."""

    action: str


@app.exception_handler(TenantError)
async def tenant_error(_: Request, error: TenantError) -> JSONResponse:
    """Expose actionable tenant errors without stack traces."""
    return JSONResponse({"detail": str(error)}, status_code=409)


@app.get("/api/health")
def health() -> dict[str, Any]:
    """Return liveness and Docker connectivity."""
    return {"status": "ok", "docker": docker.ping()}


@app.get("/api/dashboard")
def dashboard() -> dict[str, Any]:
    """Return the full administrator dashboard model."""
    return service.dashboard()


@app.post("/api/tenants", status_code=201)
def create_tenant(payload: TenantCreate) -> dict[str, Any]:
    """Provision one isolated Harness instance."""
    return service.create(payload.name, payload.slug, payload.access_username)


@app.post("/api/tenants/{tenant_id}/actions")
def tenant_action(tenant_id: int, payload: TenantAction) -> dict[str, Any]:
    """Change one tenant container's runtime state."""
    return service.action(tenant_id, payload.action)


@app.delete("/api/tenants/{tenant_id}")
def remove_tenant(tenant_id: int, purge_volume: bool = False) -> dict[str, Any]:
    """Remove a tenant container and optionally its persistent volume."""
    return service.remove(tenant_id, purge_volume)


app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.get("/", response_class=FileResponse)
def index() -> FileResponse:
    """Serve the administrator dashboard."""
    return FileResponse(static_dir / "index.html")
