import json
from pathlib import Path


def test_openapi_snapshot_contains_public_contract() -> None:
    snapshot = json.loads(
        (Path(__file__).resolve().parents[1] / "docs" / "openapi.json").read_text(encoding="utf-8")
    )
    paths = snapshot["paths"]
    required = {
        "/api/v1/auth/login",
        "/api/v1/auth/logout",
        "/api/v1/auth/me",
        "/api/v1/sessions",
        "/api/v1/actions/{action_id}/decision",
        "/api/v1/sessions/{session_id}/runs",
        "/api/v1/sessions/{session_id}/activity",
        "/api/v1/runs/{run_id}",
        "/api/v1/runs/{run_id}/trace",
        "/api/v1/sessions/{session_id}/agent-status",
        "/api/v1/plans/{session_id}/tasks/{task_id}",
        "/api/v1/plans/{session_id}/tasks/{task_id}/start",
        "/api/v1/plans/{session_id}/tasks/{task_id}/result",
        "/api/v1/reviews/{session_id}/due",
        "/api/v1/usage",
        "/api/v1/usage/agents",
        "/api/v1/notifications/test/{session_id}",
        "/health",
    }
    assert required.issubset(paths)
