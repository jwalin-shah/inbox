"""Build the bounded, read-only LifeOps current-context projection."""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, is_dataclass
from datetime import UTC, datetime
from typing import Any

SECTION_TYPES: dict[str, frozenset[str]] = {
    "people": frozenset({"person", "contact", "relationship", "person_note", "person_preference"}),
    "projects": frozenset({"project", "project_note"}),
    "goals": frozenset({"goal", "objective"}),
    "decisions": frozenset({"decision"}),
    "commitments": frozenset({"commitment", "task", "action", "reminder"}),
    "notes": frozenset({"note", "memory", "preference"}),
}

_DEFERRED_LIMITATIONS = (
    "embeddings_not_part_of_context_v1",
    "drive_documents_not_part_of_context_v1",
    "agent_runtime_memory_not_imported",
)


def _checked_at() -> str:
    return datetime.now(UTC).isoformat()


def _memory_ref(entry: dict[str, Any]) -> dict[str, str]:
    reference = {
        "kind": "memory_entry",
        "source": str(entry.get("source") or "lifeops_memory"),
        "id": str(entry.get("id") or ""),
        "memory_type": str(entry.get("memory_type") or ""),
    }
    metadata = entry.get("metadata")
    if isinstance(metadata, dict) and metadata.get("capture_id"):
        reference["capture_id"] = str(metadata["capture_id"])
    return reference


def _memory_item(entry: dict[str, Any]) -> dict[str, Any]:
    entry_id = str(entry.get("id") or "")
    return {
        "item_id": f"lifeops_memory:{entry_id}",
        "local_memory_id": entry_id,
        "title": str(entry.get("subject") or "Untitled"),
        "content": str(entry.get("content") or ""),
        "memory_type": str(entry.get("memory_type") or ""),
        "source": str(entry.get("source") or "lifeops_memory"),
        "confidence": entry.get("confidence"),
        "status": str(entry.get("status") or "active"),
        "created_at": entry.get("created_at"),
        "updated_at": entry.get("updated_at"),
        "expires_at": entry.get("expires_at"),
        "metadata": entry.get("metadata") or {},
        "source_ref": _memory_ref(entry),
    }


def _project_key(subject: str) -> str:
    """Build a conservative identity key without semantic inference."""
    return "".join(character for character in subject.casefold() if character.isalnum())


def _project_item(entries: list[dict[str, Any]]) -> dict[str, Any]:
    """Merge explicitly named project records while retaining all evidence."""
    ordered = sorted(
        entries,
        key=lambda entry: (str(entry.get("updated_at") or ""), str(entry.get("id") or "")),
        reverse=True,
    )
    primary = _memory_item(ordered[0])
    project_key = _project_key(str(ordered[0].get("subject") or "project")) or "project"
    evidence_refs: list[dict[str, Any]] = []
    linked_refs: list[dict[str, Any]] = []
    local_ids: list[str] = []
    seen_refs: set[str] = set()
    for entry in ordered:
        local_id = str(entry.get("id") or "")
        if local_id:
            local_ids.append(local_id)
        ref = _memory_ref(entry)
        ref_key = repr(sorted(ref.items()))
        if ref_key not in seen_refs:
            seen_refs.add(ref_key)
            evidence_refs.append(ref)
        metadata = entry.get("metadata")
        if isinstance(metadata, dict) and isinstance(metadata.get("source_refs"), list):
            for linked in metadata["source_refs"]:
                if isinstance(linked, dict) and linked.get("source") and linked.get("id"):
                    linked_key = repr(sorted(linked.items()))
                    if linked_key not in seen_refs:
                        seen_refs.add(linked_key)
                        linked_refs.append(dict(linked))
    primary["project_key"] = project_key
    primary["evidence_count"] = len(evidence_refs)
    primary["evidence_refs"] = evidence_refs
    primary["linked_source_refs"] = linked_refs
    primary["local_memory_ids"] = local_ids
    primary["source_ref"] = {**primary["source_ref"], "project_key": project_key}
    return primary


def _project_row_entry(row: dict[str, Any]) -> dict[str, Any] | None:
    """Adapt one explicit tracker row into the existing project read model."""
    project = str(row.get("project") or "").strip()
    source_ref = row.get("source_ref")
    if not project or not isinstance(source_ref, dict) or not source_ref.get("id"):
        return None
    details = [
        str(row.get("desired_outcome") or "").strip(),
        str(row.get("next_action") or "").strip(),
        str(row.get("next_milestone") or "").strip(),
        str(row.get("notes") or "").strip(),
    ]
    return {
        "id": f"project_record:{source_ref['id']}",
        "memory_type": "project",
        "subject": project,
        "content": "\n".join(value for value in details if value),
        "source": "google_sheets",
        "status": str(row.get("status") or "active").strip().casefold() or "active",
        "metadata": {
            "source_refs": [dict(source_ref)],
            "area": str(row.get("area") or "").strip(),
            "canonical_system": str(row.get("canonical_system") or "").strip(),
            "main_link": str(row.get("main_link") or "").strip(),
            "notion_link": str(row.get("notion_link") or "").strip(),
            "drive_folder": str(row.get("drive_folder") or "").strip(),
            "deadline": row.get("deadline"),
            "next_action": str(row.get("next_action") or "").strip(),
            "desired_outcome": str(row.get("desired_outcome") or "").strip(),
            "next_milestone": str(row.get("next_milestone") or "").strip(),
            "review_cadence": str(row.get("review_cadence") or "").strip(),
            "owner": str(row.get("owner") or "").strip(),
            "budget": row.get("budget"),
            "source_of_truth": str(row.get("source_of_truth") or "").strip(),
        },
    }


def _attention_item(item: dict[str, Any]) -> dict[str, Any]:
    source_ref = item.get("source_ref") or item.get("ref") or {}
    return {
        "item_id": str(item.get("item_id") or ""),
        "title": str(item.get("title") or "Untitled"),
        "source": str(item.get("source") or "unknown"),
        "state": str(item.get("state") or ""),
        "attention_class": str(item.get("attention_class") or ""),
        "reason": str(item.get("reason") or ""),
        "due_at": item.get("due_at"),
        "workflow": str(item.get("workflow") or ""),
        "source_ref": source_ref,
        "details": item.get("details") or {},
    }


def _master_ops_attention_item(row: dict[str, Any]) -> dict[str, Any] | None:
    """Project one curated Master Tracker email-action row into attention."""
    source_ref = row.get("source_ref")
    if not isinstance(source_ref, dict) or not source_ref.get("id"):
        return None
    status = str(row.get("status") or "open").strip().casefold()
    if status in {"closed", "done", "completed", "archive", "archived", "cancelled"}:
        return None
    title = str(row.get("subject") or row.get("text") or row.get("title") or "").strip()
    if not title:
        return None
    details = {
        key: value
        for key, value in row.items()
        if key not in {"source_ref", "subject", "text", "title", "status"}
    }
    return {
        "item_id": f"master_ops_queue:{source_ref['id']}",
        "title": title,
        "source": "google_sheets",
        "state": status,
        "attention_class": "curated_email_action",
        "reason": str(row.get("action_needed") or row.get("notes") or "").strip(),
        "due_at": row.get("due_date") or row.get("due"),
        "workflow": "master_tracker_email_action_queue",
        "source_ref": source_ref,
        "details": details,
    }


def _commitment_item(item: dict[str, Any]) -> dict[str, Any] | None:
    commitment_id = str(item.get("commitment_id") or "")
    if not commitment_id:
        return None
    capture_id = str(item.get("capture_id") or "")
    source_ref = {
        "kind": "life_commitment",
        "source": "lifeops",
        "id": commitment_id,
    }
    if capture_id:
        source_ref["capture_id"] = capture_id
    return {
        "item_id": f"lifeops_commitment:{commitment_id}",
        "title": str(item.get("title") or "Untitled commitment"),
        "source": "lifeops",
        "owner": str(item.get("owner") or ""),
        "state": str(item.get("state") or ""),
        "next_condition": str(item.get("next_condition") or ""),
        "next_condition_at": item.get("next_condition_at"),
        "confidence": item.get("confidence"),
        "capture_id": capture_id,
        "source_ref": source_ref,
    }


def _person_item(profile: Any) -> dict[str, Any] | None:
    """Convert Inbox's unified contact profile into a context item."""
    raw = asdict(profile) if is_dataclass(profile) else profile
    if not isinstance(raw, dict):
        return None
    contact_id = str(raw.get("contact_id") or "")
    if not contact_id:
        return None
    return {
        "item_id": f"unified_contact:{contact_id}",
        "contact_id": contact_id,
        "title": str(raw.get("name") or "Unknown contact"),
        "source": "inbox.unified_contacts.v1",
        "identifiers": list(raw.get("identifiers") or []),
        "sources": list(raw.get("sources") or []),
        "total_interactions": raw.get("total_interactions", 0),
        "first_interaction_at": raw.get("first_interaction_at"),
        "last_interaction_at": raw.get("last_interaction_at"),
        "relationship_score": raw.get("relationship_score"),
        "relationship_tier": raw.get("relationship_tier"),
        "communication_preferences": raw.get("communication_preferences") or {},
        "interaction_history": raw.get("interaction_history") or [],
        "source_ref": {
            "kind": "unified_contact_profile",
            "source": "inbox.unified_contacts.v1",
            "id": contact_id,
        },
    }


def _person_name_key(value: Any) -> str:
    return "".join(character for character in str(value or "").casefold() if character.isalnum())


def _lifeops_person_item(
    row: dict[str, Any], contact_rows: list[dict[str, Any]] | None = None
) -> dict[str, Any] | None:
    """Project an explicit LifeOps People row with conservative identity matching."""
    source_ref = row.get("source_ref")
    person_id = str(row.get("person_id") or "").strip()
    name = str(row.get("name") or "").strip()
    if not person_id or not name or not isinstance(source_ref, dict) or not source_ref.get("id"):
        return None
    matches = [
        contact
        for contact in contact_rows or []
        if isinstance(contact, dict)
        and _person_name_key(contact.get("name") or contact.get("display_name"))
        == _person_name_key(name)
    ]
    linked_source_refs: list[dict[str, Any]] = []
    identity_resolution = {"status": "unmatched", "method": "exact_name"}
    if len(matches) == 1:
        contact_id = str(matches[0].get("id") or matches[0].get("contact_id") or "")
        if contact_id:
            identity_resolution = {
                "status": "matched",
                "method": "exact_name",
                "contact_id": contact_id,
            }
            linked_source_refs.append(
                {
                    "kind": "contact_record",
                    "source": "contacts",
                    "id": contact_id,
                }
            )
    elif len(matches) > 1:
        identity_resolution = {"status": "ambiguous", "method": "exact_name", "match_count": len(matches)}
    return {
        "item_id": f"lifeops_sheet_person:{person_id}",
        "contact_id": person_id,
        "title": name,
        "source": "lifeops_sheet",
        "organization": str(row.get("organization") or "").strip(),
        "role": str(row.get("role") or "").strip(),
        "relationship_context": str(row.get("relationship_context") or "").strip(),
        "what_they_are_working_on": str(row.get("what_they_are_working_on") or "").strip(),
        "last_interaction_at": row.get("last_interaction"),
        "open_loop": str(row.get("open_loop") or "").strip(),
        "next_condition": str(row.get("next_condition") or "").strip(),
        "importance": str(row.get("importance") or "").strip(),
        "identity_confidence": row.get("identity_confidence"),
        "fact_confidence": row.get("fact_confidence"),
        "identity_resolution": identity_resolution,
        "linked_source_refs": linked_source_refs,
        "source_ref": source_ref,
    }


def _lifeops_action_item(row: dict[str, Any]) -> dict[str, Any] | None:
    """Project an explicit LifeOps Actions row into the open commitment view."""
    source_ref = row.get("source_ref")
    action_id = str(row.get("action_id") or "").strip()
    action = str(row.get("action") or "").strip()
    state = str(row.get("state") or "").strip()
    if not action_id or not action or not isinstance(source_ref, dict) or not source_ref.get("id"):
        return None
    if state.casefold() in {"done", "completed", "closed", "cancelled"}:
        return None
    return {
        "item_id": f"lifeops_sheet_action:{action_id}",
        "title": action,
        "source": "lifeops_sheet",
        "state": state or "OPEN",
        "owner": str(row.get("owner") or "").strip(),
        "related_person": str(row.get("related_person") or "").strip(),
        "related_project": str(row.get("related_project") or "").strip(),
        "next_condition": str(row.get("next_condition") or "").strip(),
        "time_sensitivity": str(row.get("time_sensitivity") or "").strip(),
        "priority": str(row.get("priority") or "").strip(),
        "machine_doable": str(row.get("machine_doable") or "").strip(),
        "verification": str(row.get("verification") or "").strip(),
        "source_ref": source_ref,
    }


def _place_item(event: Any) -> dict[str, Any] | None:
    """Convert a Calendar event with a location into a place observation."""
    if not isinstance(event, dict):
        return None
    location = str(event.get("location") or "").strip()
    if not location:
        return None
    event_id = str(event.get("event_id") or "")
    calendar_id = str(event.get("calendar_id") or "")
    account = str(event.get("account") or "")
    identity = event_id or ":".join(
        part for part in (calendar_id, account, str(event.get("start") or "")) if part
    )
    if not identity:
        return None
    return {
        "item_id": f"calendar_place:{identity}",
        "title": location,
        "source": "calendar",
        "place": location,
        "event_summary": str(event.get("summary") or "Untitled event"),
        "starts_at": event.get("start"),
        "ends_at": event.get("end"),
        "account": account,
        "calendar_id": calendar_id,
        "event_id": event_id,
        "source_ref": {
            "kind": "calendar_event",
            "source": "calendar",
            "id": event_id or identity,
            "calendar_id": calendar_id,
            "account": account,
        },
    }


def _contact_place_item(contact: Any, address: Any, index: int) -> dict[str, Any] | None:
    """Convert an explicit contact address into a provenance-backed place."""
    if not isinstance(contact, dict) or not isinstance(address, dict):
        return None
    contact_id = str(contact.get("id") or contact.get("contact_id") or "")
    location = str(
        address.get("formatted")
        or address.get("formattedValue")
        or address.get("street")
        or address.get("streetAddress")
        or ""
    ).strip()
    if not contact_id or not location:
        return None
    return {
        "item_id": f"contact_place:{contact_id}:{index}",
        "title": location,
        "source": "contacts",
        "place": location,
        "contact_id": contact_id,
        "contact_name": str(contact.get("name") or ""),
        "label": str(address.get("label") or address.get("type") or ""),
        "source_ref": {
            "kind": "contact_address",
            "source": "contacts",
            "id": contact_id,
            "address_index": index,
            "account": str(address.get("source_account") or ""),
        },
    }


def _section_for_type(memory_type: str) -> str:
    for section, types in SECTION_TYPES.items():
        if memory_type in types:
            return section
    return "notes"


def build_context(
    *,
    memory_entries: list[dict[str, Any]],
    triage: dict[str, Any],
    people_profiles: list[Any] | None = None,
    people_metadata: dict[str, Any] | None = None,
    calendar_events: list[dict[str, Any]] | None = None,
    calendar_metadata: dict[str, Any] | None = None,
    contact_rows: list[dict[str, Any]] | None = None,
    contact_metadata: dict[str, Any] | None = None,
    project_rows: list[dict[str, Any]] | None = None,
    project_metadata: dict[str, Any] | None = None,
    queue_rows: list[dict[str, Any]] | None = None,
    queue_metadata: dict[str, Any] | None = None,
    lifeops_people_rows: list[dict[str, Any]] | None = None,
    lifeops_action_rows: list[dict[str, Any]] | None = None,
    lifeops_metadata: dict[str, Any] | None = None,
    life_commitments: list[dict[str, Any]] | None = None,
    limit: int = 25,
    section_limit: int = 25,
) -> dict[str, Any]:
    """Build an auditable context tree from existing read models only."""
    if limit < 1 or section_limit < 1:
        raise ValueError("limit and section_limit must be at least 1")

    sections: dict[str, list[dict[str, Any]]] = {
        "attention": [],
        "people": [],
        "places": [],
        "projects": [],
        "goals": [],
        "decisions": [],
        "notes": [],
        "commitments": [],
    }
    all_memory_entries = list(memory_entries)
    for row in project_rows or []:
        entry = _project_row_entry(row)
        if entry:
            all_memory_entries.append(entry)
    seen_memory: set[str] = set()
    project_groups: dict[str, list[dict[str, Any]]] = {}
    for entry in all_memory_entries:
        if not isinstance(entry, dict):
            continue
        entry_id = str(entry.get("id") or "")
        if not entry_id or entry_id in seen_memory:
            continue
        if str(entry.get("status") or "").casefold() in {"closed", "done", "deleted", "inactive"}:
            continue
        seen_memory.add(entry_id)
        section = _section_for_type(str(entry.get("memory_type") or "").casefold())
        if section == "projects":
            key = _project_key(str(entry.get("subject") or "project")) or "project"
            project_groups.setdefault(key, []).append(entry)
        else:
            sections[section].append(_memory_item(entry))

    for entries in project_groups.values():
        sections["projects"].append(_project_item(entries))

    for item in triage.get("items", []) or []:
        if isinstance(item, dict) and item.get("source_ref"):
            sections["attention"].append(_attention_item(item))
    for row in queue_rows or []:
        attention = _master_ops_attention_item(row)
        if attention:
            sections["attention"].append(attention)
    for profile in people_profiles or []:
        person = _person_item(profile)
        if person:
            sections["people"].append(person)
    for event in calendar_events or []:
        place = _place_item(event)
        if place:
            sections["places"].append(place)
    for contact in contact_rows or []:
        addresses = contact.get("addresses") if isinstance(contact, dict) else []
        if isinstance(addresses, dict):
            addresses = [addresses]
        for index, address in enumerate(addresses or []):
            place = _contact_place_item(contact, address, index)
            if place:
                sections["places"].append(place)
    for row in lifeops_people_rows or []:
        person = _lifeops_person_item(row, contact_rows)
        if person:
            sections["people"].append(person)
    for row in lifeops_action_rows or []:
        action = _lifeops_action_item(row)
        if action:
            sections["commitments"].append(action)
    for commitment in life_commitments or []:
        normalized = _commitment_item(commitment)
        if normalized:
            sections["commitments"].append(normalized)
    curated_attention = [
        item
        for item in sections["attention"]
        if item.get("attention_class") == "curated_email_action"
    ]
    other_attention = [
        item
        for item in sections["attention"]
        if item.get("attention_class") != "curated_email_action"
    ]
    sections["attention"] = (curated_attention + other_attention)[:limit]
    sections["places"] = sections["places"][:section_limit]
    for section in SECTION_TYPES:
        sections[section] = sections[section][:section_limit]

    source_health = dict(triage.get("source_health") or {})
    if people_metadata is not None:
        source_status = people_metadata.get("source_status") or {}
        source_health["unified_contacts"] = {
            "status": "ok" if people_metadata.get("available", True) else "unavailable",
            "read_only": True,
            "schema": people_metadata.get("schema"),
            "profile_count": people_metadata.get("profile_count", 0),
            "cross_channel_profile_count": people_metadata.get(
                "cross_channel_profile_count", 0
            ),
            "source_status": source_status,
        }
    if calendar_metadata is not None:
        source_health["calendar"] = {
            "status": "ok" if calendar_metadata.get("available", True) else "unavailable",
            "read_only": True,
            "event_count": calendar_metadata.get("event_count", 0),
            "lookahead_days": calendar_metadata.get("lookahead_days", 0),
            "detail": calendar_metadata.get("detail", ""),
        }
    if contact_metadata is not None:
        source_health["contacts"] = {
            "status": "ok" if contact_metadata.get("available", True) else "unavailable",
            "read_only": True,
            "contact_count": contact_metadata.get("contact_count", 0),
            "address_count": contact_metadata.get("address_count", 0),
            "detail": contact_metadata.get("detail", ""),
        }
    if project_metadata is not None:
        source_health["projects"] = {
            "status": "ok" if project_metadata.get("available", True) else "unavailable",
            "read_only": True,
            "project_count": project_metadata.get("project_count", 0),
            "spreadsheet_id": project_metadata.get("spreadsheet_id", ""),
            "sheet_name": project_metadata.get("sheet_name", ""),
            "detail": project_metadata.get("detail", ""),
        }
    if queue_metadata is not None:
        source_health["master_ops"] = {
            "status": "ok" if queue_metadata.get("available", True) else "unavailable",
            "read_only": True,
            "email_action_count": queue_metadata.get("email_action_count", 0),
            "capture_count": queue_metadata.get("capture_count", 0),
            "task_mirror_count": queue_metadata.get("task_mirror_count", 0),
            "detail": queue_metadata.get("detail", ""),
        }
    if lifeops_metadata is not None:
        source_health["lifeops_sheet"] = {
            "status": "ok" if lifeops_metadata.get("available", True) else "unavailable",
            "read_only": True,
            "people_count": lifeops_metadata.get("people_count", 0),
            "action_count": lifeops_metadata.get("action_count", 0),
            "project_count": lifeops_metadata.get("project_count", 0),
            "detail": lifeops_metadata.get("detail", ""),
        }
    limitations = list(_DEFERRED_LIMITATIONS)
    for source, health in source_health.items():
        if not isinstance(health, dict) or health.get("status") != "ok":
            limitations.append(f"{source}_read_unavailable")
        if isinstance(health, dict) and health.get("stale") is True:
            limitations.append(f"{source}_stale")
        if isinstance(health, dict) and health.get("healthy") is False:
            limitations.append(f"{source}_unhealthy")
        for reason in health.get("reasons", []) if isinstance(health, dict) else []:
            limitations.append(f"{source}:{reason}")
        nested_status = health.get("source_status", {}) if isinstance(health, dict) else {}
        for nested_source, nested_health in nested_status.items():
            if not isinstance(nested_health, dict) or not nested_health.get("available"):
                detail = str(nested_health.get("detail") or "unavailable")
                limitations.append(f"{source}:{nested_source}:{detail}")

    references: list[dict[str, Any]] = []
    source_counts: Counter[str] = Counter()
    for section_items in sections.values():
        for item in section_items:
            item_refs = [
                item.get("source_ref"),
                *(item.get("evidence_refs") or []),
                *(item.get("linked_source_refs") or []),
            ]
            for ref in item_refs:
                if not isinstance(ref, dict) or not ref:
                    continue
                source = str(ref.get("source") or "unknown")
                source_counts[source] += 1
                if len(references) < limit:
                    references.append(ref)

    return {
        "schema_version": "lifeops.context.v1",
        "checked_at": _checked_at(),
        "read_only": True,
        "sections": sections,
        "counts": {section: len(items) for section, items in sections.items()},
        "source_health": source_health,
        "limitations": list(dict.fromkeys(limitations)),
        "provenance": {
            "reference_count": sum(source_counts.values()),
            "sources": dict(sorted(source_counts.items())),
            "references": references,
        },
    }
