"""Pure Inbox -> Bridge source adapter.

This module projects already-normalized Inbox records into the versioned Bridge
event envelope. It does not persist personal state, call a provider, or infer
execution policy from legacy fields.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping
from datetime import datetime
from typing import Any

BRIDGE_CONTRACT_VERSION = "bridge.contracts.v1"


def _required(record: Mapping[str, Any], *names: str) -> Any:
    for name in names:
        value = record.get(name)
        if value not in (None, ""):
            return value
    raise ValueError(f"record requires one of: {', '.join(names)}")


def _occurred_at(record: Mapping[str, Any]) -> str:
    value = _required(record, "occurred_at", "updated_at", "created_at")
    text = str(value)
    try:
        datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("record timestamp must be ISO-8601") from exc
    return text


def _metadata(record: Mapping[str, Any]) -> dict[str, str]:
    raw = record.get("metadata")
    if raw is None:
        return {}
    if not isinstance(raw, Mapping):
        raise ValueError("record metadata must be an object")
    return {str(key): str(value) for key, value in raw.items()}


def event_from_memory_entry(record: Mapping[str, Any]) -> dict[str, Any]:
    entry_id = str(_required(record, "id"))
    content = str(_required(record, "content", "text"))
    source = str(record.get("source") or "inbox")
    return {
        "version": BRIDGE_CONTRACT_VERSION,
        "id": f"inbox:memory:{entry_id}",
        "kind": "inbox.memory.capture",
        "source": "inbox",
        "external_id": entry_id,
        "occurred_at": _occurred_at(record),
        "payload": {
            "text": content,
            "subject": str(record.get("subject") or ""),
            "external_ref": source,
            "metadata": _metadata(record),
        },
    }


def event_from_message(record: Mapping[str, Any]) -> dict[str, Any]:
    external_id = str(_required(record, "message_id", "external_id", "id"))
    content = str(_required(record, "body", "content", "text"))
    source = str(record.get("source") or "unknown")
    return {
        "version": BRIDGE_CONTRACT_VERSION,
        "id": f"inbox:message:{source}:{external_id}",
        "kind": "inbox.message",
        "source": "inbox",
        "external_id": external_id,
        "occurred_at": _occurred_at(record),
        "payload": {
            "text": content,
            "subject": str(record.get("subject") or record.get("title") or ""),
            "external_ref": source,
            "metadata": _metadata(record),
        },
    }


def event_from_record(record: Mapping[str, Any], *, kind: str = "memory") -> dict[str, Any]:
    if kind == "memory":
        return event_from_memory_entry(record)
    if kind == "message":
        return event_from_message(record)
    raise ValueError(f"unsupported record kind: {kind}")


def _main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kind", choices=("memory", "message"), default="memory")
    args = parser.parse_args()
    try:
        record = json.load(sys.stdin)
        if not isinstance(record, Mapping):
            raise ValueError("input must be a JSON object")
        event = event_from_record(record, kind=args.kind)
    except (json.JSONDecodeError, ValueError) as exc:
        print(f"inbox_bridge_adapter: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(event, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
