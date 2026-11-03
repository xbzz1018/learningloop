from types import SimpleNamespace

import pytest

from learningloop.doctor import CapabilityDoctor
from learningloop.llm.gateway import ModelGateway
from learningloop.models import ModelRoute


def no_keys(settings):
    return settings.model_copy(update={
        "deepseek_api_key": None,
        "vibe_flash_key": None,
        "vibe_pro_key": None,
        "kcne_flash_key": None,
        "kcne_pro_key": None,
    })


def forbid_network(*args, **kwargs):
    raise AssertionError("No provider client should be constructed")


def test_configured_without_keys_is_offline(settings, db, monkeypatch):
    monkeypatch.setattr("learningloop.doctor.AsyncOpenAI", forbid_network)
    monkeypatch.setattr(ModelGateway, "_build_adapter", forbid_network)
    result = CapabilityDoctor(no_keys(settings), db).configured()
    assert len(result) == 6
    assert all(not value["configured"] for value in result.values())
    assert all(value["status"] == "missing_key" for value in result.values())


async def test_live_without_keys_persists_unavailable_without_network(settings, db, monkeypatch):
    monkeypatch.setattr("learningloop.doctor.AsyncOpenAI", forbid_network)
    result = await CapabilityDoctor(no_keys(settings), db).run_live()
    assert len(result) == 6
    assert all(not value["available"] and value["error"] == "missing_key" for value in result.values())
    rows = db.fetch_all("SELECT error,chat_ok FROM provider_capabilities")
    assert len(rows) == 6
    assert all(row["error"] == "missing_key" and row["chat_ok"] == 0 for row in rows)


def saved_result(error):
    return {"models_ok": True, "chat_ok": True, "structured_ok": True,
            "streaming_ok": True, "usage_ok": True, "responses_ok": False,
            "web_search_ok": False, "actual_model": "fake", "error": error}


@pytest.mark.parametrize("error", ["AuthenticationError", "PermissionDeniedError", "missing_key"])
def test_known_auth_failure_excluded_and_successful_retest_restores(settings, db, error):
    doctor = CapabilityDoctor(settings, db)
    doctor._save("kcne", "pro", saved_result(error))
    gateway = ModelGateway(settings, db, build_router=False)
    assert gateway._candidate_aliases(ModelRoute.PRO) == ["vibe"]
    doctor._save("kcne", "pro", saved_result(None))
    assert gateway._candidate_aliases(ModelRoute.PRO) == ["vibe", "kcne"]


def test_search_failure_does_not_disable_chat(settings, db):
    doctor = CapabilityDoctor(settings, db)
    doctor._save("kcne", "pro", saved_result("web_search:RuntimeError"))
    assert ModelGateway(settings, db, build_router=False)._candidate_aliases(ModelRoute.PRO) == ["vibe", "kcne"]
    row = db.fetch_one("SELECT tools_ok FROM provider_capabilities WHERE provider_alias='kcne'")
    assert row["tools_ok"] == 0


async def test_chat_and_structured_are_independent_and_clients_close(settings, db, monkeypatch):
    clients = []

    class Client:
        def __init__(self, **kwargs):
            self.models = self
            self.closed = False
            clients.append(self)

        async def list(self):
            return SimpleNamespace(data=[SimpleNamespace(id="deepseek-v4-flash"), SimpleNamespace(id="deepseek-v4-pro")])

        async def close(self):
            self.closed = True

    class Adapter:
        last_usage = {"tokens_in": 3, "model": "fake"}

        async def complete(self, **kwargs):
            if "response_format" in kwargs:
                return {"text": "invalid json"}
            return {"text": "OK"}

        async def stream_complete(self, **kwargs):
            yield "OK"

    doctor = CapabilityDoctor(settings, db)

    def build(alias, route, index):
        adapter = Adapter()
        doctor.gateway.adapters[f"{alias}_{route.value}"] = adapter
        return adapter

    async def search(*args):
        return {"sources": ["https://example.invalid"]}

    monkeypatch.setattr("learningloop.doctor.AsyncOpenAI", Client)
    monkeypatch.setattr(doctor.gateway, "_build_adapter", build)
    monkeypatch.setattr(doctor.search, "_responses_search", search)
    result = await doctor.run_live()
    assert result["vibe_flash"]["chat_ok"] is True
    assert result["vibe_flash"]["structured_ok"] is False
    assert result["vibe_flash"]["available"] is True
    assert result["vibe_flash"]["error"] == "structured:JSONDecodeError"
    assert result["vibe_pro"]["web_search_status"] == "not_checked"
    assert len(clients) == 4 and all(client.closed for client in clients)


async def test_auth_failure_is_redacted_unavailable_and_client_closes(settings, db, monkeypatch):
    clients = []

    class Unauthorized(Exception):
        status_code = 401

    class Client:
        def __init__(self, **kwargs):
            self.models = self
            self.closed = False
            clients.append(self)

        async def list(self):
            raise Unauthorized("secret response body must never escape")

        async def close(self):
            self.closed = True

    monkeypatch.setattr("learningloop.doctor.AsyncOpenAI", Client)
    result = await CapabilityDoctor(settings, db).run_live()
    assert result["kcne_pro"]["error"] == "AuthenticationError"
    assert result["kcne_pro"]["status"] == "unavailable"
    assert "secret response" not in str(result)
    row = db.fetch_one("SELECT error FROM provider_capabilities WHERE provider_alias='kcne' AND model_route='pro'")
    assert row["error"] == "AuthenticationError"
    assert all(client.closed for client in clients)
