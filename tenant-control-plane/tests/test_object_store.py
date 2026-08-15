"""Object-key isolation and checksum verification tests."""

import io
import unittest

from app.object_store import ObjectStore, ObjectStoreError


class FakeClient:
    def __init__(self, content: bytes) -> None:
        self.content = content

    def get_object(self, **_):
        return {"Body": io.BytesIO(self.content)}


class FakeSigner:
    def __init__(self) -> None:
        self.params = None

    def generate_presigned_url(self, operation, *, Params, ExpiresIn):
        self.params = (operation, Params, ExpiresIn)
        return "https://upload.example/signed"


class ObjectStoreTests(unittest.TestCase):
    def test_plugin_key_contains_tenant_name_and_version(self) -> None:
        key = ObjectStore.plugin_key("alice", "@scope/plugin", "1.2.3", "a" * 64)
        self.assertEqual(key, f"tenants/alice/plugins/scope__plugin/1.2.3/{'a' * 64}.tgz")

    def test_verify_rejects_changed_artifact(self) -> None:
        store = object.__new__(ObjectStore)
        store.bucket = "bucket"
        store.client = FakeClient(b"changed")
        with self.assertRaisesRegex(ObjectStoreError, "checksum"):
            store.verify("artifact", "0" * 64)

    def test_upload_signs_every_required_client_header(self) -> None:
        store = object.__new__(ObjectStore)
        store.bucket = "bucket"
        store.client = FakeSigner()

        upload = store.create_upload("plugins/example.tgz", "a" * 64)

        self.assertEqual(
            upload["headers"],
            {
                "Content-Type": "application/octet-stream",
                "x-amz-server-side-encryption": "AES256",
            },
        )
        self.assertEqual(
            store.client.params,
            (
                "put_object",
                {
                    "Bucket": "bucket",
                    "Key": "plugins/example.tgz",
                    "ContentType": "application/octet-stream",
                    "ServerSideEncryption": "AES256",
                },
                900,
            ),
        )


if __name__ == "__main__":
    unittest.main()
