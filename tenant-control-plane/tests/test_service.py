"""Tenant lifecycle orchestration tests."""

from pathlib import Path
import tempfile
import unittest

from app.capacity import HostMetrics
from app.config import Settings
from app.database import Database
from app.service import TenantService


class FakeSampler:
    """Returns a stable healthy host snapshot."""

    def snapshot(self) -> HostMetrics:
        """Return ample capacity for a tenant."""
        return HostMetrics(10, 0.5, 8, 16384, 12000, 100, 80, 80)


class FakeDocker:
    """Records managed Docker lifecycle calls."""

    def __init__(self) -> None:
        self.created: dict[str, object] | None = None
        self.started: list[str] = []
        self.stopped: list[str] = []
        self.removed: list[str] = []

    def image_exists(self, _: str) -> bool:
        return True

    def create_volume(self, _: str, __: str) -> None:
        return None

    def create_container(self, **values: object) -> str:
        self.created = values
        return "container-1"

    def inspect_container(self, _: str) -> dict[str, object]:
        return {"Config": {"Labels": {"com.deepharness.tenant-managed": "true"}}, "State": {"Running": True}}

    def start_container(self, container_id: str) -> None:
        self.started.append(container_id)

    def stop_container(self, container_id: str) -> None:
        self.stopped.append(container_id)

    def restart_container(self, _: str) -> None:
        return None

    def remove_container(self, container_id: str) -> None:
        self.removed.append(container_id)

    def remove_volume(self, _: str) -> None:
        raise AssertionError("default removal must preserve the data volume")


class TenantServiceTests(unittest.TestCase):
    """Creation allocates isolated resources and removal preserves data."""

    def test_create_stop_and_remove(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            settings = Settings(
                database_path=str(Path(directory) / "control-plane.db"),
                docker_socket="/var/run/docker.sock",
                admin_user="admin",
                admin_password="secret",
                tenant_image="example/harness:latest",
                public_host="203.0.113.10",
                tenant_scheme="http",
                port_start=18100,
                port_end=18110,
                default_cpu=1,
                default_memory_mb=1536,
                max_cpu_percent=70,
                max_load_ratio=0.9,
                minimum_free_memory_mb=2048,
                minimum_free_disk_percent=15,
                tenant_cpu_reservation_ratio=0.8,
            )
            database = Database(settings.database_path)
            database.initialize()
            docker = FakeDocker()
            service = TenantService(settings, database, docker, FakeSampler())

            tenant = service.create("Alice Team", "alice", "alice-admin")
            self.assertEqual(tenant["status"], "running")
            self.assertEqual(tenant["url"], "http://203.0.113.10:18100")
            self.assertGreater(len(tenant["initial_password"]), 24)
            self.assertEqual(docker.created["volume"], "deepharness-tenant-alice-data")
            self.assertEqual(docker.started, ["container-1"])

            service.action(tenant["id"], "stop")
            self.assertEqual(docker.stopped, ["container-1"])
            removed = service.remove(tenant["id"])
            self.assertEqual(removed["status"], "removed")
            self.assertEqual(docker.removed, ["container-1"])


if __name__ == "__main__":
    unittest.main()
