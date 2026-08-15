"""PostgreSQL persistence for tenant and plugin desired state."""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any

import psycopg
from psycopg.rows import dict_row

SCHEMA = """
CREATE TABLE IF NOT EXISTS tenants (
  id BIGSERIAL PRIMARY KEY,
  slug TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL,
  status TEXT NOT NULL,
  access_username TEXT NOT NULL,
  access_password_encrypted TEXT NOT NULL,
  runtime_token_encrypted TEXT NOT NULL,
  runtime_token_hash TEXT NOT NULL UNIQUE,
  host_port INTEGER NOT NULL UNIQUE,
  container_id TEXT,
  container_name TEXT NOT NULL UNIQUE,
  image TEXT NOT NULL,
  cpu_limit DOUBLE PRECISION NOT NULL,
  memory_mb INTEGER NOT NULL,
  safe_mode BOOLEAN NOT NULL DEFAULT FALSE,
  consecutive_failures INTEGER NOT NULL DEFAULT 0,
  last_error TEXT,
  created_at TIMESTAMPTZ NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS tenant_plugins (
  id BIGSERIAL PRIMARY KEY,
  tenant_id BIGINT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  source_type TEXT NOT NULL,
  source_ref TEXT,
  desired_version TEXT,
  observed_version TEXT,
  last_healthy_version TEXT,
  status TEXT NOT NULL,
  last_error TEXT,
  created_at TIMESTAMPTZ NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL,
  UNIQUE (tenant_id, name)
);

CREATE TABLE IF NOT EXISTS plugin_releases (
  id BIGSERIAL PRIMARY KEY,
  plugin_id BIGINT NOT NULL REFERENCES tenant_plugins(id) ON DELETE CASCADE,
  version TEXT NOT NULL,
  artifact_key TEXT NOT NULL,
  sha256 TEXT NOT NULL,
  manifest JSONB NOT NULL,
  health_status TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL,
  UNIQUE (plugin_id, version)
);

CREATE TABLE IF NOT EXISTS operation_logs (
  id BIGSERIAL PRIMARY KEY,
  tenant_id BIGINT REFERENCES tenants(id) ON DELETE SET NULL,
  action TEXT NOT NULL,
  status TEXT NOT NULL,
  detail TEXT,
  created_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS operation_logs_tenant_created
ON operation_logs (tenant_id, created_at DESC);
CREATE INDEX IF NOT EXISTS tenant_plugins_tenant_status
ON tenant_plugins (tenant_id, status);
"""


def utc_now() -> datetime:
    """Return the current timezone-aware UTC timestamp."""
    return datetime.now(timezone.utc)


def hash_runtime_token(token: str) -> str:
    """Return the irreversible lookup hash stored for a tenant runtime token."""
    return hashlib.sha256(token.encode()).hexdigest()


class Database:
    """Transactional PostgreSQL repository for control-plane state."""

    def __init__(self, url: str) -> None:
        self.url = url

    @contextmanager
    def connection(self) -> Iterator[psycopg.Connection[dict[str, Any]]]:
        """Open a transaction that returns mapping rows."""
        with psycopg.connect(self.url, row_factory=dict_row) as connection:
            yield connection

    def initialize(self) -> None:
        """Create the current schema idempotently."""
        with self.connection() as connection:
            connection.execute(SCHEMA)

    def ping(self) -> bool:
        """Return whether PostgreSQL accepts a query."""
        try:
            with self.connection() as connection:
                connection.execute("SELECT 1").fetchone()
            return True
        except psycopg.Error:
            return False

    def list_tenants(self, include_removed: bool = False) -> list[dict[str, Any]]:
        """List tenants ordered by newest first."""
        where = "" if include_removed else "WHERE status != 'removed'"
        with self.connection() as connection:
            rows = connection.execute(f"SELECT * FROM tenants {where} ORDER BY id DESC").fetchall()
        return list(rows)

    def get_tenant(self, tenant_id: int) -> dict[str, Any] | None:
        """Return one tenant by identifier."""
        with self.connection() as connection:
            return connection.execute("SELECT * FROM tenants WHERE id = %s", (tenant_id,)).fetchone()

    def get_tenant_by_token(self, token: str) -> dict[str, Any] | None:
        """Resolve a tenant from a runtime bearer token without storing the token."""
        with self.connection() as connection:
            return connection.execute(
                "SELECT * FROM tenants WHERE runtime_token_hash = %s AND status != 'removed'",
                (hash_runtime_token(token),),
            ).fetchone()

    def create_tenant(self, values: dict[str, Any]) -> dict[str, Any]:
        """Insert one tenant and return it."""
        now = utc_now()
        parameters = {
            **values,
            "container_id": values.get("container_id"),
            "last_error": values.get("last_error"),
            "created_at": now,
            "updated_at": now,
        }
        with self.connection() as connection:
            row = connection.execute(
                """
                INSERT INTO tenants (
                  slug, name, status, access_username, access_password_encrypted,
                  runtime_token_encrypted, runtime_token_hash, host_port, container_id, container_name,
                  image, cpu_limit, memory_mb, last_error, created_at, updated_at
                ) VALUES (
                  %(slug)s, %(name)s, %(status)s, %(access_username)s,
                  %(access_password_encrypted)s, %(runtime_token_encrypted)s, %(runtime_token_hash)s,
                  %(host_port)s, %(container_id)s, %(container_name)s,
                  %(image)s, %(cpu_limit)s, %(memory_mb)s, %(last_error)s,
                  %(created_at)s, %(updated_at)s
                ) RETURNING *
                """,
                parameters,
            ).fetchone()
        assert row is not None
        return row

    def update_tenant(self, tenant_id: int, **values: Any) -> dict[str, Any]:
        """Update mutable runtime fields and return the tenant."""
        allowed = {
            "status", "container_id", "last_error", "image", "safe_mode",
            "consecutive_failures", "runtime_token_encrypted", "runtime_token_hash",
        }
        unknown = set(values) - allowed
        if unknown:
            raise ValueError(f"unsupported tenant fields: {sorted(unknown)}")
        values["updated_at"] = utc_now()
        assignments = ", ".join(f"{name} = %s" for name in values)
        with self.connection() as connection:
            row = connection.execute(
                f"UPDATE tenants SET {assignments} WHERE id = %s RETURNING *",
                (*values.values(), tenant_id),
            ).fetchone()
        if row is None:
            raise KeyError(tenant_id)
        return row

    def list_plugins(self, tenant_id: int) -> list[dict[str, Any]]:
        """Return the tenant plugin inventory with desired release metadata."""
        with self.connection() as connection:
            rows = connection.execute(
                """
                SELECT p.*, r.artifact_key, r.sha256, r.manifest
                FROM tenant_plugins p
                LEFT JOIN plugin_releases r
                  ON r.plugin_id = p.id AND r.version = p.desired_version
                WHERE p.tenant_id = %s
                ORDER BY p.name
                """,
                (tenant_id,),
            ).fetchall()
        return list(rows)

    def register_plugin_release(
        self,
        tenant_id: int,
        name: str,
        source_type: str,
        source_ref: str | None,
        version: str,
        artifact_key: str,
        sha256: str,
        manifest: dict[str, Any],
    ) -> dict[str, Any]:
        """Record an immutable artifact and make it the desired tenant version."""
        now = utc_now()
        with self.connection() as connection:
            plugin = connection.execute(
                """
                INSERT INTO tenant_plugins (
                  tenant_id, name, source_type, source_ref, desired_version,
                  status, created_at, updated_at
                ) VALUES (%s, %s, %s, %s, %s, 'pending', %s, %s)
                ON CONFLICT (tenant_id, name) DO UPDATE SET
                  source_type = EXCLUDED.source_type,
                  source_ref = EXCLUDED.source_ref,
                  desired_version = EXCLUDED.desired_version,
                  status = 'pending',
                  last_error = NULL,
                  updated_at = EXCLUDED.updated_at
                RETURNING *
                """,
                (tenant_id, name, source_type, source_ref, version, now, now),
            ).fetchone()
            assert plugin is not None
            release = connection.execute(
                """
                INSERT INTO plugin_releases (
                  plugin_id, version, artifact_key, sha256, manifest,
                  health_status, created_at
                ) VALUES (%s, %s, %s, %s, %s, 'pending', %s)
                ON CONFLICT (plugin_id, version) DO NOTHING
                RETURNING id
                """,
                (plugin["id"], version, artifact_key, sha256, psycopg.types.json.Jsonb(manifest), now),
            ).fetchone()
            if release is None:
                existing = connection.execute(
                    "SELECT artifact_key, sha256, manifest FROM plugin_releases WHERE plugin_id = %s AND version = %s",
                    (plugin["id"], version),
                ).fetchone()
                if existing is None or existing["artifact_key"] != artifact_key or existing["sha256"] != sha256 \
                        or existing["manifest"] != manifest:
                    raise ValueError(f"plugin release {name}@{version} is immutable; publish a new version")
        return next(item for item in self.list_plugins(tenant_id) if item["name"] == name)

    def report_plugins(self, tenant_id: int, observed: list[dict[str, Any]]) -> None:
        """Reconcile runtime observations and promote matching versions to healthy."""
        now = utc_now()
        by_name = {item["name"]: item for item in observed}
        with self.connection() as connection:
            plugins = connection.execute(
                "SELECT * FROM tenant_plugins WHERE tenant_id = %s",
                (tenant_id,),
            ).fetchall()
            for plugin in plugins:
                item = by_name.get(plugin["name"])
                if item is None:
                    connection.execute(
                        "UPDATE tenant_plugins SET observed_version = NULL, status = 'missing', updated_at = %s WHERE id = %s",
                        (now, plugin["id"]),
                    )
                    continue
                version = item["version"]
                healthy = bool(item.get("healthy"))
                promote = healthy and version == plugin["desired_version"]
                status = "healthy" if promote else "drifted"
                connection.execute(
                    """
                    UPDATE tenant_plugins SET observed_version = %s, status = %s,
                      last_healthy_version = CASE WHEN %s THEN %s ELSE last_healthy_version END,
                      last_error = %s, updated_at = %s WHERE id = %s
                    """,
                    (version, status, promote, version, item.get("error"), now, plugin["id"]),
                )
                connection.execute(
                    "UPDATE plugin_releases SET health_status = %s WHERE plugin_id = %s AND version = %s",
                    ("healthy" if promote else "failed", plugin["id"], version),
                )

    def rollback_plugins(self, tenant_id: int) -> None:
        """Restore last healthy versions and disable plugins with no healthy release."""
        with self.connection() as connection:
            connection.execute(
                """
                UPDATE tenant_plugins SET
                  desired_version = last_healthy_version,
                  status = CASE WHEN last_healthy_version IS NULL THEN 'disabled' ELSE 'pending' END,
                  observed_version = NULL,
                  last_error = NULL,
                  updated_at = %s
                WHERE tenant_id = %s
                """,
                (utc_now(), tenant_id),
            )

    def add_log(self, tenant_id: int | None, action: str, status: str, detail: str | None = None) -> None:
        """Append an immutable administrative operation record."""
        with self.connection() as connection:
            connection.execute(
                "INSERT INTO operation_logs (tenant_id, action, status, detail, created_at) VALUES (%s, %s, %s, %s, %s)",
                (tenant_id, action, status, detail, utc_now()),
            )

    def list_logs(self, limit: int = 30) -> list[dict[str, Any]]:
        """Return recent administrative operations."""
        with self.connection() as connection:
            rows = connection.execute(
                """
                SELECT operation_logs.*, tenants.name AS tenant_name
                FROM operation_logs
                LEFT JOIN tenants ON tenants.id = operation_logs.tenant_id
                ORDER BY operation_logs.id DESC LIMIT %s
                """,
                (limit,),
            ).fetchall()
        return list(rows)

    def export_state(self) -> dict[str, list[dict[str, Any]]]:
        """Return logical tables for encrypted object-store backup."""
        tables = ("tenants", "tenant_plugins", "plugin_releases", "operation_logs")
        with self.connection() as connection:
            return {
                table: list(connection.execute(f"SELECT * FROM {table} ORDER BY id").fetchall())
                for table in tables
            }
