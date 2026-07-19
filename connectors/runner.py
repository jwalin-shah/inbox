"""
Connector runner — CLI entry point, scheduling, and the export state machine.

Usage:
    uv run python connectors/runner.py chatgpt <email>       # incremental sync
    uv run python connectors/runner.py claude <email>        # incremental sync
    uv run python connectors/runner.py chatgpt <email> --full-export  # request full ZIP export
    uv run python connectors/runner.py list                  # show all connectors
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from connectors.base import INBOX_DATA, STATE_DB, AuthStatus, JobStatus
from connectors.chatgpt.connector import ChatGPTConnector
from connectors.claude.connector import ClaudeConnector
from loguru import logger

logger.remove()
logger.add(sys.stderr, level="INFO", format="<green>{time:HH:mm:ss}</green> | {message}")


async def sync_chatgpt(account: str) -> None:
    conn = ChatGPTConnector(account_id=account)
    result = await conn.run("incremental")
    print_result(conn.connector_id, result)


async def sync_claude(account: str) -> None:
    conn = ClaudeConnector(account_id=account)
    result = await conn.run("incremental")
    print_result(conn.connector_id, result)


async def full_export_chatgpt(account: str) -> None:
    """Request and download a full ChatGPT export."""
    # TODO: ChatGPT full export flow — click Settings → Export → Confirm
    logger.info("ChatGPT full export: open browser and click through export UI")
    logger.info("Then use the Gmail API connector to watch for the completion email")


async def full_export_claude(account: str) -> None:
    conn = ClaudeConnector(account_id=account)

    # Auth check
    status = conn._get_auth_status()
    if status == AuthStatus.NEEDS_LOGIN:
        logger.info("Need login first — launching browser")
        ready = await conn.connect()
        if not ready:
            logger.error("Login failed")
            return

    await conn.probe()
    export_id = await conn.request_full_export()
    if not export_id:
        logger.error("Export request failed")
        return

    logger.info(f"Export requested: {export_id}")
    logger.info("Waiting 30s before first download attempt...")

    # Poll until ready
    for attempt in range(20):
        await asyncio.sleep(60)
        logger.info(f"Download attempt {attempt + 1}/20")
        path = await conn.download_export(export_id)
        if path:
            count = await conn.extract_and_ingest_export(export_id, path)
            logger.info(f"Export complete: {count} conversations ingested")
            return

    logger.warning("Export not ready after 20 minutes — will resume later")


def print_result(connector_id: str, result) -> None:
    print(f"\n{'='*60}")
    print(f"  {connector_id}")
    print(f"  Status:   {result.status.value}")
    print(f"  Synced:   {result.items_synced}")
    print(f"  Cursor:   {result.cursor or '—'}")
    print(f"  Error:    {result.error or '—'}")
    print(f"  Raw:      {[str(p) for p in result.raw_files]}")
    print(f"{'='*60}\n")


def list_connectors() -> None:
    db = sqlite3.connect(str(STATE_DB))
    rows = db.execute(
        "SELECT connector_id, service, account_id, auth_status, last_sync_at FROM connectors ORDER BY service"
    ).fetchall()
    print(f"\n{'Connector':<35} {'Service':<12} {'Status':<22} {'Last Sync'}")
    print("-" * 95)
    for row in rows:
        print(f"{row[0]:<35} {row[1]:<12} {row[2]:<22} {row[4] or 'never'}")
    print()


async def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return

    cmd = sys.argv[1]

    if cmd == "list":
        list_connectors()
    elif cmd == "chatgpt" and len(sys.argv) >= 3:
        account = sys.argv[2]
        if "--full-export" in sys.argv:
            await full_export_chatgpt(account)
        else:
            await sync_chatgpt(account)
    elif cmd == "claude" and len(sys.argv) >= 3:
        account = sys.argv[2]
        if "--full-export" in sys.argv:
            await full_export_claude(account)
        else:
            await sync_claude(account)
    else:
        print(f"Unknown command: {cmd}")
        print(__doc__)


if __name__ == "__main__":
    asyncio.run(main())
