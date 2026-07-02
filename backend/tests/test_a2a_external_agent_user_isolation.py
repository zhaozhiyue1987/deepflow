"""Contract tests for user-owned external A2A agent registration."""

from __future__ import annotations

from uuid import UUID

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


def _user(user_id: str, email: str) -> User:
    return User(
        id=UUID(user_id),
        email=email,
        password_hash="x",
        system_role="user",
    )


def _build_client(user: User) -> TestClient:
    from app.gateway.routers import a2a_external_agents

    app = make_authed_test_app(user_factory=lambda: user)
    app.include_router(a2a_external_agents.router)
    return TestClient(app)


def _valid_external_agent_payload(name: str = "vendor-research-agent") -> dict:
    return {
        "name": name,
        "display_name": "Vendor Research Agent",
        "description": "External A2A research agent",
        "upstream_card_url": "https://vendor.example.com/.well-known/agent-card.json",
        "upstream_auth": {
            "type": "bearer",
            "token": "upstream-secret-token",
        },
    }


def test_gateway_app_mounts_external_a2a_agent_router():
    """The production gateway app exposes external A2A agent management routes."""
    from app.gateway.app import create_app

    app = create_app()
    route_paths = {getattr(route, "path", "") for route in app.routes}

    assert "/api/a2a/external-agents" in route_paths
    assert "/api/a2a/external-agents/{name}" in route_paths


def test_normal_user_can_register_external_a2a_agent(monkeypatch):
    """A normal authenticated user can register and own an external A2A agent."""
    alice = _user("11111111-1111-1111-1111-111111111111", "alice@example.com")

    from app.gateway.routers import a2a_external_agents

    monkeypatch.setattr(
        a2a_external_agents,
        "fetch_and_validate_upstream_card",
        lambda *_args, **_kwargs: {
            "name": "vendor-research-agent",
            "description": "External A2A research agent",
            "capabilities": {"streaming": True, "cancel": True},
            "url": "https://vendor.example.com/a2a/tasks",
        },
        raising=False,
    )

    with _build_client(alice) as client:
        response = client.post("/api/a2a/external-agents", json=_valid_external_agent_payload())

    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "vendor-research-agent"
    assert body["source"] == "external"
    assert body["enabled"] is False
    assert body["card_url"] == "http://testserver/api/a2a/agents/vendor-research-agent/card"
    assert body["task_url"] == "http://testserver/api/a2a/agents/vendor-research-agent/tasks"
    assert body["health_status"] == "healthy"
    assert "upstream_auth" not in body
    assert "upstream-secret-token" not in str(body)


def test_external_a2a_agent_is_owner_scoped(monkeypatch):
    """Another normal user cannot see, update, enable, or delete someone else's external agent."""
    alice = _user("11111111-1111-1111-1111-111111111111", "alice@example.com")
    bob = _user("22222222-2222-2222-2222-222222222222", "bob@example.com")

    from app.gateway.routers import a2a_external_agents

    monkeypatch.setattr(
        a2a_external_agents,
        "fetch_and_validate_upstream_card",
        lambda *_args, **_kwargs: {
            "name": "vendor-private-agent",
            "description": "External A2A research agent",
            "capabilities": {"streaming": True},
            "url": "https://vendor.example.com/a2a/tasks",
        },
        raising=False,
    )

    with _build_client(alice) as alice_client:
        created = alice_client.post("/api/a2a/external-agents", json=_valid_external_agent_payload("vendor-private-agent"))
        assert created.status_code == 201

    with _build_client(bob) as bob_client:
        listed = bob_client.get("/api/a2a/external-agents")
        fetched = bob_client.get("/api/a2a/external-agents/vendor-private-agent")
        updated = bob_client.put(
            "/api/a2a/external-agents/vendor-private-agent",
            json={"display_name": "Bob takeover"},
        )
        enabled = bob_client.post("/api/a2a/external-agents/vendor-private-agent/a2a/enable")
        deleted = bob_client.delete("/api/a2a/external-agents/vendor-private-agent")

    assert listed.status_code == 200
    assert listed.json()["external_agents"] == []
    assert fetched.status_code == 404
    assert updated.status_code == 404
    assert enabled.status_code == 404
    assert deleted.status_code == 404
