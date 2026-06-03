#!/usr/bin/env python3
"""Read-only cross-channel reconciliation via connector search."""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from connector_registry import CONNECTORS, search_connectors  # noqa: E402

SCHEMA_VERSION = "inbox.reconcile.v1"


def _selected_connector_ids(sources: list[str] | None) -> list[str]:
    wanted = set(sources or ["all"])
    return [
        connector.id
        for connector in CONNECTORS
        if "all" in wanted or connector.id in wanted or connector.category in wanted
    ]


def build_report(
    query: str,
    *,
    sources: list[str] | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    """Search connectors and summarize per-channel coverage for one query."""
    requested = list(sources or ["all"])
    search = search_connectors(query, sources=requested, limit=limit)
    by_source: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in search.get("results", []):
        by_source[str(item.get("source", ""))].append(item)

    errors_by_source = {
        str(err.get("source", "")): err for err in search.get("errors", [])
    }
    channels: dict[str, dict[str, Any]] = {}
    for connector_id in _selected_connector_ids(requested):
        error = errors_by_source.get(connector_id)
        hits = by_source.get(connector_id, [])
        if error:
            state = str(error.get("error", "error"))
        elif hits:
            state = "ok"
        else:
            state = "empty"
        channels[connector_id] = {
            "state": state,
            "hits": len(hits),
            "results": hits,
            "error": error or None,
        }

    channels_with_hits = sum(1 for item in channels.values() if item["hits"] > 0)
    channels_with_errors = sum(1 for item in channels.values() if item["error"])

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(UTC).isoformat(),
        "query": query,
        "limit": limit,
        "sources": requested,
        "summary": {
            "total_hits": search.get("total", 0),
            "channels_requested": len(channels),
            "channels_with_hits": channels_with_hits,
            "channels_with_errors": channels_with_errors,
            "channels_empty": len(channels) - channels_with_hits - channels_with_errors,
        },
        "channels": channels,
        "timeline": search.get("results", []),
        "errors": search.get("errors", []),
    }


def format_text(report: dict[str, Any]) -> str:
    """Render a human-readable reconciliation report."""
    lines = [
        f"Reconcile: {report.get('query', '')}",
        f"Hits: {report['summary']['total_hits']} across "
        f"{report['summary']['channels_with_hits']} channel(s)",
    ]
    if report["summary"]["channels_with_errors"]:
        lines.append(f"Errors: {report['summary']['channels_with_errors']} channel(s)")

    for connector_id, channel in sorted(report.get("channels", {}).items()):
        state = channel["state"]
        hits = channel["hits"]
        if state == "ok":
            lines.append(f"  {connector_id}: {hits} hit(s)")
            top = channel["results"][0]
            lines.append(f"    latest: {top.get('title', '')} — {top.get('snippet', '')[:120]}")
        elif state == "empty":
            lines.append(f"  {connector_id}: no hits")
        else:
            detail = (channel.get("error") or {}).get("error", state)
            lines.append(f"  {connector_id}: {detail}")

    for item in report.get("timeline", [])[:5]:
        lines.append(
            f"  [{item.get('source', '')}] {item.get('timestamp', '')} "
            f"{item.get('title', '')}: {str(item.get('snippet', ''))[:80]}"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Read-only cross-channel search reconciliation via connector CLIs."
    )
    parser.add_argument("query", help="Search text to reconcile across connector channels.")
    parser.add_argument(
        "--sources",
        default="all",
        help="Comma-separated connector ids/categories or 'all' (default: all).",
    )
    parser.add_argument("--limit", type=int, default=20, help="Max merged hits (default: 20).")
    parser.add_argument("--json", action="store_true", help="Emit the report as JSON on stdout.")
    args = parser.parse_args(argv)

    sources = [part.strip() for part in args.sources.split(",") if part.strip()]
    report = build_report(args.query, sources=sources or ["all"], limit=max(1, args.limit))
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(format_text(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
