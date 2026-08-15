"""PostgreSQL schema and runtime-token tests."""

import unittest

from app.database import SCHEMA, hash_runtime_token


class DatabaseTests(unittest.TestCase):
    """Durable state includes tenant plugin reconciliation fields."""

    def test_schema_owns_plugin_versions_and_safe_mode(self) -> None:
        self.assertIn("CREATE TABLE IF NOT EXISTS tenant_plugins", SCHEMA)
        self.assertIn("CREATE TABLE IF NOT EXISTS plugin_releases", SCHEMA)
        self.assertIn("last_healthy_version", SCHEMA)
        self.assertIn("safe_mode", SCHEMA)

    def test_runtime_token_hash_is_stable_and_irreversible(self) -> None:
        digest = hash_runtime_token("tenant-token")
        self.assertEqual(len(digest), 64)
        self.assertEqual(digest, hash_runtime_token("tenant-token"))
        self.assertNotIn("tenant-token", digest)


if __name__ == "__main__":
    unittest.main()
