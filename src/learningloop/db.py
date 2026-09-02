from __future__ import annotations

import json
import sqlite3
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from learningloop.models import (
    ActionRequest,
    ApprovalRecord,
    EventRecord,
    ModelCallRecord,
    RunRecord,
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    applied_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    disabled INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS auth_sessions (
    token_hash TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_auth_sessions_user ON auth_sessions(user_id, expires_at);
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    owner_id TEXT NOT NULL DEFAULT 'local' REFERENCES users(id),
    title TEXT NOT NULL DEFAULT '新学习目标',
    pinned INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL,
    summary TEXT,
    current_run_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_message_at TEXT
);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_session_time
    ON messages(session_id, created_at DESC);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    type TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_session_id ON events(session_id, id);
CREATE TABLE IF NOT EXISTS approvals (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    tool TEXT NOT NULL,
    args_json TEXT NOT NULL,
    status TEXT NOT NULL,
    message TEXT,
    created_at TEXT NOT NULL,
    decided_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_approvals_session ON approvals(session_id, status);
CREATE TABLE IF NOT EXISTS actions (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    action_type TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    available_decisions_json TEXT NOT NULL,
    status TEXT NOT NULL,
    decision_message TEXT,
    parent_action_id TEXT,
    created_at TEXT NOT NULL,
    decided_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_actions_session_status ON actions(session_id, status, created_at DESC);
CREATE TABLE IF NOT EXISTS checkpoints (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    state_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_checkpoints_session_time
    ON checkpoints(session_id, created_at DESC);
CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    owner_id TEXT NOT NULL DEFAULT 'local',
    agent_role TEXT NOT NULL DEFAULT 'interactive',
    parent_run_id TEXT,
    turn_id TEXT NOT NULL,
    stage TEXT NOT NULL,
    status TEXT NOT NULL,
    skill_name TEXT,
    skill_hash TEXT,
    model_route TEXT,
    error_type TEXT,
    error_message TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_runs_session_time ON runs(session_id, created_at DESC);
CREATE TABLE IF NOT EXISTS agent_artifacts (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    owner_id TEXT NOT NULL DEFAULT 'local',
    artifact_type TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    source TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_agent_artifacts_run ON agent_artifacts(run_id, created_at);
CREATE INDEX IF NOT EXISTS idx_agent_artifacts_session ON agent_artifacts(session_id, created_at DESC);
CREATE TABLE IF NOT EXISTS tool_effects (
    effect_key TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    tool_name TEXT NOT NULL,
    args_hash TEXT NOT NULL,
    status TEXT NOT NULL,
    result_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tool_effects_run ON tool_effects(run_id, created_at);
CREATE TABLE IF NOT EXISTS model_calls (
    call_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    owner_id TEXT NOT NULL DEFAULT 'local',
    agent_role TEXT NOT NULL DEFAULT 'interactive',
    turn_id TEXT NOT NULL,
    task_type TEXT NOT NULL,
    call_site TEXT NOT NULL,
    provider_alias TEXT NOT NULL,
    requested_model TEXT NOT NULL,
    actual_model TEXT,
    model_route TEXT NOT NULL,
    reasoning_effort TEXT,
    started_at TEXT NOT NULL,
    latency_ms INTEGER,
    status TEXT NOT NULL,
    retry_index INTEGER NOT NULL,
    fallback_from TEXT,
    error_type TEXT,
    input_tokens INTEGER,
    cached_input_tokens INTEGER,
    cache_miss_input_tokens INTEGER,
    output_tokens INTEGER,
    reasoning_tokens INTEGER,
    total_tokens INTEGER,
    actual_cost_usd REAL,
    estimated_cost_usd REAL,
    pricing_version TEXT,
    usage_source TEXT,
    usage_unknown INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_calls_session_time
    ON model_calls(session_id, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_calls_day ON model_calls(started_at);
CREATE TABLE IF NOT EXISTS provider_capabilities (
    provider_alias TEXT NOT NULL,
    model_route TEXT NOT NULL,
    models_ok INTEGER NOT NULL DEFAULT 0,
    chat_ok INTEGER NOT NULL DEFAULT 0,
    tools_ok INTEGER NOT NULL DEFAULT 0,
    structured_ok INTEGER NOT NULL DEFAULT 0,
    streaming_ok INTEGER NOT NULL DEFAULT 0,
    usage_ok INTEGER NOT NULL DEFAULT 0,
    responses_ok INTEGER NOT NULL DEFAULT 0,
    web_search_ok INTEGER NOT NULL DEFAULT 0,
    actual_model TEXT,
    error TEXT,
    checked_at TEXT NOT NULL,
    PRIMARY KEY(provider_alias, model_route)
);
CREATE TABLE IF NOT EXISTS daily_plans (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    plan_date TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(session_id, plan_date)
);
CREATE INDEX IF NOT EXISTS idx_daily_plans_session_date
    ON daily_plans(session_id, plan_date DESC);
CREATE TABLE IF NOT EXISTS daily_reviews (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    review_date TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(session_id, review_date)
);
CREATE INDEX IF NOT EXISTS idx_daily_reviews_session_date
    ON daily_reviews(session_id, review_date DESC);
CREATE TABLE IF NOT EXISTS notification_settings (
    session_id TEXT PRIMARY KEY,
    email TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 0,
    timezone TEXT NOT NULL DEFAULT 'Asia/Shanghai',
    morning_time TEXT NOT NULL DEFAULT '08:30',
    evening_time TEXT NOT NULL DEFAULT '20:30',
    updated_at TEXT NOT NULL,
    verified_at TEXT
);
CREATE TABLE IF NOT EXISTS notification_deliveries (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    local_date TEXT NOT NULL,
    schedule_type TEXT NOT NULL,
    status TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    next_attempt_at TEXT,
    message_id TEXT,
    last_error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    sent_at TEXT,
    UNIQUE(session_id, local_date, schedule_type)
);
CREATE INDEX IF NOT EXISTS idx_notification_due
    ON notification_deliveries(status, next_attempt_at);
"""


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.initialize()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=30, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=30000")
        return conn

    def initialize(self) -> None:
        with self._lock, self._connect() as conn:
            conn.executescript(SCHEMA)
            self._apply_migrations(conn)

    def _apply_migrations(self, conn: sqlite3.Connection) -> None:
        applied = {
            int(row[0]) for row in conn.execute("SELECT version FROM schema_migrations").fetchall()
        }
        migrations = (
            (1, "legacy-columns-and-action-cards", self._migration_001),
            (2, "runtime-ledger-and-owner-isolation", self._migration_002),
            (3, "agent-roles-and-artifacts", self._migration_003),
        )
        for version, name, migration in migrations:
            if version in applied:
                continue
            migration(conn)
            conn.execute(
                "INSERT INTO schema_migrations(version,name,applied_at) VALUES(?,?,?)",
                (version, name, datetime.now(UTC).isoformat()),
            )
            conn.commit()

    def _migration_001(self, conn: sqlite3.Connection) -> None:
        self._ensure_column(conn, "sessions", "title", "TEXT NOT NULL DEFAULT '新学习目标'")
        self._ensure_column(conn, "sessions", "pinned", "INTEGER NOT NULL DEFAULT 0")
        self._ensure_column(conn, "sessions", "last_message_at", "TEXT")
        self._ensure_column(conn, "notification_settings", "verified_at", "TEXT")
        self._migrate_pending_approvals(conn)

    def _migration_002(self, conn: sqlite3.Connection) -> None:
        now = datetime.now(UTC).isoformat()
        conn.execute(
            "INSERT OR IGNORE INTO users(id,username,password_hash,disabled,created_at,updated_at) "
            "VALUES('local','local','!',1,?,?)",
            (now, now),
        )
        self._ensure_column(conn, "sessions", "owner_id", "TEXT NOT NULL DEFAULT 'local'")
        self._ensure_column(conn, "model_calls", "owner_id", "TEXT NOT NULL DEFAULT 'local'")
        conn.execute("UPDATE sessions SET owner_id='local' WHERE owner_id IS NULL OR owner_id='' ")
        conn.execute("UPDATE model_calls SET owner_id='local' WHERE owner_id IS NULL OR owner_id='' ")

    def _migration_003(self, conn: sqlite3.Connection) -> None:
        self._ensure_column(conn, "runs", "agent_role", "TEXT NOT NULL DEFAULT 'interactive'")
        self._ensure_column(conn, "runs", "parent_run_id", "TEXT")
        self._ensure_column(
            conn, "model_calls", "agent_role", "TEXT NOT NULL DEFAULT 'interactive'"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_runs_parent ON runs(parent_run_id, created_at)"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS agent_artifacts ("
            "id TEXT PRIMARY KEY,run_id TEXT NOT NULL,session_id TEXT NOT NULL,"
            "owner_id TEXT NOT NULL DEFAULT 'local',artifact_type TEXT NOT NULL,"
            "schema_version TEXT NOT NULL,payload_json TEXT NOT NULL,source TEXT NOT NULL,"
            "created_at TEXT NOT NULL)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_agent_artifacts_run "
            "ON agent_artifacts(run_id, created_at)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_agent_artifacts_session "
            "ON agent_artifacts(session_id, created_at DESC)"
        )

    @staticmethod
    def _ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
        columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        if column not in columns:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    @staticmethod
    def _migrate_pending_approvals(conn: sqlite3.Connection) -> None:
        rows = conn.execute(
            "SELECT * FROM approvals WHERE status='pending' AND id NOT IN (SELECT id FROM actions)"
        ).fetchall()
        for row in rows:
            args = json.loads(row["args_json"])
            payload = {"approval_id": row["id"], **args}
            conn.execute(
                "INSERT INTO actions(id,session_id,run_id,action_type,title,description,payload_json,"
                "available_decisions_json,status,decision_message,parent_action_id,created_at,decided_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    row["id"], row["session_id"], row["run_id"], "plan_approval",
                    "确认学习计划", row["message"] or "批准后会写入课程计划并生成今日学习任务。",
                    json.dumps(payload, ensure_ascii=False),
                    json.dumps(["execute", "next", "suggest", "reject"]),
                    "pending", None, None, row["created_at"], None,
                ),
            )

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(sql, params)
            conn.commit()

    def fetch_one(self, sql: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
        with self._lock, self._connect() as conn:
            row = conn.execute(sql, params).fetchone()
            return dict(row) if row else None

    def fetch_all(self, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        with self._lock, self._connect() as conn:
            return [dict(row) for row in conn.execute(sql, params).fetchall()]

    def create_user(self, user_id: str, username: str, password_hash: str) -> dict[str, Any]:
        now = datetime.now(UTC).isoformat()
        with self._lock, self._connect() as conn:
            active = conn.execute(
                "SELECT COUNT(*) FROM users WHERE id<>'local' AND disabled=0"
            ).fetchone()[0]
            conn.execute(
                "INSERT INTO users(id,username,password_hash,disabled,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?)",
                (user_id, username, password_hash, 0, now, now),
            )
            if int(active) == 0:
                conn.execute("UPDATE sessions SET owner_id=? WHERE owner_id='local'", (user_id,))
                conn.execute("UPDATE model_calls SET owner_id=? WHERE owner_id='local'", (user_id,))
            conn.commit()
        return self.get_user(user_id) or {}

    def get_user(self, user_id: str) -> dict[str, Any] | None:
        return self.fetch_one("SELECT * FROM users WHERE id=?", (user_id,))

    def get_user_by_username(self, username: str) -> dict[str, Any] | None:
        return self.fetch_one("SELECT * FROM users WHERE username=?", (username,))

    def list_users(self) -> list[dict[str, Any]]:
        return self.fetch_all(
            "SELECT id,username,disabled,created_at,updated_at FROM users "
            "WHERE id<>'local' ORDER BY username"
        )

    def set_user_disabled(self, username: str, disabled: bool) -> bool:
        now = datetime.now(UTC).isoformat()
        with self._lock, self._connect() as conn:
            cursor = conn.execute(
                "UPDATE users SET disabled=?,updated_at=? WHERE username=? AND id<>'local'",
                (int(disabled), now, username),
            )
            if disabled:
                conn.execute(
                    "DELETE FROM auth_sessions WHERE user_id IN "
                    "(SELECT id FROM users WHERE username=?)",
                    (username,),
                )
            conn.commit()
            return cursor.rowcount == 1

    def create_auth_session(
        self, token_hash: str, user_id: str, *, expires_at: datetime
    ) -> None:
        now = datetime.now(UTC).isoformat()
        self.execute(
            "INSERT INTO auth_sessions(token_hash,user_id,created_at,expires_at,last_seen_at) "
            "VALUES(?,?,?,?,?)",
            (token_hash, user_id, now, expires_at.isoformat(), now),
        )

    def get_auth_session(self, token_hash: str) -> dict[str, Any] | None:
        now = datetime.now(UTC).isoformat()
        row = self.fetch_one(
            "SELECT a.*,u.username,u.disabled FROM auth_sessions a "
            "JOIN users u ON u.id=a.user_id "
            "WHERE a.token_hash=? AND a.expires_at>?",
            (token_hash, now),
        )
        if row and not row["disabled"]:
            self.execute(
                "UPDATE auth_sessions SET last_seen_at=? WHERE token_hash=?",
                (now, token_hash),
            )
            return row
        return None

    def delete_auth_session(self, token_hash: str) -> None:
        self.execute("DELETE FROM auth_sessions WHERE token_hash=?", (token_hash,))

    def create_run(self, run: RunRecord) -> None:
        values = run.model_dump(mode="json")
        self.execute(
            "INSERT INTO runs(id,session_id,owner_id,agent_role,parent_run_id,turn_id,stage,status,"
            "skill_name,skill_hash,model_route,error_type,error_message,created_at,updated_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                values["id"], values["session_id"], values["owner_id"], values["agent_role"],
                values["parent_run_id"], values["turn_id"], values["stage"], values["status"],
                values["skill_name"], values["skill_hash"], values["route"], values["error_type"],
                values["error_message"],
                values["created_at"], values["updated_at"],
            ),
        )

    def update_run(self, run_id: str, **values: Any) -> None:
        allowed = {
            "stage", "status", "skill_name", "skill_hash", "model_route", "error_type",
            "error_message",
        }
        clean = {key: value for key, value in values.items() if key in allowed}
        if not clean:
            return
        clean["updated_at"] = datetime.now(UTC).isoformat()
        columns = ",".join(f"{key}=?" for key in clean)
        self.execute(
            f"UPDATE runs SET {columns} WHERE id=?",  # noqa: S608 - keys are allowlisted
            (*clean.values(), run_id),
        )

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        return self.fetch_one("SELECT * FROM runs WHERE id=?", (run_id,))

    def get_run_for_owner(self, run_id: str, owner_id: str) -> dict[str, Any] | None:
        return self.fetch_one("SELECT * FROM runs WHERE id=? AND owner_id=?", (run_id, owner_id))

    def agent_runs_for_session(
        self, session_id: str, owner_id: str | None = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        if owner_id is None:
            return self.fetch_all(
                "SELECT * FROM runs WHERE session_id=? ORDER BY created_at DESC LIMIT ?",
                (session_id, limit),
            )
        return self.fetch_all(
            "SELECT * FROM runs WHERE session_id=? AND owner_id=? "
            "ORDER BY created_at DESC LIMIT ?",
            (session_id, owner_id, limit),
        )

    def create_agent_artifact(
        self,
        *,
        artifact_id: str,
        run_id: str,
        session_id: str,
        owner_id: str,
        artifact_type: str,
        schema_version: str,
        payload: dict[str, Any],
        source: str,
    ) -> None:
        self.execute(
            "INSERT INTO agent_artifacts(id,run_id,session_id,owner_id,artifact_type,"
            "schema_version,payload_json,source,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
            (
                artifact_id,
                run_id,
                session_id,
                owner_id,
                artifact_type,
                schema_version,
                json.dumps(payload, ensure_ascii=False, default=str),
                source,
                datetime.now(UTC).isoformat(),
            ),
        )

    def agent_artifacts_for_run(
        self, run_id: str, owner_id: str | None = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        if owner_id is None:
            rows = self.fetch_all(
                "SELECT * FROM agent_artifacts WHERE run_id=? "
                "ORDER BY created_at LIMIT ?",
                (run_id, limit),
            )
        else:
            rows = self.fetch_all(
                "SELECT * FROM agent_artifacts WHERE run_id=? AND owner_id=? "
                "ORDER BY created_at LIMIT ?",
                (run_id, owner_id, limit),
            )
        for row in rows:
            row["payload"] = json.loads(row.pop("payload_json"))
        return rows

    def incomplete_runs(self) -> list[dict[str, Any]]:
        return self.fetch_all(
            "SELECT * FROM runs WHERE status IN ('running','recovering') ORDER BY created_at"
        )

    def runs_for_session(
        self, session_id: str, owner_id: str | None = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        if owner_id is None:
            return self.fetch_all(
                "SELECT * FROM runs WHERE session_id=? ORDER BY created_at DESC LIMIT ?",
                (session_id, limit),
            )
        return self.fetch_all(
            "SELECT * FROM runs WHERE session_id=? AND owner_id=? "
            "ORDER BY created_at DESC LIMIT ?",
            (session_id, owner_id, limit),
        )

    def get_tool_effect(self, effect_key: str) -> dict[str, Any] | None:
        row = self.fetch_one("SELECT * FROM tool_effects WHERE effect_key=?", (effect_key,))
        if row and row.get("result_json"):
            row["result"] = json.loads(row.pop("result_json"))
        return row

    def reserve_tool_effect(
        self,
        effect_key: str,
        *,
        run_id: str,
        session_id: str,
        tool_name: str,
        args_hash: str,
    ) -> bool:
        now = datetime.now(UTC).isoformat()
        with self._lock, self._connect() as conn:
            cursor = conn.execute(
                "INSERT OR IGNORE INTO tool_effects(effect_key,run_id,session_id,tool_name,"
                "args_hash,status,created_at,updated_at) VALUES(?,?,?,?,?,'reserved',?,?)",
                (effect_key, run_id, session_id, tool_name, args_hash, now, now),
            )
            conn.commit()
            return cursor.rowcount == 1

    def complete_tool_effect(self, effect_key: str, result: dict[str, Any]) -> None:
        self.execute(
            "UPDATE tool_effects SET status='completed',result_json=?,updated_at=? "
            "WHERE effect_key=?",
            (
                json.dumps(result, ensure_ascii=False, default=str),
                datetime.now(UTC).isoformat(),
                effect_key,
            ),
        )

    def create_session(
        self,
        session_id: str,
        status: str = "idle",
        title: str = "新学习目标",
        owner_id: str = "local",
    ) -> dict[str, Any]:
        now = datetime.now(UTC).isoformat()
        self.execute(
            "INSERT INTO sessions(id,owner_id,title,status,created_at,updated_at) "
            "VALUES(?,?,?,?,?,?)",
            (session_id, owner_id, title[:120] or "新学习目标", status, now, now),
        )
        return self.get_session(session_id) or {}

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        return self.fetch_one("SELECT * FROM sessions WHERE id=?", (session_id,))

    def get_session_for_owner(self, session_id: str, owner_id: str) -> dict[str, Any] | None:
        return self.fetch_one(
            "SELECT * FROM sessions WHERE id=? AND owner_id=?", (session_id, owner_id)
        )

    def list_sessions(self, owner_id: str | None = None) -> list[dict[str, Any]]:
        if owner_id is not None:
            return self.fetch_all(
                "SELECT * FROM sessions WHERE owner_id=? ORDER BY pinned DESC, updated_at DESC",
                (owner_id,),
            )
        return self.fetch_all("SELECT * FROM sessions ORDER BY pinned DESC, updated_at DESC")

    def update_session(self, session_id: str, **values: Any) -> None:
        allowed = {"title", "pinned", "status", "summary", "current_run_id"}
        clean = {key: value for key, value in values.items() if key in allowed}
        if not clean:
            return
        clean["updated_at"] = datetime.now(UTC).isoformat()
        columns = ",".join(f"{key}=?" for key in clean)
        self.execute(
            f"UPDATE sessions SET {columns} WHERE id=?",  # noqa: S608 - keys are allowlisted
            (*clean.values(), session_id),
        )

    def add_message(self, session_id: str, role: str, content: str) -> int:
        now = datetime.now(UTC).isoformat()
        with self._lock, self._connect() as conn:
            cursor = conn.execute(
                "INSERT INTO messages(session_id,role,content,created_at) VALUES(?,?,?,?)",
                (session_id, role, content, now),
            )
            title_update = None
            if role == "user":
                first_line = content.strip().splitlines()[0][:80]
                if first_line:
                    title_update = first_line
            if title_update:
                conn.execute(
                    "UPDATE sessions SET title=CASE WHEN title='新学习目标' THEN ? ELSE title END, "
                    "updated_at=?,last_message_at=? WHERE id=?",
                    (title_update, now, now, session_id),
                )
            else:
                conn.execute("UPDATE sessions SET updated_at=? WHERE id=?", (now, session_id))
            conn.commit()
            return int(cursor.lastrowid)

    def delete_session(self, session_id: str) -> None:
        with self._lock, self._connect() as conn:
            for table in (
                "messages", "events", "approvals", "actions", "checkpoints", "model_calls",
                "runs", "agent_artifacts", "tool_effects", "daily_plans", "daily_reviews", "notification_settings",
                "notification_deliveries",
            ):
                column = "session_id"
                conn.execute(f"DELETE FROM {table} WHERE {column}=?", (session_id,))
            conn.execute("DELETE FROM sessions WHERE id=?", (session_id,))
            conn.commit()

    def recent_messages(self, session_id: str, limit: int = 8) -> list[dict[str, Any]]:
        rows = self.fetch_all(
            "SELECT role,content,created_at FROM messages WHERE session_id=? "
            "ORDER BY id DESC LIMIT ?",
            (session_id, limit),
        )
        return list(reversed(rows))

    def latest_message_id(self, session_id: str, role: str = "user") -> int | None:
        row = self.fetch_one(
            "SELECT id FROM messages WHERE session_id=? AND role=? ORDER BY id DESC LIMIT 1",
            (session_id, role),
        )
        return int(row["id"]) if row else None

    def latest_message(self, session_id: str, role: str = "user") -> dict[str, Any] | None:
        return self.fetch_one(
            "SELECT id,role,content,created_at FROM messages WHERE session_id=? AND role=? "
            "ORDER BY id DESC LIMIT 1",
            (session_id, role),
        )

    def add_event(self, event: EventRecord) -> int:
        with self._lock, self._connect() as conn:
            cursor = conn.execute(
                "INSERT INTO events(session_id,run_id,type,payload_json,created_at) "
                "VALUES(?,?,?,?,?)",
                (
                    event.session_id,
                    event.run_id,
                    event.type,
                    json.dumps(event.payload, ensure_ascii=False, default=str),
                    event.created_at.isoformat(),
                ),
            )
            conn.commit()
            return int(cursor.lastrowid)

    def events_after(self, session_id: str, after_id: int = 0) -> list[dict[str, Any]]:
        rows = self.fetch_all(
            "SELECT * FROM events WHERE session_id=? AND id>? ORDER BY id LIMIT 200",
            (session_id, after_id),
        )
        for row in rows:
            row["payload"] = json.loads(row.pop("payload_json"))
        return rows

    def recent_events(self, session_id: str, limit: int = 100) -> list[dict[str, Any]]:
        safe_limit = max(1, min(int(limit), 500))
        rows = self.fetch_all(
            "SELECT * FROM events WHERE session_id=? ORDER BY id DESC LIMIT ?",
            (session_id, safe_limit),
        )
        for row in rows:
            row["payload"] = json.loads(row.pop("payload_json"))
        return rows

    def events_for_run(self, run_id: str, limit: int = 200) -> list[dict[str, Any]]:
        rows = self.fetch_all(
            "SELECT * FROM events WHERE run_id=? ORDER BY id LIMIT ?", (run_id, limit)
        )
        for row in rows:
            row["payload"] = json.loads(row.pop("payload_json"))
        return rows

    def last_event_id(self, session_id: str) -> int:
        row = self.fetch_one("SELECT MAX(id) AS id FROM events WHERE session_id=?", (session_id,))
        return int(row["id"] or 0) if row else 0

    def message_count(self, session_id: str) -> int:
        row = self.fetch_one(
            "SELECT COUNT(*) AS count FROM messages WHERE session_id=?", (session_id,)
        )
        return int(row["count"] if row else 0)

    def messages_before_recent(self, session_id: str, keep_last: int) -> list[dict[str, Any]]:
        return self.fetch_all(
            "SELECT role,content,created_at FROM messages WHERE session_id=? "
            "AND id NOT IN (SELECT id FROM messages WHERE session_id=? ORDER BY id DESC LIMIT ?) "
            "ORDER BY id",
            (session_id, session_id, keep_last),
        )

    def save_checkpoint(
        self, checkpoint_id: str, session_id: str, run_id: str, state: dict
    ) -> None:
        self.execute(
            "INSERT OR REPLACE INTO checkpoints(id,session_id,run_id,state_json,created_at) "
            "VALUES(?,?,?,?,?)",
            (
                checkpoint_id,
                session_id,
                run_id,
                json.dumps(state, ensure_ascii=False, default=str),
                datetime.now(UTC).isoformat(),
            ),
        )

    def latest_checkpoint(self, session_id: str) -> dict[str, Any] | None:
        row = self.fetch_one(
            "SELECT * FROM checkpoints WHERE session_id=? ORDER BY created_at DESC LIMIT 1",
            (session_id,),
        )
        if row:
            row["state"] = json.loads(row.pop("state_json"))
        return row

    def latest_checkpoint_for_run(self, run_id: str) -> dict[str, Any] | None:
        row = self.fetch_one(
            "SELECT * FROM checkpoints WHERE run_id=? ORDER BY created_at DESC LIMIT 1",
            (run_id,),
        )
        if row:
            row["state"] = json.loads(row.pop("state_json"))
        return row

    def create_approval(self, approval: ApprovalRecord) -> None:
        self.execute(
            "INSERT INTO approvals(id,session_id,run_id,tool,args_json,status,message,created_at) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (
                approval.id,
                approval.session_id,
                approval.run_id,
                approval.tool,
                json.dumps(approval.args, ensure_ascii=False, default=str),
                approval.status.value,
                approval.message,
                approval.created_at.isoformat(),
            ),
        )

    def get_approval(self, approval_id: str) -> dict[str, Any] | None:
        row = self.fetch_one("SELECT * FROM approvals WHERE id=?", (approval_id,))
        if row:
            row["args"] = json.loads(row.pop("args_json"))
        return row

    def decide_approval(self, approval_id: str, status: str, message: str | None) -> None:
        self.execute(
            "UPDATE approvals SET status=?,message=?,decided_at=? WHERE id=? AND status='pending'",
            (status, message, datetime.now(UTC).isoformat(), approval_id),
        )

    def create_action(self, action: ActionRequest) -> None:
        self.execute(
            "INSERT INTO actions(id,session_id,run_id,action_type,title,description,payload_json,"
            "available_decisions_json,status,decision_message,parent_action_id,created_at,decided_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                action.id,
                action.session_id,
                action.run_id,
                action.action_type.value,
                action.title,
                action.description,
                json.dumps(action.payload, ensure_ascii=False, default=str),
                json.dumps([item.value for item in action.available_decisions]),
                action.status.value,
                action.decision_message,
                action.parent_action_id,
                action.created_at.isoformat(),
                action.decided_at.isoformat() if action.decided_at else None,
            ),
        )

    @staticmethod
    def _decode_action(row: dict[str, Any]) -> dict[str, Any]:
        row["payload"] = json.loads(row.pop("payload_json"))
        row["available_decisions"] = json.loads(row.pop("available_decisions_json"))
        return row

    def get_action(self, action_id: str, owner_id: str | None = None) -> dict[str, Any] | None:
        if owner_id is None:
            row = self.fetch_one("SELECT * FROM actions WHERE id=?", (action_id,))
        else:
            row = self.fetch_one(
                "SELECT a.* FROM actions a JOIN sessions s ON s.id=a.session_id "
                "WHERE a.id=? AND s.owner_id=?",
                (action_id, owner_id),
            )
        return self._decode_action(row) if row else None

    def pending_actions(
        self, session_id: str | None = None, owner_id: str | None = None
    ) -> list[dict[str, Any]]:
        if session_id:
            rows = self.fetch_all(
                "SELECT * FROM actions WHERE session_id=? AND status='pending' ORDER BY created_at",
                (session_id,),
            )
        elif owner_id:
            rows = self.fetch_all(
                "SELECT a.* FROM actions a JOIN sessions s ON s.id=a.session_id "
                "WHERE s.owner_id=? AND a.status='pending' ORDER BY a.created_at",
                (owner_id,),
            )
        else:
            rows = self.fetch_all("SELECT * FROM actions WHERE status='pending' ORDER BY created_at")
        return [self._decode_action(row) for row in rows]

    def decide_action(self, action_id: str, status: str, message: str | None) -> None:
        self.execute(
            "UPDATE actions SET status=?,decision_message=?,decided_at=? WHERE id=? AND status='pending'",
            (status, message, datetime.now(UTC).isoformat(), action_id),
        )

    def add_model_call(self, record: ModelCallRecord) -> None:
        values = record.model_dump(mode="json")
        usage = values.pop("usage")
        columns = [
            "call_id",
            "run_id",
            "session_id",
            "owner_id",
            "agent_role",
            "turn_id",
            "task_type",
            "call_site",
            "provider_alias",
            "requested_model",
            "actual_model",
            "model_route",
            "reasoning_effort",
            "started_at",
            "latency_ms",
            "status",
            "retry_index",
            "fallback_from",
            "error_type",
            "input_tokens",
            "cached_input_tokens",
            "cache_miss_input_tokens",
            "output_tokens",
            "reasoning_tokens",
            "total_tokens",
            "actual_cost_usd",
            "estimated_cost_usd",
            "pricing_version",
            "usage_source",
            "usage_unknown",
        ]
        merged = {**values, **usage}
        merged["usage_unknown"] = int(bool(merged["usage_unknown"]))
        placeholders = ",".join("?" for _ in columns)
        self.execute(
            f"INSERT INTO model_calls({','.join(columns)}) VALUES({placeholders})",
            tuple(merged.get(column) for column in columns),
        )

    def model_calls(
        self,
        session_id: str | None = None,
        limit: int = 500,
        owner_id: str | None = None,
    ) -> list[dict[str, Any]]:
        if owner_id is not None:
            if session_id:
                return self.fetch_all(
                    "SELECT * FROM model_calls WHERE owner_id=? AND session_id=? "
                    "ORDER BY started_at DESC LIMIT ?",
                    (owner_id, session_id, limit),
                )
            return self.fetch_all(
                "SELECT * FROM model_calls WHERE owner_id=? ORDER BY started_at DESC LIMIT ?",
                (owner_id, limit),
            )
        if session_id:
            return self.fetch_all(
                "SELECT * FROM model_calls WHERE session_id=? ORDER BY started_at DESC LIMIT ?",
                (session_id, limit),
            )
        return self.fetch_all(
            "SELECT * FROM model_calls ORDER BY started_at DESC LIMIT ?", (limit,)
        )

    def model_calls_for_run(self, run_id: str, owner_id: str | None = None) -> list[dict[str, Any]]:
        if owner_id is None:
            return self.fetch_all(
                "SELECT * FROM model_calls WHERE run_id=? ORDER BY started_at", (run_id,)
            )
        return self.fetch_all(
            "SELECT * FROM model_calls WHERE run_id=? AND owner_id=? ORDER BY started_at",
            (run_id, owner_id),
        )

    def usage_by_agent_role(
        self, session_id: str | None = None, owner_id: str | None = None
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if session_id:
            clauses.append("session_id=?")
            params.append(session_id)
        if owner_id:
            clauses.append("owner_id=?")
            params.append(owner_id)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        return self.fetch_all(
            "SELECT agent_role, COUNT(*) AS calls, SUM(input_tokens) AS input_tokens, "
            "SUM(output_tokens) AS output_tokens, SUM(total_tokens) AS total_tokens, "
            "SUM(estimated_cost_usd) AS estimated_cost_usd "
            f"FROM model_calls {where} GROUP BY agent_role ORDER BY agent_role",
            tuple(params),
        )

    def usage_rows(
        self,
        session_id: str | None = None,
        day: str | None = None,
        owner_id: str | None = None,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if session_id:
            clauses.append("session_id=?")
            params.append(session_id)
        if day:
            clauses.append("substr(started_at,1,10)=?")
            params.append(day)
        if owner_id is not None:
            clauses.append("owner_id=?")
            params.append(owner_id)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        return self.fetch_all(f"SELECT * FROM model_calls {where}", tuple(params))

    def save_daily_plan(self, plan: Any) -> None:
        payload = json.dumps(plan.model_dump(mode="json"), ensure_ascii=False, default=str)
        now = datetime.now(UTC).isoformat()
        self.execute(
            "INSERT INTO daily_plans(id,session_id,plan_date,payload_json,created_at,updated_at) "
            "VALUES(?,?,?,?,?,?) ON CONFLICT(session_id,plan_date) DO UPDATE SET "
            "id=excluded.id,payload_json=excluded.payload_json,updated_at=excluded.updated_at",
            (plan.id, plan.session_id, plan.plan_date.isoformat(), payload, now, now),
        )

    def get_daily_plan(self, session_id: str, plan_date: str) -> dict[str, Any] | None:
        row = self.fetch_one(
            "SELECT * FROM daily_plans WHERE session_id=? AND plan_date=?",
            (session_id, plan_date),
        )
        if row:
            row["payload"] = json.loads(row.pop("payload_json"))
        return row

    def save_daily_review(self, review: Any) -> None:
        payload = json.dumps(review.model_dump(mode="json"), ensure_ascii=False, default=str)
        now = datetime.now(UTC).isoformat()
        self.execute(
            "INSERT INTO daily_reviews(id,session_id,review_date,payload_json,created_at,updated_at) "
            "VALUES(?,?,?,?,?,?) ON CONFLICT(session_id,review_date) DO UPDATE SET "
            "id=excluded.id,payload_json=excluded.payload_json,updated_at=excluded.updated_at",
            (review.id, review.session_id, review.review_date.isoformat(), payload, now, now),
        )

    def get_daily_review(self, session_id: str, review_date: str) -> dict[str, Any] | None:
        row = self.fetch_one(
            "SELECT * FROM daily_reviews WHERE session_id=? AND review_date=?",
            (session_id, review_date),
        )
        if row:
            row["payload"] = json.loads(row.pop("payload_json"))
        return row

    def get_notification_settings(self, session_id: str) -> dict[str, Any] | None:
        row = self.fetch_one("SELECT * FROM notification_settings WHERE session_id=?", (session_id,))
        if row:
            row["enabled"] = bool(row["enabled"])
        return row

    def mark_notification_verified(self, session_id: str) -> None:
        self.execute(
            "UPDATE notification_settings SET verified_at=?,updated_at=? WHERE session_id=?",
            (datetime.now(UTC).isoformat(), datetime.now(UTC).isoformat(), session_id),
        )

    def save_notification_settings(
        self,
        session_id: str,
        *,
        email: str,
        enabled: bool,
        timezone: str,
        morning_time: str,
        evening_time: str,
        verified_at: str | None = None,
    ) -> dict[str, Any]:
        self.execute(
            "INSERT INTO notification_settings(session_id,email,enabled,timezone,morning_time,"
            "evening_time,updated_at,verified_at) VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(session_id) DO UPDATE SET "
            "email=excluded.email,enabled=excluded.enabled,timezone=excluded.timezone,"
            "morning_time=excluded.morning_time,evening_time=excluded.evening_time,"
            "updated_at=excluded.updated_at,verified_at=COALESCE(excluded.verified_at,notification_settings.verified_at)",
            (
                session_id,
                email,
                int(enabled),
                timezone,
                morning_time,
                evening_time,
                datetime.now(UTC).isoformat(),
                verified_at,
            ),
        )
        return self.get_notification_settings(session_id) or {}

    def enabled_notification_settings(self) -> list[dict[str, Any]]:
        rows = self.fetch_all("SELECT * FROM notification_settings WHERE enabled=1")
        for row in rows:
            row["enabled"] = True
        return rows

    def reserve_notification_delivery(
        self, session_id: str, local_date: str, schedule_type: str, delivery_id: str
    ) -> dict[str, Any]:
        now = datetime.now(UTC).isoformat()
        self.execute(
            "INSERT OR IGNORE INTO notification_deliveries "
            "(id,session_id,local_date,schedule_type,status,attempts,next_attempt_at,created_at,updated_at) "
            "VALUES(?,?,?,?,?,?,?,?,?)",
            (delivery_id, session_id, local_date, schedule_type, "pending", 0, now, now, now),
        )
        return self.fetch_one(
            "SELECT * FROM notification_deliveries WHERE session_id=? AND local_date=? "
            "AND schedule_type=?",
            (session_id, local_date, schedule_type),
        ) or {}

    def update_notification_delivery(self, delivery_id: str, **values: Any) -> None:
        allowed = {"status", "attempts", "next_attempt_at", "message_id", "last_error", "sent_at"}
        clean = {key: value for key, value in values.items() if key in allowed}
        if not clean:
            return
        clean["updated_at"] = datetime.now(UTC).isoformat()
        columns = ",".join(f"{key}=?" for key in clean)
        self.execute(
            f"UPDATE notification_deliveries SET {columns} WHERE id=?",  # noqa: S608
            (*clean.values(), delivery_id),
        )

    def notification_deliveries(
        self, session_id: str | None = None, limit: int = 100, owner_id: str | None = None
    ) -> list[dict[str, Any]]:
        if session_id:
            return self.fetch_all(
                "SELECT * FROM notification_deliveries WHERE session_id=? "
                "ORDER BY created_at DESC LIMIT ?",
                (session_id, limit),
            )
        if owner_id:
            return self.fetch_all(
                "SELECT d.* FROM notification_deliveries d JOIN sessions s ON s.id=d.session_id "
                "WHERE s.owner_id=? ORDER BY d.created_at DESC LIMIT ?",
                (owner_id, limit),
            )
        return self.fetch_all(
            "SELECT * FROM notification_deliveries ORDER BY created_at DESC LIMIT ?", (limit,)
        )

    def cleanup(self, retention_days: int) -> dict[str, int]:
        cutoff = (datetime.now(UTC) - timedelta(days=retention_days)).isoformat()
        with self._lock, self._connect() as conn:
            messages = conn.execute("DELETE FROM messages WHERE created_at<?", (cutoff,)).rowcount
            events = conn.execute("DELETE FROM events WHERE created_at<?", (cutoff,)).rowcount
            conn.commit()
        checkpoint = "completed"
        try:
            with self._lock, self._connect() as conn:
                conn.execute("PRAGMA wal_checkpoint(PASSIVE)")
        except sqlite3.OperationalError:
            checkpoint = "deferred_locked"
        return {"messages": messages, "events": events, "checkpoint": checkpoint}
