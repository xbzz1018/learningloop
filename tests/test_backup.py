import sqlite3

import pytest

from learningloop.backup import BackupError, backup_database, restore_database


def test_sqlite_backup_and_restore(db, tmp_path) -> None:
    db.create_session("backup-session")
    backup = tmp_path / "backup.db"
    restored = tmp_path / "restored.db"
    result = backup_database(db.path, backup)
    assert result["integrity"] == "ok"
    restore_database(backup, restored, confirm=True)
    with sqlite3.connect(restored) as conn:
        assert conn.execute("SELECT id FROM sessions").fetchone()[0] == "backup-session"


def test_restore_requires_explicit_confirmation(tmp_path) -> None:
    source = tmp_path / "source.db"
    with sqlite3.connect(source) as conn:
        conn.execute("CREATE TABLE marker(value TEXT)")
        conn.execute("INSERT INTO marker VALUES('ok')")
    with pytest.raises(BackupError, match="confirm"):
        restore_database(source, tmp_path / "target.db")
