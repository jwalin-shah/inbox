"""
HTTP client for the Inbox API server.
Used by the TUI and agents to interact with inbox data.
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import httpx

SERVER_URL = "http://127.0.0.1:9849"
SERVER_SCRIPT = Path(__file__).parent / "inbox_server.py"


class InboxClient:
    def __init__(self, base_url: str = SERVER_URL, timeout: float = 30):
        self._client = httpx.Client(base_url=base_url, timeout=timeout)

    def close(self) -> None:
        self._client.close()

    # ── Health ────────────────────────────────────────────────────────────

    def health(self) -> dict:
        return self._client.get("/health").json()

    def is_server_running(self) -> bool:
        try:
            self._client.get("/health", timeout=2)
            return True
        except (httpx.ConnectError, httpx.TimeoutException):
            return False

    @staticmethod
    def start_server() -> subprocess.Popen:
        """Launch the server as a background process with logs."""
        log_path = SERVER_SCRIPT.parent / "server.log"
        log_file = open(log_path, "w")  # noqa: SIM115
        proc = subprocess.Popen(
            [sys.executable, str(SERVER_SCRIPT)],
            stdout=log_file,
            stderr=subprocess.STDOUT,
        )
        return proc

    def ensure_server(self, max_wait: float = 30) -> None:
        """Start the server if it's not running and wait for it."""
        if self.is_server_running():
            return
        proc = self.start_server()
        deadline = time.monotonic() + max_wait
        while time.monotonic() < deadline:
            time.sleep(0.5)
            # Check if process died
            if proc.poll() is not None:
                log_path = SERVER_SCRIPT.parent / "server.log"
                log = log_path.read_text() if log_path.exists() else "no log"
                raise RuntimeError(
                    f"Server crashed on startup (exit {proc.returncode}): {log[-500:]}"
                )
            if self.is_server_running():
                return
        raise RuntimeError(f"Server failed to start within {max_wait}s — check server.log")

    # ── Conversations ────────────────────────────────────────────────────

    def conversations(self, source: str = "all", limit: int = 50) -> list[dict]:
        r = self._client.get("/conversations", params={"source": source, "limit": limit})
        r.raise_for_status()
        return r.json()

    # ── Messages ─────────────────────────────────────────────────────────

    def messages(
        self,
        source: str,
        conv_id: str,
        thread_id: str = "",
        limit: int = 50,
    ) -> list[dict]:
        params: dict = {"limit": limit}
        if thread_id:
            params["thread_id"] = thread_id
        r = self._client.get(f"/messages/{source}/{conv_id}", params=params)
        r.raise_for_status()
        return r.json()

    def send(self, conv_id: str, source: str, text: str) -> bool:
        r = self._client.post(
            "/messages/send",
            json={"conv_id": conv_id, "source": source, "text": text},
        )
        r.raise_for_status()
        return r.json().get("ok", False)

    # ── Calendar ─────────────────────────────────────────────────────────

    def calendar_events(self, date: str | None = None) -> list[dict]:
        params = {"date": date} if date else {}
        r = self._client.get("/calendar/events", params=params)
        r.raise_for_status()
        return r.json()

    def create_event(
        self,
        summary: str,
        start: str,
        end: str,
        location: str = "",
        description: str = "",
        all_day: bool = False,
        account: str = "",
    ) -> dict:
        r = self._client.post(
            "/calendar/events",
            json={
                "summary": summary,
                "start": start,
                "end": end,
                "location": location,
                "description": description,
                "all_day": all_day,
                "account": account,
            },
        )
        r.raise_for_status()
        return r.json()

    def create_quick_event(self, text: str, account: str = "") -> dict:
        r = self._client.post(
            "/calendar/events/quick",
            json={"text": text, "account": account},
        )
        r.raise_for_status()
        return r.json()

    def update_event(
        self,
        event_id: str,
        calendar_id: str = "primary",
        account: str = "",
        **fields,
    ) -> bool:
        r = self._client.put(
            f"/calendar/events/{event_id}",
            params={
                "calendar_id": calendar_id,
                "account": account,
            },
            json=fields,
        )
        r.raise_for_status()
        return r.json().get("ok", False)

    def delete_event(
        self,
        event_id: str,
        calendar_id: str = "primary",
        account: str = "",
    ) -> bool:
        r = self._client.delete(
            f"/calendar/events/{event_id}",
            params={
                "calendar_id": calendar_id,
                "account": account,
            },
        )
        r.raise_for_status()
        return r.json().get("ok", False)

    # ── Notes ────────────────────────────────────────────────────────────

    def notes(self, limit: int = 50) -> list[dict]:
        r = self._client.get("/notes", params={"limit": limit})
        r.raise_for_status()
        return r.json()

    def note(self, note_id: str) -> dict:
        r = self._client.get(f"/notes/{note_id}")
        r.raise_for_status()
        return r.json()

    # ── Reminders ────────────────────────────────────────────────────────

    def reminder_lists(self) -> list[dict]:
        r = self._client.get("/reminders/lists")
        r.raise_for_status()
        return r.json()

    def reminders(
        self,
        list_name: str | None = None,
        show_completed: bool = False,
        limit: int = 100,
    ) -> list[dict]:
        params: dict = {"show_completed": show_completed, "limit": limit}
        if list_name:
            params["list_name"] = list_name
        r = self._client.get("/reminders", params=params)
        r.raise_for_status()
        return r.json()

    def reminder_complete(self, reminder_id: str) -> bool:
        r = self._client.post(f"/reminders/{reminder_id}/complete")
        r.raise_for_status()
        return r.json().get("ok", False)

    def reminder_create(
        self,
        title: str,
        list_name: str = "Reminders",
        due_date: str = "",
        notes: str = "",
    ) -> bool:
        r = self._client.post(
            "/reminders",
            json={
                "title": title,
                "list_name": list_name,
                "due_date": due_date,
                "notes": notes,
            },
        )
        r.raise_for_status()
        return r.json().get("ok", False)

    # ── GitHub ──────────────────────────────────────────────────────────

    def github_notifications(self, all_notifs: bool = False) -> list[dict]:
        r = self._client.get("/github/notifications", params={"all": all_notifs})
        r.raise_for_status()
        return r.json()

    def github_mark_read(self, notification_id: str) -> bool:
        r = self._client.post(f"/github/notifications/{notification_id}/read")
        r.raise_for_status()
        return r.json().get("ok", False)

    def github_mark_all_read(self) -> bool:
        r = self._client.post("/github/notifications/read-all")
        r.raise_for_status()
        return r.json().get("ok", False)

    def github_pulls(self, repo: str | None = None) -> list[dict]:
        params = {"repo": repo} if repo else {}
        r = self._client.get("/github/pulls", params=params)
        r.raise_for_status()
        return r.json()

    # ── Google Drive ────────────────────────────────────────────────────

    def drive_files(
        self,
        query: str = "",
        shared: bool = False,
        limit: int = 20,
        account: str = "",
    ) -> list[dict]:
        r = self._client.get(
            "/drive/files",
            params={"q": query, "shared": shared, "limit": limit, "account": account},
        )
        r.raise_for_status()
        return r.json()

    def drive_file(self, file_id: str, account: str = "") -> dict:
        r = self._client.get(f"/drive/files/{file_id}", params={"account": account})
        r.raise_for_status()
        return r.json()

    def drive_upload(self, file_path: str, folder_id: str = "", account: str = "") -> dict:
        from pathlib import Path as P

        p = P(file_path)
        with open(p, "rb") as f:
            r = self._client.post(
                "/drive/upload",
                files={"file": (p.name, f)},
                data={"folder_id": folder_id, "account": account},
                timeout=120,
            )
        r.raise_for_status()
        return r.json()

    def drive_create_folder(self, name: str, parent_id: str = "", account: str = "") -> dict:
        r = self._client.post(
            "/drive/folder",
            json={"name": name, "parent_id": parent_id, "account": account},
        )
        r.raise_for_status()
        return r.json()

    def drive_delete(self, file_id: str, account: str = "") -> bool:
        r = self._client.delete(f"/drive/files/{file_id}", params={"account": account})
        r.raise_for_status()
        return r.json().get("ok", False)

    # ── Accounts ─────────────────────────────────────────────────────────

    def accounts(self) -> dict:
        r = self._client.get("/accounts")
        r.raise_for_status()
        return r.json()

    def add_account(self) -> dict:
        r = self._client.post("/accounts/add", timeout=120)
        r.raise_for_status()
        return r.json()

    def reauth_account(self, email: str) -> dict:
        r = self._client.post("/accounts/reauth", json={"email": email}, timeout=120)
        r.raise_for_status()
        return r.json()

    # ── Ambient ─────────────────────────────────────────────────────────

    def ambient_start(self) -> dict:
        r = self._client.post("/ambient/start")
        r.raise_for_status()
        return r.json()

    def ambient_stop(self) -> dict:
        r = self._client.post("/ambient/stop")
        r.raise_for_status()
        return r.json()

    def ambient_status(self) -> dict:
        r = self._client.get("/ambient/status")
        r.raise_for_status()
        return r.json()

    def ambient_notes(self, limit: int = 30) -> list[dict]:
        r = self._client.get("/ambient/notes", params={"limit": limit})
        r.raise_for_status()
        return r.json()

    def ambient_note(self, date: str) -> dict:
        r = self._client.get(f"/ambient/notes/{date}")
        r.raise_for_status()
        return r.json()

    # ── Dictation ───────────────────────────────────────────────────────

    def dictation_start(self) -> dict:
        r = self._client.post("/dictation/start")
        r.raise_for_status()
        return r.json()

    def dictation_stop(self) -> dict:
        r = self._client.post("/dictation/stop")
        r.raise_for_status()
        return r.json()

    # ── Autocomplete ────────────────────────────────────────────────────

    def autocomplete(
        self, draft: str, messages: list[dict] | None = None, max_tokens: int = 32
    ) -> str | None:
        r = self._client.post(
            "/autocomplete",
            json={"draft": draft, "messages": messages or [], "max_tokens": max_tokens},
            timeout=10,
        )
        r.raise_for_status()
        return r.json().get("completion")

    # ── LLM ─────────────────────────────────────────────────────────────

    def llm_status(self) -> dict:
        r = self._client.get("/llm/status")
        r.raise_for_status()
        return r.json()

    def llm_warmup(self) -> dict:
        r = self._client.post("/llm/warmup", timeout=120)
        r.raise_for_status()
        return r.json()
