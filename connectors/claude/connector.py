"""
Claude connector — Playwright persistent profile, in-page fetch(),
incremental conversation sync + official full export triggering.

Two modes:
    incremental:   fetch conversation list, diff against checkpoint, batch details
    full_export:   POST export endpoint, poll until ready, download ZIP

Pattern adapted from Vana DataConnect's Claude connector.

Architecture:
    Persistent browser profile → one-time manual login →
    extract org ID from page → authenticated fetch() calls →
    conversation index → checkpoint by leaf message UUID →
    normalize to Chat Completions JSONL

Export flow:
    connect (headed, one-time) → POST /api/organizations/:org/export_data
    → poll until ZIP ready → browser download → extract → ingest
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from loguru import logger
from playwright.async_api import async_playwright

from connectors.base import (
    INBOX_DATA,
    PROFILES_DIR,
    AuthStatus,
    BaseConnector,
    JobStatus,
    SyncResult,
)

CLAUDE_BASE = "https://claude.ai"
CLAUDE_API = "https://claude.ai/api"
EXPORT_DIR = INBOX_DATA / "raw-exports" / "claude"


class ClaudeConnector(BaseConnector):
    service = "claude"

    def __init__(self, account_id: str, config: dict[str, Any] | None = None):
        super().__init__(config)
        self.account_id = account_id
        self.connector_id = f"claude:{account_id}"
        self.profile_path = PROFILES_DIR / "claude" / account_id
        self.profile_path.mkdir(parents=True, exist_ok=True)
        EXPORT_DIR.mkdir(parents=True, exist_ok=True)
        self._playwright = None
        self._context = None
        self._page = None
        self._org_id: str | None = None

    # ── Browser lifecycle ─────────────────────────────────────────

    async def _launch_browser(self, headless: bool = False) -> None:
        self._playwright = await async_playwright().start()
        self._context = await self._playwright.chromium.launch_persistent_context(
            str(self.profile_path),
            headless=headless,
            viewport={"width": 1280, "height": 800},
        )
        pages = self._context.pages
        self._page = pages[0] if pages else await self._context.new_page()

    async def _close_browser(self) -> None:
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None
            self._context = None
            self._page = None

    # ── Auth ──────────────────────────────────────────────────────

    async def connect(self) -> bool:
        """Launch visible browser, wait for manual login."""
        await self._launch_browser(headless=False)
        await self._page.goto(f"{CLAUDE_BASE}/login", wait_until="domcontentloaded")
        logger.info(f"[{self.connector_id}] Browser open — log in manually, then press Enter")
        input(">>> Press Enter once logged into Claude...")

        try:
            await self._page.goto(CLAUDE_BASE, wait_until="domcontentloaded")
            await self._page.wait_for_selector('[data-testid="chat-input"]', timeout=15000)
            self._set_auth_status(AuthStatus.READY)
            logger.info(f"[{self.connector_id}] Login verified")
            return True
        except Exception:
            logger.error(f"[{self.connector_id}] Login verification failed")
            return False

    async def probe(self) -> dict[str, Any]:
        """Extract org ID and account info from the authenticated page."""
        if not self._page:
            await self._launch_browser(headless=True)
            await self._page.goto(CLAUDE_BASE, wait_until="domcontentloaded")

        info = await self._page.evaluate("""() => {
            try {
                // Extract org ID from the page or localStorage
                const orgId = localStorage.getItem('lastActiveOrg');
                // Also try the user object from window
                const userEl = document.querySelector('[data-testid="user-menu"]');
                return { org_id: orgId, has_user_menu: !!userEl };
            } catch (e) {
                return { org_id: null };
            }
        }""")
        self._org_id = info.get("org_id") or ""

        # If not in localStorage, extract from API call
        if not self._org_id:
            self._org_id = await self._page.evaluate("""async () => {
                try {
                    const resp = await fetch('/api/organizations');
                    const orgs = await resp.json();
                    return orgs?.[0]?.uuid || '';
                } catch (e) { return ''; }
            }""")

        logger.info(f"[{self.connector_id}] Org ID: {self._org_id}")
        return {"org_id": self._org_id, "connector": self.connector_id}

    # ── Incremental sync ──────────────────────────────────────────

    async def sync(self, job_id: str) -> SyncResult:
        """Incremental conversation sync — diff against checkpoint."""
        if not self._page:
            await self._launch_browser(headless=True)
            await self._page.goto(CLAUDE_BASE, wait_until="domcontentloaded")

        # Get all conversations
        conversations = await self._fetch_conversations()
        if not conversations:
            return SyncResult(items_synced=0, status=JobStatus.COMPLETE)

        # Filter to changed since last checkpoint
        checkpoint = self._get_checkpoint()
        if checkpoint:
            checkpoint_data = json.loads(checkpoint)
            conversations = [
                c for c in conversations
                if c.get("uuid") not in checkpoint_data.get("seen_uuids", set())
            ]

        logger.info(f"[{self.connector_id}] {len(conversations)} new/changed conversations")

        # Fetch full details for each
        all_raw = []
        for conv in conversations:
            detail = await self._fetch_conversation_detail(conv.get("uuid", ""))
            if detail:
                all_raw.append(detail)
            await asyncio.sleep(1.0)  # rate limit

        # Save raw
        batch_id = f"{job_id}-{int(time.time())}"
        raw_path = self._save_raw(all_raw, batch_id)

        # Normalize
        normalized = [self._normalize_conversation(c, "claude", self.account_id) for c in all_raw]
        self._save_normalized(normalized)

        # Update checkpoint = set of all seen UUIDs
        all_uuids = {c.get("uuid", "") for c in conversations}
        new_checkpoint = json.dumps({"seen_uuids": list(all_uuids), "updated_at": datetime.now(UTC).isoformat()})

        return SyncResult(
            items_synced=len(all_raw),
            cursor=str(len(all_raw)),
            checkpoint=new_checkpoint,
            status=JobStatus.COMPLETE,
            raw_files=[raw_path],
        )

    # ── Full export ───────────────────────────────────────────────

    async def request_full_export(self) -> str | None:
        """POST the export endpoint. Returns export nonce/ID."""
        if not self._page or not self._org_id:
            await self._launch_browser(headless=True)
            await self._page.goto(CLAUDE_BASE, wait_until="domcontentloaded")
            await self.probe()

        result = await self._page.evaluate(
            """async ({orgId}) => {
            try {
                const resp = await fetch(`/api/organizations/${orgId}/export_data`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                });
                if (!resp.ok) return { error: `HTTP ${resp.status}` };
                return await resp.json();
            } catch (e) { return { error: e.message }; }
        }""",
            {"orgId": self._org_id},
        )
        export_id = result.get("id") or result.get("export_id")
        if export_id:
            logger.info(f"[{self.connector_id}] Export requested: {export_id}")
            # Record in state
            self._db.execute(
                "INSERT INTO raw_exports (export_id, connector_id, export_type, status, requested_at) VALUES (?,?,?,?,?)",
                (export_id, self.connector_id, "full_export", "requested", datetime.now(UTC).isoformat()),
            )
            self._db.commit()
        return export_id

    async def download_export(self, export_id: str) -> Path | None:
        """Download the completed export ZIP through the authenticated browser."""
        if not self._page:
            await self._launch_browser(headless=True)
            await self._page.goto(f"{CLAUDE_BASE}/settings/data", wait_until="domcontentloaded")

        download_path = EXPORT_DIR / self.account_id / f"{export_id}.zip"
        download_path.parent.mkdir(parents=True, exist_ok=True)

        # Click the download button or fetch the download URL via API
        downloaded = await self._page.evaluate(
            """async ({exportId}) => {
            try {
                // Try the export download endpoint
                const resp = await fetch(`/api/organizations/export_data/${exportId}/download`);
                if (!resp.ok) return { error: `HTTP ${resp.status}` };
                const blob = await resp.blob();
                // Convert blob to base64 for transfer
                const reader = new FileReader();
                return new Promise((resolve) => {
                    reader.onloadend = () => resolve({ data: reader.result });
                    reader.readAsDataURL(blob);
                });
            } catch (e) { return { error: e.message }; }
        }""",
            {"exportId": export_id},
        )

        if downloaded.get("data"):
            import base64

            data = downloaded["data"]
            # Strip data URL prefix
            b64 = data.split(",", 1)[1] if "," in data else data
            download_path.write_bytes(base64.b64decode(b64))
            sha = hashlib.sha256(download_path.read_bytes()).hexdigest()
            logger.info(f"[{self.connector_id}] Downloaded: {download_path} ({sha[:16]}...)")

            self._db.execute(
                "UPDATE raw_exports SET file_path=?, sha256=?, status=?, downloaded_at=? WHERE export_id=?",
                (str(download_path), sha, "downloaded", datetime.now(UTC).isoformat(), export_id),
            )
            self._db.commit()
            return download_path

        logger.warning(f"[{self.connector_id}] Download not ready yet: {downloaded}")
        return None

    async def extract_and_ingest_export(self, export_id: str, zip_path: Path) -> int:
        """Extract ZIP, normalize conversations, return count."""
        extract_dir = zip_path.with_suffix("")
        extract_dir.mkdir(exist_ok=True)

        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(extract_dir)

        # Find conversation JSON files
        conv_files = list(extract_dir.rglob("*.json"))
        conversations = []
        for f in conv_files:
            try:
                data = json.loads(f.read_text())
                if isinstance(data, list):
                    conversations.extend(data)
                elif isinstance(data, dict):
                    conversations.append(data)
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue

        normalized = [self._normalize_conversation(c, "claude", self.account_id) for c in conversations]
        self._save_normalized(normalized)

        self._db.execute(
            "UPDATE raw_exports SET item_count=?, status=?, extracted_at=?, ingested_at=? WHERE export_id=?",
            (len(conversations), "ingested", datetime.now(UTC).isoformat(), datetime.now(UTC).isoformat(), export_id),
        )
        self._db.commit()
        return len(conversations)

    # ── Internal API calls (in-page fetch) ────────────────────────

    async def _fetch_conversations(self, limit: int = 500) -> list[dict]:
        result = await self._page.evaluate(
            """async ({orgId, limit}) => {
            try {
                const resp = await fetch(`/api/organizations/${orgId}/chat_conversations?limit=${limit}`);
                if (!resp.ok) return [];
                return await resp.json();
            } catch (e) { return []; }
        }""",
            {"orgId": self._org_id or "", "limit": limit},
        )
        return list(result)

    async def _fetch_conversation_detail(self, conv_uuid: str) -> dict | None:
        result = await self._page.evaluate(
            """async ({orgId, uuid}) => {
            try {
                const resp = await fetch(`/api/organizations/${orgId}/chat_conversations/${uuid}`);
                if (!resp.ok) return null;
                return await resp.json();
            } catch (e) { return null; }
        }""",
            {"orgId": self._org_id or "", "uuid": conv_uuid},
        )
        return result

    # ── Normalization ─────────────────────────────────────────────

    def _normalize_conversation(self, conv: dict, source: str, account_id: str) -> dict:
        messages = []
        chat_messages = conv.get("chat_messages") or conv.get("messages") or []
        for msg in chat_messages:
            messages.append({
                "id": msg.get("uuid", ""),
                "role": msg.get("sender", "unknown"),
                "content": "\n".join(
                    block.get("text", "")
                    for block in (msg.get("content", []) if isinstance(msg.get("content"), list) else [])
                ),
                "timestamp": msg.get("created_at", ""),
            })

        return {
            "id": f"{source}:{account_id}:{conv.get('uuid', '')}",
            "source": source,
            "account_id": account_id,
            "external_id": conv.get("uuid", ""),
            "title": conv.get("name", ""),
            "created_at": conv.get("created_at", ""),
            "updated_at": conv.get("updated_at", ""),
            "message_count": len(messages),
            "messages": messages,
            "metadata_json": json.dumps(conv.get("metadata", {})),
        }


# ── CLI ───────────────────────────────────────────────────────────

async def main():
    import sys

    account = sys.argv[1] if len(sys.argv) > 1 else "jwalinshah13@gmail.com"
    connector = ClaudeConnector(account_id=account)

    print(f"Claude connector — {connector.connector_id}")
    print(f"Profile: {connector.profile_path}")
    print()

    result = await connector.run("incremental")
    print(f"\nResult: {result}")


if __name__ == "__main__":
    asyncio.run(main())
