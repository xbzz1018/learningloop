import asyncio
from datetime import date

from fastapi.testclient import TestClient
from pydantic import SecretStr

from learningloop.auth import AuthService
from learningloop.config import Settings
from learningloop.db import Database
from learningloop.learning.schemas import DailyPlan
from learningloop.models import ModelRoute
from learningloop.web import create_app


def auth_settings(tmp_path):
    return Settings(
        _env_file=None,
        data_dir=tmp_path / "data",
        auth_enabled=True,
        auth_cookie_secure=False,
        enable_real_models=False,
        vibe_flash_key=SecretStr("vibe-flash-test-key"),
        vibe_pro_key=SecretStr("vibe-pro-test-key"),
        kcne_flash_key=SecretStr("kcne-flash-test-key"),
        kcne_pro_key=SecretStr("kcne-pro-test-key"),
    )


def test_login_and_owner_scoped_sessions(tmp_path) -> None:
    settings = auth_settings(tmp_path)
    settings.prepare_directories()
    db = Database(settings.database_path)
    auth = AuthService(settings, db)
    db.create_user("user-a", "alice", auth.hash_password("alice-password-123"))
    db.create_user("user-b", "bob", auth.hash_password("bob-password-123"))

    with TestClient(create_app(settings)) as alice:
        login = alice.post(
            "/api/v1/auth/login",
            json={"username": "alice", "password": "alice-password-123"},
        )
        assert login.status_code == 200
        session = alice.post("/api/v1/sessions")
        assert session.status_code == 201
        session_id = session.json()["id"]
        assert alice.get("/api/v1/sessions").json()["sessions"][0]["owner_id"] == "user-a"

    with TestClient(create_app(settings)) as bob:
        assert bob.post(
            "/api/v1/auth/login",
            json={"username": "bob", "password": "bob-password-123"},
        ).status_code == 200
        assert bob.get(f"/api/v1/sessions/{session_id}/state").status_code == 404
        assert bob.get("/api/v1/sessions").json()["sessions"] == []


def test_auth_rejects_invalid_credentials(tmp_path) -> None:
    settings = auth_settings(tmp_path)
    settings.prepare_directories()
    db = Database(settings.database_path)
    auth = AuthService(settings, db)
    db.create_user("user-a", "alice", auth.hash_password("alice-password-123"))
    with TestClient(create_app(settings)) as client:
        assert client.get("/", follow_redirects=False).status_code == 303
        assert client.get("/api/v1/sessions").status_code == 401
        assert client.post(
            "/api/v1/auth/login",
            json={"username": "alice", "password": "wrong-password"},
        ).status_code == 401


def test_scheduled_model_call_uses_session_owner(tmp_path) -> None:
    settings = auth_settings(tmp_path)
    settings.prepare_directories()
    db = Database(settings.database_path)
    auth = AuthService(settings, db)
    db.create_user("user-a", "alice", auth.hash_password("alice-password-123"))
    session_id = "owned-session"
    db.create_session(session_id, owner_id="user-a")

    seen = {}

    class FakeLLM:
        async def complete(self, *args, **kwargs):
            from learningloop.llm.context import current_call_context, current_model_route

            seen["owner_id"] = current_call_context.get().owner_id
            seen["route"] = current_model_route.get()
            return {"text": DailyPlan(
                id="ignored",
                session_id=session_id,
                plan_date=date.today(),
                total_minutes=0,
                tasks=[],
            ).model_dump_json()}

    from learningloop.agent import AgentService

    service = AgentService(settings, db)
    service.gateway.llm = FakeLLM()
    base = DailyPlan(
        id="base",
        session_id=session_id,
        plan_date=date.today(),
        total_minutes=0,
        tasks=[],
    )
    result = asyncio.run(service.daily._model_plan(session_id, base))
    assert result.session_id == session_id
    assert seen == {"owner_id": "user-a", "route": ModelRoute.FLASH}
