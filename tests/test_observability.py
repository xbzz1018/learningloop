import json

from learningloop.agent.hooks import RuntimeHooks


def test_trace_redacts_model_content(tmp_path, db) -> None:
    hooks = RuntimeHooks(db, tmp_path / "traces")
    hooks.emit(
        "session",
        "run",
        "done",
        {"answer": "private answer", "token": 3, "api_key": "secret"},
    )
    line = (tmp_path / "traces" / "run.jsonl").read_text(encoding="utf-8")
    record = json.loads(line)
    assert record["payload"]["answer"] == "[content omitted]"
    assert record["payload"]["api_key"] == "[redacted]"
    assert record["payload"]["token"] == 3
