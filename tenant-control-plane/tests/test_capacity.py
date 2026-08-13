"""Capacity admission unit tests."""

from dataclasses import replace
import unittest

from app.capacity import HostMetrics, evaluate_capacity
from app.config import Settings


SETTINGS = Settings(
    database_path=":memory:",
    docker_socket="/var/run/docker.sock",
    admin_user="admin",
    admin_password="secret",
    tenant_image="example/harness:latest",
    public_host="127.0.0.1",
    tenant_scheme="http",
    port_start=8100,
    port_end=8199,
    default_cpu=1,
    default_memory_mb=1536,
    max_cpu_percent=70,
    max_load_ratio=0.9,
    minimum_free_memory_mb=2048,
    minimum_free_disk_percent=15,
    tenant_cpu_reservation_ratio=0.8,
)

METRICS = HostMetrics(
    cpu_percent=20,
    load_1m=1,
    cpu_count=8,
    memory_total_mb=16384,
    memory_available_mb=12000,
    disk_total_gb=100,
    disk_free_gb=60,
    disk_free_percent=60,
)


class CapacityTests(unittest.TestCase):
    """Admission rejects pressure and reservation overcommit."""

    def test_allows_healthy_host(self) -> None:
        decision = evaluate_capacity(SETTINGS, METRICS, [], 1, 1536)
        self.assertTrue(decision.allowed)
        self.assertEqual(decision.reasons, ())

    def test_rejects_high_cpu(self) -> None:
        decision = evaluate_capacity(SETTINGS, replace(METRICS, cpu_percent=81), [], 1, 1536)
        self.assertFalse(decision.allowed)
        self.assertTrue(any("CPU" in reason for reason in decision.reasons))

    def test_counts_error_instances_as_reserved(self) -> None:
        tenants = [{"status": "error", "cpu_limit": 6, "memory_mb": 12000}]
        decision = evaluate_capacity(SETTINGS, METRICS, tenants, 1, 1536)
        self.assertFalse(decision.allowed)
        self.assertTrue(any("配额" in reason for reason in decision.reasons))


if __name__ == "__main__":
    unittest.main()
