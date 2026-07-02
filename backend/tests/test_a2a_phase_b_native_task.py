"""Phase B RED: native A2A task should create DeerFlow thread/run instead of 501.

Run:
    cd deer-flow/backend
    UV_INDEX_URL=https://mirrors.aliyun.com/pypi/simple uv run pytest tests/test_a2a_phase_b_native_task.py -v
"""

from __future__ import annotations

from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from _router_auth_helpers import make_authed_test_app
from app.gateway.auth.models import User


def _user() -> User:
    return User(
        id=UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
        email="phaseb-tester@example.com",
        password_hash="x",
        system_role="user",
    )


@pytest.fixture(autouse=True)
def _clear_store(monkeypatch):
    from app.gateway.routers import a2a_external_agents

    a2a_external_agents.clear_external_agent_store_for_tests()
    yield
    a2a_external_agents.clear_external_agent_store_for_tests()


def _build_client(monkeypatch) -> TestClient:
    from app.gateway.routers import a2a, a2a_external_agents, agents
    from deerflow.runtime.stream_bridge.memory import MemoryStreamBridge
    from deerflow.runtime import RunRecord, RunStatus
    from deerflow.runtime.runs.schemas import DisconnectMode
    import asyncio

    app = make_authed_test_app(user_factory=_user)
    app.state.stream_bridge = MemoryStreamBridge()
    app.include_router(agents.router)
    app.include_router(a2a_external_agents.router)
    app.include_router(a2a.router)

    # Mock start_run to avoid needing full run_manager/checkpointer setup
    async def _mock_start_run(body, thread_id, request):
        record = RunRecord(
            run_id=f"run-{thread_id}",
            thread_id=thread_id,
            assistant_id=getattr(body, "assistant_id", None),
            status=RunStatus.success,
            on_disconnect=DisconnectMode.cancel,
        )
        # Set a completed task so wait_for_run_completion can observe it
        async def _done():
            pass
        record.task = asyncio.create_task(_done())
        return record

    monkeypatch.setattr(a2a, "start_run", _mock_start_run)

    return TestClient(app)


def test_native_a2a_task_creates_thread_and_run(monkeypatch):
    """Native A2A task should map to DeerFlow thread/run and return result."""
    client = _build_client(monkeypatch)

    # Create a native agent
    client.delete("/api/agents/phaseb-native", headers={"X-CSRF-Token": "test-csrf"})
    create_res = client.post(
        "/api/agents",
        json={"name": "phaseb-native", "description": "Phase B test agent"},
        headers={"X-CSRF-Token": "test-csrf"},
    )
    assert create_res.status_code in (200, 201)

    # Enable native A2A
    enable_res = client.post(
        "/api/agents/phaseb-native/a2a/enable",
        headers={"X-CSRF-Token": "test-csrf"},
    )
    assert enable_res.status_code == 200
    enabled = enable_res.json()
    gateway_token = enabled["token"]

    # Send A2A task with bearer token
    task_res = client.post(
        "/api/a2a/agents/phaseb-native/tasks",
        json={"message": {"role": "user", "parts": [{"kind": "text", "text": "hello"}]}},
        headers={"Authorization": f"Bearer {gateway_token}"},
    )

    # Phase B: should return 200 with task result, not 501
    assert task_res.status_code == 200, f"Expected 200, got {task_res.status_code}: {task_res.text}"
    task_body = task_res.json()
    assert "task_id" in task_body
    assert task_body["agent_name"] == "phaseb-native"
    assert task_body["source"] == "native"
    assert task_body["status"] in ("pending", "running", "success", "completed", "idle")
    # Result may be None if run is still pending, or contain messages if completed
    assert "result" in task_body
