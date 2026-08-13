"""Tenant lifecycle orchestration."""

from __future__ import annotations

import re
import secrets
import socket
import sqlite3
import threading
from typing import Any

from .capacity import ResourceSampler, container_usage, evaluate_capacity
from .config import Settings
from .database import Database
from .docker_client import DockerClient, DockerError


SLUG_PATTERN = re.compile(r"^[a-z][a-z0-9-]{1,30}[a-z0-9]$")


class TenantError(RuntimeError):
    """Tenant request cannot be completed safely."""


class TenantService:
    """Coordinates SQLite state, capacity checks and Docker operations."""

    def __init__(
        self,
        settings: Settings,
        database: Database,
        docker: DockerClient,
        sampler: ResourceSampler,
    ) -> None:
        self.settings = settings
        self.database = database
        self.docker = docker
        self.sampler = sampler
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
            enriched.append({**tenant, "runtime": runtime, "url": self._tenant_url(tenant)})
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
            volume_name = f"deepharness-tenant-{slug}-data"
            password = secrets.token_urlsafe(24)
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
                        "volume_name": volume_name,
                        "image": self.settings.tenant_image,
                        "cpu_limit": self.settings.default_cpu,
                        "memory_mb": self.settings.default_memory_mb,
                    }
                )
                self.docker.create_volume(volume_name, slug)
                container_id = self.docker.create_container(
                    name=container_name,
                    slug=slug,
                    image=self.settings.tenant_image,
                    volume=volume_name,
                    host_port=port,
                    access_username=access_username,
                    access_password=password,
                    trusted_host=self.settings.public_host,
                    cpu_limit=self.settings.default_cpu,
                    memory_mb=self.settings.default_memory_mb,
                )
                self.docker.start_container(container_id)
                tenant = self.database.update_tenant(tenant["id"], status="running", container_id=container_id, last_error=None)
                self.database.add_log(tenant["id"], "create", "success", f"port={port}")
            except (DockerError, sqlite3.Error) as error:
                if tenant:
                    self.database.update_tenant(tenant["id"], status="error", last_error=str(error))
                    self.database.add_log(tenant["id"], "create", "failed", str(error))
                raise TenantError(str(error)) from error
            return {**tenant, "url": self._tenant_url(tenant), "initial_password": password}

    def action(self, tenant_id: int, action: str) -> dict[str, Any]:
        """Start, stop or restart one managed tenant."""
        if action not in {"start", "stop", "restart"}:
            raise TenantError("不支持的实例操作")
        with self._mutation_lock:
            tenant = self._require_tenant(tenant_id)
            container_id = tenant.get("container_id")
            if not container_id:
                raise TenantError("实例容器不存在")
            try:
                if action == "start":
                    self.docker.start_container(container_id)
                    status = "running"
                elif action == "stop":
                    self.docker.stop_container(container_id)
                    status = "stopped"
                else:
                    self.docker.restart_container(container_id)
                    status = "running"
                tenant = self.database.update_tenant(tenant_id, status=status, last_error=None)
                self.database.add_log(tenant_id, action, "success")
                return tenant
            except DockerError as error:
                self.database.update_tenant(tenant_id, status="error", last_error=str(error))
                self.database.add_log(tenant_id, action, "failed", str(error))
                raise TenantError(str(error)) from error

    def remove(self, tenant_id: int, purge_volume: bool = False) -> dict[str, Any]:
        """Remove a managed container and optionally its persistent data."""
        with self._mutation_lock:
            tenant = self._require_tenant(tenant_id)
            try:
                if tenant.get("container_id"):
                    self.docker.remove_container(tenant["container_id"])
                if purge_volume:
                    self.docker.remove_volume(tenant["volume_name"])
                tenant = self.database.update_tenant(tenant_id, status="removed", container_id=None, last_error=None)
                detail = "volume purged" if purge_volume else "volume preserved"
                self.database.add_log(tenant_id, "remove", "success", detail)
                return tenant
            except DockerError as error:
                self.database.update_tenant(tenant_id, status="error", last_error=str(error))
                self.database.add_log(tenant_id, "remove", "failed", str(error))
                raise TenantError(str(error)) from error

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
