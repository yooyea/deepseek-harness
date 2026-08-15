"""Tenant lifecycle orchestration."""

from __future__ import annotations

import re
import secrets
import socket
import threading
from typing import Any

from .capacity import ResourceSampler, container_usage, evaluate_capacity
from .config import Settings
from .crypto import SecretCipher
from .database import Database, hash_runtime_token
from .docker_client import DockerClient, DockerError
from .object_store import ObjectStore, ObjectStoreError

SLUG_PATTERN = re.compile(r"^[a-z][a-z0-9-]{1,30}[a-z0-9]$")


class TenantError(RuntimeError):
    """Tenant request cannot be completed safely."""


class TenantService:
    """Coordinate PostgreSQL state, OSS artifacts and Docker operations."""

    def __init__(
        self,
        settings: Settings,
        database: Database,
        docker: DockerClient,
        sampler: ResourceSampler,
        cipher: SecretCipher,
        object_store: ObjectStore,
    ) -> None:
        self.settings = settings
        self.database = database
        self.docker = docker
        self.sampler = sampler
        self.cipher = cipher
        self.object_store = object_store
        self._mutation_lock = threading.Lock()

    def dashboard(self) -> dict[str, Any]:
        """Return host capacity, tenant runtime state and recent operations."""
        tenants = self.database.list_tenants()
        metrics = self.sampler.snapshot()
        decision = evaluate_capacity(
            self.settings,
            metrics,
            tenants,
            self.settings.default_cpu,
            self.settings.default_memory_mb,
        )
        enriched: list[dict[str, Any]] = []
        for tenant in tenants:
            runtime = {"running": False, "health": "unknown", "cpu_percent": 0.0, "memory_mb": 0.0, "memory_percent": 0.0}
            container_id = tenant.get("container_id")
            if container_id:
                try:
                    inspection = self.docker.inspect_container(container_id)
                    state = inspection.get("State", {})
                    runtime["running"] = bool(state.get("Running"))
                    runtime["health"] = state.get("Health", {}).get("Status", state.get("Status", "unknown"))
                    if runtime["running"]:
                        runtime.update(container_usage(self.docker.container_stats(container_id)))
                except DockerError as error:
                    runtime["health"] = "missing" if "returned 404" in str(error) else "unavailable"
            enriched.append({
                **self._public_tenant(tenant),
                "runtime": runtime,
                "url": self._tenant_url(tenant),
                "plugins": self.database.list_plugins(tenant["id"]),
            })
        return {
            "host": metrics.as_dict(),
            "capacity": decision.as_dict(),
            "docker_available": self.docker.ping(),
            "defaults": {"cpu_limit": self.settings.default_cpu, "memory_mb": self.settings.default_memory_mb},
            "tenants": enriched,
            "logs": self.database.list_logs(),
        }

    def create(self, name: str, slug: str, access_username: str) -> dict[str, Any]:
        """Create and start an isolated Harness tenant."""
        name = name.strip()
        slug = slug.strip().lower()
        access_username = access_username.strip()
        if not name or len(name) > 80:
            raise TenantError("租户名称不能为空且不能超过 80 个字符")
        if not SLUG_PATTERN.fullmatch(slug):
            raise TenantError("租户标识需为 3-32 位小写字母、数字或连字符，并以字母开头")
        if not access_username or len(access_username) > 64:
            raise TenantError("登录用户名不能为空且不能超过 64 个字符")
        with self._mutation_lock:
            tenants = self.database.list_tenants(include_removed=True)
            if any(tenant["slug"] == slug for tenant in tenants):
                raise TenantError("租户标识已经使用过，请换一个标识")
            metrics = self.sampler.snapshot()
            decision = evaluate_capacity(
                self.settings,
                metrics,
                tenants,
                self.settings.default_cpu,
                self.settings.default_memory_mb,
            )
            if not decision.allowed:
                raise TenantError("当前服务器不允许创建租户：" + "；".join(decision.reasons))
            if not self.docker.image_exists(self.settings.tenant_image):
                raise TenantError("服务器尚未拉取指定 Harness 镜像")
            port = self._allocate_port(tenants)
            container_name = f"deepharness-tenant-{slug}"
            password = secrets.token_urlsafe(24)
            runtime_token = secrets.token_urlsafe(32)
            tenant: dict[str, Any] | None = None
            try:
                tenant = self.database.create_tenant(
                    {
                        "slug": slug,
                        "name": name,
                        "status": "creating",
                        "access_username": access_username,
                        "host_port": port,
                        "container_name": container_name,
                        "image": self.settings.tenant_image,
                        "cpu_limit": self.settings.default_cpu,
                        "memory_mb": self.settings.default_memory_mb,
                        "access_password_encrypted": self.cipher.encrypt(password),
                        "runtime_token_encrypted": self.cipher.encrypt(runtime_token),
                        "runtime_token_hash": hash_runtime_token(runtime_token),
                    }
                )
                container_id = self.docker.create_container(
                    name=container_name,
                    slug=slug,
                    image=self.settings.tenant_image,
                    host_port=port,
                    access_username=access_username,
                    access_password=password,
                    trusted_host=self.settings.public_host,
                    cpu_limit=self.settings.default_cpu,
                    memory_mb=self.settings.default_memory_mb,
                    runtime_url=self.settings.runtime_base_url,
                    runtime_token=runtime_token,
                )
                self.docker.start_container(container_id)
                tenant = self.database.update_tenant(tenant["id"], status="running", container_id=container_id, last_error=None)
                self.database.add_log(tenant["id"], "create", "success", f"port={port}")
            except (DockerError, RuntimeError) as error:
                if tenant:
                    self.database.update_tenant(tenant["id"], status="error", last_error=str(error))
                    self.database.add_log(tenant["id"], "create", "failed", str(error))
                raise TenantError(str(error)) from error
            return {
                **self._public_tenant(tenant),
                "url": self._tenant_url(tenant),
                "initial_password": password,
            }

    def action(self, tenant_id: int, action: str) -> dict[str, Any]:
        """Start, stop or restart one managed tenant."""
        if action not in {"start", "stop", "restart", "rebuild", "recover"}:
            raise TenantError("不支持的实例操作")
        with self._mutation_lock:
            tenant = self._require_tenant(tenant_id)
            container_id = tenant.get("container_id")
            if not container_id and action not in {"rebuild", "recover"}:
                raise TenantError("实例容器不存在")
            try:
                if action in {"rebuild", "recover"}:
                    if action == "recover":
                        self.database.rollback_plugins(tenant_id)
                    tenant = self._replace_container(tenant, safe_mode=action == "recover")
                    status = "running"
                elif action == "start":
                    self.docker.start_container(container_id)
                    status = "running"
                elif action == "stop":
                    self.docker.stop_container(container_id)
                    status = "stopped"
                else:
                    self.docker.restart_container(container_id)
                    status = "running"
                if action not in {"rebuild", "recover"}:
                    tenant = self.database.update_tenant(tenant_id, status=status, last_error=None)
                self.database.add_log(tenant_id, action, "success")
                return self._public_tenant(tenant)
            except DockerError as error:
                self.database.update_tenant(tenant_id, status="error", last_error=str(error))
                self.database.add_log(tenant_id, action, "failed", str(error))
                raise TenantError(str(error)) from error

    def remove(self, tenant_id: int) -> dict[str, Any]:
        """Remove a managed container; durable state remains in PostgreSQL and OSS."""
        with self._mutation_lock:
            tenant = self._require_tenant(tenant_id)
            try:
                if tenant.get("container_id"):
                    self.docker.remove_container(tenant["container_id"])
                tenant = self.database.update_tenant(tenant_id, status="removed", container_id=None, last_error=None)
                self.database.add_log(tenant_id, "remove", "success", "container removed")
                return self._public_tenant(tenant)
            except DockerError as error:
                self.database.update_tenant(tenant_id, status="error", last_error=str(error))
                self.database.add_log(tenant_id, "remove", "failed", str(error))
                raise TenantError(str(error)) from error

    def plugin_upload(
        self,
        tenant_id: int,
        name: str,
        version: str,
        sha256: str,
    ) -> dict[str, Any]:
        """Return a tenant-owned short-lived URL for one immutable plugin artifact."""
        tenant = self._require_tenant(tenant_id)
        key = self.object_store.plugin_key(tenant["slug"], name, version, sha256)
        upload = self.object_store.create_upload(key, sha256)
        return {
            "artifact_key": key,
            "upload_url": upload["url"],
            "upload_headers": upload["headers"],
        }

    def register_plugin(
        self,
        tenant_id: int,
        *,
        name: str,
        source_type: str,
        source_ref: str | None,
        version: str,
        artifact_key: str,
        sha256: str,
        manifest: dict[str, Any],
    ) -> dict[str, Any]:
        """Verify an uploaded artifact before recording it as desired state."""
        tenant = self._require_tenant(tenant_id)
        expected = self.object_store.plugin_key(tenant["slug"], name, version, sha256)
        if artifact_key != expected:
            raise TenantError("插件对象路径与租户、名称或版本不匹配")
        try:
            self.object_store.verify(artifact_key, sha256)
        except ObjectStoreError as error:
            raise TenantError(str(error)) from error
        try:
            plugin = self.database.register_plugin_release(
                tenant_id, name, source_type, source_ref, version, artifact_key, sha256, manifest
            )
        except ValueError as error:
            raise TenantError(str(error)) from error
        self.database.add_log(tenant_id, "plugin-register", "success", f"{name}@{version}")
        return plugin

    def runtime_plugins(self, tenant: dict[str, Any]) -> dict[str, Any]:
        """Return desired plugin releases as short-lived private downloads."""
        plugins = self.database.list_plugins(tenant["id"])
        return {
            "safe_mode": tenant["safe_mode"],
            "plugins": [
                {
                    "name": plugin["name"],
                    "version": plugin["desired_version"],
                    "sha256": plugin["sha256"],
                    "manifest": plugin["manifest"],
                    "download_url": self.object_store.create_download_url(plugin["artifact_key"]),
                }
                for plugin in plugins
                if plugin["desired_version"] and plugin["artifact_key"]
            ],
        }

    def report_runtime_plugins(self, tenant: dict[str, Any], plugins: list[dict[str, Any]]) -> None:
        """Persist a tenant container's observed plugin inventory."""
        self.database.report_plugins(tenant["id"], plugins)
        self.database.update_tenant(
            tenant["id"],
            safe_mode=False,
            consecutive_failures=0,
            last_error=None,
        )

    def _replace_container(self, tenant: dict[str, Any], safe_mode: bool) -> dict[str, Any]:
        """Replace one disposable tenant container from durable desired state."""
        if tenant.get("container_id"):
            try:
                self.docker.remove_container(tenant["container_id"])
            except DockerError as error:
                if "returned 404" not in str(error):
                    raise
        password = self.cipher.decrypt(tenant["access_password_encrypted"])
        runtime_token = secrets.token_urlsafe(32)
        container_id = self.docker.create_container(
            name=tenant["container_name"],
            slug=tenant["slug"],
            image=tenant["image"],
            host_port=tenant["host_port"],
            access_username=tenant["access_username"],
            access_password=password,
            trusted_host=self.settings.public_host,
            cpu_limit=tenant["cpu_limit"],
            memory_mb=tenant["memory_mb"],
            runtime_url=self.settings.runtime_base_url,
            runtime_token=runtime_token,
            safe_mode=safe_mode,
        )
        self.docker.start_container(container_id)
        return self.database.update_tenant(
            tenant["id"],
            status="running",
            container_id=container_id,
            safe_mode=safe_mode,
            runtime_token_encrypted=self.cipher.encrypt(runtime_token),
            runtime_token_hash=hash_runtime_token(runtime_token),
            last_error=None,
        )

    def _require_tenant(self, tenant_id: int) -> dict[str, Any]:
        tenant = self.database.get_tenant(tenant_id)
        if not tenant or tenant["status"] == "removed":
            raise TenantError("租户不存在")
        return tenant

    def _allocate_port(self, tenants: list[dict[str, Any]]) -> int:
        used = {int(tenant["host_port"]) for tenant in tenants if tenant["status"] != "removed"}
        for port in range(self.settings.port_start, self.settings.port_end + 1):
            if port not in used and self._port_available(port):
                return port
        raise TenantError("租户端口池已经耗尽")

    @staticmethod
    def _port_available(port: int) -> bool:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                probe.bind(("0.0.0.0", port))
            except OSError:
                return False
        return True

    def _tenant_url(self, tenant: dict[str, Any]) -> str:
        return f"{self.settings.tenant_scheme}://{self.settings.public_host}:{tenant['host_port']}"

    @staticmethod
    def _public_tenant(tenant: dict[str, Any]) -> dict[str, Any]:
        """Remove encrypted and hashed credentials from administrator responses."""
        hidden = {
            "access_password_encrypted",
            "runtime_token_encrypted",
            "runtime_token_hash",
        }
        return {name: value for name, value in tenant.items() if name not in hidden}
