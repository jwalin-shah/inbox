#!/usr/bin/env python3
"""Verify the bounded LifeOps MCP read surface without printing personal data."""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

PROTOCOL_VERSION = "2025-06-18"
DEFAULT_URL = "http://127.0.0.1:9850/mcp"
REQUIRED_READ_TOOLS = (
    "life_context",
    "search",
    "fetch",
    "system_audit",
    "evidence_packet",
    "task_duplicate_review",
    "read_triage_receipt",
    "list_triage_receipts",
    "pending_actions",
)
REQUIRED_CONTEXT_SOURCES = (
    "google_account_inventory",
    "triage",
    "unified_contacts",
    "identity_links",
    "calendar",
    "tasks",
    "projects",
    "master_ops",
    "lifeops_sheet",
    "embedding_index",
    "google_drive",
    "google_docs",
    "property_evidence",
)


class VerificationError(RuntimeError):
    """Raised when the live MCP surface fails a required invariant."""


@dataclass
class RpcClient:
    url: str
    auth_token: str = ""
    timeout: float = 90.0
    session_id: str = ""
    next_id: int = 1

    def request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        request_id = self.next_id
        self.next_id += 1
        payload: dict[str, Any] = {"jsonrpc": "2.0", "id": request_id, "method": method}
        if params is not None:
            payload["params"] = params
        response = self._post(payload)
        if response.get("jsonrpc") != "2.0" or response.get("id") != request_id:
            raise VerificationError(f"invalid JSON-RPC response for {method}")
        if "error" in response:
            error = response.get("error")
            code = error.get("code") if isinstance(error, dict) else "unknown"
            raise VerificationError(f"MCP {method} returned error {code}")
        result = response.get("result")
        if not isinstance(result, dict):
            raise VerificationError(f"MCP {method} returned no object result")
        return result

    def notification(self, method: str) -> None:
        self._post({"jsonrpc": "2.0", "method": method}, expect_response=False)

    def _post(self, payload: dict[str, Any], *, expect_response: bool = True) -> dict[str, Any]:
        headers = {
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
        }
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id
        if self.auth_token:
            headers["Authorization"] = f"Bearer {self.auth_token}"
        request = Request(
            self.url,
            data=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                status = response.status
                body = response.read()
                session_id = response.headers.get("Mcp-Session-Id")
                if session_id:
                    self.session_id = session_id
        except HTTPError as exc:
            raise VerificationError(f"MCP HTTP {exc.code}") from exc
        except URLError as exc:
            raise VerificationError(f"MCP connection failed: {exc.reason}") from exc
        except TimeoutError as exc:
            raise VerificationError(f"MCP request timed out after {self.timeout:g}s") from exc
        if not expect_response:
            if status not in {200, 202}:
                raise VerificationError(f"MCP notification returned HTTP {status}")
            return {}
        if status != 200:
            raise VerificationError(f"MCP request returned HTTP {status}")
        return _decode_json_response(body)


def _decode_json_response(body: bytes) -> dict[str, Any]:
    text = body.decode("utf-8", errors="strict").strip()
    if not text:
        raise VerificationError("MCP returned an empty response")
    if text.startswith("{"):
        try:
            value = json.loads(text)
        except json.JSONDecodeError as exc:
            raise VerificationError("MCP returned invalid JSON") from exc
        if not isinstance(value, dict):
            raise VerificationError("MCP returned a non-object JSON value")
        return value
    data_lines = [line[5:] for line in text.splitlines() if line.startswith("data:")]
    if not data_lines:
        raise VerificationError("MCP returned neither JSON nor an SSE data event")
    try:
        value = json.loads("\n".join(data_lines).strip())
    except json.JSONDecodeError as exc:
        raise VerificationError("MCP returned invalid SSE JSON") from exc
    if not isinstance(value, dict):
        raise VerificationError("MCP SSE returned a non-object JSON value")
    return value


def _read_only_annotation(tool: dict[str, Any]) -> bool:
    annotations = tool.get("annotations")
    if not isinstance(annotations, dict):
        return False
    return annotations.get("read_only_hint") is True or annotations.get("readOnlyHint") is True


def summarize_read_surface(
    client: RpcClient,
    *,
    account: str,
    consumer: str = "other",
) -> dict[str, Any]:
    if not account.strip():
        raise VerificationError("an account is required; refusing an unscoped verification call")
    initialized = client.request(
        "initialize",
        {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "lifeops-read-surface-verifier", "version": "1"},
        },
    )
    if initialized.get("protocolVersion") != PROTOCOL_VERSION:
        raise VerificationError("MCP negotiated an unexpected protocol version")
    server_info = initialized.get("serverInfo")
    if not isinstance(server_info, dict):
        raise VerificationError("MCP initialize response omitted serverInfo")
    client.notification("notifications/initialized")
    tools_result = client.request("tools/list", {})
    tools = tools_result.get("tools")
    if not isinstance(tools, list):
        raise VerificationError("MCP tools/list response omitted tools")
    tool_by_name = {
        tool.get("name"): tool
        for tool in tools
        if isinstance(tool, dict) and isinstance(tool.get("name"), str)
    }
    missing = [name for name in REQUIRED_READ_TOOLS if name not in tool_by_name]
    if missing:
        raise VerificationError(f"required LifeOps tools missing: {','.join(missing)}")
    read_only = {
        name: _read_only_annotation(tool_by_name[name]) for name in REQUIRED_READ_TOOLS
    }
    unmarked = [name for name, marked in read_only.items() if not marked]
    if unmarked:
        raise VerificationError(f"required tools are not marked read-only: {','.join(unmarked)}")
    packet = client.request(
        "tools/call",
        {
            "name": "evidence_packet",
            "arguments": {
                "account": account,
                "consumer": consumer,
                "purpose": "runtime verification",
                "sections": ["attention"],
                "limit": 1,
                "calendar_days": 1,
            },
        },
    )
    packet_value = _structured_content(packet)
    if packet_value.get("schema_version") != "lifeops.evidence_packet.v1":
        raise VerificationError("evidence packet schema is not lifeops.evidence_packet.v1")
    if packet_value.get("read_only") is not True:
        raise VerificationError("evidence packet did not prove read_only=true")
    scope = packet_value.get("scope")
    if not isinstance(scope, dict):
        raise VerificationError("evidence packet omitted scope")
    forbidden = ("provider_writes", "worker_control", "secret_access", "raw_event_mutation")
    unsafe_scope = [name for name in forbidden if scope.get(name) is not False]
    if unsafe_scope:
        raise VerificationError(f"evidence packet scope is not read-only: {','.join(unsafe_scope)}")
    sections = packet_value.get("sections")
    if not isinstance(sections, dict):
        raise VerificationError("evidence packet omitted sections")
    context_result = client.request(
        "tools/call",
        {
            "name": "life_context",
            "arguments": {
                "account": account,
                "limit": 1,
                "section_limit": 1,
                "calendar_days": 1,
                "use_model": False,
            },
        },
    )
    context = _structured_content(context_result)
    if context.get("schema_version") != "lifeops.context.v1":
        raise VerificationError("life_context schema is not lifeops.context.v1")
    if context.get("read_only") is not True:
        raise VerificationError("life_context did not prove read_only=true")
    context_scope = context.get("scope")
    if not isinstance(context_scope, dict):
        raise VerificationError("life_context omitted scope")
    if context_scope.get("account") != account:
        raise VerificationError("life_context did not preserve the requested account scope")
    if context_scope.get("provider_account_scope") != "selected_account":
        raise VerificationError("life_context did not use selected_account scope")
    provider_accounts = context_scope.get("provider_accounts")
    if not isinstance(provider_accounts, list) or account not in provider_accounts:
        raise VerificationError("life_context omitted the requested provider account")
    source_health = context.get("source_health")
    if not isinstance(source_health, dict):
        raise VerificationError("life_context omitted source_health")
    missing_sources = [name for name in REQUIRED_CONTEXT_SOURCES if name not in source_health]
    if missing_sources:
        raise VerificationError(
            "life_context omitted source-health entries: " + ",".join(missing_sources)
        )
    provenance = context.get("provenance")
    if not isinstance(provenance, dict) or not isinstance(provenance.get("references"), list):
        raise VerificationError("life_context omitted provenance references")
    triage_result = client.request(
        "tools/call",
        {
            "name": "triage_all",
            "arguments": {
                "account": account,
                "limit": 1,
                "use_model": False,
            },
        },
    )
    triage_value = _structured_content(triage_result)
    triage_receipt = triage_value.get("read_receipt")
    if not isinstance(triage_receipt, dict):
        raise VerificationError("triage_all omitted read_receipt")
    run_id = str(triage_receipt.get("run_id") or "").strip()
    if not run_id or triage_receipt.get("schema_version") != "lifeops.triage_receipt.v1":
        raise VerificationError("triage_all returned an invalid read receipt")
    persistence = triage_receipt.get("persistence")
    if not isinstance(persistence, dict) or persistence.get("status") != "stored":
        raise VerificationError("triage_all did not prove durable receipt storage")
    receipt_result = client.request(
        "tools/call",
        {"name": "read_triage_receipt", "arguments": {"run_id": run_id}},
    )
    stored_receipt = _structured_content(receipt_result)
    if stored_receipt.get("schema_version") != "lifeops.triage_receipt_lookup.v1":
        raise VerificationError("read_triage_receipt returned an unexpected schema")
    if stored_receipt.get("read_only") is not True:
        raise VerificationError("read_triage_receipt did not prove read_only=true")
    stored_value = stored_receipt.get("receipt")
    if not isinstance(stored_value, dict) or stored_value.get("run_id") != run_id:
        raise VerificationError("read_triage_receipt did not return the requested run")
    list_result = client.request(
        "tools/call",
        {"name": "list_triage_receipts", "arguments": {"limit": 1}},
    )
    receipt_list = _structured_content(list_result)
    if receipt_list.get("schema_version") != "lifeops.triage_receipt_list.v1":
        raise VerificationError("list_triage_receipts returned an unexpected schema")
    listed = receipt_list.get("receipts")
    if not isinstance(listed, list) or not any(
        isinstance(value, dict) and value.get("run_id") == run_id for value in listed
    ):
        raise VerificationError("list_triage_receipts omitted the current run")
    return {
        "protocol_version": initialized["protocolVersion"],
        "server": {"name": server_info.get("name"), "version": server_info.get("version")},
        "tool_count": len(tools),
        "required_tools": {name: name in tool_by_name for name in REQUIRED_READ_TOOLS},
        "required_read_only": read_only,
        "evidence_packet": {
            "schema_version": packet_value["schema_version"],
            "read_only": packet_value["read_only"],
            "account_scope_mode": scope.get("account_scope_mode"),
            "provider_writes": scope.get("provider_writes"),
            "worker_control": scope.get("worker_control"),
            "secret_access": scope.get("secret_access"),
            "raw_event_mutation": scope.get("raw_event_mutation"),
            "section_names": sorted(name for name in sections if isinstance(name, str)),
        },
        "life_context": {
            "schema_version": context["schema_version"],
            "read_only": context["read_only"],
            "scope": {
                "account": context_scope["account"],
                "provider_account_scope": context_scope["provider_account_scope"],
                "provider_accounts": provider_accounts,
            },
            "source_status": {
                name: (value.get("status") if isinstance(value, dict) else None)
                for name, value in source_health.items()
                if name in REQUIRED_CONTEXT_SOURCES
            },
            "provenance_reference_count": provenance.get("reference_count", 0),
            "limitations": context.get("limitations", []),
        },
        "triage_receipt": {
            "run_id": run_id,
            "durable": True,
            "read_back": True,
            "listed": True,
        },
    }


def _structured_content(result: dict[str, Any]) -> dict[str, Any]:
    structured = result.get("structuredContent")
    if isinstance(structured, dict):
        return structured
    content = result.get("content")
    if isinstance(content, list):
        for item in content:
            if not isinstance(item, dict) or item.get("type") != "text":
                continue
            text = item.get("text")
            if not isinstance(text, str):
                continue
            try:
                value = json.loads(text)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                return value
    raise VerificationError("evidence_packet returned no structured object")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=os.environ.get("LIFEOPS_MCP_URL", DEFAULT_URL))
    parser.add_argument("--account", default=os.environ.get("LIFEOPS_VERIFY_ACCOUNT", ""))
    parser.add_argument("--auth-token", default=os.environ.get("LIFEOPS_MCP_AUTH_TOKEN", ""))
    parser.add_argument("--timeout", type=float, default=90.0)
    args = parser.parse_args(argv)
    try:
        summary = summarize_read_surface(
            RpcClient(args.url, auth_token=args.auth_token, timeout=args.timeout), account=args.account
        )
    except VerificationError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
