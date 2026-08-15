"""Periodic logical PostgreSQL backups written to private object storage."""

from __future__ import annotations

import gzip
import json
import time
from datetime import datetime, timezone
from typing import Any

from .config import Settings
from .database import Database
from .object_store import ObjectStore


def _json_default(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError(f"cannot serialize {type(value).__name__}")


def backup_once(database: Database, store: ObjectStore) -> str:
    """Write one compressed logical backup and return its object key."""
    timestamp = datetime.now(timezone.utc).strftime("%Y/%m/%d/%H%M%S")
    key = f"control-plane/backups/{timestamp}.json.gz"
    payload = json.dumps(database.export_state(), default=_json_default, separators=(",", ":")).encode()
    store.put_bytes(key, gzip.compress(payload), "application/gzip")
    return key


def main() -> None:
    """Run backups forever at the configured interval."""
    settings = Settings.from_env()
    database = Database(settings.database_url)
    store = ObjectStore(
        settings.oss_endpoint,
        settings.oss_region,
        settings.oss_bucket,
        settings.oss_access_key_id,
        settings.oss_access_key_secret,
    )
    interval = int(__import__("os").environ.get("BACKUP_INTERVAL_SECONDS", "86400"))
    while True:
        backup_once(database, store)
        time.sleep(interval)


if __name__ == "__main__":
    main()
