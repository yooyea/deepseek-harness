"""Tenant lifecycle and plugin persistence orchestration tests."""

import unittest

from app.capacity import HostMetrics
from app.database import hash_runtime_token
from app.service import TenantService
from tests.helpers import settings


class FakeSampler:
    def snapshot(self) -> HostMetrics:
        return HostMetrics(10, 0.5, 8, 16384, 12000, 100, 80, 80)


class FakeCipher:
    def encrypt(self, value: str) -> str:
        return f"encrypted:{value}"

    def decrypt(self, value: str) -> str:
        return value.removeprefix("encrypted:")


class FakeStore:
    def plugin_key(self, slug: str, name: str, version: str, sha256: str) -> str:
        return f"tenants/{slug}/{name}/{version}/{sha256}.tgz"

    def create_upload(self, key: str, _: str):
        return {"url": f"https://upload/{key}", "headers": {"x-amz-server-side-encryption": "AES256"}}

    def create_download_url(self, key: str) -> str:
        return f"https://download/{key}"

    def verify(self, _: str, __: str) -> None:
        return None


class FakeDatabase:
    def __init__(self) -> None:
        self.tenant = None
        self.plugins = []
        self.logs = []

    def list_tenants(self, include_removed: bool = False):
        if self.tenant is None or (self.tenant["status"] == "removed" and not include_removed):
            return []
        return [self.tenant]

    def create_tenant(self, values):
        self.tenant = {
            "id": 1,
            "safe_mode": False,
            "consecutive_failures": 0,
            **values,
        }
        return self.tenant

    def get_tenant(self, tenant_id):
        return self.tenant if tenant_id == 1 else None

    def update_tenant(self, tenant_id, **values):
        assert tenant_id == 1
        self.tenant.update(values)
        return self.tenant

    def add_log(self, tenant_id, action, status, detail=None):
        self.logs.append((tenant_id, action, status, detail))

    def list_logs(self):
        return []

    def list_plugins(self, tenant_id):
        return self.plugins

    def register_plugin_release(self, tenant_id, name, source_type, source_ref, version, artifact_key, sha256, manifest):
        plugin = {
            "tenant_id": tenant_id,
            "name": name,
            "source_type": source_type,
            "source_ref": source_ref,
            "desired_version": version,
            "artifact_key": artifact_key,
            "sha256": sha256,
            "manifest": manifest,
        }
        self.plugins = [plugin]
        return plugin

    def report_plugins(self, tenant_id, plugins):
        self.report = (tenant_id, plugins)

    def rollback_plugins(self, tenant_id):
        self.rolled_back = tenant_id


class FakeDocker:
    def __init__(self) -> None:
        self.created = []
        self.started = []
        self.removed = []

    def image_exists(self, _):
        return True

    def create_container(self, **values):
        self.created.append(values)
        return f"container-{len(self.created)}"

    def inspect_container(self, _):
        return {"State": {"Running": True, "Status": "running"}}

    def container_stats(self, _):
        return {}

    def ping(self):
        return True

    def start_container(self, container_id):
        self.started.append(container_id)

    def stop_container(self, _):
        return None

    def restart_container(self, _):
        return None

    def remove_container(self, container_id):
        self.removed.append(container_id)


class TenantServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.database = FakeDatabase()
        self.docker = FakeDocker()
        self.service = TenantService(
            settings(),
            self.database,
            self.docker,
            FakeSampler(),
            FakeCipher(),
            FakeStore(),
        )

    def test_create_and_rebuild_use_disposable_container(self) -> None:
        tenant = self.service.create("Alice Team", "alice", "alice-admin")
        self.assertEqual(tenant["status"], "running")
        self.assertNotIn("runtime_token_hash", tenant)
        self.assertNotIn("volume", self.docker.created[0])

        rebuilt = self.service.action(1, "rebuild")
        self.assertEqual(rebuilt["container_id"], "container-2")
        self.assertEqual(self.docker.removed, ["container-1"])
        self.assertEqual(
            self.database.tenant["runtime_token_hash"],
            hash_runtime_token(self.docker.created[1]["runtime_token"]),
        )

        recovered = self.service.action(1, "recover")
        self.assertTrue(recovered["safe_mode"])
        self.assertEqual(self.database.rolled_back, 1)
        self.assertTrue(self.docker.created[2]["safe_mode"])

    def test_register_plugin_verifies_tenant_owned_key(self) -> None:
        self.service.create("Alice Team", "alice", "admin")
        upload = self.service.plugin_upload(1, "@scope/plugin", "1.2.3", "a" * 64)
        plugin = self.service.register_plugin(
            1,
            name="@scope/plugin",
            source_type="npm",
            source_ref="@scope/plugin@1.2.3",
            version="1.2.3",
            artifact_key=upload["artifact_key"],
            sha256="a" * 64,
            manifest={"dsh": {"bundle": {"patch": "./cordis.patch.yml"}}},
        )
        self.assertEqual(plugin["desired_version"], "1.2.3")


if __name__ == "__main__":
    unittest.main()
