"""Phase A A2A tests: durable external registry and native publish discovery."""

from __future__ import annotations

from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from _router_auth_helpers import make_authed_test_app
from app.gateway.auth.models import User


@pytest.fixture(autouse=True)
def _a2a_home(tmp_path, monkeypatch):
    from deerflow.config import paths as paths_module
    from app.gateway.routers import a2a_external_agents

    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    paths_module._paths = None
    a2a_external_agents.clear_external_agent_store_for_tests()
    yield tmp_path
    a2a_external_agents.clear_external_agent_store_for_tests()
    paths_module._paths = None


def _user() -> User:
    return User(
        id=UUID("44444444-4444-4444-4444-444444444444"),
        email="phase-a-owner@example.com",
        password_hash="x",
        system_role="user",
    )


def _build_client(monkeypatch) -> TestClient:
    from app.gateway.routers import a2a, a2a_external_agents, agents
    from deerflow.config.agents_api_config import AgentsApiConfig, set_agents_api_config
    from deerflow.runtime import RunRecord, RunStatus
    from deerflow.runtime.runs.schemas import DisconnectMode
    import asyncio

    set_agents_api_config(AgentsApiConfig(enabled=True))

    monkeypatch.setattr(
        a2a_external_agents,
        "fetch_and_validate_upstream_card",
        lambda *_args, **_kwargs: {
            "name": "vendor-persistent-agent",
            "description": "Durable upstream card",
            "url": "https://vendor.example.com/a2a/tasks",
            "capabilities": {"streaming": True, "cancel": True, "files": False},
            "defaultInputModes": ["text/plain"],
            "defaultOutputModes": ["text/plain"],
        },
        raising=False,
    )

    async def _mock_start_run(body, thread_id, request):
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

    monkeypatch.setattr(a2a, "start_run", _mock_start_run)

    app = make_authed_test_app(user_factory=_user)
    app.include_router(agents.router)
    app.include_router(a2a_external_agents.router)
    app.include_router(a2a.router)
    return TestClient(app)


def test_external_agent_survives_store_reload_and_keeps_token_hash(monkeypatch):
    from app.gateway.routers import a2a, a2a_external_agents

    async def _forward(_record, _payload):
        return {"upstream_task_id": "upstream-after-reload", "status": "submitted", "result": None}

    monkeypatch.setattr(a2a, "forward_external_task_to_upstream", _forward, raising=False)

    with _build_client(monkeypatch) as client:
        created = client.post(
            "/api/a2a/external-agents",
            json={
                "name": "vendor-persistent-agent",
                "display_name": "Vendor Persistent Agent",
                "description": "Persisted external A2A agent",
                "upstream_card_url": "https://vendor.example.com/.well-known/agent-card.json",
                "upstream_auth": {"type": "bearer", "token": "upstream-secret-token"},
            },
        )
        assert created.status_code == 201
        token = client.post("/api/a2a/external-agents/vendor-persistent-agent/a2a/enable").json()["token"]

    a2a_external_agents.clear_external_agent_store_for_tests(clear_disk=False)

    with _build_client(monkeypatch) as client:
        listed = client.get("/api/a2a/external-agents")
        card = client.get("/api/a2a/agents/vendor-persistent-agent/card")
        task = client.post(
            "/api/a2a/agents/vendor-persistent-agent/tasks",
            headers={"Authorization": f"Bearer {token}"},
            json={"message": {"role": "user", "parts": [{"kind": "text", "text": "hello"}]}},
        )

    assert listed.status_code == 200
    body = listed.json()
    assert body["external_agents"][0]["name"] == "vendor-persistent-agent"
    assert body["external_agents"][0]["enabled"] is True
    assert body["external_agents"][0]["token"] is None
    assert "upstream-secret-token" not in str(body)
    assert card.status_code == 200
    assert task.status_code == 200
    assert task.json()["upstream_task_id"] == "upstream-after-reload"


def test_native_agent_can_be_published_to_registry_and_card(monkeypatch):
    with _build_client(monkeypatch) as client:
        created = client.post(
            "/api/agents",
            json={
                "name": "native-researcher",
                "description": "Native research agent",
                "model": "secret-model-id",
                "soul": "Do not leak this soul.",
            },
        )
        assert created.status_code == 201

        enabled = client.post("/api/agents/native-researcher/a2a/enable")
        listed_agents = client.get("/api/agents")
        registry = client.get("/api/a2a/registry")
        card = client.get("/api/a2a/agents/native-researcher/card")

    assert enabled.status_code == 200
    enabled_body = enabled.json()
    assert enabled_body["enabled"] is True
    assert enabled_body["source"] == "native"
    assert enabled_body["token"].startswith("a2a_")
    assert enabled_body["card_url"] == "http://testserver/api/a2a/agents/native-researcher/card"

    assert listed_agents.status_code == 200
    listed_native = next(agent for agent in listed_agents.json()["agents"] if agent["name"] == "native-researcher")
    assert listed_native["source"] == "native"
    assert listed_native["enabled"] is True
    assert listed_native["card_url"] == "http://testserver/api/a2a/agents/native-researcher/card"
    assert listed_native["task_url"] == "http://testserver/api/a2a/agents/native-researcher/tasks"
    assert listed_native["token_prefix"] == enabled_body["token_prefix"]
    assert listed_native["token"] is None

    assert registry.status_code == 200
    assert {
        "name": "native-researcher",
        "source": "native",
        "description": "Native research agent",
        "card_url": "http://testserver/api/a2a/agents/native-researcher/card",
        "task_url": "http://testserver/api/a2a/agents/native-researcher/tasks",
        "capabilities": {"streaming": False, "cancel": False, "files": False},
    } in registry.json()["agents"]

    assert card.status_code == 200
    card_body = card.json()
    assert card_body["name"] == "native-researcher"
    assert card_body["source"] == "native"
    assert card_body["url"] == "http://testserver/api/a2a/agents/native-researcher/tasks"
    assert "secret-model-id" not in str(card_body)
    assert "Do not leak this soul" not in str(card_body)


def test_native_phase_a_task_guard_is_explicit(monkeypatch):
    with _build_client(monkeypatch) as client:
        assert client.post(
            "/api/agents",
            json={"name": "native-task-agent", "description": "Native task guard", "soul": "private"},
        ).status_code == 201
        token = client.post("/api/agents/native-task-agent/a2a/enable").json()["token"]

        response = client.post(
            "/api/a2a/agents/native-task-agent/tasks",
            headers={"Authorization": f"Bearer {token}"},
            json={"message": {"role": "user", "parts": [{"kind": "text", "text": "run"}]}},
        )

    # Phase B: native task now maps to thread/run (mocked in test env)
    assert response.status_code == 200
    body = response.json()
    assert body["agent_name"] == "native-task-agent"
    assert body["source"] == "native"
    assert "task_id" in body
