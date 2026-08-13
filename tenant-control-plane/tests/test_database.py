"""SQLite repository unit tests."""

from pathlib import Path
import tempfile
import unittest

from app.database import Database


class DatabaseTests(unittest.TestCase):
    """Tenant records and logs persist together."""

    def test_tenant_lifecycle_and_log(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Database(str(Path(directory) / "control-plane.db"))
            database.initialize()
            tenant = database.create_tenant(
                {
                    "slug": "alice",
                    "name": "Alice",
                    "status": "creating",
                    "access_username": "admin",
                    "host_port": 8100,
                    "container_name": "deepharness-tenant-alice",
                    "volume_name": "deepharness-tenant-alice-data",
                    "image": "example/harness:latest",
                    "cpu_limit": 1,
                    "memory_mb": 1536,
                }
            )
            database.update_tenant(tenant["id"], status="running", container_id="container-id")
            database.add_log(tenant["id"], "create", "success")

            loaded = database.get_tenant(tenant["id"])
            self.assertEqual(loaded["status"], "running")
            self.assertEqual(loaded["container_id"], "container-id")
            self.assertEqual(database.list_logs()[0]["tenant_name"], "Alice")


if __name__ == "__main__":
    unittest.main()
