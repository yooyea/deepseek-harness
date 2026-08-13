"""Environment-backed control-plane configuration."""

from __future__ import annotations

from dataclasses import dataclass
import os


def _required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} must be set")
    return value


@dataclass(frozen=True)
class Settings:
    """Validated process configuration."""

    database_path: str
    docker_socket: str
    admin_user: str
    admin_password: str
    tenant_image: str
    public_host: str
    tenant_scheme: str
    port_start: int
    port_end: int
    default_cpu: float
    default_memory_mb: int
    max_cpu_percent: float
    max_load_ratio: float
    minimum_free_memory_mb: int
    minimum_free_disk_percent: float
    tenant_cpu_reservation_ratio: float

    @classmethod
    def from_env(cls) -> "Settings":
        """Load configuration from environment variables."""
        settings = cls(
            database_path=os.environ.get("CONTROL_PLANE_DB", "/data/control-plane.db"),
            docker_socket=os.environ.get("DOCKER_SOCKET", "/var/run/docker.sock"),
            admin_user=os.environ.get("CONTROL_PLANE_ADMIN_USER", "admin").strip(),
            admin_password=_required("CONTROL_PLANE_ADMIN_PASSWORD"),
            tenant_image=os.environ.get(
                "TENANT_HARNESS_IMAGE",
                "crpi-nwybe4ublujm62d9.cn-hongkong.personal.cr.aliyuncs.com/linehalo/harness:latest",
            ).strip(),
            public_host=os.environ.get("CONTROL_PLANE_PUBLIC_HOST", "127.0.0.1").strip(),
            tenant_scheme=os.environ.get("TENANT_PUBLIC_SCHEME", "http").strip(),
            port_start=int(os.environ.get("TENANT_PORT_START", "8100")),
            port_end=int(os.environ.get("TENANT_PORT_END", "8199")),
            default_cpu=float(os.environ.get("TENANT_DEFAULT_CPU", "1")),
            default_memory_mb=int(os.environ.get("TENANT_DEFAULT_MEMORY_MB", "1536")),
            max_cpu_percent=float(os.environ.get("CAPACITY_MAX_CPU_PERCENT", "70")),
            max_load_ratio=float(os.environ.get("CAPACITY_MAX_LOAD_RATIO", "0.9")),
            minimum_free_memory_mb=int(os.environ.get("CAPACITY_MIN_FREE_MEMORY_MB", "2048")),
            minimum_free_disk_percent=float(os.environ.get("CAPACITY_MIN_FREE_DISK_PERCENT", "15")),
            tenant_cpu_reservation_ratio=float(os.environ.get("CAPACITY_CPU_RESERVATION_RATIO", "0.8")),
        )
        if not settings.admin_user:
            raise RuntimeError("CONTROL_PLANE_ADMIN_USER must not be empty")
        if settings.port_start < 1024 or settings.port_end > 65535 or settings.port_start > settings.port_end:
            raise RuntimeError("TENANT_PORT_START and TENANT_PORT_END define an invalid range")
        if settings.default_cpu <= 0 or settings.default_memory_mb < 128:
            raise RuntimeError("tenant CPU and memory defaults must be positive")
        if settings.tenant_scheme not in {"http", "https"}:
            raise RuntimeError("TENANT_PUBLIC_SCHEME must be http or https")
        return settings
