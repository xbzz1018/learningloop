from __future__ import annotations

import sqlite3
from pathlib import Path


class BackupError(RuntimeError):
    """Raised when a database backup or restore fails integrity checks."""


def backup_database(source: Path, destination: Path) -> dict[str, str]:
    """Create a consistent SQLite backup using the SQLite backup API."""
    if not source.exists():
        raise BackupError(f"database does not exist: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        with sqlite3.connect(source) as source_conn, sqlite3.connect(destination) as target_conn:
            source_conn.backup(target_conn)
            check = target_conn.execute("PRAGMA integrity_check").fetchone()[0]
    except sqlite3.Error as exc:
        raise BackupError(f"backup failed: {exc}") from exc
    if check != "ok":
        raise BackupError(f"backup integrity check failed: {check}")
    return {"source": str(source), "destination": str(destination), "integrity": check}

def restore_database(source: Path, destination: Path, *, confirm: bool = False) -> dict[str, str]:
    """Restore a database after an explicit confirmation from the operator."""
    if not confirm:
        raise BackupError("restore requires confirm=True")
    if not source.exists():
        raise BackupError(f"backup does not exist: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        with sqlite3.connect(source) as source_conn, sqlite3.connect(destination) as target_conn:
            source_conn.backup(target_conn)
            check = target_conn.execute("PRAGMA integrity_check").fetchone()[0]
    except sqlite3.Error as exc:
        raise BackupError(f"restore failed: {exc}") from exc
    if check != "ok":
        raise BackupError(f"restored database integrity check failed: {check}")
    return {"source": str(source), "destination": str(destination), "integrity": check}
