from __future__ import annotations

import sqlite3

from learningloop.models import EventRecord


def test_session_messages_events_and_checkpoint(db) -> None:
    session = db.create_session("abc123")
    assert session["status"] == "idle"
    message_id = db.add_message("abc123", "user", "hello")
    assert message_id > 0
    assert db.latest_message_id("abc123") == message_id
    event_id = db.add_event(
        EventRecord(session_id="abc123", run_id="run1", type="started", payload={"ok": True})
    )
    events = db.events_after("abc123")
    assert events[0]["id"] == event_id
    assert events[0]["payload"] == {"ok": True}
    db.save_checkpoint("cp1", "abc123", "run1", {"phase": "safe"})
    assert db.latest_checkpoint("abc123")["state"] == {"phase": "safe"}


def test_database_uses_wal(db) -> None:
    with db._connect() as conn:
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode.lower() == "wal"


def test_cleanup_is_lock_safe(db) -> None:
    result = db.cleanup(90)
    assert result["messages"] == 0
    assert result["events"] == 0
    assert result["checkpoint"] in {"completed", "deferred_locked"}


def test_versioned_migration_preserves_legacy_session(tmp_path) -> None:
    path = tmp_path / "legacy.db"
    with sqlite3.connect(path) as conn:
        conn.execute(
            "CREATE TABLE sessions(id TEXT PRIMARY KEY,status TEXT NOT NULL,"
            "created_at TEXT NOT NULL,updated_at TEXT NOT NULL)"
        )
        conn.execute(
            "INSERT INTO sessions VALUES('legacy-session','idle','2026-01-01','2026-01-01')"
        )
        conn.commit()
    from learningloop.db import Database

    migrated = Database(path)
    session = migrated.get_session("legacy-session")
    assert session["owner_id"] == "local"
    assert [row["version"] for row in migrated.fetch_all("SELECT * FROM schema_migrations")] == [1, 2, 3]
