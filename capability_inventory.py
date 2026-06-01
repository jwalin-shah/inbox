"""Read-only capability inventory for Inbox providers and agent surfaces.

The inventory is policy metadata. Building it must not call providers, inspect
credential files, or execute connector binaries.
"""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
from typing import Any

from connector_registry import CONNECTORS, ConnectorDefinition
from tools_registry import _EMPTY, TOOLS, Param, Tool

SCHEMA_VERSION = "inbox.capability_inventory.v1"
MUTATING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _domain_for_path(path: str) -> str:
    first = path.strip("/").split("/", 1)[0] if path else ""
    return {
        "messages": "mail_messages",
        "gmail": "mail",
        "calendar": "calendar",
        "reminders": "tasks",
        "tasks": "tasks",
        "scheduled": "scheduler",
        "followups": "scheduler",
        "drive": "files",
        "sheets": "spreadsheets",
        "docs": "documents",
        "notes": "notes",
        "connectors": "connectors",
        "status": "system",
        "providers": "system",
        "health": "system",
        "capture": "capture",
        "egress": "egress",
        "index": "index",
        "inbox": "index",
        "search": "search",
        "whatsapp": "messaging",
        "linkedin": "social",
        "github": "repo",
        "maps": "maps",
        "preflight": "approval",
        "capabilities": "capabilities",
    }.get(first, first or "general")


def _provider_for_path(path: str) -> str:
    first = path.strip("/").split("/", 1)[0] if path else ""
    if first in {"gmail", "calendar", "drive", "sheets", "docs", "tasks", "maps"}:
        return f"google_{first}" if first != "gmail" else "google_gmail"
    return {
        "messages": "imessage_gmail",
        "reminders": "apple_reminders",
        "notes": "apple_notes",
        "scheduled": "scheduler",
        "followups": "scheduler",
        "connectors": "connector_registry",
        "whatsapp": "whatsapp",
        "linkedin": "linkedin",
        "github": "github",
        "capture": "capture_health",
        "egress": "egress_audit",
        "index": "message_index",
        "inbox": "message_index",
        "search": "federated_search",
        "preflight": "approval_preflight",
        "capabilities": "capability_inventory",
    }.get(first, "inbox")


def _category(tool: Tool) -> str:
    if tool.readonly:
        return "read"
    lowered = f"{tool.name} {tool.path}".lower()
    if tool.path in {"/memory/extract", "/notifications/config", "/voice/config"}:
        return "local_write"
    if "delete" in lowered or tool.method == "DELETE":
        return "delete"
    if "send" in lowered or "reply" in lowered:
        return "external_write"
    if "upload" in lowered or "create" in lowered or "update" in lowered or "append" in lowered:
        return "external_write"
    return "external_write" if tool.method in MUTATING_METHODS else "read"


def _risk(category: str, tool: Tool) -> str:
    if category == "read":
        return "medium" if _domain_for_path(tool.path) in {"mail", "mail_messages", "notes", "search"} else "low"
    if category == "local_write":
        return "medium"
    if category == "delete":
        return "critical"
    if any(marker in tool.path for marker in ("/send", "/reply", "/scheduled", "/followups")):
        return "high"
    return "high"


def _approval_policy(category: str, tool: Tool) -> dict[str, Any]:
    if category == "read":
        return {
            "required": False,
            "mode": "not_required_for_read",
            "confirm_parameter": False,
            "server_lease_required": False,
        }
    if category == "local_write":
        return {
            "required": False,
            "mode": "explicit_local_write_exception",
            "confirm_parameter": bool(tool.confirm),
            "server_lease_required": False,
        }
    return {
        "required": True,
        "mode": "confirm_plus_server_policy",
        "confirm_parameter": bool(tool.confirm),
        "server_lease_required": True,
    }


def _param_schema(params: list[Param]) -> dict[str, Any]:
    properties: dict[str, dict[str, str]] = {}
    required: list[str] = []
    for param in params:
        type_name = getattr(param.type, "__name__", str(param.type))
        properties[param.name] = {"type": type_name, "location": param.location}
        if param.default is _EMPTY:
            required.append(param.name)
    return {"properties": properties, "required": required}


def _tool_capability(tool: Tool) -> dict[str, Any]:
    category = _category(tool)
    capability_id = f"mcp.{tool.name}"
    return {
        "id": capability_id,
        "module_id": _provider_for_path(tool.path),
        "title": tool.name.replace("_", " ").title(),
        "description": tool.description,
        "category": category,
        "risk": _risk(category, tool),
        "route": {"method": tool.method, "path": tool.path},
        "command": None,
        "params_schema": _param_schema(tool.params),
        "result_schema": {"type": "object"},
        "requires_account": any(param.name == "account" for param in tool.params),
        "readiness": "available",
        "approval": _approval_policy(category, tool),
        "exposure": {
            "rest": True,
            "mcp_readonly": bool(tool.readonly),
            "mcp_full": True,
            "cli": False,
            "tui": True,
            "agent_safe": bool(tool.readonly),
            "workflow_safe": bool(tool.readonly),
            "default_visible": True,
        },
        "audit": {
            "namespace": f"capability.{_provider_for_path(tool.path)}",
            "event_type": "read" if category == "read" else "proposal_or_write",
            "redaction": "metadata_only",
        },
    }


def _connector_module(connector: ConnectorDefinition) -> dict[str, Any]:
    capabilities: list[str] = []
    if connector.search_command:
        capabilities.append(f"connector.{connector.id}.search")
    if connector.sync_command:
        capabilities.append(f"connector.{connector.id}.sync_plan")
    if connector.write_capable:
        capabilities.append(f"connector.{connector.id}.external_write_deferred")
    return {
        "id": f"connector.{connector.id}",
        "label": connector.label,
        "provider": connector.id,
        "domain": connector.category,
        "implementation": "local_cli",
        "adapter": connector.binary,
        "accounts": [],
        "storage_refs": [{"label": path, "secret": False} for path in connector.storage_paths],
        "capabilities": capabilities,
        "health": {"safe_check": "local_binary_and_storage_only"},
        "audit_namespace": f"connector.{connector.id}",
        "status": "deferred" if connector.write_capable else "ready",
        "notes": connector.notes,
    }


def _connector_capabilities(connector: ConnectorDefinition) -> list[dict[str, Any]]:
    caps: list[dict[str, Any]] = []
    if connector.search_command:
        caps.append(
            {
                "id": f"connector.{connector.id}.search",
                "module_id": f"connector.{connector.id}",
                "title": f"Search {connector.label}",
                "description": f"Search local {connector.label} data through the configured CLI.",
                "category": "read",
                "risk": "medium",
                "route": {"method": "POST", "path": "/connectors/search"},
                "command": {"argv_template": list(connector.search_command)},
                "params_schema": {"properties": {"query": {"type": "str"}}, "required": ["query"]},
                "result_schema": {"type": "object"},
                "requires_account": False,
                "readiness": "dry_run_only",
                "approval": _approval_policy("read", Tool("unused", "GET", "/", "", readonly=True)),
                "exposure": {
                    "rest": True,
                    "mcp_readonly": False,
                    "mcp_full": False,
                    "cli": True,
                    "tui": False,
                    "agent_safe": True,
                    "workflow_safe": True,
                    "default_visible": True,
                },
                "audit": {"namespace": f"connector.{connector.id}", "event_type": "search", "redaction": "metadata_only"},
            }
        )
    if connector.sync_command:
        caps.append(
            {
                "id": f"connector.{connector.id}.sync_plan",
                "module_id": f"connector.{connector.id}",
                "title": f"Plan {connector.label} Sync",
                "description": "Return a sync plan without executing it.",
                "category": "draft",
                "risk": "medium",
                "route": {"method": "POST", "path": f"/connectors/{connector.id}/sync"},
                "command": {"argv_template": list(connector.sync_command)},
                "params_schema": {"properties": {"execute": {"type": "bool"}}, "required": []},
                "result_schema": {"type": "object"},
                "requires_account": False,
                "readiness": "dry_run_only",
                "approval": {
                    "required": True,
                    "mode": "execute_false_only_without_approval",
                    "confirm_parameter": False,
                    "server_lease_required": True,
                },
                "exposure": {
                    "rest": True,
                    "mcp_readonly": False,
                    "mcp_full": False,
                    "cli": True,
                    "tui": False,
                    "agent_safe": False,
                    "workflow_safe": False,
                    "default_visible": True,
                },
                "audit": {"namespace": f"connector.{connector.id}", "event_type": "sync_plan", "redaction": "metadata_only"},
            }
        )
    if connector.write_capable:
        caps.append(
            {
                "id": f"connector.{connector.id}.external_write_deferred",
                "module_id": f"connector.{connector.id}",
                "title": f"{connector.label} External Write",
                "description": (
                    "Placeholder for future provider-mutating actions. This capability is "
                    "advertised for planning only and is not executable from the inventory."
                ),
                "category": "external_write",
                "risk": "high",
                "route": None,
                "command": None,
                "params_schema": {"properties": {}, "required": []},
                "result_schema": {"type": "object"},
                "requires_account": True,
                "readiness": "deferred",
                "approval": {
                    "required": True,
                    "mode": "deferred_until_server_policy_and_lease",
                    "confirm_parameter": False,
                    "server_lease_required": True,
                },
                "exposure": {
                    "rest": False,
                    "mcp_readonly": False,
                    "mcp_full": False,
                    "cli": False,
                    "tui": False,
                    "agent_safe": False,
                    "workflow_safe": False,
                    "default_visible": False,
                },
                "audit": {
                    "namespace": f"connector.{connector.id}",
                    "event_type": "external_write_deferred",
                    "redaction": "metadata_only",
                },
            }
        )
    return caps


def _module_from_tool_capabilities(module_id: str, caps: list[dict[str, Any]]) -> dict[str, Any]:
    first = caps[0]
    return {
        "id": module_id,
        "label": module_id.replace("_", " ").replace(".", " ").title(),
        "provider": module_id,
        "domain": _domain_for_path(first.get("route", {}).get("path", "")),
        "implementation": "rest_api",
        "adapter": "inbox_server",
        "accounts": [],
        "storage_refs": [],
        "capabilities": [cap["id"] for cap in caps],
        "health": {"safe_check": "inventory_only"},
        "audit_namespace": f"capability.{module_id}",
        "status": "ready",
    }


def build_capability_inventory() -> dict[str, Any]:
    tool_caps = [_tool_capability(tool) for tool in TOOLS]
    grouped: dict[str, list[dict[str, Any]]] = {}
    for cap in tool_caps:
        grouped.setdefault(cap["module_id"], []).append(cap)

    modules = [_module_from_tool_capabilities(module_id, caps) for module_id, caps in sorted(grouped.items())]
    modules.extend(_connector_module(connector) for connector in CONNECTORS)

    capabilities = [*tool_caps]
    for connector in CONNECTORS:
        capabilities.extend(_connector_capabilities(connector))

    by_category = Counter(cap["category"] for cap in capabilities)
    by_risk = Counter(cap["risk"] for cap in capabilities)
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _now(),
        "mode": "read_only_inventory_no_provider_calls",
        "invariants": {
            "provider_calls": False,
            "connector_binaries_executed": False,
            "credentials_read": False,
            "external_services_mutated": False,
            "server_state_mutated": False,
        },
        "summary": {
            "modules": len(modules),
            "capabilities": len(capabilities),
            "by_category": dict(sorted(by_category.items())),
            "by_risk": dict(sorted(by_risk.items())),
            "external_write_capabilities": by_category.get("external_write", 0),
            "delete_capabilities": by_category.get("delete", 0),
            "read_capabilities": by_category.get("read", 0),
        },
        "modules": modules,
        "capabilities": capabilities,
    }


def module_summary() -> dict[str, Any]:
    inventory = build_capability_inventory()
    return {
        "schema_version": inventory["schema_version"],
        "generated_at": inventory["generated_at"],
        "summary": inventory["summary"],
        "modules": [
            {
                "id": module["id"],
                "label": module["label"],
                "provider": module["provider"],
                "domain": module["domain"],
                "status": module["status"],
                "capability_count": len(module["capabilities"]),
            }
            for module in inventory["modules"]
        ],
    }
