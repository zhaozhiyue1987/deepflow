"""Public A2A protocol endpoints."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from fastapi import APIRouter, HTTPException, Request, status

import inspect
from uuid import uuid4

import httpx
from app.gateway.deps import get_checkpointer, get_run_manager, get_stream_bridge, get_thread_store
from app.gateway.routers.a2a_external_agents import (
    find_external_agent_by_name,
    find_native_publication_by_name,
    iter_enabled_external_agents,
    iter_enabled_native_publications,
    validate_external_agent_gateway_token,
    validate_native_gateway_token,
    _validate_safe_upstream_url,
)
from app.gateway.services import start_run, wait_for_run_completion
from deerflow.config.agents_config import load_agent_config
from deerflow.runtime import serialize_channel_values_for_api

router = APIRouter(prefix="/api/a2a", tags=["a2a"])


def _public_base_url(request: Request) -> str:
    return str(request.base_url).rstrip("/")


def _external_card(record: Any, request: Request) -> dict[str, Any]:
    upstream_card = record.upstream_card or {}
    public_base_url = _public_base_url(request)
    card_url = f"{public_base_url}/api/a2a/agents/{record.name}/card"
    task_url = f"{public_base_url}/api/a2a/agents/{record.name}/tasks"

    return {
        "name": record.name,
        "source": "external",
        "description": record.description,
        "url": task_url,
        "card_url": card_url,
        "capabilities": upstream_card.get("capabilities", {}),
        "defaultInputModes": upstream_card.get("defaultInputModes", ["text/plain"]),
        "defaultOutputModes": upstream_card.get("defaultOutputModes", ["text/plain"]),
    }


def _native_card(record: Any, request: Request) -> dict[str, Any]:
    public_base_url = _public_base_url(request)
    task_url = f"{public_base_url}/api/a2a/agents/{record.name}/tasks"
    return {
        "name": record.name,
        "source": "native",
        "description": record.description,
        "version": "1.0",
        "url": task_url,
        "card_url": f"{public_base_url}/api/a2a/agents/{record.name}/card",
        "capabilities": {"streaming": False, "cancel": False, "files": False},
        "authentication": {"schemes": ["bearer"]},
        "defaultInputModes": ["text/plain"],
        "defaultOutputModes": ["text/plain"],
    }


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


def _bearer_token(request: Request) -> str:
    authorization = request.headers.get("authorization")
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "a2a_token_missing", "message": "A2A bearer token is required."},
        )
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "a2a_token_invalid", "message": "A2A bearer token is invalid."},
        )
    return token


async def forward_external_task_to_upstream(record: Any, payload: dict[str, Any]) -> dict[str, Any]:
    upstream_task_url = (record.upstream_card or {}).get("url")
    if not isinstance(upstream_task_url, str) or not upstream_task_url:
        raise HTTPException(
            status_code=422,
            detail={"code": "a2a_upstream_invalid_card", "message": "Upstream Agent Card does not define a task URL."},
        )
    _validate_safe_upstream_url(upstream_task_url)

    headers: dict[str, str] = {}
    if getattr(record, "upstream_auth_type", None) == "bearer" and getattr(record, "upstream_auth_token", None):
        headers["Authorization"] = f"Bearer {record.upstream_auth_token}"

    try:
        async with httpx.AsyncClient(timeout=60.0, follow_redirects=False) as client:
            response = await client.post(upstream_task_url, json=payload, headers=headers)
            response.raise_for_status()
            body = response.json()
    except httpx.TimeoutException as exc:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail={"code": "a2a_upstream_timeout", "message": "Timed out forwarding external A2A task."},
        ) from exc
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"code": "a2a_upstream_unavailable", "message": "Upstream A2A task endpoint returned an error."},
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"code": "a2a_upstream_unavailable", "message": "Could not forward external A2A task."},
        ) from exc

    if not isinstance(body, dict):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"code": "a2a_upstream_invalid_response", "message": "Upstream A2A task response is invalid."},
        )

    return {
        "upstream_task_id": body.get("id") or body.get("task_id"),
        "status": body.get("status", "submitted"),
        "result": body.get("result"),
    }


async def _execute_native_task(request: Request, native_agent: Any, payload: dict[str, Any]) -> dict[str, Any]:
    """Map an A2A task to a DeerFlow thread/run and block until completion."""
    import logging

    logger = logging.getLogger(__name__)

    # Extract A2A message text
    a2a_message = payload.get("message", {})
    parts = a2a_message.get("parts", [])
    text_parts = [p.get("text", "") for p in parts if isinstance(p, dict) and p.get("kind") == "text"]
    user_text = "\n".join(text_parts) or ""

    thread_id = str(uuid4())
    agent_name = native_agent.name
    owner_user_id = getattr(native_agent, "owner_user_id", None)

    # Build run body matching RunCreateRequest shape used by start_run
    from types import SimpleNamespace

    run_body = SimpleNamespace(
        assistant_id=agent_name,
        input={"messages": [{"role": "user", "content": user_text}]},
        metadata={"source": "a2a", "agent_name": agent_name},
        config=None,
        context=None,
        command=None,
        stream_mode=None,
        stream_subgraphs=False,
        interrupt_before=None,
        interrupt_after=None,
        on_disconnect="cancel",
        on_completion="keep",
        multitask_strategy="reject",
        after_seconds=None,
        if_not_exists="create",
        feedback_keys=None,
        webhook=None,
        checkpoint_id=None,
        checkpoint=None,
    )

    # Temporarily stamp synthetic internal user so start_run can resolve
    # owner_user_id via get_trusted_internal_owner_user_id.
    old_user = getattr(request.state, "user", None)
    request.state.user = SimpleNamespace(id=owner_user_id, system_role="internal")

    try:
        record = await start_run(run_body, thread_id, request)
    finally:
        request.state.user = old_user

    # Wait for run completion
    completed = False
    if record.task is not None:
        try:
            run_mgr = get_run_manager(request)
            bridge = get_stream_bridge(request)
            completed = await wait_for_run_completion(bridge, record, request, run_mgr)
        except HTTPException as exc:
            if exc.status_code == 503 and "not available" in (exc.detail or ""):
                # Fallback: await the task directly when infrastructure is not configured
                try:
                    await record.task
                    completed = True
                except Exception:
                    pass
            else:
                raise

    # Extract result from checkpoint
    result_text: str | None = None
    if completed:
        try:
            checkpointer = get_checkpointer(request)
            config = {"configurable": {"thread_id": thread_id}}
            checkpoint_tuple = await checkpointer.aget_tuple(config)
            if checkpoint_tuple is not None:
                checkpoint = getattr(checkpoint_tuple, "checkpoint", {}) or {}
                channel_values = checkpoint.get("channel_values", {})
                serialized = serialize_channel_values_for_api(channel_values)
                messages = serialized.get("messages", [])
                # Find the last assistant message
                for msg in reversed(messages):
                    if isinstance(msg, dict) and msg.get("type") == "ai":
                        result_text = msg.get("content")
                        break
                    if hasattr(msg, "type") and getattr(msg, "type", None) == "ai":
                        result_text = getattr(msg, "content", None)
                        break
        except Exception:
            logger.exception("Failed to fetch final state for native A2A task %s", thread_id)

    return {
        "task_id": f"a2a-task-{thread_id}",
        "agent_name": agent_name,
        "source": "native",
        "status": record.status.value,
        "result": result_text,
    }


@router.get("/agents/{agent_name}/card")
async def get_agent_card(request: Request, agent_name: str) -> dict[str, Any]:
    external_agent = find_external_agent_by_name(agent_name)
    if external_agent is not None:
        if not external_agent.enabled:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"code": "a2a_agent_not_published", "message": f"A2A agent '{agent_name}' is not published."},
            )
        return _external_card(external_agent, request)

    native_agent = find_native_publication_by_name(agent_name)
    if native_agent is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "a2a_agent_not_found", "message": f"A2A agent '{agent_name}' was not found."},
        )
    if not native_agent.enabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "a2a_agent_not_published", "message": f"A2A agent '{agent_name}' is not published."},
        )
    return _native_card(native_agent, request)


@router.post("/agents/{agent_name}/tasks")
async def create_agent_task(request: Request, agent_name: str, payload: dict[str, Any]) -> dict[str, Any]:
    external_agent = find_external_agent_by_name(agent_name)
    if external_agent is not None:
        if not external_agent.enabled:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"code": "a2a_agent_not_published", "message": f"A2A agent '{agent_name}' is not published."},
            )

        token = _bearer_token(request)
        if not validate_external_agent_gateway_token(external_agent, token):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"code": "a2a_token_invalid", "message": "A2A bearer token is invalid."},
            )

        upstream = await _maybe_await(forward_external_task_to_upstream(external_agent, payload))
        return {
            "task_id": f"gw-task-{uuid4()}",
            "agent_name": external_agent.name,
            "source": "external",
            "upstream_task_id": upstream.get("upstream_task_id"),
            "status": upstream.get("status", "submitted"),
            "result": upstream.get("result"),
        }

    native_agent = find_native_publication_by_name(agent_name)
    if native_agent is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "a2a_agent_not_found", "message": f"A2A agent '{agent_name}' was not found."},
        )
    if not native_agent.enabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "a2a_agent_not_published", "message": f"A2A agent '{agent_name}' is not published."},
        )

    token = _bearer_token(request)
    if not validate_native_gateway_token(native_agent, token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "a2a_token_invalid", "message": "A2A bearer token is invalid."},
        )

    return await _execute_native_task(request, native_agent, payload)


@router.get("/registry")
async def get_registry(request: Request) -> dict[str, Any]:
    public_base_url = _public_base_url(request)
    agents: list[dict[str, Any]] = []

    for record in iter_enabled_external_agents():
        upstream_card = record.upstream_card or {}
        agents.append(
            {
                "name": record.name,
                "source": "external",
                "description": record.description,
                "card_url": f"{public_base_url}/api/a2a/agents/{record.name}/card",
                "task_url": f"{public_base_url}/api/a2a/agents/{record.name}/tasks",
                "capabilities": upstream_card.get("capabilities", {}),
            }
        )

    for record in iter_enabled_native_publications():
        try:
            agent_cfg = load_agent_config(record.name, user_id=record.owner_user_id)
        except Exception:
            agent_cfg = None
        description = getattr(agent_cfg, "description", record.description) if agent_cfg is not None else record.description
        agents.append(
            {
                "name": record.name,
                "source": "native",
                "description": description,
                "card_url": f"{public_base_url}/api/a2a/agents/{record.name}/card",
                "task_url": f"{public_base_url}/api/a2a/agents/{record.name}/tasks",
                "capabilities": {"streaming": False, "cancel": False, "files": False},
            }
        )

    agents.sort(key=lambda agent: (agent["source"], agent["name"]))
    return {"agents": agents}
