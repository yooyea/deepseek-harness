"""FastAPI entry point for the DeepHarness tenant control plane."""

from __future__ import annotations

import binascii
import hmac
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .capacity import ResourceSampler
from .config import Settings
from .crypto import SecretCipher
from .database import Database
from .docker_client import DockerClient
from .object_store import ObjectStore
from .service import TenantError, TenantService

settings = Settings.from_env()
database = Database(settings.database_url)
docker = DockerClient(settings.docker_socket)
sampler = ResourceSampler()
cipher = SecretCipher(settings.secret_key)
object_store = ObjectStore(
    settings.oss_endpoint,
    settings.oss_region,
    settings.oss_bucket,
    settings.oss_access_key_id,
    settings.oss_access_key_secret,
)
service = TenantService(settings, database, docker, sampler, cipher, object_store)
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
    if request.url.path == "/api/health" or request.url.path.startswith("/api/runtime/"):
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


class PluginUpload(BaseModel):
    """Fields used to reserve one immutable object key."""

    name: str = Field(min_length=1, max_length=128, pattern=r"^[@a-zA-Z0-9][@a-zA-Z0-9._/-]*$")
    version: str = Field(min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9][a-zA-Z0-9._+-]*$")
    sha256: str = Field(pattern=r"^[a-fA-F0-9]{64}$")


class PluginRegister(PluginUpload):
    """Metadata committed after the artifact upload succeeds."""

    artifact_key: str
    source_type: str = Field(pattern=r"^(generated|npm|upload)$")
    source_ref: str | None = Field(default=None, max_length=512)
    manifest: dict[str, Any] = Field(default_factory=dict)


class RuntimePlugin(BaseModel):
    """One plugin version observed by a tenant process."""

    name: str
    version: str
    healthy: bool
    error: str | None = None


class RuntimeReport(BaseModel):
    """Complete runtime inventory reported by one tenant."""

    plugins: list[RuntimePlugin]


@app.exception_handler(TenantError)
async def tenant_error(_: Request, error: TenantError) -> JSONResponse:
    """Expose actionable tenant errors without stack traces."""
    return JSONResponse({"detail": str(error)}, status_code=409)


@app.get("/api/health")
def health() -> JSONResponse:
    """Return dependency health without requiring administrator credentials."""
    dependencies = {
        "docker": docker.ping(),
        "database": database.ping(),
        "object_store": object_store.ping(),
    }
    healthy = all(dependencies.values())
    return JSONResponse(
        {"status": "ok" if healthy else "degraded", **dependencies},
        status_code=200 if healthy else 503,
    )


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
def remove_tenant(tenant_id: int) -> dict[str, Any]:
    """Remove a tenant container while retaining PostgreSQL and OSS records."""
    return service.remove(tenant_id)


def _runtime_tenant(request: Request) -> dict[str, Any]:
    authorization = request.headers.get("authorization", "")
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="缺少租户运行时令牌")
    tenant = database.get_tenant_by_token(authorization[7:])
    if tenant is None:
        raise HTTPException(status_code=401, detail="租户运行时令牌无效")
    return tenant


@app.get("/api/runtime/plugins")
def runtime_plugins(request: Request) -> dict[str, Any]:
    """Return desired plugin releases to the authenticated tenant."""
    return service.runtime_plugins(_runtime_tenant(request))


@app.post("/api/runtime/plugins/uploads")
def runtime_plugin_upload(request: Request, payload: PluginUpload) -> dict[str, str]:
    """Reserve a tenant-owned OSS key and short-lived upload URL."""
    tenant = _runtime_tenant(request)
    return service.plugin_upload(tenant["id"], payload.name, payload.version, payload.sha256)


@app.post("/api/runtime/plugins/register")
def runtime_plugin_register(request: Request, payload: PluginRegister) -> dict[str, Any]:
    """Commit a verified OSS artifact as the desired plugin version."""
    tenant = _runtime_tenant(request)
    return service.register_plugin(tenant["id"], **payload.model_dump())


@app.post("/api/runtime/plugins/report", status_code=204)
def runtime_plugin_report(request: Request, payload: RuntimeReport) -> Response:
    """Reconcile one tenant's complete observed plugin inventory."""
    tenant = _runtime_tenant(request)
    service.report_runtime_plugins(tenant, [item.model_dump() for item in payload.plugins])
    return Response(status_code=204)


@app.post("/api/runtime/rebuild", status_code=202)
def runtime_rebuild(request: Request, background_tasks: BackgroundTasks) -> dict[str, str]:
    """Let an authenticated tenant request replacement after publishing a plugin."""
    tenant = _runtime_tenant(request)
    background_tasks.add_task(service.action, tenant["id"], "rebuild")
    return {"status": "rebuild-scheduled"}


app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.get("/", response_class=FileResponse)
def index() -> FileResponse:
    """Serve the administrator dashboard."""
    return FileResponse(static_dir / "index.html")
