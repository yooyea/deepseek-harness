"""Host metrics and tenant admission decisions."""

from __future__ import annotations

import os
import shutil
import threading
from dataclasses import asdict, dataclass
from typing import Any

from .config import Settings


@dataclass(frozen=True)
class HostMetrics:
    """Current host resource snapshot."""

    cpu_percent: float
    load_1m: float
    cpu_count: int
    memory_total_mb: int
    memory_available_mb: int
    disk_total_gb: float
    disk_free_gb: float
    disk_free_percent: float

    def as_dict(self) -> dict[str, Any]:
        """Serialize metrics for the API."""
        return asdict(self)


@dataclass(frozen=True)
class CapacityDecision:
    """Result of evaluating a requested tenant allocation."""

    allowed: bool
    reasons: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        """Serialize the decision for the API."""
        return {"allowed": self.allowed, "reasons": list(self.reasons)}


def _read_cpu() -> tuple[int, int]:
    with open("/proc/stat", encoding="utf-8") as source:
        values = [int(value) for value in source.readline().split()[1:]]
    idle = values[3] + (values[4] if len(values) > 4 else 0)
    return sum(values), idle


def _read_memory() -> tuple[int, int]:
    values: dict[str, int] = {}
    with open("/proc/meminfo", encoding="utf-8") as source:
        for line in source:
            name, raw = line.split(":", 1)
            values[name] = int(raw.strip().split()[0])
    return values["MemTotal"] // 1024, values["MemAvailable"] // 1024


class ResourceSampler:
    """Continuously samples host CPU while serving current host metrics."""

    def __init__(self, interval_seconds: float = 5.0) -> None:
        self.interval_seconds = interval_seconds
        self._cpu_percent = 0.0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """Start background CPU sampling."""
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name="host-resource-sampler", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Stop background sampling."""
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=self.interval_seconds + 1)

    def _run(self) -> None:
        previous_total, previous_idle = _read_cpu()
        while not self._stop.wait(self.interval_seconds):
            total, idle = _read_cpu()
            total_delta = total - previous_total
            idle_delta = idle - previous_idle
            if total_delta > 0:
                self._cpu_percent = round(100 * (total_delta - idle_delta) / total_delta, 1)
            previous_total, previous_idle = total, idle

    def snapshot(self) -> HostMetrics:
        """Read host memory, disk, load and the latest sampled CPU usage."""
        memory_total, memory_available = _read_memory()
        disk = shutil.disk_usage("/")
        cpu_count = os.cpu_count() or 1
        return HostMetrics(
            cpu_percent=self._cpu_percent,
            load_1m=os.getloadavg()[0],
            cpu_count=cpu_count,
            memory_total_mb=memory_total,
            memory_available_mb=memory_available,
            disk_total_gb=round(disk.total / 1024**3, 1),
            disk_free_gb=round(disk.free / 1024**3, 1),
            disk_free_percent=round(disk.free * 100 / disk.total, 1),
        )


def evaluate_capacity(
    settings: Settings,
    metrics: HostMetrics,
    tenants: list[dict[str, Any]],
    requested_cpu: float,
    requested_memory_mb: int,
) -> CapacityDecision:
    """Evaluate actual pressure and reserved tenant resources."""
    active = [tenant for tenant in tenants if tenant["status"] != "removed"]
    reserved_cpu = sum(float(tenant["cpu_limit"]) for tenant in active)
    reserved_memory = sum(int(tenant["memory_mb"]) for tenant in active)
    reasons: list[str] = []
    if metrics.cpu_percent >= settings.max_cpu_percent:
        reasons.append(f"CPU 使用率 {metrics.cpu_percent:.1f}% 已达到 {settings.max_cpu_percent:.1f}% 阈值")
    if metrics.load_1m >= metrics.cpu_count * settings.max_load_ratio:
        reasons.append("1 分钟系统负载过高")
    if metrics.memory_available_mb - requested_memory_mb < settings.minimum_free_memory_mb:
        reasons.append("创建后主机可用内存将低于安全线")
    if reserved_memory + requested_memory_mb > metrics.memory_total_mb - settings.minimum_free_memory_mb:
        reasons.append("租户内存配额已接近主机容量")
    if reserved_cpu + requested_cpu > metrics.cpu_count * settings.tenant_cpu_reservation_ratio:
        reasons.append("租户 CPU 配额已达到可分配上限")
    if metrics.disk_free_percent < settings.minimum_free_disk_percent:
        reasons.append("主机磁盘剩余空间低于安全线")
    return CapacityDecision(allowed=not reasons, reasons=tuple(reasons))


def container_usage(stats: dict[str, Any]) -> dict[str, float]:
    """Calculate Docker CPU and memory usage percentages."""
    cpu = stats.get("cpu_stats", {})
    previous = stats.get("precpu_stats", {})
    cpu_total = cpu.get("cpu_usage", {}).get("total_usage", 0)
    previous_total = previous.get("cpu_usage", {}).get("total_usage", 0)
    system_total = cpu.get("system_cpu_usage", 0)
    previous_system = previous.get("system_cpu_usage", 0)
    online_cpus = cpu.get("online_cpus") or len(cpu.get("cpu_usage", {}).get("percpu_usage", [])) or 1
    cpu_delta = cpu_total - previous_total
    system_delta = system_total - previous_system
    cpu_percent = (cpu_delta / system_delta * online_cpus * 100) if system_delta > 0 and cpu_delta >= 0 else 0.0
    memory = stats.get("memory_stats", {})
    usage = max(0, int(memory.get("usage", 0)) - int(memory.get("stats", {}).get("cache", 0)))
    limit = int(memory.get("limit", 0))
    return {
        "cpu_percent": round(cpu_percent, 1),
        "memory_mb": round(usage / 1024**2, 1),
        "memory_percent": round(usage * 100 / limit, 1) if limit else 0.0,
    }
