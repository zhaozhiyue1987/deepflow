"""Security tests for external A2A upstream registration."""

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


def _client() -> TestClient:
    from app.gateway.routers import a2a_external_agents

    user = User(
        id=UUID("44444444-4444-4444-4444-444444444444"),
        email="security@example.com",
        password_hash="x",
        system_role="user",
    )
    app = make_authed_test_app(user_factory=lambda: user)
    app.include_router(a2a_external_agents.router)
    return TestClient(app)


@pytest.mark.parametrize(
    "upstream_card_url",
    [
        "file:///etc/passwd",
        "http://127.0.0.1:8080/.well-known/agent-card.json",
        "http://localhost:8080/.well-known/agent-card.json",
        "http://169.254.169.254/latest/meta-data/",
        "http://10.0.0.1/.well-known/agent-card.json",
    ],
)
def test_external_agent_registration_rejects_unsafe_upstream_urls(upstream_card_url: str):
    with _client() as client:
        response = client.post(
            "/api/a2a/external-agents",
            json={
                "name": "unsafe-upstream-agent",
                "display_name": "Unsafe Upstream Agent",
                "description": "Must be rejected",
                "upstream_card_url": upstream_card_url,
                "upstream_auth": {"type": "none"},
            },
        )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "a2a_upstream_url_forbidden"
