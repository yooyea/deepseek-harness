"""Private S3-compatible object storage for immutable plugin artifacts."""

from __future__ import annotations

import hashlib
from typing import BinaryIO

import boto3
from botocore.client import Config
from botocore.exceptions import BotoCoreError, ClientError


class ObjectStoreError(RuntimeError):
    """Object storage rejected or could not complete an operation."""


class ObjectStore:
    """Tenant-scoped object operations backed by Alibaba Cloud OSS."""

    def __init__(
        self,
        endpoint: str,
        region: str,
        bucket: str,
        access_key_id: str,
        access_key_secret: str,
    ) -> None:
        self.bucket = bucket
        self.client = boto3.client(
            "s3",
            endpoint_url=endpoint,
            region_name=region,
            aws_access_key_id=access_key_id,
            aws_secret_access_key=access_key_secret,
            # Alibaba Cloud documents SigV2 for boto3 because boto3's SigV4
            # uploader uses an aws-chunked transfer encoding OSS rejects.
            config=Config(signature_version="s3", s3={"addressing_style": "virtual"}),
        )

    def ping(self) -> bool:
        """Return whether the configured private bucket is reachable."""
        try:
            self.client.head_bucket(Bucket=self.bucket)
            return True
        except (BotoCoreError, ClientError):
            return False

    @staticmethod
    def plugin_key(tenant_slug: str, plugin_name: str, version: str, sha256: str) -> str:
        """Return the immutable artifact key for one tenant plugin release."""
        safe_name = plugin_name.replace("/", "__").replace("@", "")
        return f"tenants/{tenant_slug}/plugins/{safe_name}/{version}/{sha256.lower()}.tgz"

    def create_upload(self, key: str, sha256: str, expires_seconds: int = 900) -> dict[str, object]:
        """Create an encrypted short-lived upload request after validating the checksum claim."""
        if len(sha256) != 64:
            raise ObjectStoreError("plugin artifact checksum must be SHA-256")
        headers = {"x-amz-server-side-encryption": "AES256"}
        return {
            "url": self.client.generate_presigned_url(
                "put_object",
                Params={"Bucket": self.bucket, "Key": key, "ServerSideEncryption": "AES256"},
                ExpiresIn=expires_seconds,
            ),
            "headers": headers,
        }

    def create_download_url(self, key: str, expires_seconds: int = 300) -> str:
        """Create a short-lived download URL for a private artifact."""
        return self.client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": key},
            ExpiresIn=expires_seconds,
        )

    def verify(self, key: str, expected_sha256: str) -> None:
        """Require the staged artifact to exist and match its declared checksum."""
        digest = hashlib.sha256()
        try:
            response = self.client.get_object(Bucket=self.bucket, Key=key)
            body: BinaryIO = response["Body"]
            while chunk := body.read(1024 * 1024):
                digest.update(chunk)
        except (BotoCoreError, ClientError) as error:
            raise ObjectStoreError(f"cannot verify plugin artifact {key}: {error}") from error
        if digest.hexdigest() != expected_sha256.lower():
            raise ObjectStoreError("plugin artifact checksum does not match")

    def put_bytes(self, key: str, content: bytes, content_type: str) -> None:
        """Store a private encrypted object."""
        try:
            self.client.put_object(
                Bucket=self.bucket,
                Key=key,
                Body=content,
                ContentType=content_type,
                ServerSideEncryption="AES256",
            )
        except (BotoCoreError, ClientError) as error:
            raise ObjectStoreError(f"cannot upload {key}: {error}") from error
