"""A2A contract tests for externally registered agents."""

from __future__ import annotations

from uuid import UUID
from types import SimpleNamespace
import asyncio

import pytest
from fastapi.testclient import TestClient

from _router_auth_helpers import make_authed_test_app
from app.gateway.auth.models import User


@pytest.fixture(autouse=True)
def _clear_external_agent_store():
    from app.gateway.routers import a2a_external_agents

    a2a_external_agents.clear_external_agent_store_for_tests()
    yield
    a2a_external_agents.clear_external_agent_store_for_tests()


def _user() -> User:
    return User(
        id=UUID("33333333-3333-3333-3333-333333333333"),
        email="card-owner@example.com",
        password_hash="x",
        system_role="user",
    )


def _build_client(monkeypatch) -> TestClient:
    from app.gateway.routers import a2a, a2a_external_agents

    monkeypatch.setattr(
        a2a_external_agents,
        "fetch_and_validate_upstream_card",
        lambda *_args, **_kwargs: {
            "name": "vendor-card-agent",
            "description": "Upstream card description",
            "url": "https://vendor.example.com/a2a/tasks",
            "capabilities": {"streaming": True, "cancel": True, "files": False},
            "defaultInputModes": ["text/plain"],
            "defaultOutputModes": ["text/plain"],
        },
        raising=False,
    )

    app = make_authed_test_app(user_factory=_user)
    app.include_router(a2a_external_agents.router)
    app.include_router(a2a.router)
    return TestClient(app)


def test_external_agent_card_is_rewritten_to_gateway_urls(monkeypatch):
    with _build_client(monkeypatch) as client:
        created = client.post(
            "/api/a2a/external-agents",
            json={
                "name": "vendor-card-agent",
                "display_name": "Vendor Card Agent",
                "description": "Gateway-managed external agent",
                "upstream_card_url": "https://vendor.example.com/.well-known/agent-card.json",
                "upstream_auth": {"type": "bearer", "token": "upstream-secret-token"},
            },
        )
        assert created.status_code == 201

        enabled = client.post("/api/a2a/external-agents/vendor-card-agent/a2a/enable")
        assert enabled.status_code == 200

        response = client.get("/api/a2a/agents/vendor-card-agent/card")

    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "vendor-card-agent"
    assert body["source"] == "external"
    assert body["description"] == "Gateway-managed external agent"
    assert body["url"] == "http://testserver/api/a2a/agents/vendor-card-agent/tasks"
    assert body["card_url"] == "http://testserver/api/a2a/agents/vendor-card-agent/card"
    assert body["capabilities"] == {"streaming": True, "cancel": True, "files": False}
    assert body["defaultInputModes"] == ["text/plain"]
    assert body["defaultOutputModes"] == ["text/plain"]
    assert "https://vendor.example.com" not in str(body)
    assert "upstream-secret-token" not in str(body)


def test_external_agent_card_requires_enabled_publication(monkeypatch):
    with _build_client(monkeypatch) as client:
        created = client.post(
            "/api/a2a/external-agents",
            json={
                "name": "vendor-disabled-agent",
                "display_name": "Vendor Disabled Agent",
                "description": "Disabled external agent",
                "upstream_card_url": "https://vendor.example.com/.well-known/agent-card.json",
                "upstream_auth": {"type": "none"},
            },
        )
        assert created.status_code == 201

        response = client.get("/api/a2a/agents/vendor-disabled-agent/card")

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "a2a_agent_not_published"


def test_registry_lists_published_external_agent_with_gateway_urls(monkeypatch):
    with _build_client(monkeypatch) as client:
        created = client.post(
            "/api/a2a/external-agents",
            json={
                "name": "vendor-registry-agent",
                "display_name": "Vendor Registry Agent",
                "description": "External registry entry",
                "upstream_card_url": "https://vendor.example.com/.well-known/agent-card.json",
                "upstream_auth": {"type": "none"},
            },
        )
        assert created.status_code == 201
        enabled = client.post("/api/a2a/external-agents/vendor-registry-agent/a2a/enable")
        assert enabled.status_code == 200

        response = client.get("/api/a2a/registry")

    assert response.status_code == 200
    body = response.json()
    assert body["agents"] == [
        {
            "name": "vendor-registry-agent",
            "source": "external",
            "description": "External registry entry",
            "card_url": "http://testserver/api/a2a/agents/vendor-registry-agent/card",
            "task_url": "http://testserver/api/a2a/agents/vendor-registry-agent/tasks",
            "capabilities": {"streaming": True, "cancel": True, "files": False},
        }
    ]


def test_external_task_requires_gateway_token(monkeypatch):
    with _build_client(monkeypatch) as client:
        created = client.post(
            "/api/a2a/external-agents",
            json={
                "name": "vendor-token-agent",
                "display_name": "Vendor Token Agent",
                "description": "Token protected external agent",
                "upstream_card_url": "https://vendor.example.com/.well-known/agent-card.json",
                "upstream_auth": {"type": "none"},
            },
        )
        assert created.status_code == 201
        enabled = client.post("/api/a2a/external-agents/vendor-token-agent/a2a/enable")
        assert enabled.status_code == 200
        assert enabled.json()["token"].startswith("a2a_")

        response = client.post(
            "/api/a2a/agents/vendor-token-agent/tasks",
            json={"message": {"role": "user", "parts": [{"kind": "text", "text": "hello"}]}},
        )

    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "a2a_token_missing"


def test_external_agent_disable_unpublishes_card_and_task(monkeypatch):
    with _build_client(monkeypatch) as client:
        created = client.post(
            "/api/a2a/external-agents",
            json={
                "name": "vendor-disable-agent",
                "display_name": "Vendor Disable Agent",
                "description": "Disable external publication",
                "upstream_card_url": "https://vendor.example.com/.well-known/agent-card.json",
                "upstream_auth": {"type": "none"},
            },
        )
        assert created.status_code == 201
        enabled = client.post("/api/a2a/external-agents/vendor-disable-agent/a2a/enable")
        assert enabled.status_code == 200
        token = enabled.json()["token"]

        disabled = client.post("/api/a2a/external-agents/vendor-disable-agent/a2a/disable")
        card = client.get("/api/a2a/agents/vendor-disable-agent/card")
        task = client.post(
            "/api/a2a/agents/vendor-disable-agent/tasks",
            headers={"Authorization": f"Bearer {token}"},
            json={"message": {"role": "user", "parts": [{"kind": "text", "text": "hello"}]}},
        )

    assert disabled.status_code == 200
    assert disabled.json()["enabled"] is False
    assert disabled.json()["token"] is None
    assert disabled.json()["token_prefix"] is None
    assert card.status_code == 403
    assert card.json()["detail"]["code"] == "a2a_agent_not_published"
    assert task.status_code == 403
    assert task.json()["detail"]["code"] == "a2a_agent_not_published"


def test_external_agent_rotate_returns_new_token_and_revokes_old_token(monkeypatch):
    from app.gateway.routers import a2a

    async def _forward(record, payload):
        return {"upstream_task_id": "upstream-task-rotated", "status": "submitted", "result": None}

    monkeypatch.setattr(a2a, "forward_external_task_to_upstream", _forward, raising=False)

    with _build_client(monkeypatch) as client:
        created = client.post(
            "/api/a2a/external-agents",
            json={
                "name": "vendor-rotate-agent",
                "display_name": "Vendor Rotate Agent",
                "description": "Rotate gateway token",
                "upstream_card_url": "https://vendor.example.com/.well-known/agent-card.json",
                "upstream_auth": {"type": "none"},
            },
        )
        assert created.status_code == 201
        old_token = client.post("/api/a2a/external-agents/vendor-rotate-agent/a2a/enable").json()["token"]

        rotated = client.post("/api/a2a/external-agents/vendor-rotate-agent/a2a/rotate")
        new_token = rotated.json()["token"]
        old_task = client.post(
            "/api/a2a/agents/vendor-rotate-agent/tasks",
            headers={"Authorization": f"Bearer {old_token}"},
            json={"message": {"role": "user", "parts": [{"kind": "text", "text": "old"}]}},
        )
        new_task = client.post(
            "/api/a2a/agents/vendor-rotate-agent/tasks",
            headers={"Authorization": f"Bearer {new_token}"},
            json={"message": {"role": "user", "parts": [{"kind": "text", "text": "new"}]}},
        )

    assert rotated.status_code == 200
    assert rotated.json()["enabled"] is True
    assert new_token.startswith("a2a_")
    assert new_token != old_token
    assert old_task.status_code == 401
    assert old_task.json()["detail"]["code"] == "a2a_token_invalid"
    assert new_task.status_code == 200
    assert new_task.json()["upstream_task_id"] == "upstream-task-rotated"


def test_external_task_forwards_to_upstream_with_gateway_token(monkeypatch):
    from app.gateway.routers import a2a

    forwarded: dict = {}

    async def _forward(record, payload):
        forwarded["agent_name"] = record.name
        forwarded["payload"] = payload
        return {
            "upstream_task_id": "upstream-task-1",
            "status": "completed",
            "result": {"message": {"role": "agent", "parts": [{"kind": "text", "text": "done"}]}},
        }

    monkeypatch.setattr(a2a, "forward_external_task_to_upstream", _forward, raising=False)

    with _build_client(monkeypatch) as client:
        created = client.post(
            "/api/a2a/external-agents",
            json={
                "name": "vendor-forward-agent",
                "display_name": "Vendor Forward Agent",
                "description": "Forwarded external agent",
                "upstream_card_url": "https://vendor.example.com/.well-known/agent-card.json",
                "upstream_auth": {"type": "bearer", "token": "upstream-secret-token"},
            },
        )
        assert created.status_code == 201
        token = client.post("/api/a2a/external-agents/vendor-forward-agent/a2a/enable").json()["token"]

        response = client.post(
            "/api/a2a/agents/vendor-forward-agent/tasks",
            headers={"Authorization": f"Bearer {token}"},
            json={"message": {"role": "user", "parts": [{"kind": "text", "text": "hello"}]}},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["agent_name"] == "vendor-forward-agent"
    assert body["source"] == "external"
    assert body["task_id"].startswith("gw-task-")
    assert body["upstream_task_id"] == "upstream-task-1"
    assert body["status"] == "completed"
    assert body["result"]["message"]["parts"][0]["text"] == "done"
    assert forwarded["agent_name"] == "vendor-forward-agent"
    assert forwarded["payload"]["message"]["parts"][0]["text"] == "hello"
    assert "upstream-secret-token" not in str(body)


def test_forward_external_task_posts_to_upstream_with_stored_auth(monkeypatch):
    from app.gateway.routers import a2a

    calls: dict = {}

    class _FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"id": "upstream-real-1", "status": "submitted"}

    class _FakeAsyncClient:
        def __init__(self, **kwargs):
            calls["client_kwargs"] = kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_exc):
            return None

        async def post(self, url, *, json, headers):
            calls["url"] = url
            calls["json"] = json
            calls["headers"] = headers
            return _FakeResponse()

    monkeypatch.setattr(a2a.httpx, "AsyncClient", _FakeAsyncClient)

    record = SimpleNamespace(
        upstream_card={"url": "https://example.com/a2a/tasks"},
        upstream_auth_type="bearer",
        upstream_auth_token="upstream-secret-token",
    )
    payload = {"message": {"role": "user", "parts": [{"kind": "text", "text": "hello"}]}}

    result = asyncio.run(a2a.forward_external_task_to_upstream(record, payload))

    assert calls["client_kwargs"]["timeout"] == 60.0
    assert calls["url"] == "https://example.com/a2a/tasks"
    assert calls["json"] == payload
    assert calls["headers"] == {"Authorization": "Bearer upstream-secret-token"}
    assert result == {"upstream_task_id": "upstream-real-1", "status": "submitted", "result": None}
