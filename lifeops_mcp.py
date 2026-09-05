from __future__ import annotations

import asyncio
import base64
import fcntl
import hashlib
import json
import os
import re
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any, Literal
from urllib.parse import parse_qs, urlencode, urlsplit
from uuid import uuid4

import httpx
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from lifeops.deepseek import classify_items
from lifeops.read_receipt_store import ReadReceiptStore
from lifeops.triage import apply_model_labels, build_triage, build_unified_triage
from lifeops.work_item_store import WorkItemStore

INBOX_BASE_URL = os.environ.get("INBOX_SERVER_URL", "http://127.0.0.1:9849").rstrip("/")
INBOX_TOKEN = os.environ.get("INBOX_SERVER_TOKEN", "").strip()
MCP_PORT = int(os.environ.get("LIFEOPS_MCP_PORT", "9850"))
# LifeOps/Master Ops workbooks are canonical personal-operations sources, not
# one mailbox's provider data. Keep their Google account explicit so selecting
# a Gmail account does not accidentally make the shared personal graph vanish.
# Deployments with a different canonical account must set this override.
LIFEOPS_CANONICAL_GOOGLE_ACCOUNT = os.environ.get(
    "LIFEOPS_CANONICAL_GOOGLE_ACCOUNT", "jshah1331@gmail.com"
).strip()
_TRIAGE_READ_TIMEOUT_SECONDS = 8.0
_TRIAGE_TOTAL_TIMEOUT_SECONDS = 45.0
_LIFE_CONTEXT_READ_TIMEOUT_SECONDS = 8.0
_LIFE_CONTEXT_TOTAL_TIMEOUT_SECONDS = 120.0

_LIFE_CONTEXT_GATE_STATE: tuple[Any, asyncio.Semaphore, asyncio.Lock] | None = None
_LIFEOPS_READ_LOCK_FILE = os.environ.get(
    "LIFEOPS_READ_LOCK_FILE", f"/tmp/lifeops-inbox-read-{os.getuid()}.lock"
).strip()
_READ_RECEIPT_STORE: ReadReceiptStore | None = None
_WORK_ITEM_STORE: WorkItemStore | None = None


def _read_receipt_store() -> ReadReceiptStore:
    global _READ_RECEIPT_STORE
    if _READ_RECEIPT_STORE is None:
        _READ_RECEIPT_STORE = ReadReceiptStore()
    return _READ_RECEIPT_STORE


def _work_item_store() -> WorkItemStore:
    global _WORK_ITEM_STORE
    if _WORK_ITEM_STORE is None:
        _WORK_ITEM_STORE = WorkItemStore()
    return _WORK_ITEM_STORE


def _life_context_gates() -> tuple[asyncio.Semaphore, asyncio.Lock]:
    """Share bounded provider gates across concurrent MCP client requests."""
    global _LIFE_CONTEXT_GATE_STATE
    loop = asyncio.get_running_loop()
    if _LIFE_CONTEXT_GATE_STATE is None or _LIFE_CONTEXT_GATE_STATE[0] is not loop:
        _LIFE_CONTEXT_GATE_STATE = (loop, asyncio.Semaphore(2), asyncio.Lock())
    return _LIFE_CONTEXT_GATE_STATE[1], _LIFE_CONTEXT_GATE_STATE[2]


@asynccontextmanager
async def _lifeops_read_process_lock():
    """Coordinate Inbox reads across separate LifeOps MCP processes."""
    if not _LIFEOPS_READ_LOCK_FILE:
        yield
        return
    file_descriptor = await asyncio.to_thread(
        os.open,
        _LIFEOPS_READ_LOCK_FILE,
        os.O_CREAT | os.O_RDWR,
        0o600,
    )
    try:
        await asyncio.to_thread(os.fchmod, file_descriptor, 0o600)
        await asyncio.to_thread(fcntl.flock, file_descriptor, fcntl.LOCK_EX)
        yield
    finally:
        await asyncio.to_thread(fcntl.flock, file_descriptor, fcntl.LOCK_UN)
        os.close(file_descriptor)

mcp = FastMCP(
    "LifeOps",
    instructions=(
        "LifeOps exposes evidence-backed personal context and bounded actions through the local Inbox server. "
        "Prefer reads before writes. Never infer a write succeeded: execute it, then verify the resulting state. "
        "Approval tools may only be used after the user explicitly confirms the exact pending action."
    ),
    host="127.0.0.1",
    port=MCP_PORT,
    streamable_http_path="/mcp",
    stateless_http=True,
    json_response=True,
)


_WORK_ITEM_WORKERS = frozenset(
    {
        "bridge",
        "orca",
        "claude",
        "codex",
        "cursor",
        "agy",
        "pi",
        "deepseek",
        "btw",
        "hyperagent",
        "local",
    }
)
_WORK_ITEM_SECRET_KEYS = frozenset(
    {
        "api_key",
        "apikey",
        "access_token",
        "credential",
        "password",
        "private_key",
        "secret",
        "token",
    }
)
_WORK_ITEM_EXECUTION_KEYS = frozenset(
    {"argv", "command", "cwd", "env", "executable", "shell", "terminal"}
)


def _reject_unsafe_work_item_metadata(value: Any, path: str = "metadata") -> None:
    """Reject credential and execution material before it reaches SQLite."""
    if isinstance(value, dict):
        for key, nested in value.items():
            clean_key = str(key).strip().casefold()
            if clean_key in _WORK_ITEM_SECRET_KEYS:
                raise ValueError(f"work-item metadata cannot contain credential field: {path}.{key}")
            if clean_key in _WORK_ITEM_EXECUTION_KEYS:
                raise ValueError(f"work-item metadata cannot contain execution field: {path}.{key}")
            _reject_unsafe_work_item_metadata(nested, f"{path}.{key}")
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            _reject_unsafe_work_item_metadata(nested, f"{path}[{index}]")
    elif isinstance(value, str) and "-----BEGIN" in value:
        raise ValueError("work-item metadata cannot contain private-key material")


def _validate_work_item_request(
    *,
    idempotency_key: str,
    objective: str,
    scope: dict[str, Any],
    evidence_refs: list[dict[str, Any]],
    worker: str,
    model: str,
    budget: dict[str, Any],
    acceptance_criteria: list[str],
) -> dict[str, Any]:
    clean_key = str(idempotency_key or "").strip()
    if not clean_key or len(clean_key) > 120 or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]*", clean_key):
        raise ValueError("idempotency_key must be 1-120 characters: letters, numbers, . _ : -")
    clean_objective = str(objective or "").strip()
    if not clean_objective or len(clean_objective) > 240:
        raise ValueError("objective is required and must be at most 240 characters")
    clean_worker = str(worker or "").strip().casefold()
    if clean_worker not in _WORK_ITEM_WORKERS:
        raise ValueError("worker must be one of the governed worker names")
    clean_model = str(model or "").strip()
    if len(clean_model) > 120:
        raise ValueError("model must be at most 120 characters")
    if not isinstance(scope, dict) or not scope:
        raise ValueError("scope must be a non-empty metadata object")
    if not isinstance(evidence_refs, list) or len(evidence_refs) > 100:
        raise ValueError("evidence_refs must be a list of at most 100 metadata references")
    for index, reference in enumerate(evidence_refs):
        if not isinstance(reference, dict) or not str(reference.get("source") or "").strip() or not str(reference.get("ref") or "").strip():
            raise ValueError(f"evidence_refs[{index}] requires source and ref")
    if not isinstance(acceptance_criteria, list) or not 1 <= len(acceptance_criteria) <= 20:
        raise ValueError("acceptance_criteria must contain 1-20 checks")
    clean_acceptance = [str(item or "").strip() for item in acceptance_criteria]
    if any(not item or len(item) > 240 for item in clean_acceptance):
        raise ValueError("each acceptance criterion is required and must be at most 240 characters")
    if not isinstance(budget, dict) or not budget:
        raise ValueError("budget must be a non-empty metadata object")
    max_seconds = budget.get("max_seconds")
    if isinstance(max_seconds, bool) or not isinstance(max_seconds, int) or not 1 <= max_seconds <= 3600:
        raise ValueError("budget.max_seconds must be an integer from 1 through 3600")
    if "max_cost_usd" in budget:
        max_cost = budget["max_cost_usd"]
        if isinstance(max_cost, bool) or not isinstance(max_cost, (int, float)) or not 0 <= max_cost <= 1000:
            raise ValueError("budget.max_cost_usd must be a number from 0 through 1000")

    payload = {
        "idempotency_key": clean_key,
        "objective": clean_objective,
        "scope": scope,
        "evidence_refs": evidence_refs,
        "worker": clean_worker,
        "model": clean_model or None,
        "budget": budget,
        "acceptance_criteria": clean_acceptance,
    }
    _reject_unsafe_work_item_metadata(payload)
    return payload


@mcp.tool(
    title="Record governed LifeOps work-item proposal",
    annotations=ToolAnnotations(
        read_only_hint=False,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=False,
    ),
)
async def create_work_item(
    idempotency_key: str,
    objective: str,
    scope: dict[str, Any],
    evidence_refs: list[dict[str, Any]],
    worker: Literal[
        "bridge",
        "orca",
        "claude",
        "codex",
        "cursor",
        "agy",
        "pi",
        "deepseek",
        "btw",
        "hyperagent",
        "local",
    ],
    model: str = "",
    budget: dict[str, Any] | None = None,
    acceptance_criteria: list[str] | None = None,
) -> dict[str, Any]:
    """Durably record a bounded proposal without dispatching a worker.

    This is the first half of the LifeOps-to-Bridge seam.  It creates no
    provider-side effect, injects no secret, and launches no process.  A
    future adapter must independently admit this exact proposal before any
    worker is started.
    """
    proposal = _validate_work_item_request(
        idempotency_key=idempotency_key,
        objective=objective,
        scope=scope,
        evidence_refs=evidence_refs,
        worker=worker,
        model=model,
        budget=budget or {},
        acceptance_criteria=acceptance_criteria or [],
    )
    return await asyncio.to_thread(_work_item_store().create, proposal)


@mcp.tool(
    title="Get governed LifeOps work item",
    annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False),
)
async def get_work_item(work_item_id: str) -> dict[str, Any]:
    """Return a durable proposal and its append-only metadata events."""
    result = await asyncio.to_thread(_work_item_store().get, work_item_id)
    if result is None:
        raise ValueError("work item not found")
    return result


@mcp.tool(
    title="List recent governed LifeOps work items",
    annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False),
)
async def list_work_items(limit: int = 50) -> dict[str, Any]:
    """Return recent metadata-only proposals, newest first."""
    return {
        "schema_version": "lifeops.work_item_list.v1",
        "items": await asyncio.to_thread(_work_item_store().list_recent, limit),
        "dispatch_authority": "not_admitted",
        "note": "Listing work items does not dispatch workers or grant credentials.",
    }


def _headers(extra: dict[str, str] | None = None) -> dict[str, str]:
    if not INBOX_TOKEN:
        raise RuntimeError("INBOX_SERVER_TOKEN is required")
    headers = {"Authorization": f"Bearer {INBOX_TOKEN}"}
    if extra:
        headers.update(extra)
    return headers


async def _request(
    method: str,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    body: dict[str, Any] | None = None,
    extra_headers: dict[str, str] | None = None,
) -> Any:
    async with httpx.AsyncClient(base_url=INBOX_BASE_URL, timeout=45.0) as client:
        response = await client.request(
            method,
            path,
            params=params,
            json=body,
            headers=_headers(extra_headers),
        )
        response.raise_for_status()
        if not response.content:
            return None
        return response.json()


def _encode_search_id(query: str, sources: list[str]) -> str:
    encoded = json.dumps(
        {"query": query, "sources": sources},
        ensure_ascii=False,
        sort_keys=True,
    ).encode("utf-8")
    token = base64.urlsafe_b64encode(encoded).decode("ascii").rstrip("=")
    return f"search:{token}"


def _decode_search_id(item_id: str) -> dict[str, Any]:
    if not item_id.startswith("search:"):
        raise ValueError("Unsupported item id")
    token = item_id.removeprefix("search:")
    token += "=" * (-len(token) % 4)
    decoded = base64.urlsafe_b64decode(token.encode("ascii")).decode("utf-8")
    try:
        payload = json.loads(decoded)
    except json.JSONDecodeError:
        # Preserve compatibility with the original v0 query-only ids.
        return {"query": decoded, "sources": ["all"]}
    if not isinstance(payload, dict) or not isinstance(payload.get("query"), str):
        raise ValueError("Malformed search item id")
    sources = payload.get("sources")
    if not isinstance(sources, list) or not all(isinstance(source, str) for source in sources):
        raise ValueError("Malformed search sources")
    return {"query": payload["query"], "sources": sources}


def _approval_path(path: str, params: dict[str, str] | None = None) -> str:
    clean = path
    if params:
        nonempty = {k: v for k, v in params.items() if v != ""}
        if nonempty:
            clean = f"{path}?{urlencode(nonempty)}"
    return clean


async def _request_approval(method: str, path: str, body: dict[str, Any]) -> dict[str, Any]:
    return await _request(
        "POST",
        "/approvals/request",
        body={"method": method, "path": path, "body": body},
    )


def _same_temporal_value(expected: str, observed: str) -> bool:
    """Compare provider ISO values without treating timezone formatting as drift."""
    if not expected or not observed:
        return expected == observed
    if expected == observed:
        return True
    try:
        expected_dt = datetime.fromisoformat(expected.replace("Z", "+00:00"))
        observed_dt = datetime.fromisoformat(observed.replace("Z", "+00:00"))
    except ValueError:
        return False
    if expected_dt.tzinfo is None or observed_dt.tzinfo is None:
        return expected_dt == observed_dt
    return expected_dt.astimezone(UTC) == observed_dt.astimezone(UTC)


def _verification_result(
    *,
    status: str,
    action: str,
    read_path: str = "",
    evidence: Any = None,
    mismatches: list[str] | None = None,
    detail: str = "",
) -> dict[str, Any]:
    return {
        "status": status,
        "action": action,
        "read_only": True,
        "read_path": read_path,
        "evidence": evidence,
        "mismatches": mismatches or [],
        "detail": detail,
        "verified_at": datetime.now(UTC).isoformat(),
    }


async def _verify_approved_action(row: dict[str, Any], result: Any = None) -> dict[str, Any]:
    """Read the provider/local projection and verify the exact approved payload.

    This deliberately reports ambiguity instead of claiming success when a
    create action could match an older item.  A successful mutation response
    alone is never treated as proof of durable state.
    """
    method = str(row.get("method", "")).upper()
    path = str(row.get("path", ""))
    path_only = path.split("?", 1)[0]
    body = json.loads(row.get("body_json") or "{}")

    if method == "POST" and path_only == "/tasks":
        if result is not None and (not isinstance(result, dict) or result.get("ok") is not True):
            return _verification_result(
                status="not_verified",
                action="google_task_create",
                detail="The write response did not report ok=true.",
            )
        query = parse_qs(urlsplit(path).query)
        list_id = str(body.get("list_id") or "@default")
        account = str((query.get("account") or [""])[-1])
        observed = await _request(
            "GET",
            "/tasks",
            params={
                "list_id": list_id,
                "show_completed": True,
                "limit": 200,
                "account": account,
            },
        )
        matches = []
        for task in observed if isinstance(observed, list) else []:
            if not isinstance(task, dict):
                continue
            if task.get("title") != body.get("title"):
                continue
            if task.get("notes", "") != body.get("notes", ""):
                continue
            expected_due = str(body.get("due") or "")
            observed_due = str(task.get("due") or "")
            if expected_due and not _same_temporal_value(expected_due, observed_due):
                continue
            if not expected_due and observed_due:
                continue
            matches.append(task)
        status = "verified" if len(matches) == 1 else "ambiguous" if matches else "not_verified"
        return _verification_result(
            status=status,
            action="google_task_create",
            read_path="/tasks",
            evidence={"match_count": len(matches), "matches": matches[:5]},
            detail=(
                "Exactly one task matched the approved title, notes, and due time."
                if status == "verified"
                else "No unique exact task match was found after the write."
            ),
        )

    person_match = re.fullmatch(r"/people/([^/]+)/(notes|relationships)", path_only)
    if method == "POST" and person_match:
        person_id, kind = person_match.groups()
        profile_path = f"/people/{person_id}/profile"
        profile = await _request("GET", profile_path, params={"include_activity": False})
        payload_key = "note" if kind == "notes" else "relationship"
        item_key = "notes" if kind == "notes" else "relationships"
        created = result.get(payload_key) if isinstance(result, dict) else None
        created_id = created.get("note_id" if kind == "notes" else "relationship_id") if isinstance(created, dict) else None
        items = profile.get(item_key, []) if isinstance(profile, dict) else []
        exact = [item for item in items if isinstance(item, dict) and item.get("body" if kind == "notes" else "label") == body.get("body" if kind == "notes" else "label")]
        if created_id:
            exact = [item for item in exact if item.get("note_id" if kind == "notes" else "relationship_id") == created_id]
        status = "verified" if len(exact) == 1 else "ambiguous" if len(exact) > 1 else "not_verified"
        return _verification_result(
            status=status,
            action=f"person_{kind[:-1]}_create",
            read_path=profile_path,
            evidence={"match_count": len(exact), "matches": exact[:5]},
            detail=(
                "The exact local person record is present in the profile read-back."
                if status == "verified"
                else "The local person record was not uniquely confirmed."
            ),
        )

    if method == "POST" and path_only == "/identity/links":
        if result is not None and (not isinstance(result, dict) or result.get("ok") is not True):
            return _verification_result(
                status="not_verified",
                action="identity_link_create",
                detail="The write response did not report ok=true.",
            )
        links = await _request(
            "GET",
            "/identity/links",
            params={
                "canonical_person_id": str(body.get("canonical_person_id") or ""),
                "target_source": str(body.get("target_source") or "contacts"),
                "target_id": str(body.get("target_id") or ""),
                "limit": 100,
            },
        )
        observed = links.get("links", []) if isinstance(links, dict) else []
        created = result.get("link") if isinstance(result, dict) else None
        created_id = created.get("link_id") if isinstance(created, dict) else None
        exact = [
            link
            for link in observed
            if isinstance(link, dict)
            and str(link.get("canonical_person_id") or "")
            == str(body.get("canonical_person_id") or "")
            and str(link.get("target_source") or "contacts")
            == str(body.get("target_source") or "contacts")
            and str(link.get("target_id") or "") == str(body.get("target_id") or "")
        ]
        if created_id:
            exact = [link for link in exact if link.get("link_id") == created_id]
        status = "verified" if len(exact) == 1 else "ambiguous" if len(exact) > 1 else "not_verified"
        return _verification_result(
            status=status,
            action="identity_link_create",
            read_path="/identity/links",
            evidence={"match_count": len(exact), "matches": exact[:5]},
            detail=(
                "The approved identity link is present in the local read-back."
                if status == "verified"
                else "The identity link was not uniquely confirmed."
            ),
        )

    event_match = re.fullmatch(r"/calendar/events/([^/]+)", path_only)
    if method == "PUT" and event_match:
        event_id = event_match.group(1)
        query = parse_qs(urlsplit(path).query)
        params = {
            "calendar_id": str((query.get("calendar_id") or ["primary"])[-1]),
            "account": str((query.get("account") or [""])[-1]),
        }
        read_path = f"/calendar/events/{event_id}"
        observed = await _request("GET", read_path, params=params)
        mismatches: list[str] = []
        if result is not None and (not isinstance(result, dict) or result.get("ok") is not True):
            mismatches.append("write_response_not_ok")
        if not isinstance(observed, dict):
            mismatches.append("event_readback_missing")
        else:
            for field in ("summary", "location", "description"):
                if field in body and observed.get(field, "") != body[field]:
                    mismatches.append(field)
            for field in ("start", "end"):
                if field in body and not _same_temporal_value(str(body[field]), str(observed.get(field) or "")):
                    mismatches.append(field)
        status = "verified" if not mismatches else "not_verified"
        return _verification_result(
            status=status,
            action="calendar_event_update",
            read_path=read_path,
            evidence=observed,
            mismatches=mismatches,
            detail=(
                "The event read-back matches every approved field."
                if status == "verified"
                else "The event read-back did not match every approved field."
            ),
        )

    return _verification_result(
        status="unsupported",
        action="unknown",
        detail="No bounded read-back contract exists for this approved action.",
    )


def _allowed_execution(row: dict[str, Any]) -> bool:
    method = str(row.get("method", "")).upper()
    path = str(row.get("path", ""))
    path_only = path.split("?", 1)[0]
    if method == "POST" and path_only == "/tasks":
        return True
    if method == "POST" and path_only == "/tasks/from-message":
        return True
    if method == "POST" and re.fullmatch(r"/people/[^/]+/(notes|relationships)", path_only):
        return True
    if method == "POST" and path_only == "/identity/links":
        return True
    return method == "PUT" and bool(re.fullmatch(r"/calendar/events/[^/]+", path_only))


@mcp.tool(
    title="Search LifeOps sources",
    annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False),
)
async def search(query: str, sources: list[str] | None = None, limit: int = 50) -> str:
    """Search Inbox-backed personal sources with optional source scoping."""
    source_list = [source.strip() for source in (sources or ["all"]) if source.strip()]
    if not source_list:
        source_list = ["all"]
    bounded_limit = max(1, min(limit, 200))
    data = await _request(
        "POST",
        "/search",
        body={"q": query, "sources": source_list, "limit": bounded_limit},
    )
    item_id = _encode_search_id(query, source_list)
    payload = {
        "results": [
            {
                "id": item_id,
                "title": f"LifeOps search: {query}",
                "url": f"lifeops://{item_id}",
            }
        ],
        "total": data.get("total", 0) if isinstance(data, dict) else 0,
        "sources": source_list,
    }
    return json.dumps(payload, ensure_ascii=False)


@mcp.tool(
    title="Fetch LifeOps search evidence",
    annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False),
)
async def fetch(item_id: str) -> str:
    """Fetch the evidence bundle for a LifeOps search result id returned by search."""
    search_spec = _decode_search_id(item_id)
    query = search_spec["query"]
    sources = search_spec["sources"]
    data = await _request("POST", "/search", body={"q": query, "sources": sources, "limit": 50})
    payload = {
        "id": item_id,
        "title": f"LifeOps search: {query}",
        "text": json.dumps(data, ensure_ascii=False),
        "url": f"lifeops://{item_id}",
        "metadata": {"query": query, "sources": sources, "source": "Inbox /search"},
    }
    return json.dumps(payload, ensure_ascii=False)


@mcp.tool(
    title="Search the fast local LifeOps index",
    annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False),
)
async def search_indexed_messages(
    query: str,
    mode: Literal["keyword", "semantic", "hybrid"] = "hybrid",
    source: str = "",
    account: str = "",
    limit: int = 25,
) -> dict[str, Any]:
    """Search captured messages locally with exact and semantic matching."""
    params: dict[str, Any] = {
        "q": query,
        "mode": mode,
        "limit": max(1, min(limit, 100)),
    }
    if source:
        params["source"] = source
    if account:
        params["account"] = account
    data = dict(await _request("GET", "/index/search", params=params) or {})
    data["attribution"] = {
        "authority": "inbox_message_index",
        "source": source or "all_indexed_sources",
        "account": account,
        "derived": True,
        "read_only": True,
        "method": "inbox_index_search",
        "retrieved_at": datetime.now(UTC).isoformat(),
    }
    return data


@mcp.tool(
    title="Read LifeOps embedding index status",
    annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False),
)
async def embedding_status() -> dict[str, Any]:
    """Report whether the local semantic index is complete or still building."""
    return dict(await _request("GET", "/index/embedding-status") or {})


@mcp.tool(
    title="List LifeOps Drive files",
    annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False),
)
async def list_drive_files(query: str = "", account: str = "", limit: int = 20) -> list[dict[str, Any]]:
    """Read bounded Drive metadata through Inbox without downloading file contents."""
    params: dict[str, Any] = {"limit": max(1, min(limit, 100))}
    if query:
        params["q"] = query
    if account:
        params["account"] = account
    data = await _request("GET", "/drive/files", params=params)
    return list(data or [])


@mcp.tool(
    title="List LifeOps Google Docs",
    annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False),
)
async def list_docs(query: str = "", account: str = "", limit: int = 20) -> list[dict[str, Any]]:
    """Read bounded Google Docs metadata through Inbox without reading document bodies."""
    params: dict[str, Any] = {"limit": max(1, min(limit, 100))}
    if query:
        params["q"] = query
    if account:
        params["account"] = account
    data = await _request("GET", "/docs", params=params)
    return list(data or [])


@mcp.tool(
    title="Read bounded Google Doc evidence",
    annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False),
)
async def document_evidence(
    document_id: str,
    account: str = "",
    max_chars: int = 12000,
) -> dict[str, Any]:
    """Read one bounded Google Doc body with an explicit provenance receipt."""
    bounded_chars = max(1, min(max_chars, 50000))
    params = {"account": account} if account else None
    metadata = dict(await _request("GET", f"/docs/{document_id}", params=params) or {})
    body = dict(await _request("GET", f"/docs/{document_id}/text", params=params) or {})
    text = str(body.get("text") or "")
    return {
        "schema_version": "lifeops.document_evidence.v1",
        "read_only": True,
        "document": {
            "id": str(metadata.get("id") or document_id),
            "title": str(metadata.get("title") or "Untitled"),
            "url": str(metadata.get("url") or ""),
            "account": str(metadata.get("account") or account or ""),
        },
        "text": text[:bounded_chars],
        "truncated": len(text) > bounded_chars,
        "char_count": len(text),
        "returned_char_count": min(len(text), bounded_chars),
        "source_ref": {
            "kind": "google_doc_body",
            "source": "google_docs",
            "id": str(metadata.get("id") or document_id),
            "account": str(metadata.get("account") or account or ""),
        },
        "retrieved_at": datetime.now(UTC).isoformat(),
    }


@mcp.tool(
    title="Search LifeOps Google Sheets",
    annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False),
)
async def search_sheets(query: str = "", account: str = "", limit: int = 20) -> list[dict[str, Any]]:
    """Find Google Sheets through Inbox without a second Google credential store."""
    params: dict[str, Any] = {"q": query, "limit": max(1, min(limit, 100))}
    if account:
        params["account"] = account
    data = await _request("GET", "/sheets", params=params)
    return list(data or [])


@mcp.tool(
    title="Get Google Sheet metadata",
    annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False),
)
async def sheet_metadata(spreadsheet_id: str, account: str = "") -> dict[str, Any]:
    """Read exact spreadsheet and tab metadata before reading any cell range."""
    params = {"account": account} if account else None
    data = await _request("GET", f"/sheets/{spreadsheet_id}", params=params)
    return dict(data or {})


@mcp.tool(
    title="Read a bounded Google Sheet range",
    annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False),
)
async def read_sheet_range(
    spreadsheet_id: str,
    range_: str,
    account: str = "",
) -> dict[str, Any]:
    """Read a metadata-derived A1 range; this tool never writes spreadsheet cells."""
    params = {"account": account} if account else None
    data = await _request("GET", f"/sheets/{spreadsheet_id}/values/{range_}", params=params)
    return dict(data or {})


@mcp.tool(
    title="Search unified contacts",
    annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False),
)
async def contacts_search(query: str = "", limit: int = 20) -> list[dict[str, Any]]:
    """Search the existing Inbox contact merger across local and Google-backed sources."""
    data = await _request(
        "GET",
        "/contacts/search",
        params={"q": query, "limit": max(1, min(limit, 100))},
    )
    return list(data or [])


@mcp.tool(
    title="Get unified contact profile",
    annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False),
)
async def contact_profile(contact_id: str) -> dict[str, Any]:
    """Read a contact's merged activity profile without changing any address book."""
    data = await _request("GET", f"/contacts/{contact_id}/profile")
    profile = dict(data or {})
    profile["attribution"] = {
        "authority": "inbox_contact_merger",
        "source": "contacts",
        "account": "",
        "reference": {"kind": "contact_profile", "contact_id": contact_id},
        "source_timestamp": None,
        "retrieved_at": datetime.now(UTC).isoformat(),
        "derived": True,
        "read_only": True,
        "method": "inbox_contact_profile",
    }
    return profile


@mcp.tool(
    title="Search LifeOps people",
    annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False),
)
async def people_search(query: str = "", limit: int = 20) -> list[dict[str, Any]]:
    """Search source contacts and local LifeOps person profiles."""
    data = await _request("GET", "/people/search", params={"q": query, "limit": max(1, min(limit, 100))})
    return list(data or [])


@mcp.tool(
    title="Get LifeOps person profile",
    annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False),
)
async def person_profile(person_id: str, include_activity: bool = False) -> dict[str, Any]:
    """Read a person profile with identifiers, confirmed notes, relationship claims, and source activity."""
    return dict(
        await _request(
            "GET",
            f"/people/{person_id}/profile",
            params={"include_activity": include_activity},
        )
        or {}
    )


@mcp.tool(
    title="Read a message thread",
    annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False),
)
async def message_thread(
    source: Literal["imessage", "gmail", "linkedin", "whatsapp"],
    conversation_id: str,
    thread_id: str = "",
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Read the underlying messages after search identifies a relevant conversation."""
    params: dict[str, Any] = {"limit": max(1, min(limit, 200))}
    if thread_id:
        params["thread_id"] = thread_id
    data = await _request("GET", f"/messages/{source}/{conversation_id}", params=params)
    retrieved_at = datetime.now(UTC).isoformat()
    messages: list[dict[str, Any]] = []
    for message in data or []:
        if not isinstance(message, dict):
            continue
        item = dict(message)
        item["attribution"] = {
            "authority": source,
            "source": source,
            "account": str(message.get("account") or ""),
            "reference": {
                "kind": "message",
                "source": source,
                "conversation_id": conversation_id,
                "thread_id": thread_id,
                "message_id": str(message.get("message_id") or ""),
            },
            "source_timestamp": message.get("ts"),
            "retrieved_at": retrieved_at,
            "derived": False,
            "read_only": True,
            "method": "inbox_message_thread",
        }
        messages.append(item)
    return messages


@mcp.tool(
    title="Read one calendar event",
    annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False),
)
async def calendar_event(
    event_id: str,
    calendar_id: str = "primary",
    account: str = "",
) -> dict[str, Any]:
    """Read one exact event so a proposed update can be verified by read-back."""
    params: dict[str, Any] = {"calendar_id": calendar_id}
    if account:
        params["account"] = account
    data = await _request("GET", f"/calendar/events/{event_id}", params=params)
    event = dict(data or {})
    event["attribution"] = {
        "authority": "google_calendar",
        "source": "calendar",
        "account": str(event.get("account") or account),
        "reference": {
            "kind": "event",
            "source": "calendar",
            "event_id": event_id,
            "calendar_id": calendar_id,
        },
        "source_timestamp": event.get("start"),
        "retrieved_at": datetime.now(UTC).isoformat(),
        "derived": False,
        "read_only": True,
        "method": "inbox_calendar_event",
    }
    return event


@mcp.tool(
    title="Read current location",
    annotations=ToolAnnotations(read_only_hint=True, open_world_hint=True),
)
async def current_location() -> dict[str, Any]:
    """Read macOS Core Location or Inbox's configured home-address fallback."""
    data = await _request("GET", "/location/current")
    return dict(data or {})


@mcp.tool(
    title="Triage LifeOps attention",
    annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False),
)
async def life_triage(limit: int = 25, workflow: str = "", account: str = "") -> dict[str, Any]:
    """Return a bounded, attributed attention projection without changing any source."""
    params: dict[str, Any] = {"limit": max(1, min(limit, 100))}
    if workflow:
        params["workflow"] = workflow
    if account:
        params["account"] = account
    try:
        inbox_now = await _request("GET", "/inbox/now", params=params)
    except Exception as exc:
        result = build_triage(None, limit=limit)
        result["coverage"]["inbox_now"] = {
            "status": "unavailable",
            "read_only": True,
            "reasons": [f"inbox_read_failed:{type(exc).__name__}"],
        }
        return result
    return build_triage(inbox_now, limit=limit)


@mcp.tool(
    title="Triage all LifeOps sources",
    annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False),
)
async def triage_all(limit: int = 50, account: str = "", use_model: bool = True) -> dict[str, Any]:
    """Build a read-only, attributed triage across Inbox, Gmail, iMessage, Calendar, Tasks, Contacts, and Sheets."""
    bounded_limit = max(1, min(limit, 100))
    params = {"limit": bounded_limit}
    if account:
        params["account"] = account
    results: dict[str, Any] = {}
    run_id = f"triage:{uuid4().hex}"
    run_started_at = datetime.now(UTC)
    read_trace: list[dict[str, Any]] = []
    deadline = asyncio.get_running_loop().time() + _TRIAGE_TOTAL_TIMEOUT_SECONDS

    async def read(name: str, method: str, path: str, **kwargs: Any) -> None:
        last_error: Exception | None = None
        source_started_at = datetime.now(UTC)
        monotonic_started = asyncio.get_running_loop().time()
        for attempt in range(2):
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                results[name] = None
                results[f"{name}_error"] = "triage_deadline_exceeded"
                read_trace.append(
                    {
                        "name": name,
                        "path": path,
                        "status": "deadline_exceeded",
                        "attempts": attempt,
                        "started_at": source_started_at.isoformat(),
                        "finished_at": datetime.now(UTC).isoformat(),
                        "elapsed_ms": round((asyncio.get_running_loop().time() - monotonic_started) * 1000),
                        "error": "triage_deadline_exceeded",
                    }
                )
                return
            try:
                results[name] = await asyncio.wait_for(
                    _request(method, path, **kwargs),
                    timeout=min(_TRIAGE_READ_TIMEOUT_SECONDS, remaining),
                )
                read_trace.append(
                    {
                        "name": name,
                        "path": path,
                        "status": "ok",
                        "attempts": attempt + 1,
                        "started_at": source_started_at.isoformat(),
                        "finished_at": datetime.now(UTC).isoformat(),
                        "elapsed_ms": round((asyncio.get_running_loop().time() - monotonic_started) * 1000),
                    }
                )
                return
            except Exception as exc:
                last_error = exc
                if attempt == 0:
                    remaining = deadline - asyncio.get_running_loop().time()
                    if remaining > 0:
                        await asyncio.sleep(min(0.5, remaining))
        results[name] = None
        if deadline - asyncio.get_running_loop().time() <= 0:
            results[f"{name}_error"] = "triage_deadline_exceeded"
            error = "triage_deadline_exceeded"
        else:
            error = (
                f"{type(last_error).__name__}:{str(last_error)[:240]}" if last_error else "read_failed"
            )
            results[f"{name}_error"] = error
        read_trace.append(
            {
                "name": name,
                "path": path,
                "status": "error",
                "attempts": 2,
                "started_at": source_started_at.isoformat(),
                "finished_at": datetime.now(UTC).isoformat(),
                "elapsed_ms": round((asyncio.get_running_loop().time() - monotonic_started) * 1000),
                "error": error,
            }
        )

    # These reads touch the same local provider/session objects. Keep them
    # bounded and sequential so the triage run cannot overload Inbox and then
    # report a falsely complete multi-source snapshot.
    await read("inbox_now", "GET", "/inbox/now", params=params)
    await read(
        "read_proof",
        "POST",
        "/gateway/read-proof",
        body={
            "account": account,
            "gmail_query": "in:inbox",
            "gmail_limit": min(bounded_limit, 50),
            "calendar_days": 7,
            "calendar_limit": min(bounded_limit, 50),
            "task_limit": min(bounded_limit, 50),
        },
    )
    await read("imessage", "GET", "/conversations", params={"source": "imessage", "limit": bounded_limit})
    await read("sheets", "GET", "/sheets", params={"account": account, "limit": 100})
    await read("contacts", "GET", "/contacts/search", params={"q": "", "limit": 1})
    await read("provider_health", "GET", "/status/providers")

    result = build_unified_triage(
        results.get("inbox_now"),
        results.get("read_proof"),
        imessage_conversations=results.get("imessage"),
        sheets=results.get("sheets"),
        contacts=results.get("contacts"),
        provider_health=results.get("provider_health"),
        limit=bounded_limit,
    )
    result["read_errors"] = {
        key.removesuffix("_error"): value
        for key, value in results.items()
        if key.endswith("_error")
    }
    result["read_receipt"] = {
        "schema_version": "lifeops.triage_receipt.v1",
        "run_id": run_id,
        "started_at": run_started_at.isoformat(),
        "finished_at": datetime.now(UTC).isoformat(),
        "account": account,
        "account_scope": "selected_account" if account else "all_loaded_accounts",
        "limit": bounded_limit,
        "use_model": use_model,
        "read_only": True,
        "transport_complete": not bool(result["read_errors"]),
        "sources": read_trace,
        "note": (
            "This receipt describes this bounded read attempt; it is not proof of exhaustive provider coverage."
        ),
    }
    try:
        result["read_receipt"]["persistence"] = await asyncio.to_thread(
            _read_receipt_store().record,
            result["read_receipt"],
        )
    except Exception as exc:
        # A local audit-store failure must not turn a provider read into a
        # false success or prevent the caller from seeing the in-memory trace.
        result["read_receipt"]["persistence"] = {
            "status": "unavailable",
            "run_id": run_id,
            "error": type(exc).__name__,
        }
    if use_model:
        model_result = await asyncio.to_thread(classify_items, result["items"])
        result = apply_model_labels(result, model_result)
    return result


@mcp.tool(
    title="Read a LifeOps triage receipt",
    annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False),
)
async def read_triage_receipt(run_id: str) -> dict[str, Any]:
    """Read one durable metadata-only triage receipt by run ID."""
    clean_run_id = str(run_id or "").strip()
    if not clean_run_id:
        raise ValueError("run_id is required")
    receipt = await asyncio.to_thread(_read_receipt_store().get, clean_run_id)
    if receipt is None:
        raise ValueError("triage receipt was not found")
    return {
        "schema_version": "lifeops.triage_receipt_lookup.v1",
        "read_only": True,
        "receipt": receipt,
    }


@mcp.tool(
    title="List recent LifeOps triage receipts",
    annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False),
)
async def list_triage_receipts(limit: int = 50) -> dict[str, Any]:
    """List recent durable metadata-only triage receipts."""
    receipts = await asyncio.to_thread(_read_receipt_store().list_recent, limit)
    return {
        "schema_version": "lifeops.triage_receipt_list.v1",
        "read_only": True,
        "receipts": receipts,
        "count": len(receipts),
        "limit": max(1, min(int(limit), 200)),
    }


def _context_rows(data: Any, *keys: str) -> list[dict[str, Any]]:
    """Extract bounded row lists from Inbox list responses without guessing."""
    if isinstance(data, list):
        return [row for row in data if isinstance(row, dict)]
    if not isinstance(data, dict):
        return []
    for key in keys:
        rows = data.get(key)
        if isinstance(rows, list):
            return [row for row in rows if isinstance(row, dict)]
    return []


def _context_documents(
    drive_rows: list[dict[str, Any]], docs_rows: list[dict[str, Any]], limit: int
) -> list[dict[str, Any]]:
    """Project bounded Drive/Docs metadata while preserving provider IDs and links."""
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row, kind in [*( (item, "drive_file") for item in drive_rows), *(
        (item, "google_doc") for item in docs_rows
    )]:
        identifier = str(row.get("id") or row.get("file_id") or "").strip()
        if not identifier or identifier in seen:
            continue
        seen.add(identifier)
        title = str(row.get("name") or row.get("title") or "Untitled").strip()
        source = "google_drive" if kind == "drive_file" else "google_docs"
        result.append(
            {
                "item_id": f"{source}:{identifier}",
                "title": title,
                "source": source,
                "kind": kind,
                "mime_type": row.get("mime_type") or row.get("mimeType") or "",
                "modified_at": row.get("modified") or row.get("modified_time") or row.get("modified_at"),
                "web_link": row.get("web_link") or row.get("url") or "",
                "account": str(row.get("account") or ""),
                "parents": row.get("parents") or [],
                "source_ref": {
                    "kind": kind,
                    "source": source,
                    "id": identifier,
                    "account": str(row.get("account") or ""),
                },
            }
        )
        if len(result) >= limit:
            break
    return result


def _context_lifeops_auxiliary_notes(
    tabs: dict[str, Any], limit: int
) -> list[dict[str, Any]]:
    """Expose selected LifeOps workbook tabs as generic source-linked notes."""
    title_fields = (
        "title",
        "value",
        "question",
        "fact_family",
        "normalized_intent",
        "raw_capture",
        "context_or_event",
        "source_name",
        "setting",
        "thing_to_do",
        "layer",
    )
    result: list[dict[str, Any]] = []
    for tab_name, tab_data in tabs.items():
        if tab_name in {"people", "actions", "projects"} or not isinstance(tab_data, dict):
            continue
        for row in _context_rows(tab_data, "records"):
            source_ref = row.get("source_ref")
            if not isinstance(source_ref, dict) or not source_ref.get("id"):
                continue
            title = next(
                (str(row.get(field) or "").strip() for field in title_fields if row.get(field)),
                f"{tab_name} record",
            )
            content_fields = {
                key: value for key, value in row.items() if key != "source_ref" and value not in (None, "")
            }
            result.append(
                {
                    "item_id": f"lifeops_sheet:{tab_name}:{source_ref['id']}",
                    "title": title,
                    "source": "lifeops_sheet",
                    "tab": tab_name,
                    "record": content_fields,
                    "content": json.dumps(content_fields, ensure_ascii=False, default=str)[:4000],
                    "status": str(row.get("status") or "").strip(),
                    "source_ref": source_ref,
                }
            )
            if len(result) >= limit:
                return result
    return result


def _stale_health_limitations(value: Any, prefix: str = "source") -> list[str]:
    """Report nested stale/failed freshness checkpoints without hiding them."""
    limitations: list[str] = []
    if isinstance(value, dict):
        if value.get("stale") is True:
            limitations.append(f"{prefix}_stale")
        if value.get("healthy") is False:
            limitations.append(f"{prefix}_unhealthy")
        for reason in value.get("reasons", []) if isinstance(value.get("reasons"), list) else []:
            limitations.append(f"{prefix}:{reason}")
        for key, nested in value.items():
            if isinstance(nested, (dict, list)) and key not in {"reasons"}:
                limitations.extend(_stale_health_limitations(nested, f"{prefix}.{key}"))
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            limitations.extend(_stale_health_limitations(nested, f"{prefix}.{index}"))
    return limitations


def _context_email_action_rows(data: Any) -> list[dict[str, Any]]:
    """Extract the curated Email Action Queue without treating it as Gmail."""
    if not isinstance(data, dict):
        return []
    queues = data.get("queues")
    if not isinstance(queues, dict):
        return []
    email_actions = queues.get("email_actions")
    if not isinstance(email_actions, dict):
        return []
    records = email_actions.get("records")
    return [row for row in records if isinstance(row, dict)] if isinstance(records, list) else []


def _context_queue_attention(rows: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    """Project open curated email-action rows into clearly labeled attention."""
    result: list[dict[str, Any]] = []
    for row in rows:
        source_ref = row.get("source_ref")
        if not isinstance(source_ref, dict) or not source_ref.get("id"):
            continue
        status = str(row.get("status") or "open").casefold()
        if status in {"closed", "done", "completed", "archive", "archived", "cancelled"}:
            continue
        title = str(row.get("subject") or row.get("title") or "").strip()
        if not title:
            continue
        result.append(
            {
                "item_id": f"master_ops_queue:{source_ref['id']}",
                "title": title,
                "source": "google_sheets",
                "state": status,
                "attention_class": "curated_email_action",
                "reason": str(row.get("action_needed") or row.get("notes") or "").strip(),
                "due_at": row.get("due_date") or row.get("due"),
                "workflow": "master_tracker_email_action_queue",
                "source_ref": source_ref,
                "details": {
                    key: value
                    for key, value in row.items()
                    if key not in {"source_ref", "subject", "title", "status"}
                },
            }
        )
        if len(result) >= limit:
            break
    return result


def _context_ref(
    *,
    kind: str,
    source: str,
    identifier: str,
    account: str = "",
    **extra: Any,
) -> dict[str, Any]:
    reference: dict[str, Any] = {"kind": kind, "source": source, "id": identifier}
    if account:
        reference["account"] = account
    reference.update({key: value for key, value in extra.items() if value not in (None, "")})
    return reference


def _context_people(rows: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        identifier = str(row.get("contact_id") or row.get("id") or row.get("person_id") or "")
        if not identifier or identifier in seen:
            continue
        seen.add(identifier)
        source_ref = row.get("source_ref")
        if not isinstance(source_ref, dict):
            source_ref = _context_ref(
                kind="unified_contact_profile",
                source="contacts",
                identifier=identifier,
                account=str(row.get("account") or ""),
            )
        result.append(
            {
                "item_id": f"unified_contact:{identifier}",
                "contact_id": identifier,
                "title": str(row.get("name") or row.get("display_name") or "Unknown contact"),
                "source": "contacts",
                "identifiers": row.get("identifiers") or [],
                "sources": row.get("sources") or [],
                "addresses": row.get("addresses") or [],
                "total_interactions": row.get("total_interactions", 0),
                "last_interaction_at": row.get("last_interaction_at") or row.get("last_ts"),
                "relationship_score": row.get("relationship_score"),
                "relationship_tier": row.get("relationship_tier"),
                "source_ref": source_ref,
            }
        )
        if len(result) >= limit:
            break
    return result


def _person_name_keys(value: Any, *, include_fragments: bool = True) -> set[str]:
    """Return explicit full-name/alias keys and optional review fragments."""
    raw = str(value or "").strip().casefold()
    if not raw:
        return set()
    aliases = {raw}
    for match in re.findall(r"\(([^()]*)\)", raw):
        if match.strip():
            aliases.add(match.strip())
    without_parenthetical = re.sub(r"\([^()]*\)", "", raw).strip()
    if without_parenthetical:
        aliases.add(without_parenthetical)
        if include_fragments:
            aliases.update(
                token for token in re.findall(r"[a-z0-9]+", without_parenthetical) if len(token) >= 3
            )
    return {
        "".join(character for character in alias if character.isalnum())
        for alias in aliases
        if "".join(character for character in alias if character.isalnum())
    }


def _contact_candidate_ref(contact: dict[str, Any]) -> dict[str, Any]:
    """Return bounded disambiguation evidence without treating it as a match."""
    ref: dict[str, Any] = {
        "kind": "contact_record",
        "source": "contacts",
        "id": str(contact.get("id") or contact.get("contact_id") or ""),
        "name": str(contact.get("name") or contact.get("display_name") or ""),
    }
    for field in ("emails", "phones", "addresses", "source_counts"):
        value = contact.get(field)
        if value:
            ref[field] = value
    github_handle = str(contact.get("github_handle") or "").strip()
    if github_handle:
        ref["github_handle"] = github_handle
    return ref


def _context_lifeops_people(
    rows: list[dict[str, Any]],
    contacts: list[dict[str, Any]],
    limit: int,
    identity_links: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Project People rows with explicit matches and non-merging review candidates."""
    result: list[dict[str, Any]] = []
    for row in rows:
        source_ref = row.get("source_ref")
        person_id = str(row.get("person_id") or "").strip()
        name = str(row.get("name") or "").strip()
        if not person_id or not name or not isinstance(source_ref, dict) or not source_ref.get("id"):
            continue
        linked_refs: list[dict[str, Any]] = []
        candidate_refs: list[dict[str, Any]] = []
        resolution: dict[str, Any] = {"status": "unmatched", "method": "explicit_name_or_alias"}
        approved_links = [
            link
            for link in (identity_links or [])
            if isinstance(link, dict)
            and str(link.get("canonical_person_id") or "") == person_id
            and str(link.get("target_source") or "")
            and str(link.get("target_id") or "")
        ]
        if len(approved_links) == 1:
            link = approved_links[0]
            contact_id = str(link.get("target_id") or "")
            link_ref = {
                "kind": "identity_link",
                "source": "inbox_identity_links",
                "id": str(link.get("link_id") or ""),
                "canonical_person_id": person_id,
            }
            linked_refs.extend(
                [
                    {
                        "kind": "contact_record",
                        "source": str(link.get("target_source") or "contacts"),
                        "id": contact_id,
                        "name": str(link.get("target_name") or ""),
                    },
                    link_ref,
                ]
            )
            resolution = {
                "status": "matched",
                "method": "approved_identity_link",
                "contact_id": contact_id,
                "identity_link_id": str(link.get("link_id") or ""),
            }
        elif len(approved_links) > 1:
            resolution = {
                "status": "ambiguous",
                "method": "approved_identity_link",
                "match_count": len(approved_links),
                "candidate_source_refs": [
                    {
                        "kind": "identity_link",
                        "source": "inbox_identity_links",
                        "id": str(link.get("link_id") or ""),
                    }
                    for link in approved_links
                ],
            }
        else:
            row_explicit_keys = _person_name_keys(name, include_fragments=False)
            exact_matches = [
                contact
                for contact in contacts
                if row_explicit_keys
                & _person_name_keys(
                    contact.get("name") or contact.get("display_name"),
                    include_fragments=False,
                )
            ]
            if len(exact_matches) == 1:
                contact_id = str(exact_matches[0].get("id") or exact_matches[0].get("contact_id") or "")
                if contact_id:
                    resolution = {
                        "status": "matched",
                        "method": "exact_name_or_alias",
                        "contact_id": contact_id,
                    }
                    linked_refs.append(
                        {
                            "kind": "contact_record",
                            "source": "contacts",
                            "id": contact_id,
                            "name": str(exact_matches[0].get("name") or exact_matches[0].get("display_name") or ""),
                        }
                    )
            elif len(exact_matches) > 1:
                ambiguous_refs = [
                    _contact_candidate_ref(contact)
                    for contact in exact_matches
                    if str(contact.get("id") or contact.get("contact_id") or "")
                ]
                candidate_refs.extend(ambiguous_refs)
                resolution = {
                    "status": "ambiguous",
                    "method": "exact_name_or_alias",
                    "match_count": len(exact_matches),
                    "candidate_source_refs": ambiguous_refs,
                }
            else:
                without_parenthetical = re.sub(r"\([^()]*\)", "", name).strip()
                aliases = [match.strip() for match in re.findall(r"\(([^()]*)\)", name) if match.strip()]
                if not aliases and len(re.findall(r"[a-z0-9]+", without_parenthetical.casefold())) == 1:
                    aliases = [without_parenthetical]
                fragment_keys = {
                    key
                    for alias in aliases
                    for key in _person_name_keys(alias, include_fragments=False)
                }
                fragment_matches = [
                    contact
                    for contact in contacts
                    if fragment_keys
                    & _person_name_keys(
                        contact.get("name") or contact.get("display_name"),
                        include_fragments=True,
                    )
                ]
                if len(fragment_matches) == 1:
                    candidate = fragment_matches[0]
                    contact_id = str(candidate.get("id") or candidate.get("contact_id") or "")
                    if contact_id:
                        candidate_ref = _contact_candidate_ref(candidate)
                        candidate_refs.append(candidate_ref)
                        resolution = {
                            "status": "candidate",
                            "method": "unique_name_fragment",
                            "candidate_count": 1,
                        }
                elif len(fragment_matches) > 1:
                    ambiguous_refs = [
                        _contact_candidate_ref(contact)
                        for contact in fragment_matches
                        if str(contact.get("id") or contact.get("contact_id") or "")
                    ]
                    candidate_refs.extend(ambiguous_refs)
                    resolution = {
                        "status": "ambiguous",
                        "method": "name_fragment",
                        "match_count": len(fragment_matches),
                        "candidate_source_refs": ambiguous_refs,
                    }
        result.append(
            {
                "item_id": f"lifeops_sheet_person:{person_id}",
                "contact_id": person_id,
                "title": name,
                "source": "lifeops_sheet",
                "organization": str(row.get("organization") or "").strip(),
                "role": str(row.get("role") or "").strip(),
                "relationship_context": str(row.get("relationship_context") or "").strip(),
                "what_they_are_working_on": str(row.get("what_they_are_working_on") or "").strip(),
                "open_loop": str(row.get("open_loop") or "").strip(),
                "next_condition": str(row.get("next_condition") or "").strip(),
                "importance": str(row.get("importance") or "").strip(),
                "identity_confidence": row.get("identity_confidence"),
                "fact_confidence": row.get("fact_confidence"),
                "identity_resolution": resolution,
                "candidate_source_refs": candidate_refs,
                "linked_source_refs": linked_refs,
                "source_ref": source_ref,
            }
        )
        if len(result) >= limit:
            break
    return result


def _resolve_explicit_people(
    value: Any, people_rows: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Link explicit related-person text to canonical People rows conservatively."""
    refs: list[dict[str, Any]] = []
    resolutions: list[dict[str, Any]] = []
    parts = [part.strip() for part in re.split(r"[;,/]|\band\b", str(value or ""), flags=re.IGNORECASE)]
    for part in parts:
        if not part:
            continue
        matches = [
            row
            for row in people_rows
            if isinstance(row.get("source_ref"), dict)
            and row["source_ref"].get("id")
            and _person_name_keys(part)
            & _person_name_keys(row.get("name"), include_fragments=True)
        ]
        if len(matches) == 1:
            row = matches[0]
            ref = dict(row["source_ref"])
            ref.update(
                {
                    "person_id": str(row.get("person_id") or ""),
                    "person_name": str(row.get("name") or ""),
                }
            )
            if ref not in refs:
                refs.append(ref)
            resolutions.append({"input": part, "status": "matched", "person_id": ref["person_id"]})
        elif len(matches) > 1:
            resolutions.append(
                {
                    "input": part,
                    "status": "ambiguous",
                    "candidate_person_ids": [str(row.get("person_id") or "") for row in matches],
                }
            )
        else:
            resolutions.append({"input": part, "status": "unmatched"})
    return refs, resolutions


def _resolve_explicit_projects(
    value: Any, project_rows: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Link project text conservatively, retaining shorthand as a candidate."""
    refs: list[dict[str, Any]] = []
    resolutions: list[dict[str, Any]] = []
    parts = [part.strip() for part in re.split(r"[;,/]|\band\b", str(value or ""), flags=re.IGNORECASE)]
    for part in parts:
        if not part:
            continue
        key = _project_key(part)
        matches = [
            row
            for row in project_rows
            if key and key == _project_key(str(row.get("title") or ""))
        ]
        if len(matches) == 1:
            row = matches[0]
            source_ref = row.get("source_ref")
            if isinstance(source_ref, dict) and source_ref.get("id"):
                ref = dict(source_ref)
                ref.update(
                    {
                        "project_id": str(row.get("project_id") or row.get("item_id") or ""),
                        "project_name": str(row.get("title") or ""),
                    }
                )
                refs.append(ref)
                resolutions.append(
                    {
                        "input": part,
                        "status": "matched",
                        "project_id": ref["project_id"],
                    }
                )
                continue
        if len(matches) > 1:
            resolutions.append(
                {
                    "input": part,
                    "status": "ambiguous",
                    "candidate_project_ids": [
                        str(row.get("project_id") or row.get("item_id") or "") for row in matches
                    ],
                }
            )
            continue
        candidate_matches = [
            row
            for row in project_rows
            if key
            and len(key) >= 5
            and key in _project_key(str(row.get("title") or ""))
        ]
        if len(candidate_matches) == 1:
            row = candidate_matches[0]
            resolutions.append(
                {
                    "input": part,
                    "status": "candidate",
                    "candidate_project_ids": [
                        str(row.get("project_id") or row.get("item_id") or "")
                    ],
                    "candidate_project_names": [str(row.get("title") or "")],
                }
            )
        elif len(candidate_matches) > 1:
            resolutions.append(
                {
                    "input": part,
                    "status": "ambiguous",
                    "candidate_project_ids": [
                        str(row.get("project_id") or row.get("item_id") or "")
                        for row in candidate_matches
                    ],
                    "candidate_project_names": [
                        str(row.get("title") or "") for row in candidate_matches
                    ],
                }
            )
        else:
            resolutions.append({"input": part, "status": "unmatched"})
    return refs, resolutions


def _context_lifeops_actions(
    rows: list[dict[str, Any]],
    limit: int,
    people_rows: list[dict[str, Any]] | None = None,
    project_rows: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Project active explicit LifeOps Actions rows into commitments."""
    result: list[dict[str, Any]] = []
    for row in rows:
        source_ref = row.get("source_ref")
        action_id = str(row.get("action_id") or "").strip()
        action = str(row.get("action") or "").strip()
        state = str(row.get("state") or "").strip()
        if (
            not action_id
            or not action
            or not isinstance(source_ref, dict)
            or not source_ref.get("id")
            or state.casefold() in {"done", "completed", "closed", "cancelled"}
        ):
            continue
        related_person_refs, person_resolution = _resolve_explicit_people(
            row.get("related_person"), people_rows or []
        )
        related_project_refs, project_resolution = _resolve_explicit_projects(
            row.get("related_project"), project_rows or []
        )
        result.append(
            {
                "item_id": f"lifeops_sheet_action:{action_id}",
                "title": action,
                "source": "lifeops_sheet",
                "state": state or "OPEN",
                "owner": str(row.get("owner") or "").strip(),
                "related_person": str(row.get("related_person") or "").strip(),
                "related_project": str(row.get("related_project") or "").strip(),
                "next_condition": str(row.get("next_condition") or "").strip(),
                "time_sensitivity": str(row.get("time_sensitivity") or "").strip(),
                "priority": str(row.get("priority") or "").strip(),
                "machine_doable": str(row.get("machine_doable") or "").strip(),
                "verification": str(row.get("verification") or "").strip(),
                "related_person_refs": related_person_refs,
                "related_person_resolution": person_resolution,
                "related_project_refs": related_project_refs,
                "related_project_resolution": project_resolution,
                "source_ref": source_ref,
            }
        )
        if len(result) >= limit:
            break
    return result


def _context_lifeops_projects(
    rows: list[dict[str, Any]], people_rows: list[dict[str, Any]] | None = None
) -> list[dict[str, Any]]:
    """Adapt explicit LifeOps Projects rows to the shared project projection."""
    result: list[dict[str, Any]] = []
    for row in rows:
        source_ref = row.get("source_ref")
        project_id = str(row.get("project_id") or "").strip()
        project = str(row.get("project") or "").strip()
        if not project_id or not project or not isinstance(source_ref, dict) or not source_ref.get("id"):
            continue
        related_person_refs, person_resolution = _resolve_explicit_people(
            row.get("related_people"), people_rows or []
        )
        result.append(
            {
                "id": f"lifeops_sheet_project:{project_id}",
                "subject": project,
                "content": str(row.get("desired_outcome") or row.get("notes") or "").strip(),
                "source": "lifeops_sheet",
                "status": str(row.get("status") or "active").casefold() or "active",
                "updated_at": str(row.get("next_milestone") or ""),
                "metadata": {
                    "source_refs": [source_ref],
                    "project_id": project_id,
                    "next_milestone": str(row.get("next_milestone") or "").strip(),
                    "related_people": str(row.get("related_people") or "").strip(),
                    "authority": str(row.get("authority") or "").strip(),
                    "current_system": str(row.get("current_system") or "").strip(),
                    "related_person_refs": related_person_refs,
                    "related_person_resolution": person_resolution,
                },
            }
        )
    return result


def _context_contact_places(rows: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    """Project explicit Apple/Google contact addresses as place observations."""
    if limit < 1:
        return []
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        contact_id = str(row.get("contact_id") or row.get("id") or "")
        if not contact_id:
            continue
        addresses = row.get("addresses") or []
        if isinstance(addresses, dict):
            addresses = [addresses]
        for index, address in enumerate(addresses):
            if not isinstance(address, dict):
                continue
            formatted = str(
                address.get("formatted")
                or address.get("formattedValue")
                or address.get("street")
                or address.get("streetAddress")
                or ""
            ).strip()
            if not formatted:
                continue
            identity = f"{contact_id}:{index}:{formatted.casefold()}"
            if identity in seen:
                continue
            seen.add(identity)
            result.append(
                {
                    "item_id": f"contact_place:{contact_id}:{index}",
                    "title": formatted,
                    "source": "contacts",
                    "place": formatted,
                    "contact_id": contact_id,
                    "contact_name": str(row.get("name") or row.get("display_name") or ""),
                    "label": str(address.get("label") or address.get("type") or ""),
                    "source_ref": _context_ref(
                        kind="contact_address",
                        source="contacts",
                        identifier=contact_id,
                        account=str(address.get("source_account") or ""),
                        address_index=index,
                    ),
                }
            )
            if len(result) >= limit:
                return result
    return result


def _project_key(subject: str) -> str:
    """Build the same conservative explicit-name key as the stdio projection."""
    return "".join(character for character in subject.casefold() if character.isalnum())


def _context_projects(rows: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    """Deduplicate explicit project records while retaining every evidence ref."""
    groups: dict[str, list[dict[str, Any]]] = {}
    for raw_row in rows:
        row = raw_row
        if raw_row.get("project") and raw_row.get("source_ref"):
            source_ref = dict(raw_row["source_ref"])
            row = {
                "id": f"project_record:{source_ref['id']}",
                "subject": str(raw_row.get("project") or ""),
                "content": "\n".join(
                    value
                    for value in (
                        str(raw_row.get("next_action") or "").strip(),
                        str(raw_row.get("notes") or "").strip(),
                    )
                    if value
                ),
                "source": "google_sheets",
                "status": str(raw_row.get("status") or "active").casefold() or "active",
                "metadata": {
                    "source_refs": [source_ref],
                    "area": str(raw_row.get("area") or "").strip(),
                    "canonical_system": str(raw_row.get("canonical_system") or "").strip(),
                    "main_link": str(raw_row.get("main_link") or "").strip(),
                    "notion_link": str(raw_row.get("notion_link") or "").strip(),
                    "drive_folder": str(raw_row.get("drive_folder") or "").strip(),
                    "deadline": raw_row.get("deadline"),
                    "next_action": str(raw_row.get("next_action") or "").strip(),
                    "review_cadence": str(raw_row.get("review_cadence") or "").strip(),
                    "owner": str(raw_row.get("owner") or "").strip(),
                    "budget": raw_row.get("budget"),
                    "source_of_truth": str(raw_row.get("source_of_truth") or "").strip(),
                },
            }
        if str(row.get("status") or "active").casefold() in {"closed", "done", "deleted", "inactive"}:
            continue
        subject = str(row.get("subject") or "Untitled project")
        key = _project_key(subject) or "project"
        groups.setdefault(key, []).append(row)

    result: list[dict[str, Any]] = []
    for project_key, group in groups.items():
        ordered = sorted(
            group,
            key=lambda row: (str(row.get("updated_at") or ""), str(row.get("id") or "")),
            reverse=True,
        )
        primary = ordered[0]
        evidence_refs: list[dict[str, Any]] = []
        linked_refs: list[dict[str, Any]] = []
        seen_refs: set[str] = set()
        local_ids: list[str] = []
        for row in ordered:
            identifier = str(row.get("id") or "")
            if identifier:
                local_ids.append(identifier)
            metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
            ref = _context_ref(
                kind="memory_entry",
                source="lifeops_memory",
                identifier=identifier,
                memory_type="project",
                capture_id=str(metadata.get("capture_id") or ""),
            )
            ref_key = repr(sorted(ref.items()))
            if ref_key not in seen_refs:
                seen_refs.add(ref_key)
                evidence_refs.append(ref)
            linked_candidates = []
            if isinstance(metadata.get("source_refs"), list):
                linked_candidates.extend(metadata["source_refs"])
            if isinstance(metadata.get("related_person_refs"), list):
                linked_candidates.extend(metadata["related_person_refs"])
            for linked in linked_candidates:
                if isinstance(linked, dict) and linked.get("source") and linked.get("id"):
                    linked_key = repr(sorted(linked.items()))
                    if linked_key not in seen_refs:
                        seen_refs.add(linked_key)
                        linked_refs.append(dict(linked))
        result.append(
            {
                "item_id": f"lifeops_project:{project_key}",
                "project_id": str(primary.get("id") or ""),
                "project_key": project_key,
                "title": str(primary.get("subject") or "Untitled project"),
                "description": str(primary.get("content") or ""),
                "source": str(primary.get("source") or "lifeops_memory"),
                "confidence": primary.get("confidence"),
                "status": str(primary.get("status") or "active"),
                "capture_id": str(
                    (primary.get("metadata") or {}).get("capture_id")
                    if isinstance(primary.get("metadata"), dict)
                    else ""
                ),
                "evidence_count": len(evidence_refs),
                "evidence_refs": evidence_refs,
                "linked_source_refs": linked_refs,
                "local_memory_ids": local_ids,
                "source_ref": {**evidence_refs[0], "project_key": project_key},
            }
        )
        if len(result) >= limit:
            break
    return result


def _context_places(rows: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        location = str(row.get("location") or "").strip()
        identifier = str(row.get("event_id") or row.get("id") or "")
        if not location or not identifier or identifier in seen:
            continue
        seen.add(identifier)
        account = str(row.get("account") or row.get("gmail_account") or "")
        result.append(
            {
                "item_id": f"calendar_place:{identifier}",
                "title": location,
                "source": "calendar",
                "place": location,
                "event_summary": str(row.get("summary") or row.get("title") or "Untitled event"),
                "starts_at": row.get("start"),
                "ends_at": row.get("end"),
                "account": account,
                "calendar_id": str(row.get("calendar_id") or "primary"),
                "event_id": identifier,
                "source_ref": _context_ref(
                    kind="calendar_event",
                    source="calendar",
                    identifier=identifier,
                    account=account,
                    calendar_id=str(row.get("calendar_id") or "primary"),
                ),
            }
        )
        if len(result) >= limit:
            break
    return result


def _context_merge_places(rows: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    """Merge conservatively equivalent place observations without dropping evidence.

    This is deliberately a string-level normalization, not geocoding.  It only
    removes presentation punctuation/whitespace differences and expands
    common street suffix abbreviations.  Semantic separators such as hyphens
    and slashes, unit identifiers, and all other tokens remain part of the key,
    so distinct apartments or addresses are not merged.
    """

    suffixes = {
        "alley": "aly",
        "avenue": "ave",
        "boulevard": "blvd",
        "circle": "cir",
        "court": "ct",
        "drive": "dr",
        "expressway": "expy",
        "freeway": "fwy",
        "highway": "hwy",
        "junction": "jct",
        "lane": "ln",
        "parkway": "pkwy",
        "place": "pl",
        "road": "rd",
        "square": "sq",
        "street": "st",
        "terrace": "ter",
        "trail": "trl",
        "turnpike": "tpke",
        "way": "way",
    }

    def place_key(value: Any) -> str:
        text = str(value or "").casefold().strip()
        # Keep hyphenated/slashed address tokens intact (for example, 12-A is
        # not the same address token as 12 A). Commas, periods, and repeated
        # whitespace remain presentation differences.
        tokens = re.findall(r"[a-z0-9]+(?:[-/][a-z0-9]+)*", text)
        return " ".join(suffixes.get(token, token) for token in tokens)

    merged: dict[str, dict[str, Any]] = {}
    for row in rows:
        title = str(row.get("place") or row.get("title") or "").strip()
        key = place_key(title)
        if not key:
            continue
        current = merged.get(key)
        if current is None:
            current = dict(row)
            current["place_key"] = key
            current["normalization_method"] = "case_punctuation_whitespace_and_street_suffix"
            current["observation_count"] = 1
            current["evidence_refs"] = [row["source_ref"]] if isinstance(row.get("source_ref"), dict) else []
            current["linked_source_refs"] = []
            source = str(row.get("source") or "unknown")
            current["observed_sources"] = [source]
            current["source_counts"] = {source: 1}
            merged[key] = current
            continue
        current["observation_count"] = int(current.get("observation_count") or 0) + 1
        source = str(row.get("source") or "unknown")
        source_counts = current.setdefault("source_counts", {})
        source_counts[source] = int(source_counts.get(source) or 0) + 1
        observed_sources = current.setdefault("observed_sources", [])
        if source not in observed_sources:
            observed_sources.append(source)
            observed_sources.sort()
        source_ref = row.get("source_ref")
        if isinstance(source_ref, dict):
            refs = current.setdefault("evidence_refs", [])
            if source_ref not in refs:
                refs.append(source_ref)
        for field in ("contact_id", "contact_name", "event_id", "event_summary"):
            value = row.get(field)
            if value not in (None, "") and current.get(field) in (None, ""):
                current[field] = value
    return list(merged.values())[:limit]


def _context_commitments(rows: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        if row.get("completed") or str(row.get("status") or "").casefold() in {"done", "completed"}:
            continue
        identifier = str(row.get("id") or row.get("task_id") or "")
        if not identifier or identifier in seen:
            continue
        seen.add(identifier)
        account = str(row.get("account") or "")
        result.append(
            {
                "item_id": f"google_task:{identifier}",
                "title": str(row.get("title") or "Untitled task"),
                "source": "tasks",
                "state": "OPEN",
                "due_at": row.get("due"),
                "account": account,
                "list_id": str(row.get("list_id") or "@default"),
                "source_ref": _context_ref(
                    kind="task",
                    source="tasks",
                    identifier=identifier,
                    account=account,
                    list_id=str(row.get("list_id") or "@default"),
                ),
            }
        )
        if len(result) >= limit:
            break
    return result


def _context_property_evidence(data: Any, limit: int) -> list[dict[str, Any]]:
    """Adapt captured property events into bounded context records."""
    rows = _context_rows(data, "events")
    result: list[dict[str, Any]] = []
    for row in rows:
        event_id = str(row.get("event_id") or "").strip()
        if not event_id:
            continue
        metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
        result.append(
            {
                "item_id": f"property_evidence:{event_id}",
                "title": str(metadata.get("title") or metadata.get("zone_id") or "Property observation"),
                "source": "property",
                "property_id": str(metadata.get("property_id") or ""),
                "zone_id": str(metadata.get("zone_id") or ""),
                "evidence_kind": str(metadata.get("evidence_kind") or "observation"),
                "confidence": row.get("confidence"),
                "occurred_at": row.get("occurred_at"),
                "observed_at": row.get("observed_at"),
                "metadata": metadata,
                "observation": row.get("payload"),
                "source_ref": _context_ref(
                    kind="property_observation",
                    source="property",
                    identifier=event_id,
                    source_object_id=str(row.get("source_object_id") or ""),
                ),
            }
        )
        if len(result) >= limit:
            break
    return result


@mcp.tool(
    title="Read unified LifeOps context",
    annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False),
)
async def life_context(
    limit: int = 25,
    section_limit: int = 25,
    calendar_days: int = 7,
    account: str = "",
    use_model: bool = False,
) -> dict[str, Any]:
    """Return one bounded, provenance-backed read model across LifeOps sources.

    This is a transport projection over Inbox's existing read endpoints. It is
    not a second database or a write authority; source systems remain
    authoritative and every returned item carries a source reference.
    """
    bounded_limit = max(1, min(limit, 100))
    bounded_section_limit = max(1, min(section_limit, 100))
    bounded_days = max(1, min(calendar_days, 30))
    context_deadline = (
        asyncio.get_running_loop().time() + _LIFE_CONTEXT_TOTAL_TIMEOUT_SECONDS
    )
    triage = await triage_all(limit=bounded_limit, account=account, use_model=use_model)

    # Keep the fan-out below Inbox's provider/session pressure point across
    # concurrent MCP clients. These gates are process-wide: per-request gates
    # would still let two clients create an unsafe combined burst.
    read_gate, sheet_gate = _life_context_gates()
    sheet_paths = {
        "/memory",
        "/project-records",
        "/master-ops/queues",
        "/lifeops-sheet/projection",
    }

    async def safe_read(path: str, params: dict[str, Any]) -> tuple[Any, str | None]:
        for attempt in range(2):
            remaining = context_deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                return None, f"{path}:life_context_deadline_exceeded"
            try:
                async def read_with_gates() -> Any:
                    async with read_gate, _lifeops_read_process_lock():
                        if path in sheet_paths:
                            async with sheet_gate:
                                return await _request("GET", path, params=params)
                        return await _request("GET", path, params=params)

                return await asyncio.wait_for(
                    read_with_gates(),
                    timeout=min(_LIFE_CONTEXT_READ_TIMEOUT_SECONDS, remaining),
                ), None
            except TimeoutError:
                if context_deadline - asyncio.get_running_loop().time() <= 0:
                    return None, f"{path}:life_context_deadline_exceeded"
                return None, f"{path}:life_context_read_timeout"
            except httpx.TransportError as exc:
                # Only retry transport failures for this read-only projection.
                # Do not broaden this into the shared request helper: approval
                # and provider writes must never be silently replayed.
                if attempt == 0:
                    await asyncio.sleep(0.25)
                    continue
                detail = str(exc).replace("\n", " ")[:160]
                return None, f"{path}:{type(exc).__name__}:{detail}"
            except Exception as exc:
                detail = str(exc).replace("\n", " ")[:160]
                return None, f"{path}:{type(exc).__name__}:{detail}"

    account_inventory_error: str | None = None
    if account:
        provider_accounts = [account]
        provider_account_scope = "selected_account"
    else:
        account_inventory, account_inventory_error = await safe_read("/accounts", {})
        provider_accounts_set: set[str] = set()
        if isinstance(account_inventory, dict):
            for provider in ("gmail", "calendar", "drive", "docs", "tasks"):
                values = account_inventory.get(provider)
                if isinstance(values, list):
                    provider_accounts_set.update(
                        str(value).strip() for value in values if str(value).strip()
                    )
        # Keep the legacy default as a fail-loud fallback if the account
        # inventory cannot be read. The resulting limitation makes it clear
        # that this is not proof of all-account completeness.
        provider_accounts = sorted(provider_accounts_set) or [""]
        provider_account_scope = (
            "all_loaded_provider_accounts" if provider_accounts_set else "provider_default_fallback"
        )

    async def safe_read_account_rows(
        path: str,
        params: dict[str, Any],
        *keys: str,
    ) -> tuple[list[dict[str, Any]], str | None]:
        rows: list[dict[str, Any]] = []
        errors: list[str] = []
        for provider_account in provider_accounts:
            data, error = await safe_read(path, {**params, "account": provider_account})
            if error:
                errors.append(f"{provider_account or 'default'}:{error}")
                continue
            rows.extend(_context_rows(data, *keys))
        return rows, "; ".join(errors) if errors else None

    # These reads use the same provider/session objects. Schedule them
    # explicitly in sequence so each per-read timeout measures the endpoint
    # itself rather than time spent queued behind the cross-process lock.
    canonical_sheet_params = {
        "limit": bounded_section_limit,
        "account": LIFEOPS_CANONICAL_GOOGLE_ACCOUNT,
    }
    people_data, people_error = await safe_read(
        "/contacts/search",
        {"q": "", "limit": min(300, max(bounded_section_limit * 8, bounded_section_limit))},
    )
    identity_link_data, identity_link_error = await safe_read("/identity/links", {"limit": 500})
    project_data, project_error = await safe_read(
        "/memory",
        {"memory_type": "project", "status": "active", "limit": bounded_section_limit},
    )
    project_tracker_data, project_tracker_error = await safe_read(
        "/project-records", canonical_sheet_params.copy()
    )
    queue_data, queue_error = await safe_read("/master-ops/queues", canonical_sheet_params.copy())
    lifeops_data, lifeops_error = await safe_read(
        "/lifeops-sheet/projection",
        {
            **canonical_sheet_params,
            "include_tabs": "captures,interactions,values,research_cache,research_sources,authority_map,interview_queue,source_registry",
        },
    )
    embedding_data, embedding_error = await safe_read("/index/embedding-status", {})
    drive_data, drive_error = await safe_read_account_rows(
        "/drive/files", {"limit": bounded_section_limit}, "items", "files"
    )
    docs_data, docs_error = await safe_read_account_rows(
        "/docs", {"limit": bounded_section_limit}, "items", "documents"
    )
    calendar_data, calendar_error = await safe_read_account_rows(
        "/calendar/upcoming", {"days": bounded_days, "limit": bounded_section_limit}
    )
    tasks_data, tasks_error = await safe_read_account_rows(
        "/tasks", {"limit": bounded_section_limit, "show_completed": False}
    )
    property_data, property_error = await safe_read(
        "/events",
        {
            "source": "property",
            "event_type": "property.observation",
            "limit": bounded_section_limit,
        },
    )

    queue_attention = _context_queue_attention(
        _context_email_action_rows(queue_data), bounded_section_limit
    )
    lifeops_tabs = lifeops_data.get("tabs") if isinstance(lifeops_data, dict) else {}
    lifeops_people_rows = _context_rows(
        lifeops_tabs.get("people") if isinstance(lifeops_tabs, dict) else None,
        "records",
    )
    lifeops_action_rows = _context_rows(
        lifeops_tabs.get("actions") if isinstance(lifeops_tabs, dict) else None,
        "records",
    )
    lifeops_project_rows = _context_rows(
        lifeops_tabs.get("projects") if isinstance(lifeops_tabs, dict) else None,
        "records",
    )
    lifeops_auxiliary_notes = _context_lifeops_auxiliary_notes(
        lifeops_tabs if isinstance(lifeops_tabs, dict) else {}, bounded_section_limit
    )
    contact_rows = _context_rows(people_data, "items", "contacts", "profiles")
    identity_link_rows = _context_rows(identity_link_data, "links", "items")
    task_rows = _context_rows(tasks_data, "items", "tasks")
    drive_rows = _context_rows(drive_data, "items", "files")
    docs_rows = _context_rows(docs_data, "items", "documents")
    property_rows = _context_property_evidence(property_data, bounded_section_limit)
    project_rows = (
        _context_rows(project_data, "items", "memory", "entries")
        + _context_rows(project_tracker_data, "records", "items")
        + _context_lifeops_projects(lifeops_project_rows, lifeops_people_rows)
    )
    context_projects = _context_projects(project_rows, bounded_section_limit)
    lifeops_people = _context_lifeops_people(
        lifeops_people_rows, contact_rows, bounded_section_limit, identity_link_rows
    )
    lifeops_actions = _context_lifeops_actions(
        lifeops_action_rows,
        bounded_section_limit,
        lifeops_people_rows,
        context_projects,
    )
    sections: dict[str, list[dict[str, Any]]] = {
        "attention": [
            item for item in (triage.get("items") or []) if isinstance(item, dict) and item.get("source_ref")
        ][:bounded_limit],
        "people": _context_people(
            contact_rows, bounded_section_limit
        )
        + lifeops_people,
        "places": [],
        "projects": context_projects,
        "goals": [],
        "decisions": [],
        "notes": lifeops_auxiliary_notes,
        "documents": _context_documents(drive_rows, docs_rows, bounded_section_limit),
        "commitments": lifeops_actions
        + _context_commitments(task_rows, bounded_section_limit),
    }
    sections["attention"] = (queue_attention + sections["attention"])[:bounded_limit]
    # Collect each source independently before applying the shared section
    # limit. Otherwise repeated calendar locations can consume the budget and
    # hide distinct contact addresses before deduplication has a chance to
    # collapse the repeats.
    place_rows = _context_places(
        _context_rows(calendar_data, "items", "events"), bounded_section_limit
    )
    place_rows.extend(
        _context_contact_places(
            _context_rows(people_data, "items", "contacts", "profiles"),
            bounded_section_limit,
        )
    )
    sections["places"] = _context_merge_places(place_rows, bounded_section_limit)

    triage_health = dict(triage.get("coverage") or {})
    triage_health["status"] = "degraded" if triage.get("read_errors") else "ok"
    triage_health["read_only"] = True
    source_health = {
        "google_account_inventory": {
            "status": "ok" if account_inventory_error is None else "unavailable",
            "read_only": True,
            "scope": provider_account_scope,
            "accounts": [value for value in provider_accounts if value],
            "error": account_inventory_error,
        },
        "triage": triage_health,
        "unified_contacts": {
            "status": "ok" if people_error is None else "unavailable",
            "read_only": True,
            "profile_count": len(_context_people(contact_rows, bounded_section_limit)),
            "lifeops_profile_count": len(lifeops_people),
            "error": people_error,
        },
        "identity_links": {
            "status": "ok" if identity_link_error is None else "unavailable",
            "read_only": True,
            "link_count": len(identity_link_rows),
            "error": identity_link_error,
        },
        "calendar": {
            "status": "ok" if calendar_error is None else "unavailable",
            "read_only": True,
            "scope": provider_account_scope,
            "accounts": [value for value in provider_accounts if value],
            "event_count": len(_context_rows(calendar_data, "items", "events")),
            "lookahead_days": bounded_days,
            "error": calendar_error,
        },
        "tasks": {
            "status": "ok" if tasks_error is None else "unavailable",
            "read_only": True,
            "scope": provider_account_scope,
            "accounts": [value for value in provider_accounts if value],
            "open_task_count": len(_context_commitments(task_rows, bounded_section_limit)),
            "error": tasks_error,
        },
        "projects": {
            "status": "ok" if project_error is None or project_tracker_error is None else "unavailable",
            "read_only": True,
            "project_count": len(sections["projects"]),
            "error": project_error,
            "tracker_status": "ok" if project_tracker_error is None else "unavailable",
            "tracker_error": project_tracker_error,
            "tracker_scope": "canonical_user_scoped",
            "tracker_source_account": LIFEOPS_CANONICAL_GOOGLE_ACCOUNT,
        },
        "master_ops": {
            "status": "ok" if queue_error is None else "unavailable",
            "read_only": True,
            "scope": "canonical_user_scoped",
            "source_account": LIFEOPS_CANONICAL_GOOGLE_ACCOUNT,
            "email_action_count": len(_context_email_action_rows(queue_data)),
            "error": queue_error,
        },
        "lifeops_sheet": {
            "status": "ok" if lifeops_error is None else "unavailable",
            "read_only": True,
            "scope": "canonical_user_scoped",
            "source_account": LIFEOPS_CANONICAL_GOOGLE_ACCOUNT,
            "people_count": len(lifeops_people_rows),
            "action_count": len(lifeops_action_rows),
            "project_count": len(lifeops_project_rows),
            "auxiliary_note_count": len(lifeops_auxiliary_notes),
            "included_tabs": [
                name for name in lifeops_tabs if name not in {"people", "actions", "projects"}
            ],
            "error": lifeops_error,
        },
        "embedding_index": {
            "status": "ok" if embedding_error is None else "unavailable",
            "read_only": True,
            "model_id": embedding_data.get("model_id") if isinstance(embedding_data, dict) else "",
            "items": embedding_data.get("items", 0) if isinstance(embedding_data, dict) else 0,
            "embedded": embedding_data.get("embedded", 0) if isinstance(embedding_data, dict) else 0,
            "pending": embedding_data.get("pending", 0) if isinstance(embedding_data, dict) else 0,
            "error": embedding_error,
        },
        "google_drive": {
            "status": "ok" if drive_error is None else "unavailable",
            "read_only": True,
            "scope": provider_account_scope,
            "accounts": [value for value in provider_accounts if value],
            "file_count": len(drive_rows),
            "error": drive_error,
        },
        "google_docs": {
            "status": "ok" if docs_error is None else "unavailable",
            "read_only": True,
            "scope": provider_account_scope,
            "accounts": [value for value in provider_accounts if value],
            "document_count": len(docs_rows),
            "error": docs_error,
        },
        "property_evidence": {
            "status": "ok" if property_error is None else "unavailable",
            "read_only": True,
            "observation_count": len(property_rows),
            "error": property_error,
        },
    }
    limitations = [
        "agent_runtime_memory_not_imported",
        "document_content_not_part_of_context_v1",
    ]
    if account_inventory_error:
        limitations.append("provider_account_inventory_unavailable")
    elif provider_account_scope == "provider_default_fallback":
        limitations.append("provider_account_inventory_empty")
    if embedding_error:
        limitations.append("embedding_index_read_unavailable")
    elif isinstance(embedding_data, dict) and int(embedding_data.get("pending") or 0) > 0:
        limitations.append("embeddings_pending")
    limitations.extend(_stale_health_limitations(source_health.get("triage"), "triage"))
    if project_error and project_tracker_error:
        limitations.append("projects_read_unavailable")
    elif not sections["projects"]:
        limitations.append("no_explicit_project_records_observed")
    for name, error in (
        ("contacts", people_error),
        ("identity_links", identity_link_error),
        ("calendar", calendar_error),
        ("tasks", tasks_error),
        ("projects", project_error),
        ("project_tracker", project_tracker_error),
        ("master_ops", queue_error),
        ("lifeops_sheet", lifeops_error),
        ("embedding_index", embedding_error),
        ("google_drive", drive_error),
        ("google_docs", docs_error),
        ("property_evidence", property_error),
    ):
        if error:
            limitations.append(f"{name}_read_unavailable")
    if property_error is None and not property_rows:
        limitations.append("property_evidence_not_captured")

    references: list[dict[str, Any]] = []
    source_counts: dict[str, int] = {}
    for section_items in sections.values():
        for item in section_items:
            item_reference_keys: set[str] = set()
            item_refs = [
                item.get("source_ref"),
                *(item.get("evidence_refs") or []),
                *(item.get("linked_source_refs") or []),
                *(item.get("candidate_source_refs") or []),
                *(item.get("related_person_refs") or []),
            ]
            for reference in item_refs:
                if not isinstance(reference, dict):
                    continue
                reference_key = repr(sorted(reference.items()))
                if reference_key in item_reference_keys:
                    continue
                item_reference_keys.add(reference_key)
                source = str(reference.get("source") or "unknown")
                source_counts[source] = source_counts.get(source, 0) + 1
                if len(references) < bounded_limit:
                    references.append(reference)

    return {
        "schema_version": "lifeops.context.v1",
        "checked_at": datetime.now(UTC).isoformat(),
        "read_only": True,
        "scope": {
            "account": account or "all_observed_accounts",
            "provider_account_scope": provider_account_scope,
            "provider_accounts": [value for value in provider_accounts if value],
            "canonical_google_account": LIFEOPS_CANONICAL_GOOGLE_ACCOUNT,
        },
        "sections": sections,
        "property_evidence": property_rows,
        "counts": {name: len(items) for name, items in sections.items()},
        "source_health": source_health,
        "limitations": limitations,
        "provenance": {
            "reference_count": sum(source_counts.values()),
            "sources": dict(sorted(source_counts.items())),
            "references": references,
        },
    }


_EVIDENCE_PACKET_SECTIONS = frozenset(
    {
        "attention",
        "people",
        "places",
        "projects",
        "commitments",
        "notes",
        "documents",
        "property_evidence",
        "provenance",
    }
)
_DEFAULT_EVIDENCE_PACKET_SECTIONS = (
    "attention",
    "people",
    "places",
    "projects",
    "commitments",
    "property_evidence",
    "provenance",
)
_WORKER_EVIDENCE_PACKET_SECTIONS = frozenset(_DEFAULT_EVIDENCE_PACKET_SECTIONS)


def _worker_account_allowlist() -> frozenset[str]:
    """Return explicitly configured worker account identities."""
    raw = os.environ.get("LIFEOPS_WORKER_ACCOUNT_ALLOWLIST", "")
    return frozenset(value.strip().casefold() for value in raw.split(",") if value.strip())


@mcp.tool(
    title="Build a scoped LifeOps evidence packet",
    annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False),
)
async def evidence_packet(
    consumer: Literal["orca", "claude", "pi", "deepseek", "openclaw", "cursor", "agy", "btw", "other"] = "other",
    purpose: str = "review",
    sections: list[str] | None = None,
    limit: int = 25,
    calendar_days: int = 7,
    account: str = "",
) -> dict[str, Any]:
    """Return bounded context for a worker without granting provider access.

    The packet is an ephemeral projection over ``life_context``. It carries
    source references, health, and limitations but no Inbox credential, tool
    grant, or write authority. The default intentionally excludes notes and
    document metadata; callers must request those sections explicitly.
    """
    clean_purpose = str(purpose or "").strip()
    if not clean_purpose:
        raise ValueError("purpose is required")
    if len(clean_purpose) > 240:
        raise ValueError("purpose must be at most 240 characters")

    selected = tuple(dict.fromkeys(sections or _DEFAULT_EVIDENCE_PACKET_SECTIONS))
    unknown = sorted(set(selected) - _EVIDENCE_PACKET_SECTIONS)
    if unknown:
        raise ValueError(f"Unsupported evidence packet section(s): {', '.join(unknown)}")
    if os.environ.get("LIFEOPS_MCP_PROFILE", "full").strip().lower() == "worker":
        restricted = sorted(set(selected) - _WORKER_EVIDENCE_PACKET_SECTIONS)
        if restricted:
            raise ValueError(
                "Worker evidence packets cannot include: " + ", ".join(restricted)
            )
        allowed_accounts = _worker_account_allowlist()
        requested_account = str(account or "").strip().casefold()
        if not allowed_accounts:
            raise ValueError(
                "Worker account scope is not configured; set "
                "LIFEOPS_WORKER_ACCOUNT_ALLOWLIST to one or more exact accounts"
            )
        if not requested_account or requested_account not in allowed_accounts:
            raise ValueError("Worker account is outside the configured allowlist")

    bounded_limit = max(1, min(limit, 100))
    bounded_days = max(1, min(calendar_days, 30))
    context = await life_context(
        limit=bounded_limit,
        section_limit=bounded_limit,
        calendar_days=bounded_days,
        account=account,
        use_model=False,
    )
    context_sections = context.get("sections") if isinstance(context, dict) else {}
    packet_sections: dict[str, Any] = {}
    for section in selected:
        if section == "property_evidence":
            value = context.get("property_evidence", []) if isinstance(context, dict) else []
        elif section == "provenance":
            value = context.get("provenance", {}) if isinstance(context, dict) else {}
        else:
            value = context_sections.get(section, []) if isinstance(context_sections, dict) else []
        packet_sections[section] = value[:bounded_limit] if isinstance(value, list) else value

    limitations = list(context.get("limitations", [])) if isinstance(context, dict) else []
    limitations.append("packet_is_ephemeral_and_read_only")
    limitations.append("worker_has_no_provider_or_terminal_authority")
    if account:
        limitations.append(
            "account_scope_applies_to_provider_reads; canonical_local_personal_sources_are_user_scoped"
        )
    return {
        "schema_version": "lifeops.evidence_packet.v1",
        "packet_id": f"evidence_packet:{uuid4().hex}",
        "generated_at": datetime.now(UTC).isoformat(),
        "read_only": True,
        "consumer": consumer,
        "purpose": clean_purpose,
        "scope": {
            "account": account or "all_observed_accounts",
            "sections": list(selected),
            "max_items_per_section": bounded_limit,
            "calendar_days": bounded_days,
            "account_scope_mode": (
                "provider_account_where_supported; canonical_local_personal_sources_are_user_scoped"
                if account
                else "all_observed_accounts_and_canonical_local_personal_sources"
            ),
            "source_access": "LifeOps read models only",
            "provider_writes": False,
            "worker_control": False,
            "secret_access": False,
            "raw_event_mutation": False,
        },
        "sections": packet_sections,
        "source_health": context.get("source_health", {}) if isinstance(context, dict) else {},
        "limitations": limitations,
        "provenance": context.get("provenance", {}) if isinstance(context, dict) else {},
    }


@mcp.tool(
    title="Review LifeOps identity and place links",
    annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False),
)
async def identity_review(
    status: Literal["", "matched", "candidate", "ambiguous", "unmatched"] = "",
    limit: int = 50,
    account: str = "",
) -> dict[str, Any]:
    """Return unresolved people plus place/project evidence needing review.

    This is a projection over ``life_context``. It never promotes a candidate
    to a canonical identity and never edits Contacts, Calendar, or the
    LifeOps workbook.
    """
    bounded_limit = max(1, min(limit, 100))
    context = await life_context(
        limit=bounded_limit,
        section_limit=100,
        calendar_days=30,
        account=account,
        use_model=False,
    )
    people: list[dict[str, Any]] = []
    requested_statuses = {status} if status else {"candidate", "ambiguous", "unmatched"}
    for item in context.get("sections", {}).get("people", []):
        if not isinstance(item, dict):
            continue
        resolution = item.get("identity_resolution")
        if not isinstance(resolution, dict):
            continue
        item_status = str(resolution.get("status") or "unmatched")
        if item_status not in requested_statuses:
            continue
        people.append(item)
        if len(people) >= bounded_limit:
            break

    places = [
        item
        for item in context.get("sections", {}).get("places", [])
        if isinstance(item, dict)
    ][:bounded_limit]
    projects = [
        item
        for item in context.get("sections", {}).get("projects", [])
        if isinstance(item, dict)
    ][:bounded_limit]
    references: list[dict[str, Any]] = []
    seen_refs: set[str] = set()
    for item in [*people, *places, *projects]:
        candidates = [item.get("source_ref"), *(item.get("evidence_refs") or []), *(item.get("candidate_source_refs") or []), *(item.get("linked_source_refs") or [])]
        for reference in candidates:
            if not isinstance(reference, dict):
                continue
            key = repr(sorted(reference.items()))
            if key in seen_refs:
                continue
            seen_refs.add(key)
            references.append(reference)
            if len(references) >= bounded_limit:
                break
        if len(references) >= bounded_limit:
            break
    return {
        "schema_version": "lifeops.identity_review.v1",
        "checked_at": datetime.now(UTC).isoformat(),
        "read_only": True,
        "filter": {"status": status, "account": account},
        "people": people,
        "places": places,
        "projects": projects,
        "counts": {
            "people": len(people),
            "places": len(places),
            "projects": len(projects),
        },
        "source_health": context.get("source_health", {}),
        "limitations": [
            "identity links remain candidates until explicitly confirmed",
            "place records are observations and do not update Contacts automatically",
        ],
        "provenance": {"reference_count": len(references), "references": references},
    }


@mcp.tool(
    title="Read LifeOps review queue",
    annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False),
)
async def review_queue(
    limit: int = 50,
    offset: int = 0,
    account: str = "",
) -> dict[str, Any]:
    """Return one bounded queue of unresolved identity and project links."""
    bounded_limit = max(1, min(limit, 100))
    bounded_offset = max(0, min(offset, 10_000))
    context = await life_context(
        limit=bounded_limit,
        section_limit=100,
        calendar_days=30,
        account=account,
        use_model=False,
    )
    items: list[dict[str, Any]] = []
    priority_by_status = {"ambiguous": 1, "candidate": 2, "unmatched": 3}
    people = context.get("sections", {}).get("people", [])
    for person in people if isinstance(people, list) else []:
        if not isinstance(person, dict):
            continue
        resolution = person.get("identity_resolution")
        if not isinstance(resolution, dict):
            continue
        status = str(resolution.get("status") or "unmatched")
        if status not in priority_by_status:
            continue
        item_id = str(person.get("item_id") or person.get("contact_id") or person.get("title") or "")
        items.append(
            {
                "queue_id": f"identity:{item_id}",
                "kind": "identity_link",
                "status": status,
                "priority": priority_by_status[status],
                "title": str(person.get("title") or "Unknown person"),
                "suggested_action": (
                    "choose one contact candidate"
                    if status in {"candidate", "ambiguous"}
                    else "find corroborating evidence before linking"
                ),
                "identity_resolution": resolution,
                "candidate_source_refs": person.get("candidate_source_refs") or [],
                "source_ref": person.get("source_ref"),
            }
        )

    commitments = context.get("sections", {}).get("commitments", [])
    for commitment in commitments if isinstance(commitments, list) else []:
        if not isinstance(commitment, dict):
            continue
        resolutions = commitment.get("related_project_resolution")
        if not isinstance(resolutions, list):
            continue
        for resolution in resolutions:
            if not isinstance(resolution, dict):
                continue
            status = str(resolution.get("status") or "unmatched")
            if status not in priority_by_status:
                continue
            input_name = str(resolution.get("input") or "").strip()
            if not input_name:
                continue
            commitment_id = str(commitment.get("item_id") or commitment.get("title") or "")
            items.append(
                {
                    "queue_id": f"project:{commitment_id}:{_project_key(input_name)}",
                    "kind": "project_link",
                    "status": status,
                    "priority": priority_by_status[status],
                    "title": str(commitment.get("title") or "Untitled action"),
                    "project_text": input_name,
                    "suggested_action": (
                        "choose one project candidate"
                        if status in {"candidate", "ambiguous"}
                        else "leave unresolved or add a canonical project alias"
                    ),
                    "project_resolution": resolution,
                    "related_person_refs": commitment.get("related_person_refs") or [],
                    "source_ref": commitment.get("source_ref"),
                }
            )

    coverage_data: dict[str, Any] = {}
    coverage_error: str | None = None
    try:
        coverage_data = dict(await coverage_report() or {})
    except Exception as exc:
        coverage_error = f"{type(exc).__name__}:{str(exc).replace(chr(10), ' ')[:160]}"

    source_priority = {"blocked": 1, "stale": 1, "unknown": 3}
    coverage_sources: list[tuple[str, dict[str, Any]]] = []
    for account_row in coverage_data.get("accounts", []) if isinstance(coverage_data.get("accounts"), list) else []:
        if not isinstance(account_row, dict):
            continue
        account_name = str(account_row.get("account") or "")
        for source in account_row.get("sources", []) if isinstance(account_row.get("sources"), list) else []:
            if not isinstance(source, dict):
                continue
            coverage_sources.append((account_name, source))
    for source in coverage_data.get("unscoped_sources", []) if isinstance(coverage_data.get("unscoped_sources"), list) else []:
        if isinstance(source, dict):
            coverage_sources.append(("", source))
    for account_name, source in coverage_sources:
        source_id = str(source.get("source_id") or "")
        freshness = source.get("freshness") if isinstance(source.get("freshness"), dict) else {}
        source_status = str(source.get("status") or "")
        freshness_status = str(freshness.get("status") or "")
        if source_status == "blocked" or not source.get("readable", True):
            review_status = "blocked"
            suggested_action = "inspect connector blockers before relying on this source"
        elif freshness_status == "stale":
            review_status = "stale"
            suggested_action = "refresh the source before using it for current decisions"
        elif freshness_status == "unknown":
            review_status = "unknown"
            suggested_action = "establish a freshness checkpoint for this source"
        else:
            continue
        items.append(
            {
                "queue_id": f"source:{account_name}:{source_id}",
                "kind": "source_health",
                "status": review_status,
                "priority": source_priority[review_status],
                "title": f"{source.get('display_name') or source_id} ({account_name or 'local'})",
                "suggested_action": suggested_action,
                "account": account_name,
                "source_id": source_id,
                "configured": source.get("configured"),
                "authenticated": source.get("authenticated"),
                "readable": source.get("readable"),
                "blockers": source.get("blockers") or [],
                "coverage_notes": str(source.get("coverage_notes") or ""),
                "freshness": freshness,
                "source_status": source_status,
            }
        )
    completeness = coverage_data.get("completeness") if isinstance(coverage_data.get("completeness"), dict) else {}
    for planned_source in completeness.get("planned_sources", []) if isinstance(completeness.get("planned_sources"), list) else []:
        planned_name = str(planned_source or "").strip()
        if not planned_name:
            continue
        items.append(
            {
                "queue_id": f"planned_source:{planned_name}",
                "kind": "source_gap",
                "status": "planned",
                "priority": 4,
                "title": planned_name,
                "suggested_action": "add this source only when it closes a demonstrated workflow gap",
                "source_id": planned_name,
            }
        )

    inherited_limitations = [
        str(value).strip()
        for value in (context.get("limitations", []) if isinstance(context, dict) else [])
        if str(value).strip()
    ]
    review_limitations = [
        value
        for value in inherited_limitations
        if (
            value.endswith("_read_unavailable")
            or value.endswith("_stale")
            or value.endswith("_unhealthy")
            or value.startswith("triage:")
            or value.startswith("provider_account_inventory")
        )
    ]
    if coverage_error:
        review_limitations.append(f"coverage_report_unavailable:{coverage_error}")
    if any(
        item.get("kind") == "source_health"
        and item.get("status") in {"blocked", "stale", "unknown"}
        for item in items
    ):
        review_limitations.append("coverage_has_unresolved_source_gaps")
    review_limitations = list(dict.fromkeys(review_limitations))

    items.sort(key=lambda item: (int(item.get("priority") or 9), str(item.get("kind") or ""), str(item.get("title") or "")))
    available_items = list(items)
    items = available_items[bounded_offset : bounded_offset + bounded_limit]

    def queue_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
        return {
            "total": len(rows),
            "identity_link": sum(item.get("kind") == "identity_link" for item in rows),
            "project_link": sum(item.get("kind") == "project_link" for item in rows),
            "source_health": sum(item.get("kind") == "source_health" for item in rows),
            "source_gap": sum(item.get("kind") == "source_gap" for item in rows),
            "ambiguous": sum(item.get("status") == "ambiguous" for item in rows),
            "candidate": sum(item.get("status") == "candidate" for item in rows),
            "unmatched": sum(item.get("status") == "unmatched" for item in rows),
        }

    references = [item.get("source_ref") for item in items if isinstance(item.get("source_ref"), dict)]
    return {
        "schema_version": "lifeops.review_queue.v1",
        "checked_at": datetime.now(UTC).isoformat(),
        "read_only": True,
        "filter": {"account": account, "offset": bounded_offset},
        "items": items,
        "counts": queue_counts(items),
        "available_counts": queue_counts(available_items),
        "complete": not review_limitations,
        "completeness": {
            "status": "complete" if not review_limitations else "partial",
            "scope": "identity, project-link, and source-health review",
            "limitations": review_limitations,
        },
        "truncated": bounded_offset > 0 or bounded_offset + len(items) < len(available_items),
        "pagination": {
            "offset": bounded_offset,
            "limit": bounded_limit,
            "has_more": bounded_offset + len(items) < len(available_items),
            "next_offset": (
                bounded_offset + len(items)
                if bounded_offset + len(items) < len(available_items)
                else None
            ),
        },
        "source_health": context.get("source_health", {}),
        "limitations": [
            "review items are not writes",
            "identity and project links require explicit confirmation before mutation",
            "the queue is bounded and may require a larger limit for complete review",
        ] + review_limitations,
        "provenance": {"reference_count": len(references), "references": references},
    }


@mcp.tool(
    title="Triage email and messages",
    annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False),
)
async def triage_messages(
    source: Literal["", "gmail", "imessage"] = "",
    account: str = "",
    category: Literal["", "reply_now", "task", "calendar", "waiting", "fyi", "archive"] = "",
    limit: int = 50,
    offset: int = 0,
    use_model: bool = True,
) -> dict[str, Any]:
    """Explain which indexed email/message threads matter and why, read-only.

    Use offset plus limit to review successive pages of the bounded queue.
    """
    data = dict(
        await _request(
            "POST",
            "/triage/messages",
            body={
                "source": source,
                "account": account,
                "category": category,
                "limit": max(1, min(limit, 200)),
                "offset": max(0, min(offset, 100000)),
            },
        )
        or {}
    )
    if use_model:
        model_result = await asyncio.to_thread(classify_items, data.get("items", []))
        data = apply_model_labels(data, model_result)
    return data


@mcp.tool(
    title="Read Gmail normalization",
    annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False),
)
async def gmail_normalization() -> dict[str, Any]:
    """Report indexed Gmail coverage, sync freshness, and action counts per account."""
    return dict(await _request("GET", "/gmail/normalization") or {})


@mcp.tool(
    title="Read todo candidates",
    annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False),
)
async def todo_candidates(
    source: Literal["", "gmail", "imessage"] = "",
    account: str = "",
    category: Literal["", "reply_now", "task", "calendar", "waiting"] = "",
    limit: int = 100,
) -> dict[str, Any]:
    """Read deduplicated, attributed action candidates without creating tasks."""
    return dict(
        await _request(
            "GET",
            "/triage/todo-candidates",
            params={
                "source": source,
                "account": account,
                "category": category,
                "limit": max(1, min(limit, 500)),
            },
        )
        or {}
    )


@mcp.tool(
    title="Check LifeOps source health",
    annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False),
)
async def source_health() -> dict[str, Any]:
    """Check which local and cloud sources are configured, readable, writable, stale, or blocked."""
    providers, capture, egress = await _parallel_reads()
    return {"providers": providers, "capture": capture, "egress": egress}


@mcp.tool(
    title="List LifeOps source registry",
    annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False),
)
async def source_registry() -> dict[str, Any]:
    """Return source authority, capture mode, and freshness policy without probing providers."""
    return dict(await _request("GET", "/sources/registry") or {})


def _coverage_age_seconds(timestamp: Any, checked_at: datetime) -> float | None:
    if not isinstance(timestamp, str) or not timestamp.strip():
        return None
    try:
        observed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError:
        return None
    if observed.tzinfo is None:
        observed = observed.replace(tzinfo=UTC)
    return max(0.0, (checked_at - observed.astimezone(UTC)).total_seconds())


def _coverage_freshness(
    source_id: str,
    *,
    last_success_at: str = "",
    newest_seen_at: str = "",
    policy_by_source: dict[str, dict[str, Any]],
    checked_at: datetime,
) -> dict[str, Any]:
    policy = policy_by_source.get(source_id, {})
    freshness_seconds = policy.get("freshness_seconds")
    sync_age = _coverage_age_seconds(last_success_at, checked_at)
    newest_age = _coverage_age_seconds(newest_seen_at, checked_at)
    if sync_age is None:
        status = "unknown"
    elif freshness_seconds is None:
        status = "observed"
    else:
        status = "fresh" if sync_age <= float(freshness_seconds) else "stale"
    return {
        "status": status,
        "policy_seconds": freshness_seconds,
        "last_success_at": last_success_at,
        "last_success_age_seconds": sync_age,
        "newest_seen_at": newest_seen_at,
        "newest_seen_age_seconds": newest_age,
    }


def _coverage_provider_source_id(provider: dict[str, Any]) -> str:
    provider_id = str(provider.get("provider") or "")
    return {
        "google_gmail": "gmail",
        "google_calendar": "google_calendar",
        "google_tasks": "google_tasks",
        "google_drive": "google_drive",
        "google_sheets": "google_sheets",
        "google_docs": "google_docs",
        "google_contacts": "google_contacts",
    }.get(provider_id, provider_id)


def _coverage_capture_status(source: dict[str, Any]) -> str:
    status = str(source.get("status") or "unknown")
    return {"ok": "ready", "not_configured": "not_configured", "error": "blocked"}.get(
        status, status
    )


def _coverage_provider_status(provider: dict[str, Any]) -> str:
    if not provider.get("configured"):
        return "not_configured"
    if provider.get("readable") is not True or provider.get("blockers"):
        return "blocked"
    return "ready"


def _coverage_reason(source_id: str, status: str, detail: dict[str, Any]) -> str:
    if status == "blocked":
        blockers = detail.get("blockers") or []
        return f"{source_id}:{','.join(str(item) for item in blockers) or 'not_readable'}"
    if status == "not_configured":
        return f"{source_id}:not_configured"
    if status == "stale":
        return f"{source_id}:stale"
    return ""


def _coverage_source_report(
    source_id: str,
    capture: dict[str, Any],
    provider: dict[str, Any],
    policy_by_source: dict[str, dict[str, Any]],
    checked_at: datetime,
) -> dict[str, Any]:
    """Build one coverage row for either an account-scoped or local source."""
    last_success_at = str(capture.get("last_success_at") or "")
    newest_seen_at = str(capture.get("newest_seen_at") or "")
    status = _coverage_capture_status(capture) if capture else _coverage_provider_status(provider)
    if capture and status == "ready" and provider:
        provider_status = _coverage_provider_status(provider)
        if provider_status in {"blocked", "not_configured"}:
            status = provider_status
    return {
        "source_id": source_id,
        "display_name": policy_by_source.get(source_id, {}).get("display_name", source_id),
        "authority": policy_by_source.get(source_id, {}).get("authority", ""),
        "status": status,
        "configured": capture.get("configured", provider.get("configured")),
        "authenticated": capture.get("authenticated", provider.get("authenticated")),
        "readable": capture.get("readable", provider.get("readable")),
        "writable": capture.get("writable", provider.get("writable")),
        "last_error": capture.get("last_error", ""),
        "item_count": capture.get("item_count", provider.get("item_count", 0)),
        "blockers": provider.get("blockers", []),
        "coverage_notes": capture.get("coverage_notes", provider.get("notes", "")),
        "freshness": _coverage_freshness(
            source_id,
            last_success_at=last_success_at,
            newest_seen_at=newest_seen_at,
            policy_by_source=policy_by_source,
            checked_at=checked_at,
        ),
    }


async def _coverage_read(coro: Any) -> tuple[Any, str]:
    try:
        return await coro, ""
    except Exception as exc:  # noqa: BLE001 - report source failure in the read model
        return {}, f"{type(exc).__name__}: {str(exc)[:160]}"


@mcp.tool(
    title="Report LifeOps coverage and freshness",
    annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False),
)
async def coverage_report() -> dict[str, Any]:
    """Combine source registry, account health, indexed coverage, and freshness."""
    checked_at = datetime.now(UTC)
    (health, health_error), (gmail, gmail_error), (embedding, embedding_error), (registry, registry_error) = await asyncio.gather(
        _coverage_read(source_health()),
        _coverage_read(gmail_normalization()),
        _coverage_read(embedding_status()),
        _coverage_read(source_registry()),
    )
    provider_payload = health.get("providers") if isinstance(health, dict) else {}
    providers = provider_payload.get("providers", []) if isinstance(provider_payload, dict) else []
    capture_payload = health.get("capture") if isinstance(health, dict) else {}
    capture_sources = capture_payload.get("sources", []) if isinstance(capture_payload, dict) else []
    registry_rows = registry.get("sources", []) if isinstance(registry, dict) else []
    policy_by_source = {
        str(row.get("source_id")): row
        for row in registry_rows
        if isinstance(row, dict) and row.get("source_id")
    }
    providers_by_source = {
        _coverage_provider_source_id(row): row
        for row in providers
        if isinstance(row, dict) and _coverage_provider_source_id(row)
    }
    captures_by_key = {
        str(row.get("key")): row
        for row in capture_sources
        if isinstance(row, dict) and row.get("key")
    }
    gmail_accounts = {
        str(row.get("account")): row
        for row in (gmail.get("accounts", []) if isinstance(gmail, dict) else [])
        if isinstance(row, dict) and row.get("account")
    }

    accounts: set[str] = set(gmail_accounts)
    for provider in providers:
        if not isinstance(provider, dict):
            continue
        accounts.update(str(account) for account in provider.get("accounts", []) if account)
    account_reports: list[dict[str, Any]] = []
    reasons: list[str] = []
    for account in sorted(accounts):
        source_ids: set[str] = {"gmail"} if account in gmail_accounts else set()
        for source_id, provider in providers_by_source.items():
            if account in [str(value) for value in provider.get("accounts", [])]:
                source_ids.add(source_id)
        for key in captures_by_key:
            if key.endswith(f":{account}"):
                source_ids.add(key.split(":", 1)[0])

        source_reports: list[dict[str, Any]] = []
        for source_id in sorted(source_ids):
            provider = providers_by_source.get(source_id, {})
            capture = captures_by_key.get(f"{source_id}:{account}", {})
            source_report = _coverage_source_report(
                source_id, capture, provider, policy_by_source, checked_at
            )
            if source_id == "gmail" and account in gmail_accounts:
                gmail_row = gmail_accounts[account]
                sync = gmail_row.get("sync") or {}
                source_report.update(
                    {
                        "indexed": gmail_row.get("indexed"),
                        "item_count": gmail_row.get("item_count", 0),
                        "thread_count": gmail_row.get("thread_count", 0),
                        "unread_item_count": gmail_row.get("unread_item_count", 0),
                        "actionable_count": gmail_row.get("actionable_count", 0),
                        "open_loop_count": gmail_row.get("open_loop_count", 0),
                        "time_sensitive_count": gmail_row.get("time_sensitive_count", 0),
                        "latest_item_at": gmail_row.get("latest_item_at", ""),
                        "coverage": gmail_row.get("coverage", ""),
                    }
                )
                if sync.get("last_success_at"):
                    source_report["freshness"] = _coverage_freshness(
                        source_id,
                        last_success_at=str(sync.get("last_success_at")),
                        newest_seen_at=str(gmail_row.get("latest_item_at") or ""),
                        policy_by_source=policy_by_source,
                        checked_at=checked_at,
                    )
                source_report["sync"] = sync
            source_reports.append(source_report)
            reason = _coverage_reason(source_id, source_report["status"], source_report)
            if reason:
                reasons.append(f"{account}:{reason}")
            if source_report["freshness"]["status"] == "stale":
                reasons.append(f"{account}:{source_id}:stale")
        counts = {
            "ready": sum(row["status"] == "ready" for row in source_reports),
            "blocked": sum(row["status"] == "blocked" for row in source_reports),
            "not_configured": sum(row["status"] == "not_configured" for row in source_reports),
        }
        account_reports.append(
            {
                "account": account,
                "status": "ready" if counts["blocked"] == 0 and counts["not_configured"] == 0 else "partial",
                "source_counts": counts,
                "sources": source_reports,
            }
        )

    # Local and other unscoped sources do not belong to a Google account. Keep
    # them in the same coverage contract so callers cannot mistake an
    # account-only report for complete LifeOps coverage. Skip aggregate Google
    # placeholders when account-specific rows exist.
    unscoped_sources: list[dict[str, Any]] = []
    account_scoped_source_ids = {
        key.split(":", 1)[0]
        for key in captures_by_key
        if ":" in key and key.split(":", 1)[1]
    }
    for key, capture in sorted(captures_by_key.items()):
        source_id, _, account = key.partition(":")
        if account or source_id in account_scoped_source_ids:
            continue
        provider = providers_by_source.get(source_id, {})
        source_report = _coverage_source_report(
            source_id, capture, provider, policy_by_source, checked_at
        )
        unscoped_sources.append(source_report)
        reason = _coverage_reason(source_id, source_report["status"], source_report)
        if reason:
            reasons.append(f"unscoped:{reason}")
        if source_report["freshness"]["status"] == "stale":
            reasons.append(f"unscoped:{source_id}:stale")

    if health_error:
        reasons.append(f"source_health_read_error:{health_error}")
    if gmail_error:
        reasons.append(f"gmail_normalization_read_error:{gmail_error}")
    if embedding_error:
        reasons.append(f"embedding_status_read_error:{embedding_error}")
    if registry_error:
        reasons.append(f"source_registry_read_error:{registry_error}")
    if isinstance(embedding, dict) and int(embedding.get("pending") or 0) > 0:
        reasons.append("embedding_index_pending")
    planned_sources = [
        str(row.get("source_id"))
        for row in registry_rows
        if isinstance(row, dict) and row.get("lifecycle") == "planned"
    ]
    reasons.extend(f"planned_source:{source_id}" for source_id in planned_sources)
    unique_reasons = list(dict.fromkeys(reasons))
    return {
        "schema_version": "lifeops.coverage.v1",
        "checked_at": checked_at.isoformat(),
        "read_only": True,
        "completeness": {
            "status": "complete_for_observed_accounts" if not unique_reasons else "partial",
            "reasons": unique_reasons,
            "planned_sources": planned_sources,
        },
        "accounts": account_reports,
        "unscoped_sources": unscoped_sources,
        "provider_summary": provider_payload.get("summary", {}) if isinstance(provider_payload, dict) else {},
        "embedding_index": embedding if isinstance(embedding, dict) else {},
        "source_registry": {
            "registry_version": registry.get("registry_version", "") if isinstance(registry, dict) else "",
            "source_count": len(registry_rows),
        },
        "limitations": [
            "account-level completeness is based on Inbox capture and indexed sync state",
            "provider-side mailbox completeness beyond recorded checkpoints is not proven",
            "planned sources are not connected by this report",
        ],
    }


@mcp.tool(
    title="Audit LifeOps system readiness",
    annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False),
)
async def system_audit() -> dict[str, Any]:
    """Return one read-only, fail-loud audit of the current LifeOps boundary.

    This is deliberately a review surface rather than an automation trigger.
    It combines existing read models, preserves their limitations, and reports
    known capability gaps instead of collapsing partial coverage into a green
    status.  It never creates tasks, changes providers, or grants workers
    access.
    """
    checked_at = datetime.now(UTC)
    (coverage, coverage_error), (tasks, tasks_error), (property_data, property_error) = await asyncio.gather(
        _coverage_read(coverage_report()),
        _coverage_read(task_reconciliation(limit=500)),
        _coverage_read(property_evidence(limit=50)),
    )

    issues: list[dict[str, Any]] = []

    def add_issue(code: str, severity: str, detail: str) -> None:
        issues.append({"code": code, "severity": severity, "detail": detail})

    if coverage_error:
        add_issue("coverage_unavailable", "blocking", coverage_error)
    else:
        completeness = coverage.get("completeness") if isinstance(coverage, dict) else {}
        if isinstance(completeness, dict) and completeness.get("status") != "complete_for_observed_accounts":
            for reason in completeness.get("reasons", [])[:25]:
                add_issue("coverage_partial", "attention", str(reason))

    if tasks_error:
        add_issue("task_reconciliation_unavailable", "blocking", tasks_error)
    else:
        duplicate_groups = tasks.get("duplicate_task_groups", []) if isinstance(tasks, dict) else []
        if duplicate_groups:
            add_issue(
                "duplicate_tasks_detected",
                "attention",
                f"{len(duplicate_groups)} conservative duplicate group(s) require review; no task was changed.",
            )

    if property_error:
        add_issue("property_evidence_unavailable", "attention", property_error)
    else:
        property_count = int(property_data.get("count") or 0) if isinstance(property_data, dict) else 0
        if property_count == 0:
            add_issue(
                "property_evidence_not_captured",
                "attention",
                "No property observations are captured; geometry and floor-plan claims remain unproven.",
            )

    embedding = coverage.get("embedding_index", {}) if isinstance(coverage, dict) else {}
    pending_embeddings = int(embedding.get("pending") or 0) if isinstance(embedding, dict) else 0
    if pending_embeddings:
        add_issue(
            "embeddings_pending",
            "attention",
            f"{pending_embeddings} indexed item(s) still lack embeddings.",
        )

    known_gaps = [
        {
            "code": "agent_runtime_adapter_not_exposed",
            "detail": "LifeOps can durably record bounded work-item proposals, but Bridge/Orca dispatch is fail-closed until exact ticket admission, tree binding, and independent verification are proven.",
        },
        {
            "code": "cursor_and_agy_adapter_not_exposed",
            "detail": "Cursor and Agy are local tools, but have no governed LifeOps adapter yet.",
        },
        {
            "code": "btw_v2_adapter_not_exposed",
            "detail": "BTW v2 must consume scoped evidence packets; it is not a canonical personal-data authority.",
        },
        {
            "code": "provider_mailbox_completeness_unproven",
            "detail": "Indexed checkpoints do not prove that every provider-side item has been captured.",
        },
    ]

    blocking_count = sum(issue["severity"] == "blocking" for issue in issues)
    overall_status = "blocked" if blocking_count else "attention" if issues else "ready"
    return {
        "schema_version": "lifeops.system_audit.v1",
        "checked_at": checked_at.isoformat(),
        "read_only": True,
        "overall_status": overall_status,
        "checks": {
            "coverage": {
                "status": "unavailable" if coverage_error else "observed",
                "error": coverage_error,
                "read_model": "lifeops.coverage.v1",
            },
            "task_reconciliation": {
                "status": "unavailable" if tasks_error else "observed",
                "error": tasks_error,
                "duplicate_group_count": len(tasks.get("duplicate_task_groups", []))
                if isinstance(tasks, dict)
                else 0,
                "read_model": "inbox.tasks.reconciliation",
            },
            "property_evidence": {
                "status": "unavailable" if property_error else "not_captured" if property_count == 0 else "observed",
                "error": property_error,
                "observation_count": int(property_data.get("count") or 0)
                if isinstance(property_data, dict)
                else 0,
                "read_model": "lifeops.property_evidence.v1",
            },
            "embedding_index": {
                "status": "unavailable" if not isinstance(embedding, dict) else "pending" if pending_embeddings else "ready",
                "pending": pending_embeddings,
                "model_id": embedding.get("model_id", "") if isinstance(embedding, dict) else "",
            },
            "write_policy": {
                "status": "ready",
                "rule": "proposal -> explicit approval -> single-use lease -> execute -> read-back",
            },
        },
        "issues": issues,
        "known_gaps": known_gaps,
        "scope": {
            "provider_writes": False,
            "worker_control": False,
            "secret_access": False,
            "raw_event_mutation": False,
        },
        "limitations": [
            "This audit reports the LifeOps read boundary; it does not inspect arbitrary Mac files or credentials.",
            "A ready audit means the observed read checks responded, not that every planned source is connected.",
            "Known gaps remain explicit until a governed adapter and its live verification receipts exist.",
        ],
    }


@mcp.tool(
    title="List LifeOps evidence events",
    annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False),
)
async def evidence_events(
    source: str = "",
    event_type: str = "",
    limit: int = 50,
) -> dict[str, Any]:
    """Read bounded raw observations with their original provenance."""
    params = {
        "source": source,
        "event_type": event_type,
        "limit": max(1, min(limit, 200)),
    }
    return dict(await _request("GET", "/events", params=params) or {})


@mcp.tool(
    title="Read property evidence",
    annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False),
)
async def property_evidence(
    event_type: str = "property.observation",
    limit: int = 50,
) -> dict[str, Any]:
    """Read captured property observations without inferring or changing geometry.

    Photos, measurements, parcel records, and sun/shadow observations are
    stored as append-only events.  Their metadata can carry a property and
    zone identifier, while the original payload remains the evidence.
    """
    bounded_limit = max(1, min(limit, 200))
    data = dict(
        await _request(
            "GET",
            "/events",
            params={"source": "property", "event_type": event_type, "limit": bounded_limit},
        )
        or {}
    )
    events = data.get("events") if isinstance(data.get("events"), list) else []
    observations: list[dict[str, Any]] = []
    for event in events:
        if not isinstance(event, dict):
            continue
        metadata = event.get("metadata") if isinstance(event.get("metadata"), dict) else {}
        observations.append(
            {
                **event,
                "property_id": metadata.get("property_id", ""),
                "zone_id": metadata.get("zone_id", ""),
                "evidence_kind": metadata.get("evidence_kind", "observation"),
                "source_ref": {
                    "kind": "property_observation",
                    "source": "property",
                    "id": event.get("event_id", ""),
                    "source_object_id": event.get("source_object_id", ""),
                },
            }
        )
    return {
        "schema_version": "lifeops.property_evidence.v1",
        "checked_at": datetime.now(UTC).isoformat(),
        "read_only": True,
        "observations": observations,
        "count": len(observations),
        "filters": {"event_type": event_type, "limit": bounded_limit},
        "coverage": {
            "source": "property",
            "authority": "append_only_event_log",
            "provider_calls": False,
        },
        "limitations": [
            "only explicitly captured property evidence is returned",
            "geometry, floor plans, and sun/shadow conclusions are not inferred by this read",
        ],
    }


@mcp.tool(
    title="Capture a LifeOps observation",
    annotations=ToolAnnotations(
        read_only_hint=False,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=False,
    ),
)
async def capture_observation(
    text: str,
    source: str = "manual",
    event_type: str = "manual.capture",
    source_object_id: str = "",
    occurred_at: str = "",
    confidence: float = 1.0,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Append a user observation locally; this never calls or mutates an external provider."""
    if not text.strip():
        raise ValueError("text is required")
    body: dict[str, Any] = {
        "source": source,
        "event_type": event_type,
        "source_object_id": source_object_id,
        "occurred_at": occurred_at,
        "content": text,
        "confidence": confidence,
        "metadata": metadata or {},
        "provenance": {"channel": "lifeops_mcp"},
    }
    return dict(await _request("POST", "/events/capture", body=body) or {})


async def _parallel_reads() -> tuple[Any, Any, Any]:
    import asyncio

    return tuple(
        await asyncio.gather(
            _request("GET", "/status/providers"),
            _request("GET", "/capture/health"),
            _request("GET", "/egress/status"),
        )
    )  # type: ignore[return-value]


@mcp.tool(
    title="Get calendar events",
    annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False),
)
async def calendar_events(date: str) -> list[dict[str, Any]]:
    """Get calendar events for an ISO date such as 2026-08-24 before reasoning about commitments or travel."""
    data = await _request("GET", "/calendar/events", params={"date": date})
    return list(data or [])


@mcp.tool(
    title="Calculate departure times",
    annotations=ToolAnnotations(read_only_hint=True, open_world_hint=True),
)
async def departure_times(
    origin: str = "",
    mode: Literal["driving", "walking", "bicycling", "transit"] = "driving",
    buffer_minutes: int = 10,
    lookahead_hours: int = 24,
) -> list[dict[str, Any]]:
    """Calculate traffic-aware leave times for upcoming calendar events that have locations."""
    params: dict[str, Any] = {
        "mode": mode,
        "buffer_minutes": max(0, min(buffer_minutes, 120)),
        "lookahead_hours": max(1, min(lookahead_hours, 72)),
    }
    if origin:
        params["origin"] = origin
    data = await _request("GET", "/calendar/departure-times", params=params)
    return list(data or [])


@mcp.tool(
    title="Calculate travel time",
    annotations=ToolAnnotations(read_only_hint=True, open_world_hint=True),
)
async def travel_time(
    origin: str,
    destination: str,
    mode: Literal["driving", "walking", "bicycling", "transit"] = "driving",
) -> dict[str, Any]:
    """Calculate current travel time between two places using Inbox's maps service."""
    data = await _request(
        "GET",
        "/maps/travel-time",
        params={"origin": origin, "destination": destination, "mode": mode},
    )
    return dict(data or {})


@mcp.tool(
    title="Calculate a multi-stop route",
    annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False),
)
async def multi_stop_route(
    stops: list[dict[str, Any]],
    arrival_time: str,
    origin: str = "",
    origin_name: str = "Origin",
    mode: Literal["driving", "walking", "bicycling", "transit"] = "driving",
    buffer_minutes: int = 10,
) -> dict[str, Any]:
    """Calculate one read-only leave time for an ordered pickup or travel chain."""
    data = await _request(
        "POST",
        "/maps/route",
        body={
            "origin": origin,
            "origin_name": origin_name,
            "stops": stops,
            "arrival_time": arrival_time,
            "mode": mode,
            "buffer_minutes": buffer_minutes,
        },
    )
    return dict(data or {})


@mcp.tool(
    title="List Google Tasks",
    annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False),
)
async def tasks(
    list_id: str = "@default",
    show_completed: bool = False,
    limit: int = 50,
    account: str = "",
) -> list[dict[str, Any]]:
    """Read current Google Tasks before proposing task changes or checking whether work already exists."""
    params: dict[str, Any] = {
        "list_id": list_id,
        "show_completed": show_completed,
        "limit": max(1, min(limit, 200)),
    }
    if account:
        params["account"] = account
    data = await _request("GET", "/tasks", params=params)
    return list(data or [])


@mcp.tool(
    title="Reconcile LifeOps tasks",
    annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False),
)
async def task_reconciliation(
    source: Literal["", "gmail", "imessage"] = "",
    account: str = "",
    limit: int = 500,
) -> dict[str, Any]:
    """Compare existing Google Tasks with message-derived candidates without writes."""
    return dict(
        await _request(
            "GET",
            "/tasks/reconciliation",
            params={
                "source": source,
                "account": account,
                "limit": max(1, min(limit, 500)),
            },
        )
        or {}
    )


@mcp.tool(
    title="Review duplicate Google Tasks",
    annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False),
)
async def task_duplicate_review(
    account: str = "",
    limit: int = 100,
) -> dict[str, Any]:
    """Return bounded duplicate-task groups for human review without mutation."""
    bounded_limit = max(1, min(limit, 100))
    reconciliation = await task_reconciliation(account=account, limit=500)
    raw_groups = reconciliation.get("duplicate_task_groups", [])
    reviews: list[dict[str, Any]] = []

    def normalized_title(value: Any) -> str:
        return " ".join(re.findall(r"[a-z0-9]+", str(value or "").casefold()))

    for group in raw_groups[:bounded_limit] if isinstance(raw_groups, list) else []:
        if not isinstance(group, list):
            continue
        tasks_in_group = [task for task in group if isinstance(task, dict)]
        task_ids = sorted(str(task.get("id") or "") for task in tasks_in_group)
        task_ids = [task_id for task_id in task_ids if task_id]
        if len(task_ids) < 2:
            continue
        titles = {normalized_title(task.get("title")) for task in tasks_in_group}
        titles.discard("")
        account_values = {
            str(task.get("account") or "")
            for task in tasks_in_group
            if str(task.get("account") or "")
        }
        review_key = "\x00".join([*account_values, *task_ids]).encode()
        reviews.append(
            {
                "review_id": f"task_duplicate_review:{hashlib.sha256(review_key).hexdigest()[:24]}",
                "status": "review_required",
                "match_type": "exact_title" if len(titles) == 1 else "conservative_near_duplicate",
                "automatic_mutation": False,
                "tasks": [
                    {
                        "id": str(task.get("id") or ""),
                        "account": str(task.get("account") or ""),
                        "title": str(task.get("title") or ""),
                    }
                    for task in tasks_in_group
                ],
                "recommendation": (
                    "Review the task pair and choose a canonical task manually; "
                    "this tool never deletes, merges, or edits tasks."
                ),
            }
        )

    return {
        "schema_version": "lifeops.task_duplicate_review.v1",
        "checked_at": datetime.now(UTC).isoformat(),
        "read_only": True,
        "account": account,
        "groups": reviews,
        "group_count": len(reviews),
        "task_count": reconciliation.get("task_count", 0),
        "unmatched_existing_task_count": reconciliation.get("unmatched_existing_task_count", 0),
        "source_projection": reconciliation.get("projection", ""),
        "coverage": reconciliation.get("coverage", {}),
        "authority_rule": (
            "Google Tasks remains authoritative; duplicate groups are conservative "
            "derived suggestions requiring human review."
        ),
    }


@mcp.tool(
    title="Propose Google Task creation",
    annotations=ToolAnnotations(
        read_only_hint=False,
        destructive_hint=False,
        idempotent_hint=False,
        open_world_hint=False,
    ),
)
async def propose_create_task(
    title: str,
    due: str = "",
    notes: str = "",
    list_id: str = "@default",
    account: str = "",
) -> dict[str, Any]:
    """Create a pending, payload-bound approval request for a new Google Task. This does not create the task yet."""
    params = {"account": account} if account else None
    path = _approval_path("/tasks", params)
    body = {"title": title, "list_id": list_id, "due": due, "notes": notes}
    return await _request_approval("POST", path, body)


@mcp.tool(
    title="Propose task from todo candidate",
    annotations=ToolAnnotations(
        read_only_hint=False,
        destructive_hint=False,
        idempotent_hint=False,
        open_world_hint=False,
    ),
)
async def propose_task_from_candidate(
    candidate_id: str,
    list_id: str = "@default",
    task_type: Literal["google_tasks", "reminders"] = "google_tasks",
) -> dict[str, Any]:
    """Bind an exact todo candidate to a pending, approval-gated task creation."""
    items: list[dict[str, Any]] = []
    for candidate_category in ("reply_now", "task", "calendar", "waiting"):
        data = await _request(
            "GET",
            "/triage/todo-candidates",
            params={"category": candidate_category, "limit": 500},
        )
        if isinstance(data, dict):
            items.extend(data.get("items", []))
    candidate = next((item for item in items if item.get("candidate_id") == candidate_id), None)
    if not candidate:
        raise ValueError("todo candidate was not found in the current read model")
    evidence = candidate.get("evidence") or {}
    body = {
        "message_id": str(evidence.get("external_id") or ""),
        "message_source": str(candidate.get("source") or ""),
        "title": str(candidate.get("suggested_task_title") or candidate.get("title") or "Follow up"),
        "task_type": task_type,
        "list_id": list_id,
        "notes": str(candidate.get("notes") or ""),
        "thread_id": str(candidate.get("thread_id") or ""),
        "account": str(candidate.get("account") or ""),
    }
    return await _request_approval("POST", "/tasks/from-message", body)


@mcp.tool(
    title="Propose a person note",
    annotations=ToolAnnotations(
        read_only_hint=False,
        destructive_hint=False,
        idempotent_hint=False,
        open_world_hint=False,
    ),
)
async def propose_person_note(
    person_id: str,
    body: str,
    source: str = "manual",
    source_ref: str = "",
    confirmed: bool = True,
    expires_at: str = "",
) -> dict[str, Any]:
    """Propose a local person note; no note is saved until the exact payload is approved and executed."""
    payload = {
        "body": body,
        "source": source,
        "source_ref": source_ref,
        "confidence": 1.0 if confirmed else 0.5,
        "confirmed": confirmed,
        "expires_at": expires_at,
    }
    return await _request_approval("POST", f"/people/{person_id}/notes", payload)


@mcp.tool(
    title="Propose a relationship claim",
    annotations=ToolAnnotations(
        read_only_hint=False,
        destructive_hint=False,
        idempotent_hint=False,
        open_world_hint=False,
    ),
)
async def propose_person_relationship(
    person_id: str,
    label: str,
    context: str = "",
    confirmed: bool = True,
) -> dict[str, Any]:
    """Propose a local relationship claim; no external contact is changed."""
    payload = {
        "label": label,
        "context": context,
        "source": "manual",
        "source_ref": "",
        "confidence": 1.0 if confirmed else 0.5,
        "confirmed": confirmed,
    }
    return await _request_approval("POST", f"/people/{person_id}/relationships", payload)


@mcp.tool(
    title="Propose a person identity link",
    annotations=ToolAnnotations(
        read_only_hint=False,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=False,
    ),
)
async def propose_person_identity_link(
    canonical_person_id: str,
    canonical_name: str,
    target_id: str,
    target_name: str = "",
    target_source: str = "contacts",
    source_refs: list[dict[str, Any]] | None = None,
    confidence: float = 1.0,
) -> dict[str, Any]:
    """Propose a durable local identity link; no provider contact is changed."""
    payload = {
        "canonical_person_id": canonical_person_id,
        "canonical_name": canonical_name,
        "target_source": target_source,
        "target_id": target_id,
        "target_name": target_name,
        "confidence": max(0.0, min(float(confidence), 1.0)),
        "confirmed": True,
        "source_refs": source_refs or [],
    }
    return await _request_approval("POST", "/identity/links", payload)


@mcp.tool(
    title="Propose calendar event update",
    annotations=ToolAnnotations(
        read_only_hint=False,
        destructive_hint=False,
        idempotent_hint=False,
        open_world_hint=False,
    ),
)
async def propose_update_calendar_event(
    event_id: str,
    calendar_id: str = "primary",
    account: str = "",
    summary: str | None = None,
    start: str | None = None,
    end: str | None = None,
    location: str | None = None,
    description: str | None = None,
) -> dict[str, Any]:
    """Create a pending, payload-bound approval request to update an existing calendar event. No update happens yet."""
    body = {
        key: value
        for key, value in {
            "summary": summary,
            "start": start,
            "end": end,
            "location": location,
            "description": description,
        }.items()
        if value is not None
    }
    if not body:
        raise ValueError("At least one field must be supplied")
    path = _approval_path(
        f"/calendar/events/{event_id}",
        {"calendar_id": calendar_id, "account": account},
    )
    return await _request_approval("PUT", path, body)


@mcp.tool(
    title="List pending LifeOps actions for review",
    annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False),
)
async def pending_actions(limit: int = 50) -> dict[str, Any]:
    """Show supported pending proposals without approving or executing them.

    The exact method, path, and body are returned so a user can approve one
    unambiguously.  Unsupported guarded routes are deliberately omitted: this
    adapter must never imply that it can approve an action it cannot execute
    and verify.  The returned body is proposal data, not a credential.
    """
    bounded_limit = max(1, min(limit, 100))
    rows = await _request(
        "GET",
        "/approvals",
        params={"state": "pending", "limit": bounded_limit},
    )
    if not isinstance(rows, list):
        raise ValueError("Inbox returned an invalid approval list")

    items: list[dict[str, Any]] = []
    omitted_unsupported = 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        if str(row.get("state") or "") != "pending":
            continue
        if not _allowed_execution(row):
            omitted_unsupported += 1
            continue
        try:
            body = json.loads(row.get("body_json") or "{}")
        except (TypeError, json.JSONDecodeError) as exc:
            raise ValueError(
                f"Pending approval {row.get('request_id', '')} has invalid body data"
            ) from exc
        if not isinstance(body, dict):
            raise ValueError(
                f"Pending approval {row.get('request_id', '')} body is not an object"
            )
        items.append(
            {
                "request_id": str(row.get("request_id") or ""),
                "state": "pending",
                "created_at": str(row.get("created_at") or ""),
                "method": str(row.get("method") or ""),
                "path": str(row.get("path") or ""),
                "body": body,
                "provider": str(row.get("provider") or ""),
                "operation": str(row.get("operation") or ""),
                "approval_class": str(row.get("approval_class") or ""),
                "executor": str(row.get("executor") or ""),
                "account": str(row.get("account_ref") or ""),
                "resource": str(row.get("resource_ref") or ""),
                "item_count": int(row.get("item_count") or 0),
                "payload_hash": str(row.get("payload_hash") or ""),
                "query_hash": str(row.get("query_hash") or ""),
            }
        )
    return {
        "schema_version": "lifeops.pending_actions.v1",
        "checked_at": datetime.now(UTC).isoformat(),
        "read_only": True,
        "items": items,
        "count": len(items),
        "omitted_unsupported": omitted_unsupported,
        "limitations": [
            "Listing a proposal does not approve or execute it.",
            "Only supported task, calendar, and local person-profile actions are listed.",
        ],
    }


@mcp.tool(
    title="Approve pending LifeOps action",
    annotations=ToolAnnotations(
        read_only_hint=False,
        destructive_hint=True,
        idempotent_hint=False,
        open_world_hint=False,
    ),
)
async def approve_pending_action(request_id: str) -> dict[str, Any]:
    """Approve a pending LifeOps action. Only use after the user explicitly confirms the exact pending action in this conversation."""
    row = await _request("GET", f"/approvals/{request_id}")
    if not isinstance(row, dict) or not _allowed_execution(row):
        raise ValueError("This MCP adapter only approves task, calendar, and local person-profile actions")
    if row.get("state") != "pending":
        return row
    return await _request(
        "POST",
        f"/approvals/{request_id}/decide",
        body={"approve": True, "decided_by": "chatgpt-business-lifeops"},
    )


@mcp.tool(
    title="Execute approved LifeOps action",
    annotations=ToolAnnotations(
        read_only_hint=False,
        destructive_hint=False,
        idempotent_hint=False,
        open_world_hint=False,
    ),
)
async def execute_approved_action(request_id: str) -> dict[str, Any]:
    """Execute and read back exactly the approved action bound to request_id."""
    row = await _request("GET", f"/approvals/{request_id}")
    if not isinstance(row, dict) or not _allowed_execution(row):
        raise ValueError("This MCP adapter only executes task, calendar, and local person-profile actions")
    if row.get("state") != "approved" or not row.get("lease_id"):
        raise ValueError("Action is not approved or has no approval lease")

    body = json.loads(row.get("body_json") or "{}")
    method = str(row["method"]).upper()
    path = str(row["path"])
    # Keep the exact path/query that was approved. httpx accepts the query in the path string.
    result = await _request(
        method,
        path,
        body=body,
        extra_headers={"X-Inbox-Approval-Lease": str(row["lease_id"])},
    )
    verification = await _verify_approved_action(row, result)
    return {
        "request_id": request_id,
        "executed": True,
        "verified": verification["status"] == "verified",
        "result": result,
        "verification": verification,
    }


@mcp.tool(
    title="Verify LifeOps action read-back",
    annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False),
)
async def verify_approved_action(request_id: str) -> dict[str, Any]:
    """Re-read an approved action's target and return an evidence-backed verification receipt."""
    row = await _request("GET", f"/approvals/{request_id}")
    if not isinstance(row, dict) or not _allowed_execution(row):
        raise ValueError("This MCP adapter only verifies task, calendar, and local person-profile actions")
    if row.get("state") != "approved":
        raise ValueError("Action is not approved")
    return {
        "request_id": request_id,
        "executed": False,
        "verification": await _verify_approved_action(row),
    }


def _allowed_tools_for_profile(profile: str, tools: list[Any]) -> set[str] | None:
    """Return the tool allowlist for a named transport profile.

    ``read_only`` is derived from the MCP annotations and therefore fails
    closed when a tool omits its read-only hint. ``worker`` remains a smaller
    fixed contract for untrusted local workers.
    """
    if profile not in {"full", "read_only", "worker"}:
        raise ValueError("LIFEOPS_MCP_PROFILE must be full, read_only, or worker")
    if profile == "full":
        return None
    if profile == "read_only":
        # Fail closed from the tool annotation: an omitted or false hint is
        # not enough to cross the read-only boundary.
        return {
            tool.name
            for tool in tools
            if getattr(getattr(tool, "annotations", None), "read_only_hint", False)
            is True
        }
    return {"evidence_packet", "system_audit"}


def _apply_mcp_profile() -> None:
    profile = os.environ.get("LIFEOPS_MCP_PROFILE", "full").strip().lower()
    tools = list(mcp._tool_manager.list_tools())
    allowed = _allowed_tools_for_profile(profile, tools)
    if allowed is None:
        return

    for tool in tools:  # FastMCP has no public bulk-filter API.
        if tool.name not in allowed:
            mcp.remove_tool(tool.name)


def _server_discovery_response(request_id: Any) -> dict[str, Any]:
    """Return the sessionless discovery card used by newer MCP clients.

    FastMCP 1.27 still serves the legacy initialize/tools-list lifecycle, while
    the Secure MCP Tunnel validator probes ``server/discover`` first. Keep the
    advertised version honest: this adapter remains a 2025-06-18 server and
    does not claim support for the newer per-request lifecycle.
    """
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "result": {
            "resultType": "complete",
            "supportedVersions": ["2025-06-18"],
            "capabilities": {"tools": {}},
            "_meta": {
                "io.modelcontextprotocol/serverInfo": {
                    "name": "LifeOps",
                    "version": "1.27.0",
                }
            },
            "instructions": (
                "Use read-only search, context, triage, contacts, calendar, tasks, "
                "Drive, Sheets, and provenance tools; source systems remain authoritative."
            ),
            "ttlMs": 300000,
            "cacheScope": "private",
        },
    }


class _DiscoveryAwareApp:
    """Intercept the tunnel validator's discovery probe before FastMCP."""

    def __init__(self, downstream: Any) -> None:
        self._downstream = downstream

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope.get("type") != "http" or scope.get("path") != "/mcp":
            await self._downstream(scope, receive, send)
            return

        body = b""
        while True:
            message = await receive()
            body += message.get("body", b"")
            if not message.get("more_body", False):
                break
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            payload = None

        if isinstance(payload, dict) and payload.get("method") == "server/discover":
            response = json.dumps(
                _server_discovery_response(payload.get("id")),
                separators=(",", ":"),
            ).encode("utf-8")
            await send(
                {
                    "type": "http.response.start",
                    "status": 200,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"content-length", str(len(response)).encode("ascii")),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": response})
            return

        sent = False

        async def replay() -> dict[str, Any]:
            nonlocal sent
            if sent:
                return {"type": "http.disconnect"}
            sent = True
            return {"type": "http.request", "body": body, "more_body": False}

        await self._downstream(scope, replay, send)


async def _run_streamable_http() -> None:
    import uvicorn

    app = _DiscoveryAwareApp(mcp.streamable_http_app())
    config = uvicorn.Config(
        app,
        host=mcp.settings.host,
        port=mcp.settings.port,
        log_level=mcp.settings.log_level.lower(),
    )
    server = uvicorn.Server(config)
    await server.serve()


if __name__ == "__main__":
    transport = os.environ.get("LIFEOPS_MCP_TRANSPORT", "streamable-http")
    if transport not in {"stdio", "streamable-http"}:
        raise ValueError("LIFEOPS_MCP_TRANSPORT must be stdio or streamable-http")
    _apply_mcp_profile()
    if transport == "streamable-http":
        import anyio

        anyio.run(_run_streamable_http)
    else:
        mcp.run(transport=transport)
