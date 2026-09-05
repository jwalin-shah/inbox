"""
ChatGPT connector — Playwright persistent profile, in-page fetch(),
batch conversation retrieval, checkpoint per conversation ID.

Pattern adapted from Vana DataConnect's ChatGPT connector.

Architecture:
    Persistent browser profile → one-time manual login →
    extract session tokens → fetch() inside the authenticated page →
    batch conversation details → checkpoint ID + update_time →
    normalize to Chat Completions JSONL

Never: script password entry, fight Cloudflare programmatically,
        try to keep session alive through cookie export alone.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any

from loguru import logger
from playwright.async_api import async_playwright

from connectors.base import (
    PROFILES_DIR,
    AuthStatus,
    BaseConnector,
    JobStatus,
    SyncResult,
)

# ── ChatGPT internal API endpoints (unsupported — adapter must be replaceable) ──

CHATGPT_BASE = "https://chatgpt.com"
CONVERSATIONS_API = "https://chatgpt.com/backend-api/conversations"
CONVERSATION_API = "https://chatgpt.com/backend-api/conversation/{}"
BATCH_CONVERSATIONS_API = "https://chatgpt.com/backend-api/conversations/batch"

BATCH_SIZE = 10          # ChatGPT batch limit
RATE_LIMIT_DELAY = 2.0   # seconds between batches


class ChatGPTConnector(BaseConnector):
    service = "chatgpt"

    def __init__(self, account_id: str, config: dict[str, Any] | None = None):
        super().__init__(config)
        self.account_id = account_id
        self.connector_id = f"chatgpt:{account_id}"
        self.profile_path = PROFILES_DIR / "chatgpt" / account_id
        self.profile_path.mkdir(parents=True, exist_ok=True)
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None

    # ── Browser lifecycle ─────────────────────────────────────────

    async def _launch_browser(self, headless: bool = False) -> None:
        """Launch persistent Playwright context. Session survives restarts."""
        self._playwright = await async_playwright().start()
        self._context = await self._playwright.chromium.launch_persistent_context(
            str(self.profile_path),
            headless=headless,
            viewport={"width": 1280, "height": 800},
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/150.0.0.0 Safari/537.36"
            ),
        )
        pages = self._context.pages
        self._page = pages[0] if pages else await self._context.new_page()

    async def _close_browser(self) -> None:
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None
            self._browser = None
            self._context = None
            self._page = None

    # ── Auth ──────────────────────────────────────────────────────

    async def connect(self) -> bool:
        """Launch visible browser for one-time login. Returns True when authenticated."""
        await self._launch_browser(headless=False)
        await self._page.goto("https://chatgpt.com/auth/login", wait_until="domcontentloaded")

        logger.info(f"[{self.connector_id}] Browser open — log in manually, then press Enter here")
        # Wait for user to complete login (blocking, but correct for first run)
        input(">>> Press Enter once logged into ChatGPT...")

        # Verify we have a session
        try:
            await self._page.goto(CHATGPT_BASE, wait_until="domcontentloaded")
            await self._page.wait_for_selector('textarea[data-id="root"]', timeout=10000)
            self._set_auth_status(AuthStatus.READY)
            logger.info(f"[{self.connector_id}] Login verified")
            return True
        except Exception:
            logger.error(f"[{self.connector_id}] Login verification failed")
            return False

    async def probe(self) -> dict[str, Any]:
        """Verify account identity via the authenticated session."""
        if not self._page:
            await self._launch_browser(headless=True)

        # Extract session info from the ChatGPT page
        user_info = await self._page.evaluate("""() => {
            try {
                const raw = document.getElementById('__NEXT_DATA__')?.textContent;
                if (raw) {
                    const data = JSON.parse(raw);
                    const user = data?.props?.pageProps?.user;
                    return { email: user?.email, name: user?.name, id: user?.id };
                }
            } catch (e) {}
            return { email: null, name: null, id: null };
        }""")
        logger.info(f"[{self.connector_id}] Probe: {user_info}")
        return dict(user_info)

    # ── Conversation sync ─────────────────────────────────────────

    async def sync(self, job_id: str) -> SyncResult:
        """Retrieve conversations since last cursor using authenticated fetch()."""
        if not self._page:
            await self._launch_browser(headless=True)

        # Navigate to ChatGPT to establish the authenticated page context
        await self._page.goto(CHATGPT_BASE, wait_until="domcontentloaded")
        try:
            await self._page.wait_for_selector('textarea[data-id="root"]', timeout=15000)
        except Exception:
            return SyncResult(status=JobStatus.FAILED, error="auth_expired")

        # Get conversation list with update times
        conversations = await self._fetch_conversation_list()
        if not conversations:
            return SyncResult(items_synced=0, status=JobStatus.COMPLETE)

        # Filter to new/changed since last cursor
        cursor = self._get_cursor()
        if cursor:
            conversations = [c for c in conversations if self._is_newer(c, cursor)]
        logger.info(f"[{self.connector_id}] {len(conversations)} conversations to sync")

        # Fetch full conversation details in batches
        all_raw = []
        conv_ids = [c["id"] for c in conversations]
        for i in range(0, len(conv_ids), BATCH_SIZE):
            batch = conv_ids[i : i + BATCH_SIZE]
            details = await self._fetch_batch_details(batch)
            all_raw.extend(details)
            await asyncio.sleep(RATE_LIMIT_DELAY)

        # Save raw data
        batch_id = f"{job_id}-{int(time.time())}"
        raw_path = self._save_raw(all_raw, batch_id)

        # Normalize
        normalized = [self._normalize_conversation(c, "chatgpt", self.account_id) for c in all_raw]
        self._save_normalized(normalized)

        # New cursor = max update_time
        new_cursor = max(
            (c.get("update_time", "") for c in conversations), default=""
        )

        return SyncResult(
            items_synced=len(all_raw),
            cursor=new_cursor,
            checkpoint=batch_id,
            status=JobStatus.COMPLETE,
            raw_files=[raw_path],
        )

    # ── Internal API calls (in-page fetch) ────────────────────────

    async def _fetch_conversation_list(self, limit: int = 500) -> list[dict]:
        """Get conversation index with IDs and update timestamps."""
        result = await self._page.evaluate(
            """async ({limit}) => {
            try {
                const resp = await fetch(
                    `/backend-api/conversations?offset=0&limit=${limit}&order=updated`
                );
                if (!resp.ok) return [];
                const data = await resp.json();
                return (data.items || []).map(c => ({
                    id: c.id,
                    title: c.title || '',
                    create_time: c.create_time || '',
                    update_time: c.update_time || '',
                }));
            } catch (e) { return []; }
        }""",
            {"limit": limit},
        )
        return list(result)

    async def _fetch_batch_details(self, conv_ids: list[str]) -> list[dict]:
        """Fetch full conversation details in one batch request."""
        result = await self._page.evaluate(
            """async ({ids}) => {
            try {
                const resp = await fetch('/backend-api/conversations/batch', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ conversation_ids: ids }),
                });
                if (!resp.ok) return [];
                const data = await resp.json();
                return data.items || data.conversations || [];
            } catch (e) { return []; }
        }""",
            {"ids": conv_ids},
        )
        return list(result)

    async def _fetch_single_conversation(self, conv_id: str) -> dict | None:
        """Fetch a single conversation with full message tree (fallback)."""
        result = await self._page.evaluate(
            """async ({id}) => {
            try {
                const resp = await fetch(`/backend-api/conversation/${id}`);
                if (!resp.ok) return null;
                return await resp.json();
            } catch (e) { return null; }
        }""",
            {"id": conv_id},
        )
        return result

    # ── Helpers ───────────────────────────────────────────────────

    @staticmethod
    def _is_newer(conv: dict, cursor: str) -> bool:
        return (conv.get("update_time", "") or "") > cursor

    def _normalize_conversation(self, conv: dict, source: str, account_id: str) -> dict:
        """Normalize ChatGPT conversation to common schema."""
        messages = []
        # ChatGPT stores messages in a mapping tree — flatten to chronological list
        mapping = conv.get("mapping") or conv.get("message_map") or {}
        if mapping:
            for node in mapping.values():
                msg = node.get("message") or node
                if not msg or not msg.get("content"):
                    continue
                role = msg.get("author", {}).get("role", "unknown")
                if role == "assistant":
                    role = "assistant"
                elif role == "user":
                    role = "user"
                elif role == "system":
                    role = "system"

                content = msg.get("content", {})
                if isinstance(content, dict):
                    parts = content.get("parts", [])
                    text = "\n".join(str(p) for p in parts if isinstance(p, str))
                else:
                    text = str(content)

                messages.append({
                    "id": msg.get("id", ""),
                    "role": role,
                    "content": text,
                    "timestamp": msg.get("create_time", ""),
                })

        messages.sort(key=lambda m: m.get("timestamp", ""))

        return {
            "id": f"{source}:{account_id}:{conv.get('conversation_id', conv.get('id', ''))}",
            "source": source,
            "account_id": account_id,
            "external_id": str(conv.get("conversation_id", conv.get("id", ""))),
            "title": conv.get("title", ""),
            "created_at": conv.get("create_time", ""),
            "updated_at": conv.get("update_time", ""),
            "message_count": len(messages),
            "messages": messages,
            "metadata_json": json.dumps({
                "model": conv.get("model"),
                "plugin_ids": conv.get("plugin_ids", []),
            }),
        }


# ── CLI entry point ───────────────────────────────────────────────

async def main():
    import sys

    account = sys.argv[1] if len(sys.argv) > 1 else "jwalinshah13@gmail.com"
    connector = ChatGPTConnector(account_id=account)

    print(f"ChatGPT connector — {connector.connector_id}")
    print(f"Profile: {connector.profile_path}")
    print()

    result = await connector.run("incremental")
    print(f"\nResult: {result}")


if __name__ == "__main__":
    asyncio.run(main())
