"""Multi-account Google service resolution (shared by inbox_server and tests)."""

from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any, Protocol

from fastapi import HTTPException

from services import Contact, drive_get, tasks_lists


class GoogleMultiAccountState(Protocol):
    gmail_services: dict[str, object]
    cal_services: dict[str, object]
    drive_services: dict[str, object]
    sheets_services: dict[str, object]
    docs_services: dict[str, object]
    tasks_services: dict[str, object]
    conv_cache: dict[str, Contact]


def default_google_account(services: dict[str, object]) -> str:
    """Pick the default account for a Google service.

    Priority: INBOX_DEFAULT_GOOGLE_ACCOUNT env var if present in services,
    then first service key.
    """
    preferred = os.environ.get("INBOX_DEFAULT_GOOGLE_ACCOUNT", "").strip()
    if preferred and preferred in services:
        return preferred
    return next(iter(services)) if services else ""


def get_gmail_service(
    state: GoogleMultiAccountState,
    msg_id: str,
    cache_key: Callable[[str, str], str],
) -> tuple[object, Contact | None]:
    """Look up the correct Gmail service for a message, using cache or fallback."""
    contact = state.conv_cache.get(cache_key("gmail", msg_id))
    if contact and contact.gmail_account in state.gmail_services:
        return state.gmail_services[contact.gmail_account], contact
    default_acct = default_google_account(state.gmail_services)
    if default_acct:
        return state.gmail_services[default_acct], contact
    raise HTTPException(404, "No Gmail service available")


def get_gmail_service_for_account(
    state: GoogleMultiAccountState, account: str = ""
) -> tuple[str, object]:
    acct = account or default_google_account(state.gmail_services)
    svc = state.gmail_services.get(acct)
    if not svc:
        raise HTTPException(404, "No Gmail account available")
    return acct, svc


def gmail_message_or_thread_exists(service: Any, msg_id: str = "", thread_id: str = "") -> bool:
    """Return True if the Gmail message or thread exists in the given mailbox."""
    try:
        if msg_id:
            (
                service.users()
                .messages()
                .get(
                    userId="me",
                    id=msg_id,
                    format="metadata",
                    metadataHeaders=["Message-ID"],
                )
                .execute()
            )
            return True
        if thread_id:
            service.users().threads().get(userId="me", id=thread_id, format="metadata").execute()
            return True
    except Exception:
        return False
    return False


def get_gmail_service_for_message(
    state: GoogleMultiAccountState,
    msg_id: str = "",
    thread_id: str = "",
    account: str = "",
    *,
    cache_key: Callable[[str, str], str],
) -> tuple[str, object]:
    """Resolve the mailbox that owns a Gmail message/thread, falling back conservatively."""
    if account:
        return get_gmail_service_for_account(state, account)

    for cache_id in filter(None, [msg_id, thread_id]):
        contact = state.conv_cache.get(cache_key("gmail", cache_id))
        if contact and contact.gmail_account in state.gmail_services:
            return contact.gmail_account, state.gmail_services[contact.gmail_account]

    for acct, svc in state.gmail_services.items():
        if gmail_message_or_thread_exists(svc, msg_id=msg_id, thread_id=thread_id):
            return acct, svc

    return get_gmail_service_for_account(state, "")


def get_sheets_service_for_account(
    state: GoogleMultiAccountState, account: str = ""
) -> tuple[str, object]:
    acct = account or default_google_account(state.sheets_services)
    svc = state.sheets_services.get(acct)
    if not svc:
        raise HTTPException(404, "No Sheets account available")
    return acct, svc


def get_drive_service_for_account(
    state: GoogleMultiAccountState, account: str = ""
) -> tuple[str, object]:
    acct = account or default_google_account(state.drive_services)
    svc = state.drive_services.get(acct)
    if not svc:
        raise HTTPException(404, "No Drive account available")
    return acct, svc


def get_tasks_service_for_account(
    state: GoogleMultiAccountState, account: str = ""
) -> tuple[str, object]:
    acct = account or default_google_account(state.tasks_services)
    svc = state.tasks_services.get(acct)
    if not svc:
        raise HTTPException(404, "No Tasks account available")
    return acct, svc


def get_docs_service_for_account(
    state: GoogleMultiAccountState, account: str = ""
) -> tuple[str, object]:
    """Get docs service for account, return (account_email, service). Raises HTTPException on failure."""
    acct = account or default_google_account(state.docs_services)
    if not acct or acct not in state.docs_services:
        raise HTTPException(400, "No docs service available")
    return acct, state.docs_services[acct]


def get_cal_service_for_account(
    state: GoogleMultiAccountState, account: str = ""
) -> tuple[str, object]:
    """Get calendar service for account, raising HTTPException if unavailable."""
    acct = account or default_google_account(state.cal_services)
    svc = state.cal_services.get(acct)
    if not svc:
        raise HTTPException(404, "No calendar account available")
    return acct, svc


def preflight_google_write_payload(
    state: GoogleMultiAccountState,
    kind: str,
    account: str = "",
    folder_id: str = "",
    list_id: str = "",
    calendar_id: str = "",
    title: str = "",
) -> dict[str, Any]:
    """Inspect where a Google write will land without executing it. Payload for PreflightResult."""
    warnings: list[str] = []

    if kind in ("doc", "sheet", "drive_folder"):
        resolved = account or default_google_account(state.drive_services)
        if not resolved or resolved not in state.drive_services:
            return {
                "kind": kind,
                "resolved_account": resolved,
                "destination": "Drive",
                "destination_id": folder_id,
                "valid": False,
                "warnings": ["No Drive account available"],
                "explanation": f"No Drive service available for account '{resolved}'",
            }
        svc = state.drive_services[resolved]
        destination = "Drive root"
        dest_id = folder_id or ""
        if folder_id:
            try:
                folder = drive_get(svc, folder_id)
                if folder:
                    destination = f"Folder '{folder.name}'"
                else:
                    warnings.append(f"Folder '{folder_id}' not found")
                    return {
                        "kind": kind,
                        "resolved_account": resolved,
                        "destination": f"Unknown folder '{folder_id}'",
                        "destination_id": folder_id,
                        "valid": False,
                        "warnings": warnings,
                        "explanation": f"Folder '{folder_id}' not found in Drive for {resolved}",
                    }
            except Exception:
                warnings.append(f"Could not verify folder '{folder_id}'")
                destination = f"Folder '{folder_id}' (unverified)"
        label = f"'{title}' " if title else ""
        return {
            "kind": kind,
            "resolved_account": resolved,
            "destination": destination,
            "destination_id": dest_id,
            "valid": True,
            "warnings": warnings,
            "explanation": f"Will create {kind} {label}in {destination} using {resolved}",
        }

    if kind == "task":
        resolved = account or default_google_account(state.tasks_services)
        if not resolved or resolved not in state.tasks_services:
            return {
                "kind": kind,
                "resolved_account": resolved,
                "destination": "Google Tasks",
                "destination_id": list_id,
                "valid": False,
                "warnings": ["No Tasks account available"],
                "explanation": f"No Tasks service available for account '{resolved}'",
            }
        svc = state.tasks_services[resolved]
        destination = "My Tasks"
        dest_id = list_id or "@default"
        if list_id and list_id != "@default":
            try:
                all_lists = tasks_lists(svc)
                matched = next(
                    (
                        lst
                        for lst in all_lists
                        if lst.get("id") == list_id or lst.get("title") == list_id
                    ),
                    None,
                )
                if matched:
                    destination = f"Task list '{matched.get('title', list_id)}'"
                    dest_id = matched.get("id", list_id)
                else:
                    warnings.append(f"Task list '{list_id}' not found")
                    return {
                        "kind": kind,
                        "resolved_account": resolved,
                        "destination": f"Unknown list '{list_id}'",
                        "destination_id": list_id,
                        "valid": False,
                        "warnings": warnings,
                        "explanation": f"Task list '{list_id}' not found for {resolved}",
                    }
            except Exception:
                warnings.append(f"Could not verify task list '{list_id}'")
                destination = f"List '{list_id}' (unverified)"
        label = f"'{title}' " if title else ""
        return {
            "kind": kind,
            "resolved_account": resolved,
            "destination": destination,
            "destination_id": dest_id,
            "valid": True,
            "warnings": warnings,
            "explanation": f"Will create task {label}in {destination} using {resolved}",
        }

    if kind == "calendar_event":
        resolved = account or default_google_account(state.cal_services)
        if not resolved or resolved not in state.cal_services:
            return {
                "kind": kind,
                "resolved_account": resolved,
                "destination": "Calendar",
                "destination_id": calendar_id,
                "valid": False,
                "warnings": ["No calendar account available"],
                "explanation": f"No calendar service available for account '{resolved}'",
            }
        cal_id = calendar_id or "primary"
        destination = "primary calendar" if cal_id == "primary" else f"Calendar '{cal_id}'"
        label = f"'{title}' " if title else ""
        return {
            "kind": kind,
            "resolved_account": resolved,
            "destination": destination,
            "destination_id": cal_id,
            "valid": True,
            "warnings": warnings,
            "explanation": f"Will create event {label}in {destination} using {resolved}",
        }

    return {
        "kind": kind,
        "resolved_account": "",
        "destination": "",
        "destination_id": "",
        "valid": False,
        "warnings": [f"Unknown kind '{kind}'"],
        "explanation": f"Unknown write kind '{kind}'. Expected: doc, sheet, drive_folder, task, calendar_event",
    }
