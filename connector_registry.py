"""Read-only connector registry for local personal-data CLIs.

This module keeps external connector tooling behind a narrow, inspectable
contract: status, search, and sync planning. It does not perform writes.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

DEFAULT_TIMEOUT_SECONDS = 12


@dataclass(frozen=True)
class ConnectorDefinition:
    id: str
    label: str
    binary: str
    category: str
    storage_paths: tuple[str, ...] = ()
    auth_command: tuple[str, ...] = ()
    search_command: tuple[str, ...] = ()
    sync_command: tuple[str, ...] = ()
    write_capable: bool = False
    notes: str = ""


CONNECTORS: tuple[ConnectorDefinition, ...] = (
    ConnectorDefinition(
        id="google",
        label="Google Workspace",
        binary="gog",
        category="workspace",
        storage_paths=("~/Library/Application Support/gogcli",),
        auth_command=(),
        search_command=("gog", "gmail", "search", "{query}", "--max", "{limit}", "--json"),
        sync_command=(),
        write_capable=True,
        notes=(
            "Gmail, Calendar, Drive, Docs, Sheets, Contacts through Google OAuth. "
            "Status avoids Keychain reads; verify auth explicitly when needed."
        ),
    ),
    ConnectorDefinition(
        id="whatsapp",
        label="WhatsApp",
        binary="wacli",
        category="messaging",
        storage_paths=("~/.wacli",),
        auth_command=("wacli", "doctor", "--json"),
        search_command=("wacli", "messages", "search", "{query}", "--limit", "{limit}", "--json"),
        sync_command=("wacli", "sync", "--once"),
        write_capable=True,
        notes="Local WhatsApp history/search; sends must be confirmed separately.",
    ),
    ConnectorDefinition(
        id="imessage",
        label="iMessage/SMS",
        binary="imsg",
        category="messaging",
        storage_paths=("~/Library/Messages/chat.db",),
        auth_command=("imsg", "chats", "--limit", "1", "--json"),
        search_command=("imsg", "search", "{query}", "--limit", "{limit}", "--json"),
        sync_command=(),
        write_capable=True,
        notes="Reads Messages.app history; sending requires Automation permission and confirmation.",
    ),
    ConnectorDefinition(
        id="discord",
        label="Discord",
        binary="discrawl",
        category="messaging",
        storage_paths=("~/Library/Application Support/discrawl/discrawl.db",),
        auth_command=("discrawl", "status", "--json"),
        search_command=("discrawl", "search", "{query}", "--limit", "{limit}", "--json"),
        sync_command=("discrawl", "sync"),
        write_capable=False,
        notes="Bot-token Discord archive/search. No user-token scraping.",
    ),
    ConnectorDefinition(
        id="twitter",
        label="X/Twitter",
        binary="birdclaw",
        category="social",
        storage_paths=("~/.birdclaw/birdclaw.sqlite",),
        auth_command=("birdclaw", "auth", "status", "--json"),
        search_command=("birdclaw", "search", "{query}", "--limit", "{limit}", "--json"),
        sync_command=("birdclaw", "sync"),
        write_capable=True,
        notes="Local archive/search; live reads/writes need xurl auth and explicit confirmation.",
    ),
)


def _expand(path: str) -> Path:
    return Path(path).expanduser()


def _run(
    command: tuple[str, ...], *, timeout: int = DEFAULT_TIMEOUT_SECONDS
) -> tuple[int, str, str]:
    try:
        proc = subprocess.run(
            list(command),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as exc:
        return 127, "", str(exc)
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout if isinstance(exc.stdout, str) else ""
        stderr = exc.stderr if isinstance(exc.stderr, str) else ""
        return 124, stdout, stderr or f"Timed out after {timeout}s"
    return proc.returncode, proc.stdout.strip(), proc.stderr.strip()


def _parse_json(raw: str) -> Any:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def _format_command(
    command: tuple[str, ...], *, query: str = "", limit: int = 20
) -> tuple[str, ...]:
    return tuple(part.format(query=query, limit=str(limit)) for part in command)


def _storage_status(paths: tuple[str, ...]) -> list[dict[str, Any]]:
    statuses: list[dict[str, Any]] = []
    for raw_path in paths:
        path = _expand(raw_path)
        exists = path.exists()
        item: dict[str, Any] = {
            "path": str(path),
            "exists": exists,
            "kind": "missing",
        }
        if exists:
            item["kind"] = "dir" if path.is_dir() else "file"
            with suppress_os_error():
                item["bytes"] = path.stat().st_size
        statuses.append(item)
    return statuses


class suppress_os_error:
    def __enter__(self) -> None:
        return None

    def __exit__(self, exc_type: object, exc: object, tb: object) -> bool:
        return isinstance(exc, OSError)


def connector_status(connector: ConnectorDefinition) -> dict[str, Any]:
    binary_path = shutil.which(connector.binary)
    installed = binary_path is not None
    auth_state = "not_installed"
    auth_detail: Any = None
    auth_error = ""
    auth_exit_code: int | None = None

    if installed and connector.auth_command:
        code, stdout, stderr = _run(connector.auth_command)
        auth_exit_code = code
        parsed = _parse_json(stdout)
        auth_detail = parsed if parsed is not None else stdout[:1000]
        auth_error = stderr[:1000]
        auth_state = "ok" if code == 0 else "needs_attention"
    elif installed:
        auth_state = "unknown"

    return {
        "id": connector.id,
        "label": connector.label,
        "category": connector.category,
        "binary": connector.binary,
        "binary_path": binary_path or "",
        "installed": installed,
        "auth_state": auth_state,
        "auth_exit_code": auth_exit_code,
        "auth_detail": auth_detail,
        "auth_error": auth_error,
        "storage": _storage_status(connector.storage_paths),
        "supports_search": bool(connector.search_command),
        "supports_sync": bool(connector.sync_command),
        "write_capable": connector.write_capable,
        "write_policy": "external writes require explicit confirmation"
        if connector.write_capable
        else "read-only",
        "notes": connector.notes,
    }


def connectors_status() -> dict[str, Any]:
    statuses = [connector_status(connector) for connector in CONNECTORS]
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "connectors": statuses,
        "summary": {
            "total": len(statuses),
            "installed": sum(1 for item in statuses if item["installed"]),
            "ok": sum(1 for item in statuses if item["auth_state"] == "ok"),
            "needs_attention": sum(
                1 for item in statuses if item["auth_state"] == "needs_attention"
            ),
        },
    }


def _connector_by_id(connector_id: str) -> ConnectorDefinition | None:
    return next((connector for connector in CONNECTORS if connector.id == connector_id), None)


def _normalize_search_results(connector_id: str, raw: str) -> list[dict[str, Any]]:
    parsed = _parse_json(raw)
    if parsed is None:
        if not raw:
            return []
        return [
            {
                "source": connector_id,
                "id": "",
                "title": connector_id,
                "snippet": raw[:500],
                "timestamp": "",
                "metadata": {"format": "text"},
            }
        ]

    if isinstance(parsed, dict):
        for key in ("results", "messages", "items", "data"):
            value = parsed.get(key)
            if isinstance(value, list):
                parsed = value
                break
        else:
            parsed = [parsed]

    if not isinstance(parsed, list):
        return []

    results: list[dict[str, Any]] = []
    for idx, item in enumerate(parsed):
        if not isinstance(item, dict):
            results.append(
                {
                    "source": connector_id,
                    "id": str(idx),
                    "title": connector_id,
                    "snippet": str(item)[:500],
                    "timestamp": "",
                    "metadata": {},
                }
            )
            continue

        title = (
            item.get("title")
            or item.get("subject")
            or item.get("name")
            or item.get("chat_name")
            or item.get("channel_name")
            or connector_id
        )
        snippet = (
            item.get("snippet")
            or item.get("text")
            or item.get("body")
            or item.get("content")
            or item.get("message")
            or ""
        )
        timestamp = item.get("timestamp") or item.get("created_at") or item.get("date") or ""
        result_id = item.get("id") or item.get("message_id") or item.get("rowid") or str(idx)
        results.append(
            {
                "source": connector_id,
                "id": str(result_id),
                "title": str(title),
                "snippet": str(snippet)[:1000],
                "timestamp": str(timestamp),
                "metadata": item,
            }
        )
    return results


def search_connectors(
    query: str,
    *,
    sources: list[str] | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    if not query.strip():
        return {"query": query, "total": 0, "results": [], "errors": []}

    wanted = set(sources or ["all"])
    selected = [
        connector
        for connector in CONNECTORS
        if "all" in wanted or connector.id in wanted or connector.category in wanted
    ]
    results: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    for connector in selected:
        if not connector.search_command:
            continue
        if shutil.which(connector.binary) is None:
            errors.append({"source": connector.id, "error": "not_installed"})
            continue
        command = _format_command(connector.search_command, query=query, limit=limit)
        code, stdout, stderr = _run(command)
        if code != 0:
            errors.append(
                {
                    "source": connector.id,
                    "exit_code": code,
                    "error": (stderr or stdout)[:1000],
                }
            )
            continue
        results.extend(_normalize_search_results(connector.id, stdout))

    results.sort(key=lambda item: item.get("timestamp", ""), reverse=True)
    results = results[:limit]
    return {"query": query, "total": len(results), "results": results, "errors": errors}


def connector_sync_plan(connector_id: str, *, execute: bool = False) -> dict[str, Any]:
    connector = _connector_by_id(connector_id)
    if connector is None:
        return {"ok": False, "connector": connector_id, "error": "unknown_connector"}
    if not connector.sync_command:
        return {
            "ok": False,
            "connector": connector.id,
            "error": "sync_not_supported",
            "command": [],
        }
    command = list(connector.sync_command)
    if not execute:
        return {
            "ok": True,
            "connector": connector.id,
            "dry_run": True,
            "command": command,
            "write_policy": "sync reads remote/local source data into local storage only",
        }
    if shutil.which(connector.binary) is None:
        return {
            "ok": False,
            "connector": connector.id,
            "error": "not_installed",
            "command": command,
        }
    code, stdout, stderr = _run(connector.sync_command, timeout=60)
    return {
        "ok": code == 0,
        "connector": connector.id,
        "dry_run": False,
        "command": command,
        "exit_code": code,
        "stdout": stdout[-2000:],
        "stderr": stderr[-2000:],
    }
