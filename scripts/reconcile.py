#!/usr/bin/env python3
"""Read-only cross-channel reconciliation via connector search.

Connector CLIs: gog, imsg, wacli.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
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
STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "the",
    "to",
    "with",
}
CONFIRMED_SCORE = 0.75
CANDIDATE_SCORE = 0.35


def _selected_connector_ids(sources: list[str] | None) -> list[str]:
    wanted = set(sources or ["all"])
    return [
        connector.id
        for connector in CONNECTORS
        if "all" in wanted or connector.id in wanted or connector.category in wanted
    ]


def _tokens(text: str) -> list[str]:
    return [
        token
        for token in re.findall(r"[a-z0-9]+", text.lower())
        if len(token) > 1 and token not in STOPWORDS
    ]


def _fingerprint(item: dict[str, Any]) -> str:
    source = str(item.get("source") or "")
    result_id = str(item.get("id") or "")
    if source and result_id:
        return f"{source}:{result_id}"
    text = " ".join(str(item.get(key, "")) for key in ("title", "snippet", "timestamp"))
    tokens = sorted(set(_tokens(text)))
    if tokens:
        return " ".join(tokens[:16])
    digest = hashlib.sha256(json.dumps(item, sort_keys=True, default=str).encode()).hexdigest()
    return digest[:16]


def _match_state(score: float) -> str:
    if score >= CONFIRMED_SCORE:
        return "confirmed"
    if score >= CANDIDATE_SCORE:
        return "candidate"
    return "weak"


def _annotate_result(query: str, item: dict[str, Any]) -> dict[str, Any]:
    query_terms = set(_tokens(query))
    title_terms = set(_tokens(str(item.get("title", ""))))
    body_terms = set(
        _tokens(" ".join(str(item.get(key, "")) for key in ("title", "snippet")))
    )
    matched_terms = sorted(query_terms & body_terms)
    missing_terms = sorted(query_terms - body_terms)
    coverage = len(matched_terms) / len(query_terms) if query_terms else 0.0
    title_coverage = len(query_terms & title_terms) / len(query_terms) if query_terms else 0.0
    haystack = " ".join(str(item.get(key, "")) for key in ("title", "snippet")).lower()
    exact_phrase = bool(query.strip()) and query.strip().lower() in haystack
    score = min(1.0, (0.45 if exact_phrase else 0.0) + (coverage * 0.45) + (title_coverage * 0.10))

    annotated = dict(item)
    annotated["reconciliation"] = {
        "score": round(score, 3),
        "state": _match_state(score),
        "matched_terms": matched_terms,
        "missing_terms": missing_terms,
        "exact_phrase": exact_phrase,
        "fingerprint": _fingerprint(item),
    }
    return annotated


def _dedupe_results(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: dict[str, dict[str, Any]] = {}
    for item in results:
        reconciliation = item.get("reconciliation") or {}
        key = str(reconciliation.get("fingerprint") or _fingerprint(item))
        existing = deduped.get(key)
        if existing is None:
            deduped[key] = item
            continue
        existing_score = (existing.get("reconciliation") or {}).get("score", 0)
        item_score = reconciliation.get("score", 0)
        if (item_score, item.get("timestamp", "")) > (existing_score, existing.get("timestamp", "")):
            deduped[key] = item
    return list(deduped.values())


def _channel_reconciliation(hits: list[dict[str, Any]]) -> dict[str, Any]:
    scores = [(item.get("reconciliation") or {}).get("score", 0.0) for item in hits]
    best_score = max(scores, default=0.0)
    matched_terms = sorted(
        {
            term
            for item in hits
            for term in (item.get("reconciliation") or {}).get("matched_terms", [])
        }
    )
    missing_terms = sorted(
        {
            term
            for item in hits
            for term in (item.get("reconciliation") or {}).get("missing_terms", [])
        }
        - set(matched_terms)
    )
    return {
        "state": _match_state(best_score) if hits else "empty",
        "best_score": round(best_score, 3),
        "matched_terms": matched_terms,
        "missing_terms": missing_terms,
    }


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
    annotated_results = [_annotate_result(query, item) for item in search.get("results", [])]
    annotated_results = _dedupe_results(annotated_results)
    annotated_results.sort(
        key=lambda item: (
            (item.get("reconciliation") or {}).get("score", 0.0),
            item.get("timestamp", ""),
        ),
        reverse=True,
    )
    for item in annotated_results:
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
        reconciliation = _channel_reconciliation(hits)
        channels[connector_id] = {
            "state": state,
            "hits": len(hits),
            "results": hits,
            "error": error or None,
            "reconciliation": reconciliation,
        }

    channels_with_hits = sum(1 for item in channels.values() if item["hits"] > 0)
    channels_with_errors = sum(1 for item in channels.values() if item["error"])
    channels_confirmed = sum(
        1
        for item in channels.values()
        if (item.get("reconciliation") or {}).get("state") == "confirmed"
    )
    channels_candidates = sum(
        1
        for item in channels.values()
        if (item.get("reconciliation") or {}).get("state") == "candidate"
    )
    duplicate_groups = len(search.get("results", [])) - len(annotated_results)

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(UTC).isoformat(),
        "query": query,
        "limit": limit,
        "sources": requested,
        "summary": {
            "total_hits": len(annotated_results),
            "raw_hits": search.get("total", len(search.get("results", []))),
            "channels_requested": len(channels),
            "channels_with_hits": channels_with_hits,
            "channels_with_errors": channels_with_errors,
            "channels_empty": len(channels) - channels_with_hits - channels_with_errors,
            "channels_confirmed": channels_confirmed,
            "channels_candidates": channels_candidates,
            "duplicate_results_removed": duplicate_groups,
        },
        "channels": channels,
        "timeline": annotated_results,
        "errors": search.get("errors", []),
    }


def format_text(report: dict[str, Any]) -> str:
    """Render a human-readable reconciliation report."""
    lines = [
        f"Reconcile: {report.get('query', '')}",
        f"Hits: {report['summary']['total_hits']} across "
        f"{report['summary']['channels_with_hits']} channel(s)",
        f"Confirmed: {report['summary'].get('channels_confirmed', 0)} channel(s), "
        f"candidates: {report['summary'].get('channels_candidates', 0)}",
    ]
    if report["summary"].get("duplicate_results_removed"):
        lines.append(f"Duplicates removed: {report['summary']['duplicate_results_removed']}")
    if report["summary"]["channels_with_errors"]:
        lines.append(f"Errors: {report['summary']['channels_with_errors']} channel(s)")

    for connector_id, channel in sorted(report.get("channels", {}).items()):
        state = channel["state"]
        hits = channel["hits"]
        reconciliation = channel.get("reconciliation") or {}
        if state == "ok":
            match_state = reconciliation.get("state", "weak")
            score = reconciliation.get("best_score", 0)
            matched = ", ".join(reconciliation.get("matched_terms", [])[:8]) or "none"
            lines.append(f"  {connector_id}: {hits} hit(s), {match_state} match ({score})")
            lines.append(f"    matched terms: {matched}")
            for top in channel["results"][:3]:
                item_reconciliation = top.get("reconciliation") or {}
                lines.append(
                    f"    - {item_reconciliation.get('score', 0)} "
                    f"{top.get('title', '')}: {top.get('snippet', '')[:120]}"
                )
        elif state == "empty":
            lines.append(f"  {connector_id}: no hits")
        else:
            detail = (channel.get("error") or {}).get("error", state)
            lines.append(f"  {connector_id}: {detail}")

    for item in report.get("timeline", [])[:5]:
        reconciliation = item.get("reconciliation") or {}
        lines.append(
            f"  [{item.get('source', '')} score={reconciliation.get('score', 0)}] "
            f"{item.get('timestamp', '')} "
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
