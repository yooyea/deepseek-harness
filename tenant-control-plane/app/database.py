"""SQLite persistence for tenants and administrative operations."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
from typing import Any, Iterator


SCHEMA = """
CREATE TABLE IF NOT EXISTS tenants (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  slug TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL,
  status TEXT NOT NULL,
  access_username TEXT NOT NULL,
  host_port INTEGER NOT NULL UNIQUE,
  container_id TEXT,
  container_name TEXT NOT NULL UNIQUE,
  volume_name TEXT NOT NULL UNIQUE,
  image TEXT NOT NULL,
  cpu_limit REAL NOT NULL,
  memory_mb INTEGER NOT NULL,
  last_error TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS operation_logs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  tenant_id INTEGER,
  action TEXT NOT NULL,
  status TEXT NOT NULL,
  detail TEXT,
  created_at TEXT NOT NULL,
  FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS operation_logs_tenant_created
ON operation_logs (tenant_id, created_at DESC);
"""


def utc_now() -> str:
    """Return an ISO-8601 UTC timestamp."""
    return datetime.now(timezone.utc).isoformat()


class Database:
    """Small transactional repository around one SQLite database."""

    def __init__(self, path: str) -> None:
        self.path = path

    def initialize(self) -> None:
        """Create the database and enable WAL mode."""
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA foreign_keys=ON")
            connection.executescript(SCHEMA)

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        """Open a row-oriented SQLite connection."""
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def list_tenants(self, include_removed: bool = False) -> list[dict[str, Any]]:
        """List tenants ordered by newest first."""
        where = "" if include_removed else "WHERE status != 'removed'"
        with self.connection() as connection:
            rows = connection.execute(f"SELECT * FROM tenants {where} ORDER BY id DESC").fetchall()
        return [dict(row) for row in rows]
    def get_tenant(self, tenant_id: int) -> dict[str, Any] | None:
        """Return one tenant by numeric identifier."""
        with self.connection() as connection:
            row = connection.execute("SELECT * FROM tenants WHERE id = ?", (tenant_id,)).fetchone()
        return dict(row) if row else None

    def create_tenant(self, values: dict[str, Any]) -> dict[str, Any]:
        """Insert one tenant and return it."""
        now = utc_now()
        with self.connection() as connection:
            cursor = connection.execute(
                """
                INSERT INTO tenants (
                  slug, name, status, access_username, host_port, container_id,
                  container_name, volume_name, image, cpu_limit, memory_mb,
                  last_error, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    values["slug"], values["name"], values["status"], values["access_username"],
                    values["host_port"], values.get("container_id"), values["container_name"],
                    values["volume_name"], values["image"], values["cpu_limit"], values["memory_mb"],
                    values.get("last_error"), now, now,
                ),
            )
            tenant_id = int(cursor.lastrowid)
        tenant = self.get_tenant(tenant_id)
        assert tenant is not None
        return tenant

    def update_tenant(self, tenant_id: int, **values: Any) -> dict[str, Any]:
        """Update selected mutable tenant fields."""
        allowed = {"status", "container_id", "last_error", "image"}
        unknown = set(values) - allowed
        if unknown:
            raise ValueError(f"unsupported tenant fields: {sorted(unknown)}")
        values["updated_at"] = utc_now()
        assignments = ", ".join(f"{name} = ?" for name in values)
        parameters = [*values.values(), tenant_id]
        with self.connection() as connection:
            cursor = connection.execute(f"UPDATE tenants SET {assignments} WHERE id = ?", parameters)
            if cursor.rowcount != 1:
                raise KeyError(tenant_id)
        tenant = self.get_tenant(tenant_id)
        assert tenant is not None
        return tenant

    def add_log(self, tenant_id: int | None, action: str, status: str, detail: str | None = None) -> None:
        """Append an immutable administrative operation record."""
        with self.connection() as connection:
            connection.execute(
                "INSERT INTO operation_logs (tenant_id, action, status, detail, created_at) VALUES (?, ?, ?, ?, ?)",
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
                ORDER BY operation_logs.id DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]
