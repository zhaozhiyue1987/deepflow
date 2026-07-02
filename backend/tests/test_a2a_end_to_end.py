"""End-to-end A2A test: external + native agent full lifecycle.

Run:
    cd deer-flow/backend
    UV_INDEX_URL=https://mirrors.aliyun.com/pypi/simple uv run pytest tests/test_a2a_end_to_end.py -v
"""

from __future__ import annotations

import asyncio
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from _router_auth_helpers import make_authed_test_app
from app.gateway.auth.models import User
from deerflow.runtime import RunRecord, RunStatus
from deerflow.runtime.runs.schemas import DisconnectMode


def _user() -> User:
    return User(
        id=UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
        email="e2e-tester@example.com",
        password_hash="x",
        system_role="user",
    )


@pytest.fixture(autouse=True)
def _clear_store(monkeypatch):
    from app.gateway.routers import a2a, a2a_external_agents

    a2a_external_agents.clear_external_agent_store_for_tests()
    monkeypatch.setattr(
        a2a_external_agents,
        "fetch_and_validate_upstream_card",
        lambda *_a, **_k: {
            "name": "upstream-demo",
            "description": "Upstream description",
            "url": "https://upstream.example.com/tasks",
            "capabilities": {"streaming": False, "cancel": False, "files": False},
            "defaultInputModes": ["text/plain"],
            "defaultOutputModes": ["text/plain"],
        },
        raising=False,
    )
    monkeypatch.setattr(
        a2a,
        "forward_external_task_to_upstream",
        lambda _record, _payload: {
            "task_id": "upstream-task-123",
            "status": "completed",
            "messages": [{"role": "assistant", "parts": [{"kind": "text", "text": "Done"}]}],
        },
        raising=False,
    )
    yield
    a2a_external_agents.clear_external_agent_store_for_tests()


async def _mock_start_run(body, thread_id, request):
    """Mock DeerFlow start_run so tests don't need full runtime infrastructure."""
    record = RunRecord(
        run_id=f"run-{thread_id}",
        thread_id=thread_id,
        assistant_id=getattr(body, "assistant_id", None),
        status=RunStatus.success,
        on_disconnect=DisconnectMode.cancel,
    )

    async def _done():
        pass

    record.task = asyncio.create_task(_done())
    return record


def _build_client(monkeypatch) -> TestClient:
    from app.gateway.routers import a2a, a2a_external_agents, agents

    monkeypatch.setattr(a2a, "start_run", _mock_start_run)

    app = make_authed_test_app(user_factory=_user)
    app.include_router(agents.router)
    app.include_router(a2a_external_agents.router)
    app.include_router(a2a.router)
    return TestClient(app)


def test_a2a_external_full_lifecycle(monkeypatch):
    """External A2A: register -> enable -> registry -> card -> task -> rotate -> old-token-invalid -> disable -> gone.
    """
    client = _build_client(monkeypatch)

    # 1. Register
    create = client.post(
        "/api/a2a/external-agents",
        json={
            "name": "e2e-writer",
            "display_name": "E2E Writer",
            "description": "End-to-end test agent",
            "upstream_card_url": "https://upstream.example.com/.well-known/agent-card.json",
            "upstream_auth": {"type": "none"},
        },
        headers={"X-CSRF-Token": "test-csrf"},
    )
    assert create.status_code == 201
    body = create.json()
    assert body["name"] == "e2e-writer"
    assert body["source"] == "external"
    assert body["enabled"] is False
    assert body["health_status"] == "healthy"

    # 2. Enable
    enable = client.post(
        "/api/a2a/external-agents/e2e-writer/a2a/enable",
        headers={"X-CSRF-Token": "test-csrf"},
    )
    assert enable.status_code == 200
    enabled = enable.json()
    assert enabled["enabled"] is True
    assert enabled["token_prefix"].startswith("a2a_")
    assert enabled["token"].startswith("a2a_")
    token_1 = enabled["token"]

    # 3. Registry public
    registry = client.get("/api/a2a/registry")
    assert registry.status_code == 200
    agents = registry.json()["agents"]
    match = next((a for a in agents if a["name"] == "e2e-writer"), None)
    assert match is not None
    assert match["source"] == "external"
    assert "/api/a2a/agents/e2e-writer/card" in match["card_url"]
    assert "/api/a2a/agents/e2e-writer/tasks" in match["task_url"]

    # 4. Card public
    card = client.get("/api/a2a/agents/e2e-writer/card")
    assert card.status_code == 200
    c = card.json()
    assert c["name"] == "e2e-writer"
    assert c["source"] == "external"
    assert "/api/a2a/agents/e2e-writer/tasks" in c["url"]
    assert "/api/a2a/agents/e2e-writer/card" in c["card_url"]
    assert "upstream" not in c.get("authentication", {})

    # 5. Task with bearer
    task = client.post(
        "/api/a2a/agents/e2e-writer/tasks",
        json={"message": {"role": "user", "parts": [{"kind": "text", "text": "Write"}]}},
        headers={"Authorization": f"Bearer {token_1}"},
    )
    assert task.status_code == 200
    t = task.json()
    assert t["agent_name"] == "e2e-writer"
    assert t["source"] == "external"
    assert "upstream_task_id" in t
    assert t["status"] in ("submitted", "completed")

    # 6. Rotate token
    rotate = client.post(
        "/api/a2a/external-agents/e2e-writer/a2a/rotate",
        headers={"X-CSRF-Token": "test-csrf"},
    )
    assert rotate.status_code == 200
    rotated = rotate.json()
    assert rotated["token"].startswith("a2a_")
    token_2 = rotated["token"]
    assert token_2 != token_1
    assert rotated["token_prefix"].startswith("a2a_")

    # 7. Old token is now invalid
    bad = client.post(
        "/api/a2a/agents/e2e-writer/tasks",
        json={"message": {"role": "user", "parts": [{"kind": "text", "text": "Write"}]}},
        headers={"Authorization": f"Bearer {token_1}"},
    )
    assert bad.status_code == 401
    assert bad.json()["detail"]["code"] == "a2a_token_invalid"

    # New token still works
    ok = client.post(
        "/api/a2a/agents/e2e-writer/tasks",
        json={"message": {"role": "user", "parts": [{"kind": "text", "text": "Write"}]}},
        headers={"Authorization": f"Bearer {token_2}"},
    )
    assert ok.status_code == 200

    # 8. Disable -> agent disappears from registry
    disable = client.post(
        "/api/a2a/external-agents/e2e-writer/a2a/disable",
        headers={"X-CSRF-Token": "test-csrf"},
    )
    assert disable.status_code == 200
    assert disable.json()["enabled"] is False

    registry_after = client.get("/api/a2a/registry")
    assert not any(a["name"] == "e2e-writer" for a in registry_after.json()["agents"])

    # Card returns 403 after disable
    card_after = client.get("/api/a2a/agents/e2e-writer/card")
    assert card_after.status_code == 403


def test_a2a_native_full_lifecycle(monkeypatch):
    """Native A2A: create -> enable -> registry -> card -> task -> rotate -> old-token-invalid -> disable -> gone.
    """
    client = _build_client(monkeypatch)

    # 1. Create native agent
    client.delete("/api/agents/e2e-native", headers={"X-CSRF-Token": "test-csrf"})
    create = client.post(
        "/api/agents",
        json={"name": "e2e-native", "description": "Native test agent"},
        headers={"X-CSRF-Token": "test-csrf"},
    )
    assert create.status_code in (200, 201)

    # 2. Enable A2A
    enable = client.post(
        "/api/agents/e2e-native/a2a/enable",
        headers={"X-CSRF-Token": "test-csrf"},
    )
    assert enable.status_code == 200
    enabled = enable.json()
    assert enabled["enabled"] is True
    assert enabled["token"].startswith("a2a_")
    token_1 = enabled["token"]

    # 3. Registry
    registry = client.get("/api/a2a/registry")
    assert registry.status_code == 200
    match = next((a for a in registry.json()["agents"] if a["name"] == "e2e-native"), None)
    assert match is not None
    assert match["source"] == "native"

    # 4. Card
    card = client.get("/api/a2a/agents/e2e-native/card")
    assert card.status_code == 200
    c = card.json()
    assert c["source"] == "native"
    assert "bearer" in c.get("authentication", {}).get("schemes", [])

    # 5. Task with bearer (Phase B)
    task = client.post(
        "/api/a2a/agents/e2e-native/tasks",
        json={"message": {"role": "user", "parts": [{"kind": "text", "text": "hello"}]}},
        headers={"Authorization": f"Bearer {token_1}"},
    )
    assert task.status_code == 200
    t = task.json()
    assert t["agent_name"] == "e2e-native"
    assert t["source"] == "native"
    assert "task_id" in t
    assert t["status"] in ("pending", "running", "success", "completed", "idle")
    assert "result" in t

    # 6. Rotate
    rotate = client.post(
        "/api/agents/e2e-native/a2a/rotate",
        headers={"X-CSRF-Token": "test-csrf"},
    )
    assert rotate.status_code == 200
    rotated = rotate.json()
    token_2 = rotated["token"]
    assert token_2 != token_1

    # 7. Old token invalid
    bad = client.post(
        "/api/a2a/agents/e2e-native/tasks",
        json={"message": {"role": "user", "parts": [{"kind": "text", "text": "hello"}]}},
        headers={"Authorization": f"Bearer {token_1}"},
    )
    assert bad.status_code == 401
    assert bad.json()["detail"]["code"] == "a2a_token_invalid"

    # New token works
    ok = client.post(
        "/api/a2a/agents/e2e-native/tasks",
        json={"message": {"role": "user", "parts": [{"kind": "text", "text": "hello"}]}},
        headers={"Authorization": f"Bearer {token_2}"},
    )
    assert ok.status_code == 200

    # 8. Disable
    disable = client.post(
        "/api/agents/e2e-native/a2a/disable",
        headers={"X-CSRF-Token": "test-csrf"},
    )
    assert disable.status_code == 200
    assert disable.json()["enabled"] is False

    # Gone from registry
    registry_after = client.get("/api/a2a/registry")
    assert not any(a["name"] == "e2e-native" for a in registry_after.json()["agents"])

    # Card 403
    card_after = client.get("/api/a2a/agents/e2e-native/card")
    assert card_after.status_code == 403


def test_a2a_registry_contains_both_native_and_external(monkeypatch):
    """Registry must list both native and external agents when both are enabled."""
    client = _build_client(monkeypatch)

    # External
    client.post(
        "/api/a2a/external-agents",
        json={
            "name": "ext-1",
            "display_name": "Ext 1",
            "description": "x",
            "upstream_card_url": "https://upstream.example.com/card",
            "upstream_auth": {"type": "none"},
        },
        headers={"X-CSRF-Token": "test-csrf"},
    )
    client.post("/api/a2a/external-agents/ext-1/a2a/enable", headers={"X-CSRF-Token": "test-csrf"})

    # Native
    client.delete("/api/agents/native-1", headers={"X-CSRF-Token": "test-csrf"})
    client.post("/api/agents", json={"name": "native-1", "description": "n"}, headers={"X-CSRF-Token": "test-csrf"})
    client.post("/api/agents/native-1/a2a/enable", headers={"X-CSRF-Token": "test-csrf"})

    registry = client.get("/api/a2a/registry")
    assert registry.status_code == 200
    agents = registry.json()["agents"]
    names = {a["name"]: a["source"] for a in agents}
    assert names.get("ext-1") == "external"
    assert names.get("native-1") == "native"
