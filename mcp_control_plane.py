"""Ingest-only Inbox MCP control plane (PR-1 + PR-2B Bridge intake).

Bind: 127.0.0.1:8002
Frozen tools: resolve, capture, submit_work, get_work, cancel_work,
verify_work, run_shortcut.

This surface can accept and capture work and forward submit_work to Bridge
`ingest`. It cannot mint authority or execute workers, providers, or
Shortcuts. confirm=true is intent, not a lease. Bridge intake ≠ spawn.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path
from secrets import compare_digest
from typing import Any

from starlette.applications import Starlette
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from approval_store import ApprovalStore
from bridge_work_client import (
    BridgeIngestError,
    BridgeWorkClient,
    BridgeWorkClientProtocol,
    build_submit_work_envelope,
)
from event_store import CaptureEvent, EventStore, EventStoreConflict, EventStoreValidationError

CONTROL_PLANE_HOST = "127.0.0.1"
CONTROL_PLANE_PORT = 8002
CONTROL_PLANE_TOKEN_ENV = "INBOX_CONTROL_PLANE_TOKEN"
SPAWN_ENV = "INBOX_CONTROL_PLANE_SPAWN"
TRUST_LOOPBACK_ENV = "INBOX_CONTROL_PLANE_TRUST_LOOPBACK"
CONTROL_PLANE_TOOL_NAMES = (
    "resolve",
    "capture",
    "submit_work",
    "get_work",
    "cancel_work",
    "verify_work",
    "run_shortcut",
)
AUTHORITY_TYPES = frozenset(
    {
        "inbox_event",
        "lifeops_packet",
        "github",
        "google_drive",
        "research_claim",
    }
)
MODEL_SUPPLIED_AUTHORITY_KEYS = frozenset(
    {
        "lease",
        "lease_token",
        "lease_id",
        "capability",
        "capability_token",
        "capability_id",
        "approval_digest",
        "approval_credential",
        "approval_token",
        "fencing_token",
        "worker_token",
        "worker",
        "spawn",
        "shortcut_name",
        "stored_name",
    }
)
EVIDENCE_REF_KEYS = frozenset(
    {
        "ref",
        "authority_type",
        "authority_id",
        "source_revision",
        "as_of",
        "digest",
        "span",
    }
)
SPAN_KEYS = frozenset({"path", "start", "end", "locator"})

BASE_DIR = Path(__file__).parent
DEFAULT_SHORTCUT_REGISTRY = BASE_DIR / "config" / "shortcut_registry.example.json"


def spawn_flag() -> int:
    raw = os.getenv(SPAWN_ENV, "0").strip() or "0"
    return 1 if raw in {"1", "true", "TRUE", "yes"} else 0


def trust_loopback() -> bool:
    """ChatGPT Secure MCP Tunnel cannot paste our Bearer into Apps.

    OpenAI authenticates the tunnel. Requests then arrive on 127.0.0.1.
    Direct TestClient/curl still need the Bearer unless this flag is on.
    """
    raw = os.getenv(TRUST_LOOPBACK_ENV, "0").strip() or "0"
    return raw in {"1", "true", "TRUE", "yes"}


def _now_work_id() -> str:
    return f"wrk_{uuid.uuid4().hex}"


def _collect_mapping_keys(value: Any) -> set[str]:
    keys: set[str] = set()
    if isinstance(value, dict):
        for key, inner in value.items():
            keys.add(str(key))
            keys.update(_collect_mapping_keys(inner))
    elif isinstance(value, list):
        for item in value:
            keys.update(_collect_mapping_keys(item))
    return keys


def _denied(reason: str, **extra: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "result": "DENIED",
        "reason": reason,
        "executed": False,
        "spawn_flag": spawn_flag(),
    }
    payload.update(extra)
    return payload


def _intake(work_id: str, **extra: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "result": "accepted_for_intake",
        "work_id": work_id,
        "executed": False,
        "spawn_flag": spawn_flag(),
    }
    payload.update(extra)
    return payload


def load_shortcut_registry(path: Path | None = None) -> dict[str, Any]:
    registry_path = path or Path(os.getenv("INBOX_SHORTCUT_REGISTRY", DEFAULT_SHORTCUT_REGISTRY))
    if not registry_path.is_file():
        return {"entries": {}, "unknown_id": "DENIED"}
    raw = json.loads(registry_path.read_text(encoding="utf-8"))
    entries = raw.get("entries") if isinstance(raw, dict) else {}
    if not isinstance(entries, dict):
        entries = {}
    return {"entries": entries, "unknown_id": "DENIED"}


def server_discovery_response(request_id: Any) -> dict[str, Any]:
    """Sessionless card for ChatGPT Secure MCP Tunnel `server/discover`.

    FastMCP still serves initialize/tools/list. The tunnel validator probes
    discover first and does not send our bearer (connector headers override
    tunnel extra_headers). Discover advertises identity only; it cannot execute.
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
                    "name": "Inbox Control Plane",
                    "version": "1.27.0",
                }
            },
            "instructions": (
                "Ingest-only control plane. Propose work with submit_work. "
                "confirm=true is not authority. This surface does not spawn "
                "workers, send mail, or run Shortcuts."
            ),
            "ttlMs": 300000,
            "cacheScope": "private",
        },
    }


class FailClosedAuthMiddleware(BaseHTTPMiddleware):
    """Bearer auth that denies when the control-plane token is unset."""

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if path == "/health" or path.startswith("/.well-known/"):
            return await call_next(request)
        if request.method == "POST" and path.rstrip("/") == "/mcp":
            try:
                payload = json.loads((await request.body()).decode("utf-8") or "null")
            except (UnicodeDecodeError, json.JSONDecodeError):
                payload = None
            if isinstance(payload, dict) and payload.get("method") == "server/discover":
                return JSONResponse(server_discovery_response(payload.get("id")))
        token = os.getenv(CONTROL_PLANE_TOKEN_ENV, "").strip()
        if not token:
            return JSONResponse(
                {"detail": "Unauthorized"},
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )
        client_host = request.client.host if request.client else ""
        if trust_loopback() and client_host in {"127.0.0.1", "::1"}:
            return await call_next(request)
        auth_header = request.headers.get("authorization", "")
        provided = ""
        if auth_header.lower().startswith("bearer "):
            provided = auth_header[7:].strip()
        elif request.headers.get("x-api-key"):
            provided = request.headers.get("x-api-key", "").strip()
        if not provided or not compare_digest(provided, token):
            return JSONResponse(
                {"detail": "Unauthorized"},
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )
        return await call_next(request)


class ControlPlane:
    """Ingest-only tool handlers. Execution is unconditionally disabled."""

    def __init__(
        self,
        *,
        event_store: EventStore,
        approval_store: ApprovalStore,
        shortcut_registry: dict[str, Any] | None = None,
        bridge_client: BridgeWorkClientProtocol | None = None,
    ) -> None:
        self.event_store = event_store
        self.approval_store = approval_store
        self.shortcut_registry = shortcut_registry or load_shortcut_registry()
        # Default: real Bridge ingest client (fail-closed when env unset).
        # Tests inject a stub; never a spawn/orchestrator client.
        self.bridge_client: BridgeWorkClientProtocol = bridge_client or BridgeWorkClient.from_env()
        self.work: dict[str, dict[str, Any]] = {}
        self.execution_log: list[dict[str, Any]] = []

    def _reject_model_authority(self, payload: Any) -> dict[str, Any] | None:
        keys = _collect_mapping_keys(payload)
        hit = sorted(keys & MODEL_SUPPLIED_AUTHORITY_KEYS)
        if hit:
            return _denied("model_supplied_authority", keys=hit)
        return None

    def _lookup_unused_approval(self, operation: str) -> dict[str, Any] | None:
        for row in self.approval_store.list_requests(state="approved", limit=200):
            if row.get("operation") != operation:
                continue
            if not str(row.get("lease_id") or "").strip():
                continue
            return row
        return None

    def _record_intake(
        self,
        *,
        operation: str,
        body: dict[str, Any],
        resource_ref: str,
        work_id: str | None = None,
        bridge: dict[str, Any] | None = None,
    ) -> str:
        work_id = work_id or _now_work_id()
        created = self.approval_store.create_request(
            method="MCP",
            path=f"/control-plane/{operation}",
            body=body,
            provider="inbox.control_plane",
            operation=operation,
            approval_class="intake",
            executor="none",
            account_ref="",
            resource_ref=resource_ref,
            item_count=1,
            payload_hash="",
            query_hash="",
        )
        record = {
            "work_id": work_id,
            "operation": operation,
            "state": "accepted_for_intake",
            "executed": False,
            "approval_request_id": created["request_id"],
            "server_authority": self._lookup_unused_approval(operation),
            "body": body,
        }
        if bridge:
            record["bridge"] = bridge
        self.work[work_id] = record
        self.approval_store.log_event(
            "control_plane_intake",
            request_id=created["request_id"],
            operation=operation,
            result="accepted_for_intake",
            detail={
                "work_id": work_id,
                "executed": False,
                "spawn_flag": spawn_flag(),
                "bridge": bridge,
            },
        )
        return work_id

    def _validate_evidence_refs(self, evidence_refs: Any) -> str | None:
        if not isinstance(evidence_refs, list) or not evidence_refs:
            return "missing_evidence_refs"
        for item in evidence_refs:
            if not isinstance(item, dict):
                return "invalid_evidence_ref"
            extra = set(item) - EVIDENCE_REF_KEYS
            if extra:
                return "invalid_evidence_ref"
            ref = str(item.get("ref") or "").strip()
            authority_type = str(item.get("authority_type") or "").strip()
            authority_id = str(item.get("authority_id") or "").strip()
            if not ref or not authority_id:
                return "invalid_evidence_ref"
            if authority_type not in AUTHORITY_TYPES:
                return "invalid_evidence_ref"
            if authority_type == "research_claim" and not str(item.get("digest") or "").strip():
                return "research_claim_requires_manifest_digest"
            span = item.get("span")
            if span is not None and (not isinstance(span, dict) or (set(span) - SPAN_KEYS)):
                return "invalid_evidence_ref"
        return None

    def resolve(self, worlds: list[str] | None = None) -> dict[str, Any]:
        requested = list(worlds or ["control_plane", "capture", "approvals"])
        probes = {
            "control_plane": {
                "status": "ok",
                "source": "local",
                "bind": f"{CONTROL_PLANE_HOST}:{CONTROL_PLANE_PORT}",
            },
            "capture": {
                "status": "ok" if self.event_store is not None else "unavailable",
                "source": "event_store",
            },
            "approvals": {
                "status": "ok" if self.approval_store is not None else "unavailable",
                "source": "approval_store",
            },
            "shortcut_registry": {
                "status": "ok" if self.shortcut_registry.get("entries") else "unavailable",
                "source": "local_registry",
            },
            "bridge": {"status": "unavailable", "source": "not_probed"},
        }
        results = []
        required_failed = False
        for world in requested:
            name = str(world or "").strip()
            if name in probes:
                row = {"world": name, **probes[name]}
            else:
                row = {"world": name, "status": "unavailable", "source": "unknown_world"}
            if row["status"] != "ok":
                required_failed = True
            results.append(row)
        return {
            "result": "DENIED" if required_failed else "ok",
            "worlds": results,
            "missing_filled_from_memory": False,
            "executed": False,
            "spawn_flag": spawn_flag(),
        }

    def capture(self, **observation: Any) -> dict[str, Any]:
        denied = self._reject_model_authority(observation)
        if denied:
            return denied
        try:
            event = CaptureEvent.create(
                source=observation.get("source", ""),
                source_object_id=observation.get("source_object_id", ""),
                observed_at=observation.get("observed_at", ""),
                occurred_at=observation.get("occurred_at", ""),
                event_type=observation.get("event_type", "manual.capture"),
                payload=observation.get("payload"),
                provenance=observation.get("provenance"),
                event_id=observation.get("event_id") or None,
            )
            stored, result = self.event_store.append(event)
        except EventStoreConflict as exc:
            return {"result": "error", "error": str(exc), "event": None, "executed": False}
        except EventStoreValidationError as exc:
            return {"result": "error", "error": str(exc), "event": None, "executed": False}
        return {"result": result, "event": stored.to_dict(), "executed": False}

    def submit_work(
        self,
        evidence_refs: list[dict[str, Any]] | None = None,
        *,
        confirm: bool = False,
        summary: str = "",
        **kwargs: Any,
    ) -> dict[str, Any]:
        payload = {
            "evidence_refs": evidence_refs,
            "confirm": confirm,
            "summary": summary,
            **kwargs,
        }
        denied = self._reject_model_authority(payload)
        if denied:
            self.approval_store.log_event(
                "control_plane_denied",
                operation="submit_work",
                result="DENIED",
                detail={"reason": denied["reason"], "confirm": confirm},
            )
            return denied
        invalid = self._validate_evidence_refs(evidence_refs)
        if invalid:
            return _denied(invalid)

        # Allocate id before Bridge so the EventEnvelope external_id is stable.
        # Bridge reject → no local work record and no executor invocation.
        work_id = _now_work_id()
        envelope = build_submit_work_envelope(
            work_id=work_id,
            summary=summary,
            evidence_refs=list(evidence_refs or []),
            occurred_at=datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        )
        try:
            receipt = self.bridge_client.ingest_event(envelope)
        except BridgeIngestError as exc:
            self.approval_store.log_event(
                "control_plane_denied",
                operation="submit_work",
                result="DENIED",
                detail={
                    "reason": str(exc) or "bridge_rejected",
                    "confirm": confirm,
                    "executed": False,
                },
            )
            return _denied(str(exc) or "bridge_rejected", confirm_is_authority=False)

        bridge_meta = {
            "result_id": receipt.result_id,
            "work_packet_id": receipt.work_packet_id,
            "intake_path": receipt.intake_path,
            "status": receipt.status,
            "summary": receipt.summary,
        }
        self._record_intake(
            operation="submit_work",
            body={
                "evidence_refs": evidence_refs,
                "confirm": confirm,
                "summary": summary,
            },
            resource_ref="submit_work",
            work_id=work_id,
            bridge=bridge_meta,
        )
        return _intake(
            work_id,
            confirm_is_authority=False,
            server_authority_present=bool(self.work[work_id]["server_authority"]),
            bridge_intake_path=receipt.intake_path,
            bridge_result_id=receipt.result_id,
            bridge_work_packet_id=receipt.work_packet_id,
        )

    def get_work(self, work_id: str = "") -> dict[str, Any]:
        if work_id:
            record = self.work.get(work_id)
            if record is None:
                return _denied("unknown_work")
            return {
                "result": "ok",
                "work": {k: v for k, v in record.items() if k != "body"},
                "executed": False,
                "spawn_flag": spawn_flag(),
            }
        return {
            "result": "ok",
            "work": [{k: v for k, v in row.items() if k != "body"} for row in self.work.values()],
            "executed": False,
            "spawn_flag": spawn_flag(),
        }

    def cancel_work(self, work_id: str, *, confirm: bool = False, **kwargs: Any) -> dict[str, Any]:
        payload = {"work_id": work_id, "confirm": confirm, **kwargs}
        denied = self._reject_model_authority(payload)
        if denied:
            return denied
        if work_id not in self.work:
            return _denied("unknown_work")
        intake_id = self._record_intake(
            operation="cancel_work",
            body={"work_id": work_id, "confirm": confirm},
            resource_ref=work_id,
        )
        self.work[work_id]["state"] = "cancel_accepted_for_intake"
        return _intake(intake_id, target_work_id=work_id)

    def verify_work(
        self, work_id: str = "", *, confirm: bool = False, **kwargs: Any
    ) -> dict[str, Any]:
        payload = {"work_id": work_id, "confirm": confirm, **kwargs}
        denied = self._reject_model_authority(payload)
        if denied:
            return denied
        if work_id and work_id not in self.work:
            return _denied("unknown_work")
        intake_id = self._record_intake(
            operation="verify_work",
            body={"work_id": work_id, "confirm": confirm},
            resource_ref=work_id or "verify_work",
        )
        return _intake(intake_id, target_work_id=work_id or None, verifier_executed=False)

    def run_shortcut(
        self,
        shortcut_id: str,
        *,
        confirm: bool = False,
        shortcut_input: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        payload = {
            "shortcut_id": shortcut_id,
            "confirm": confirm,
            "shortcut_input": shortcut_input or {},
            **kwargs,
        }
        denied = self._reject_model_authority(payload)
        if denied:
            return denied
        entries = self.shortcut_registry.get("entries") or {}
        entry = entries.get(str(shortcut_id or "").strip())
        if not isinstance(entry, dict):
            return _denied("unknown_shortcut_id")
        intake_id = self._record_intake(
            operation="run_shortcut",
            body={"shortcut_id": shortcut_id, "confirm": confirm},
            resource_ref=shortcut_id,
        )
        return _intake(
            intake_id,
            shortcut_id=shortcut_id,
            stored_name_returned=False,
            argv_executed=False,
        )


def build_control_plane_mcp(plane: ControlPlane):
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("The 'mcp' package is required. Install with: uv sync") from exc

    mcp = FastMCP(
        "Inbox Control Plane",
        stateless_http=True,
        json_response=True,
        host=CONTROL_PLANE_HOST,
        port=CONTROL_PLANE_PORT,
        streamable_http_path="/mcp",
    )

    @mcp.tool()
    async def resolve(worlds: list[str] | None = None) -> dict:
        """Per-world health. Missing required worlds fail closed. Never fills from memory."""
        return plane.resolve(worlds)

    @mcp.tool()
    async def capture(
        source: str,
        source_object_id: str,
        observed_at: str,
        occurred_at: str,
        payload: dict,
        provenance: dict,
        event_type: str = "manual.capture",
        event_id: str = "",
    ) -> dict:
        """Append one observation via EventStore. Local evidence only. Not a grant."""
        return plane.capture(
            source=source,
            source_object_id=source_object_id,
            observed_at=observed_at,
            occurred_at=occurred_at,
            payload=payload,
            provenance=provenance,
            event_type=event_type,
            event_id=event_id,
        )

    @mcp.tool()
    async def submit_work(
        evidence_refs: list[dict],
        confirm: bool = False,
        summary: str = "",
    ) -> dict:
        """Accept work for intake. confirm is not authority. Never executes."""
        return plane.submit_work(evidence_refs, confirm=confirm, summary=summary)

    @mcp.tool()
    async def get_work(work_id: str = "") -> dict:
        """Read accepted intake records. Does not execute workers."""
        return plane.get_work(work_id)

    @mcp.tool()
    async def cancel_work(work_id: str, confirm: bool = False) -> dict:
        """Record a cancel request for intake. Does not kill sessions or workers."""
        return plane.cancel_work(work_id, confirm=confirm)

    @mcp.tool()
    async def verify_work(work_id: str = "", confirm: bool = False) -> dict:
        """Queue bounded verification. Does not run verifier argv or mint receipts."""
        return plane.verify_work(work_id, confirm=confirm)

    @mcp.tool()
    async def run_shortcut(
        shortcut_id: str,
        confirm: bool = False,
        shortcut_input: dict | None = None,
    ) -> dict:
        """Accept an opaque shortcut_id for intake. Never runs Shortcuts."""
        return plane.run_shortcut(shortcut_id, confirm=confirm, shortcut_input=shortcut_input)

    return mcp


def make_control_plane(
    *,
    event_db: Path | None = None,
    approval_db: Path | None = None,
    shortcut_registry: dict[str, Any] | None = None,
    bridge_client: BridgeWorkClientProtocol | None = None,
) -> ControlPlane:
    return ControlPlane(
        event_store=EventStore(event_db),
        approval_store=ApprovalStore(approval_db),
        shortcut_registry=shortcut_registry,
        bridge_client=bridge_client,
    )


def make_control_plane_app(plane: ControlPlane | None = None) -> Starlette:
    plane = plane or make_control_plane()
    mcp = build_control_plane_mcp(plane)

    async def health(_request: Request) -> JSONResponse:
        return JSONResponse(
            {
                "status": "ok",
                "mcp_path": "/mcp",
                "bind": f"{CONTROL_PLANE_HOST}:{CONTROL_PLANE_PORT}",
                "spawn_flag": spawn_flag(),
                "execution_enabled": False,
                "auth_fail_closed": True,
                "trust_loopback": trust_loopback(),
                "tools": list(CONTROL_PLANE_TOOL_NAMES),
            }
        )

    # Native FastMCP Streamable HTTP app owns session_manager.run() lifespan.
    # Do not nest that app under a /mcp prefix — that double-prefixes the path
    # and drops the session-manager lifespan.
    mcp.custom_route("/health", methods=["GET"])(health)
    # Do not serve RFC 9728 here. LifeOps 404s these paths and ChatGPT
    # Auth=None create succeeds. A 200 PRMD with bearer_methods_supported
    # makes Create Connector fail even when discover returns 200.
    app = mcp.streamable_http_app()
    app.add_middleware(FailClosedAuthMiddleware)
    return app


def main() -> None:
    import uvicorn

    uvicorn.run(
        make_control_plane_app(),
        host=CONTROL_PLANE_HOST,
        port=CONTROL_PLANE_PORT,
        log_level="info",
    )


if __name__ == "__main__":
    main()
