from __future__ import annotations

import os
from contextlib import suppress
from typing import Any

import httpx

SERVER_URL_ENV = "INBOX_SERVER_URL"
SERVER_TOKEN_ENV = "INBOX_SERVER_TOKEN"  # nosec: B105 - env var name, not a hardcoded credential
DEFAULT_SERVER_URL = "http://127.0.0.1:9849"


class InboxBackendError(RuntimeError):
    pass


class InboxBackend:
    def __init__(self, base_url: str | None = None, token: str | None = None) -> None:
        self.base_url = (base_url or os.getenv(SERVER_URL_ENV, DEFAULT_SERVER_URL)).rstrip("/")
        self.token = token if token is not None else os.getenv(SERVER_TOKEN_ENV, "").strip()

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> Any:
        try:
            async with httpx.AsyncClient(base_url=self.base_url, timeout=30.0) as client:
                response = await client.request(
                    method,
                    path,
                    params=params,
                    json=json,
                    headers=self._headers(),
                )
        except httpx.HTTPError as exc:
            raise InboxBackendError(
                f"Unable to reach inbox server at {self.base_url}: {exc}"
            ) from exc

        if response.status_code >= 400:
            detail = response.text
            with suppress(Exception):
                detail = response.json().get("detail", detail)
            raise InboxBackendError(f"{method} {path} failed: {detail}")
        return response.json()

    async def health(self) -> dict[str, Any]:
        return await self._request("GET", "/health")

    async def list_inbox_threads(self, limit: int = 20, account: str = "") -> list[dict[str, Any]]:
        return await self._request(
            "GET",
            "/gmail/conversations",
            params={"label": "INBOX", "limit": limit, "account": account},
        )

    async def search_email(
        self,
        query: str,
        limit: int = 20,
        account: str = "",
        label: str = "",
    ) -> list[dict[str, Any]]:
        return await self._request(
            "GET",
            "/gmail/search",
            params={
                "q": query,
                "limit": limit,
                "account": account,
                "label": label,
            },
        )

    async def get_email_thread(
        self,
        message_id: str,
        thread_id: str = "",
    ) -> list[dict[str, Any]]:
        return await self._request(
            "GET",
            f"/messages/gmail/{message_id}",
            params={"thread_id": thread_id},
        )

    async def send_email_reply(
        self,
        *,
        msg_id: str,
        body: str,
        thread_id: str = "",
        to: str = "",
        subject: str = "",
        message_id_header: str = "",
        account: str = "",
    ) -> dict[str, Any]:
        return await self._request(
            "POST",
            "/messages/gmail/reply",
            json={
                "msg_id": msg_id,
                "body": body,
                "thread_id": thread_id,
                "to": to,
                "subject": subject,
                "message_id_header": message_id_header,
                "account": account,
            },
        )

    async def archive_email_thread(self, message_id: str) -> dict[str, Any]:
        return await self._request("POST", f"/messages/gmail/{message_id}/archive")

    async def mark_email_read(self, message_id: str) -> dict[str, Any]:
        return await self._request("POST", f"/messages/gmail/{message_id}/read")

    async def list_message_threads(self, limit: int = 20) -> list[dict[str, Any]]:
        return await self._request(
            "GET",
            "/conversations",
            params={"source": "imessage", "limit": limit},
        )

    async def get_message_thread(self, conv_id: str, limit: int = 50) -> list[dict[str, Any]]:
        return await self._request(
            "GET",
            f"/messages/imessage/{conv_id}",
            params={"limit": limit},
        )

    async def send_imessage(self, conv_id: str, text: str) -> dict[str, Any]:
        return await self._request(
            "POST",
            "/messages/send",
            json={"conv_id": conv_id, "source": "imessage", "text": text},
        )

    async def list_notes(self, limit: int = 20) -> list[dict[str, Any]]:
        return await self._request("GET", "/notes", params={"limit": limit})

    async def get_note(self, note_id: str) -> dict[str, Any]:
        return await self._request("GET", f"/notes/{note_id}")

    async def list_reminders(
        self,
        list_name: str = "",
        show_completed: bool = False,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        return await self._request(
            "GET",
            "/reminders",
            params={
                "list_name": list_name or None,
                "show_completed": str(show_completed).lower(),
                "limit": limit,
            },
        )

    async def create_reminder(
        self,
        title: str,
        list_name: str = "Reminders",
        due_date: str = "",
        notes: str = "",
    ) -> dict[str, Any]:
        return await self._request(
            "POST",
            "/reminders",
            json={
                "title": title,
                "list_name": list_name,
                "due_date": due_date,
                "notes": notes,
            },
        )

    async def complete_reminder(self, reminder_id: str) -> dict[str, Any]:
        return await self._request("POST", f"/reminders/{reminder_id}/complete")

    async def search_all(
        self,
        query: str,
        sources: list[str] | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        return await self._request(
            "POST",
            "/search",
            json={
                "q": query,
                "sources": sources or ["all"],
                "limit": limit,
            },
        )

    async def list_gmail_labels(self, account: str = "") -> list[dict[str, Any]]:
        return await self._request(
            "GET",
            "/gmail/labels",
            params={"account": account},
        )

    async def batch_modify_emails(
        self,
        msg_ids: list[str],
        add_labels: list[str] | None = None,
        remove_labels: list[str] | None = None,
        account: str = "",
    ) -> dict[str, Any]:
        return await self._request(
            "POST",
            "/gmail/batch-modify",
            json={
                "msg_ids": msg_ids,
                "add_label_ids": add_labels or [],
                "remove_label_ids": remove_labels or [],
                "account": account,
            },
        )

    async def create_gmail_filter(
        self,
        from_filter: str = "",
        subject_filter: str = "",
        add_labels: list[str] | None = None,
        remove_labels: list[str] | None = None,
        account: str = "",
    ) -> dict[str, Any]:
        return await self._request(
            "POST",
            "/gmail/filters",
            json={
                "from_filter": from_filter,
                "subject_filter": subject_filter,
                "add_label_ids": add_labels or [],
                "remove_label_ids": remove_labels or [],
                "account": account,
            },
        )

    async def create_gmail_label(
        self,
        name: str,
        visibility: str = "labelShow",
        account: str = "",
    ) -> dict[str, Any]:
        return await self._request(
            "POST",
            "/gmail/labels",
            params={"name": name, "visibility": visibility, "account": account},
        )

    async def check_calendar_conflicts(
        self,
        start: str,
        end: str,
        account: str = "",
    ) -> dict[str, Any]:
        return await self._request(
            "POST",
            "/calendar/conflicts",
            json={
                "start": start,
                "end": end,
                "account": account,
            },
        )

    async def extract_memory(
        self,
        text: str,
        source: str = "manual",
        auto_save: bool = False,
    ) -> dict[str, Any]:
        return await self._request(
            "POST",
            "/memory/extract",
            params={"text": text, "source": source, "auto_save": str(auto_save).lower()},
        )
