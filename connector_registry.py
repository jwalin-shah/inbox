"""Read-only registry for local personal-data connector CLIs.

The registry keeps external connector tooling behind a narrow contract: status,
search, and sync planning. Sync execution is opt-in; sends and writes stay out
of this module.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

DEFAULT_TIMEOUT_SECONDS = 12
CONNECTOR_SOURCE_PREFIX = "connector:"
CONNECTOR_ALL_SOURCE = "connectors"


@dataclass(frozen=True)
class CredentialReference:
    id: str
    label: str
    kind: str
    encrypted_ref: str
    required: bool = True
    scopes: tuple[str, ...] = ()
    notes: str = ""


@dataclass(frozen=True)
class ConnectorAccountScope:
    id: str
    label: str
    subject_ref: str
    read_scopes: tuple[str, ...] = ()
    write_scopes: tuple[str, ...] = ()
    credential_refs: tuple[CredentialReference, ...] = ()
    notes: str = ""


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
    required_env: tuple[str, ...] = ()
    required_permissions: tuple[str, ...] = ()
    remediation: tuple[str, ...] = ()
    accounts: tuple[ConnectorAccountScope, ...] = ()
    write_capable: bool = False
    notes: str = ""


APPROVAL_REQUIRED_ACTIONS: tuple[dict[str, str], ...] = (
    {
        "action": "send",
        "approval_class": "external_write",
        "policy": "approval_required",
        "executor": "outside_connector_registry",
    },
    {
        "action": "delete",
        "approval_class": "external_destructive",
        "policy": "approval_required",
        "executor": "outside_connector_registry",
    },
    {
        "action": "calendar_write",
        "approval_class": "external_write",
        "policy": "approval_required",
        "executor": "outside_connector_registry",
    },
    {
        "action": "sync_execute",
        "approval_class": "external_write",
        "policy": "approval_required",
        "executor": "inbox.connectors.sync",
    },
)


def _credential_pattern() -> dict[str, Any]:
    return {
        "mode": "encrypted_reference_only",
        "plaintext_material_allowed": False,
        "allowed_reference_schemes": ["infisical://", "keychain://", "file://"],
        "required_envelope_fields": [
            "connector_id",
            "account_id",
            "credential_ref",
            "scopes",
            "encrypted",
        ],
        "required_envelope_values": {"encrypted": True},
    }


def _credential_ref_to_dict(ref: CredentialReference) -> dict[str, Any]:
    return {
        "id": ref.id,
        "label": ref.label,
        "kind": ref.kind,
        "encrypted_ref": ref.encrypted_ref,
        "encrypted": True,
        "required": ref.required,
        "scopes": list(ref.scopes),
        "notes": ref.notes,
    }


def _account_scope_to_dict(account: ConnectorAccountScope) -> dict[str, Any]:
    return {
        "id": account.id,
        "label": account.label,
        "subject_ref": account.subject_ref,
        "read_scopes": list(account.read_scopes),
        "write_scopes": list(account.write_scopes),
        "credential_refs": [_credential_ref_to_dict(ref) for ref in account.credential_refs],
        "notes": account.notes,
        "write_policy": "write scopes are metadata only; provider writes require approval lease",
    }


CONNECTORS: tuple[ConnectorDefinition, ...] = (
    ConnectorDefinition(
        id="google",
        label="Google Workspace",
        binary="gog",
        category="workspace",
        storage_paths=("~/Library/Application Support/gogcli",),
        auth_command=("gog", "auth", "status", "--json"),
        search_command=("gog", "gmail", "search", "{query}", "--max", "{limit}", "--json"),
        sync_command=("gog", "sync", "--dry-run", "--json"),
        required_permissions=("Google OAuth scopes for Gmail, Calendar, Drive, Sheets, Docs, Tasks",),
        accounts=(
            ConnectorAccountScope(
                id="google:workspace",
                label="Google Workspace account",
                subject_ref="gog authenticated account email",
                read_scopes=(
                    "gmail.read",
                    "calendar.read",
                    "drive.read",
                    "sheets.read",
                    "docs.read",
                    "tasks.read",
                ),
                write_scopes=(
                    "gmail.send",
                    "gmail.modify",
                    "calendar.write",
                    "drive.write",
                    "sheets.write",
                    "docs.write",
                    "tasks.write",
                ),
                credential_refs=(
                    CredentialReference(
                        id="gog_oauth_token",
                        label="Google OAuth token envelope",
                        kind="oauth_refresh_token",
                        encrypted_ref="file://~/Library/Application Support/gogcli/tokens.enc",
                        scopes=("gmail", "calendar", "drive", "sheets", "docs", "tasks"),
                        notes="Registry stores the encrypted reference only; gog owns decryption.",
                    ),
                ),
            ),
        ),
        remediation=(
            "Install gog and ensure it is on PATH.",
            "Run gog auth/login for the intended Google accounts.",
            "Run gog auth status --json and gog sync --dry-run --json before live use.",
        ),
        write_capable=True,
        notes="Gmail, Calendar, Drive, Docs, Sheets, and Contacts through Google OAuth.",
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
        required_permissions=("WhatsApp local/browser session or configured export source",),
        accounts=(
            ConnectorAccountScope(
                id="whatsapp:local",
                label="WhatsApp local session",
                subject_ref="wacli configured phone/session",
                read_scopes=("whatsapp.messages.read",),
                write_scopes=("whatsapp.messages.send",),
                credential_refs=(
                    CredentialReference(
                        id="wacli_session",
                        label="WhatsApp session envelope",
                        kind="browser_or_export_session",
                        encrypted_ref="file://~/.wacli/session.enc",
                        scopes=("whatsapp.messages",),
                    ),
                ),
            ),
        ),
        remediation=(
            "Install wacli and ensure it is on PATH.",
            "Run wacli doctor --json and address reported auth/session gaps.",
            "Run POST /connectors/whatsapp/sync without execute first to review the sync command.",
        ),
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
        required_permissions=("Full Disk Access for ~/Library/Messages/chat.db",),
        accounts=(
            ConnectorAccountScope(
                id="imessage:local",
                label="Messages.app local account",
                subject_ref="local macOS Messages identity",
                read_scopes=("imessage.messages.read", "sms.messages.read"),
                write_scopes=("imessage.messages.send", "sms.messages.send"),
                credential_refs=(
                    CredentialReference(
                        id="macos_messages_access",
                        label="macOS Messages access grant",
                        kind="local_os_permission",
                        encrypted_ref="keychain://local/automation/messages",
                        scopes=("messages.full_disk_access", "messages.automation"),
                        notes="Full Disk Access and Automation are OS grants; no plaintext secret is stored.",
                    ),
                ),
            ),
        ),
        remediation=(
            "Install imsg and ensure it is on PATH.",
            "Grant Full Disk Access to the launcher process if chat.db is unreadable.",
            "Run imsg chats --limit 1 --json to confirm read access.",
        ),
        write_capable=True,
        notes="Reads Messages.app history; sending requires Automation permission and confirmation.",
    ),
    ConnectorDefinition(
        id="linkedin",
        label="LinkedIn",
        binary="python3",
        category="social",
        storage_paths=(
            "~/.openhuman/users/local/workspace/linkedin_data/linkedin_data.db",
            "~/.openhuman-staging/users/local/workspace/linkedin_data/linkedin_data.db",
        ),
        auth_command=(
            "python3",
            "-c",
            "from scripts import linkedin_web_scanner; print('{\"scanner_importable\":true}')",
        ),
        search_command=(),
        sync_command=(),
        required_env=("INBOX_ENABLE_LINKEDIN_SCRAPER",),
        required_permissions=("Signed-in LinkedIn Messaging tab in the configured CDP browser",),
        accounts=(
            ConnectorAccountScope(
                id="linkedin:browser",
                label="LinkedIn browser session",
                subject_ref="signed-in browser profile",
                read_scopes=("linkedin.messages.read",),
                credential_refs=(
                    CredentialReference(
                        id="linkedin_browser_profile",
                        label="LinkedIn browser profile/session",
                        kind="browser_session",
                        encrypted_ref="keychain://local/browser/linkedin",
                        scopes=("linkedin.messaging",),
                        notes="Scanner is opt-in and reads from the configured local browser session.",
                    ),
                ),
            ),
        ),
        remediation=(
            "Use the LinkedIn data export path when possible.",
            "For scanner use, open LinkedIn Messaging in the CDP browser and set INBOX_ENABLE_LINKEDIN_SCRAPER=1 only for that command.",
            "Sync the resulting linkedin_data.db into the inbox index before relying on job outreach readiness.",
        ),
        notes="Local LinkedIn scanner/export backing store; disabled by default and read-only from Inbox.",
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
        accounts=(
            ConnectorAccountScope(
                id="discord:bot_archive",
                label="Discord archive account",
                subject_ref="discrawl configured bot/application",
                read_scopes=("discord.archive.read",),
                credential_refs=(
                    CredentialReference(
                        id="discrawl_bot_token",
                        label="Discord bot token envelope",
                        kind="bot_token",
                        encrypted_ref="infisical://inbox/connectors/discord/bot_token",
                        scopes=("discord.archive",),
                    ),
                ),
            ),
        ),
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
        accounts=(
            ConnectorAccountScope(
                id="twitter:archive",
                label="X/Twitter archive account",
                subject_ref="birdclaw configured account",
                read_scopes=("twitter.archive.read",),
                write_scopes=("twitter.post", "twitter.delete"),
                credential_refs=(
                    CredentialReference(
                        id="birdclaw_oauth_token",
                        label="X/Twitter OAuth token envelope",
                        kind="oauth_token",
                        encrypted_ref="infisical://inbox/connectors/twitter/oauth_token",
                        scopes=("twitter.archive", "twitter.write"),
                    ),
                ),
            ),
        ),
        write_capable=True,
        notes="Local archive/search; live reads/writes need explicit confirmation.",
    ),
)


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
    with suppress(json.JSONDecodeError):
        return json.loads(raw)
    return None


def _format_command(
    command: tuple[str, ...], *, query: str = "", limit: int = 20
) -> tuple[str, ...]:
    return tuple(part.format(query=query, limit=str(limit)) for part in command)


def _storage_status(paths: tuple[str, ...]) -> list[dict[str, Any]]:
    statuses: list[dict[str, Any]] = []
    for raw_path in paths:
        path = Path(raw_path).expanduser()
        item: dict[str, Any] = {"path": str(path), "exists": path.exists(), "kind": "missing"}
        if item["exists"]:
            item["kind"] = "dir" if path.is_dir() else "file"
            with suppress(OSError):
                item["bytes"] = path.stat().st_size
        statuses.append(item)
    return statuses


def _env_status(names: tuple[str, ...]) -> list[dict[str, Any]]:
    return [{"name": name, "present": bool(os.environ.get(name))} for name in names]


def _safe_command_preview(command: tuple[str, ...]) -> list[str]:
    return list(command)


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

    storage = _storage_status(connector.storage_paths)
    missing_env = [item["name"] for item in _env_status(connector.required_env) if not item["present"]]
    missing_storage = [item["path"] for item in storage if not item["exists"]]
    remediation = list(connector.remediation)
    install_step = f"Install {connector.binary} and ensure it is on PATH."
    if not installed and install_step not in remediation:
        remediation.insert(0, install_step)
    if missing_env:
        remediation.append(f"Set required env for live scanner/auth use: {', '.join(missing_env)}.")
    if missing_storage and connector.storage_paths:
        remediation.append("Create or sync the backing local store before relying on search/readiness.")

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
        "storage": storage,
        "required_env": _env_status(connector.required_env),
        "required_permissions": list(connector.required_permissions),
        "commands": {
            "auth": _safe_command_preview(connector.auth_command),
            "search": _safe_command_preview(connector.search_command),
            "sync": _safe_command_preview(connector.sync_command),
        },
        "accounts": [_account_scope_to_dict(account) for account in connector.accounts],
        "credential_pattern": _credential_pattern(),
        "action_policy": {
            "read": {"policy": "allowed", "approval_required": False},
            "search": {"policy": "allowed", "approval_required": False},
            "mutations": list(APPROVAL_REQUIRED_ACTIONS),
            "registry_executes_provider_writes": False,
        },
        "sync_ready": installed and bool(connector.sync_command),
        "supports_search": bool(connector.search_command),
        "supports_sync": bool(connector.sync_command),
        "remediation": remediation,
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


def connector_source_ids() -> frozenset[str]:
    return frozenset(connector.id for connector in CONNECTORS)


def partition_search_sources(sources: list[str]) -> tuple[list[str], list[str]]:
    built_in_sources: list[str] = []
    connector_sources: list[str] = []
    valid_connector_ids = connector_source_ids()

    for source in sources:
        if source == CONNECTOR_ALL_SOURCE:
            connector_sources = ["all"]
        elif source.startswith(CONNECTOR_SOURCE_PREFIX):
            connector_id = source.removeprefix(CONNECTOR_SOURCE_PREFIX)
            if connector_id in valid_connector_ids:
                connector_sources.append(connector_id)
        else:
            built_in_sources.append(source)

    return built_in_sources, connector_sources


def merge_connector_search_results(
    result: dict[str, Any],
    connector_result: dict[str, Any],
    *,
    limit: int,
) -> dict[str, Any]:
    merged = dict(result)
    merged_results = [*result.get("results", []), *connector_result.get("results", [])]
    merged_results.sort(key=lambda item: item.get("timestamp", ""), reverse=True)
    merged["results"] = merged_results[:limit]
    merged["total"] = len(merged["results"])
    merged["connector_errors"] = connector_result.get("errors", [])
    return merged


def _connector_by_id(connector_id: str) -> ConnectorDefinition | None:
    return next((connector for connector in CONNECTORS if connector.id == connector_id), None)


def _normalize_search_results(connector_id: str, raw: str) -> list[dict[str, Any]]:
    parsed = _parse_json(raw)
    if parsed is None:
        if not raw:
            return []
        raise ValueError("malformed_json")

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
        try:
            results.extend(_normalize_search_results(connector.id, stdout))
        except ValueError as exc:
            errors.append(
                {
                    "source": connector.id,
                    "error": str(exc),
                    "detail": stdout[:1000],
                }
            )
            continue

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
            "approval_required_for_execute": True,
        }
    approval_lease = os.getenv("INBOX_APPROVAL_LEASE", "")
    if not approval_lease:
        return {
            "ok": False,
            "connector": connector.id,
            "error": "approval_required",
            "dry_run": True,
            "command": command,
            "approval_required_for_execute": True,
            "write_policy": "live connector sync execution requires a per-action approval lease",
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
