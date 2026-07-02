"""Management API for user-owned external A2A agents."""

from __future__ import annotations

import inspect
import hashlib
import ipaddress
import json
import secrets
import socket
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field
from deerflow.config.paths import get_paths

router = APIRouter(prefix="/api/a2a/external-agents", tags=["a2a-external-agents"])


class UpstreamAuthRequest(BaseModel):
    type: Literal["none", "bearer"] = "none"
    token: str | None = None


class ExternalAgentCreateRequest(BaseModel):
    name: str = Field(min_length=1, pattern=r"^[a-zA-Z0-9_-]+$")
    display_name: str = Field(min_length=1)
    description: str = ""
    upstream_card_url: str = Field(min_length=1)
    upstream_auth: UpstreamAuthRequest = Field(default_factory=UpstreamAuthRequest)


class ExternalAgentUpdateRequest(BaseModel):
    display_name: str | None = None
    description: str | None = None


class ExternalAgentResponse(BaseModel):
    name: str
    source: Literal["external"] = "external"
    display_name: str
    description: str
    enabled: bool
    health_status: Literal["unknown", "healthy", "unhealthy"]
    card_url: str
    task_url: str
    upstream_card_fetched_at: str | None
    token_prefix: str | None = None
    token: str | None = None


class ExternalAgentsListResponse(BaseModel):
    external_agents: list[ExternalAgentResponse]


class _ExternalAgentRecord(BaseModel):
    owner_user_id: str
    name: str
    display_name: str
    description: str
    enabled: bool = False
    health_status: Literal["unknown", "healthy", "unhealthy"] = "unknown"
    upstream_card_url: str
    upstream_auth_type: str
    upstream_auth_token: str | None
    upstream_card: dict[str, Any]
    upstream_card_fetched_at: datetime | None
    token_prefix: str | None = None
    token_hash: str | None = None


class _NativePublicationRecord(BaseModel):
    owner_user_id: str
    name: str
    description: str
    enabled: bool = False
    token_prefix: str | None = None
    token_hash: str | None = None


_STORE: dict[tuple[str, str], _ExternalAgentRecord] = {}
_NATIVE_PUBLICATIONS: dict[tuple[str, str], _NativePublicationRecord] = {}
_STORE_LOADED = False


def _store_path() -> Path:
    return get_paths().base_dir / "a2a_registry.json"


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value)


def _record_to_json(record: _ExternalAgentRecord) -> dict[str, Any]:
    data = record.model_dump()
    fetched_at = data.get("upstream_card_fetched_at")
    if isinstance(fetched_at, datetime):
        data["upstream_card_fetched_at"] = fetched_at.isoformat()
    return data


def _load_store() -> None:
    global _STORE_LOADED
    if _STORE_LOADED:
        return

    _STORE.clear()
    _NATIVE_PUBLICATIONS.clear()
    path = _store_path()
    if path.exists():
        raw = json.loads(path.read_text(encoding="utf-8"))
        for item in raw.get("external_agents", []):
            item["upstream_card_fetched_at"] = _parse_datetime(item.get("upstream_card_fetched_at"))
            record = _ExternalAgentRecord(**item)
            _STORE[(record.owner_user_id, record.name)] = record
        for item in raw.get("native_publications", []):
            record = _NativePublicationRecord(**item)
            _NATIVE_PUBLICATIONS[(record.owner_user_id, record.name)] = record
    _STORE_LOADED = True


def _save_store() -> None:
    path = _store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "external_agents": [_record_to_json(record) for record in _STORE.values()],
        "native_publications": [record.model_dump() for record in _NATIVE_PUBLICATIONS.values()],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


async def fetch_and_validate_upstream_card(upstream_card_url: str, upstream_auth: UpstreamAuthRequest) -> dict[str, Any]:
    """Fetch and validate an upstream Agent Card with SSRF protections."""
    _validate_safe_upstream_url(upstream_card_url)

    headers: dict[str, str] = {}
    if upstream_auth.type == "bearer" and upstream_auth.token:
        headers["Authorization"] = f"Bearer {upstream_auth.token}"

    try:
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=False) as client:
            response = await client.get(upstream_card_url, headers=headers)
            response.raise_for_status()
            card = response.json()
    except httpx.TimeoutException as exc:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail={"code": "a2a_upstream_timeout", "message": "Timed out fetching upstream Agent Card."},
        ) from exc
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"code": "a2a_upstream_unavailable", "message": "Upstream Agent Card returned an error."},
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"code": "a2a_upstream_unavailable", "message": "Could not fetch upstream Agent Card."},
        ) from exc

    if not isinstance(card, dict) or not isinstance(card.get("name"), str):
        raise HTTPException(
            status_code=422,
            detail={"code": "a2a_upstream_invalid_card", "message": "Upstream Agent Card is invalid."},
        )

    return card


def _validate_safe_upstream_url(raw_url: str) -> None:
    parsed = urlparse(raw_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        _raise_forbidden_upstream_url()

    hostname = parsed.hostname.lower()
    if hostname in {"localhost", "localhost.localdomain"} or hostname.endswith(".localhost"):
        _raise_forbidden_upstream_url()

    try:
        ip = ipaddress.ip_address(hostname)
        if _is_forbidden_ip(ip):
            _raise_forbidden_upstream_url()
        return
    except ValueError:
        pass

    try:
        infos = socket.getaddrinfo(hostname, parsed.port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"code": "a2a_upstream_unavailable", "message": "Could not resolve upstream Agent Card host."},
        ) from exc

    for info in infos:
        resolved_ip = ipaddress.ip_address(info[4][0])
        if _is_forbidden_ip(resolved_ip):
            _raise_forbidden_upstream_url()


def _is_forbidden_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return any(
        (
            ip.is_private,
            ip.is_loopback,
            ip.is_link_local,
            ip.is_multicast,
            ip.is_reserved,
            ip.is_unspecified,
        )
    )


def _raise_forbidden_upstream_url() -> None:
    raise HTTPException(
        status_code=422,
        detail={
            "code": "a2a_upstream_url_forbidden",
            "message": "External A2A upstream URL is not allowed.",
        },
    )


def _current_user_id(request: Request) -> str:
    user = getattr(request.state, "user", None)
    user_id = getattr(user, "id", None)
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "not_authenticated", "message": "Authentication required."},
        )
    return str(user_id)


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


def _public_base_url(request: Request) -> str:
    return str(request.base_url).rstrip("/")


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _new_gateway_token() -> str:
    return f"a2a_{secrets.token_urlsafe(32)}"


def _to_response(record: _ExternalAgentRecord, request: Request, *, token: str | None = None) -> ExternalAgentResponse:
    public_base_url = _public_base_url(request)
    return ExternalAgentResponse(
        name=record.name,
        display_name=record.display_name,
        description=record.description,
        enabled=record.enabled,
        health_status=record.health_status,
        card_url=f"{public_base_url}/api/a2a/agents/{record.name}/card",
        task_url=f"{public_base_url}/api/a2a/agents/{record.name}/tasks",
        upstream_card_fetched_at=record.upstream_card_fetched_at.isoformat() if record.upstream_card_fetched_at else None,
        token_prefix=record.token_prefix,
        token=token,
    )


def _get_owned_record(request: Request, name: str) -> _ExternalAgentRecord:
    _load_store()
    user_id = _current_user_id(request)
    record = _STORE.get((user_id, name))
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "a2a_external_agent_not_found", "message": f"External A2A agent '{name}' was not found."},
        )
    return record


def find_external_agent_by_name(name: str) -> _ExternalAgentRecord | None:
    """Return the first external agent matching a public name.

    The persistent registry slice will replace this in-memory lookup with a
    repository query and namespace-aware resolution.
    """
    _load_store()
    for (_, record_name), record in _STORE.items():
        if record_name == name:
            return record
    return None


def validate_external_agent_gateway_token(record: _ExternalAgentRecord, token: str) -> bool:
    return bool(record.token_hash and secrets.compare_digest(record.token_hash, _hash_token(token)))


def iter_enabled_external_agents() -> list[_ExternalAgentRecord]:
    _load_store()
    return sorted((record for record in _STORE.values() if record.enabled), key=lambda record: record.name)


def clear_external_agent_store_for_tests(*, clear_disk: bool = True) -> None:
    global _STORE_LOADED
    _STORE.clear()
    _NATIVE_PUBLICATIONS.clear()
    _STORE_LOADED = False
    if clear_disk:
        path = _store_path()
        if path.exists():
            path.unlink()


def enable_native_publication(owner_user_id: str, name: str, description: str) -> tuple[_NativePublicationRecord, str]:
    _load_store()
    token = _new_gateway_token()
    record = _NativePublicationRecord(
        owner_user_id=owner_user_id,
        name=name,
        description=description,
        enabled=True,
        token_prefix=token[:12],
        token_hash=_hash_token(token),
    )
    _NATIVE_PUBLICATIONS[(owner_user_id, name)] = record
    _save_store()
    return record, token


def disable_native_publication(owner_user_id: str, name: str) -> _NativePublicationRecord:
    _load_store()
    record = _NATIVE_PUBLICATIONS.get((owner_user_id, name))
    if record is None:
        record = _NativePublicationRecord(owner_user_id=owner_user_id, name=name, description="", enabled=False)
        _NATIVE_PUBLICATIONS[(owner_user_id, name)] = record
    record.enabled = False
    record.token_hash = None
    record.token_prefix = None
    _save_store()
    return record


def rotate_native_publication(owner_user_id: str, name: str, description: str) -> tuple[_NativePublicationRecord, str]:
    return enable_native_publication(owner_user_id, name, description)


def find_native_publication_by_name(name: str) -> _NativePublicationRecord | None:
    _load_store()
    for (_, record_name), record in _NATIVE_PUBLICATIONS.items():
        if record_name == name:
            return record
    return None


def get_native_publication(owner_user_id: str, name: str) -> _NativePublicationRecord | None:
    _load_store()
    return _NATIVE_PUBLICATIONS.get((owner_user_id, name))


def iter_enabled_native_publications() -> list[_NativePublicationRecord]:
    _load_store()
    return sorted((record for record in _NATIVE_PUBLICATIONS.values() if record.enabled), key=lambda record: record.name)


def validate_native_gateway_token(record: _NativePublicationRecord, token: str) -> bool:
    return bool(record.token_hash and secrets.compare_digest(record.token_hash, _hash_token(token)))


@router.get("", response_model=ExternalAgentsListResponse)
async def list_external_agents(request: Request) -> ExternalAgentsListResponse:
    _load_store()
    user_id = _current_user_id(request)
    records = [record for (owner_id, _), record in _STORE.items() if owner_id == user_id]
    records.sort(key=lambda record: record.name)
    return ExternalAgentsListResponse(external_agents=[_to_response(record, request) for record in records])


@router.post("", status_code=status.HTTP_201_CREATED, response_model=ExternalAgentResponse)
async def create_external_agent(request: Request, body: ExternalAgentCreateRequest) -> ExternalAgentResponse:
    _load_store()
    user_id = _current_user_id(request)
    key = (user_id, body.name)
    if key in _STORE:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "a2a_external_agent_conflict", "message": f"External A2A agent '{body.name}' already exists."},
        )

    upstream_card = await _maybe_await(fetch_and_validate_upstream_card(body.upstream_card_url, body.upstream_auth))
    record = _ExternalAgentRecord(
        owner_user_id=user_id,
        name=body.name,
        display_name=body.display_name,
        description=body.description,
        upstream_card_url=body.upstream_card_url,
        upstream_auth_type=body.upstream_auth.type,
        upstream_auth_token=body.upstream_auth.token,
        upstream_card=upstream_card,
        upstream_card_fetched_at=datetime.now(UTC),
        health_status="healthy",
    )
    _STORE[key] = record
    _save_store()
    return _to_response(record, request)


@router.get("/{name}", response_model=ExternalAgentResponse)
async def get_external_agent(request: Request, name: str) -> ExternalAgentResponse:
    return _to_response(_get_owned_record(request, name), request)


@router.put("/{name}", response_model=ExternalAgentResponse)
async def update_external_agent(request: Request, name: str, body: ExternalAgentUpdateRequest) -> ExternalAgentResponse:
    record = _get_owned_record(request, name)
    if body.display_name is not None:
        record.display_name = body.display_name
    if body.description is not None:
        record.description = body.description
    _save_store()
    return _to_response(record, request)


@router.post("/{name}/a2a/enable", response_model=ExternalAgentResponse)
async def enable_external_agent(request: Request, name: str) -> ExternalAgentResponse:
    record = _get_owned_record(request, name)
    token = _new_gateway_token()
    record.token_hash = _hash_token(token)
    record.token_prefix = token[:12]
    record.enabled = True
    _save_store()
    return _to_response(record, request, token=token)


@router.post("/{name}/a2a/disable", response_model=ExternalAgentResponse)
async def disable_external_agent(request: Request, name: str) -> ExternalAgentResponse:
    record = _get_owned_record(request, name)
    record.enabled = False
    record.token_hash = None
    record.token_prefix = None
    _save_store()
    return _to_response(record, request)


@router.post("/{name}/a2a/rotate", response_model=ExternalAgentResponse)
async def rotate_external_agent_token(request: Request, name: str) -> ExternalAgentResponse:
    record = _get_owned_record(request, name)
    token = _new_gateway_token()
    record.token_hash = _hash_token(token)
    record.token_prefix = token[:12]
    record.enabled = True
    _save_store()
    return _to_response(record, request, token=token)


@router.delete("/{name}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_external_agent(request: Request, name: str) -> None:
    _load_store()
    user_id = _current_user_id(request)
    key = (user_id, name)
    if key not in _STORE:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "a2a_external_agent_not_found", "message": f"External A2A agent '{name}' was not found."},
        )
    del _STORE[key]
    _save_store()
