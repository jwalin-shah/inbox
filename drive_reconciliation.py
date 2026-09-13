"""Read-only, authority-bound Google Drive tree reconciliation.

This module deliberately accepts an already-resolved Drive service.  Callers
must resolve that service from an explicit account before invoking it.  The
adapter only uses Drive ``get``, ``list``, ``getStartPageToken`` and
``changes.list`` operations; it has no mutation path.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

SCHEMA_VERSION = "drive.reconciliation_proof.v1"
FOLDER_MIME_TYPE = "application/vnd.google-apps.folder"
SHORTCUT_MIME_TYPE = "application/vnd.google-apps.shortcut"
_ROOT_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")
_ACCOUNT_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_MAX_DEPTH = 1_000
_FILE_FIELDS = (
    "nextPageToken,"
    "files(id,name,mimeType,modifiedTime,size,md5Checksum,parents,shortcutDetails,trashed)"
)
_ROOT_FIELDS = "id,name,mimeType,parents,trashed"
_CHANGE_FIELDS = "nextPageToken,newStartPageToken,changes(fileId,removed,file(id,parents,trashed))"


class ReconciliationInputError(ValueError):
    """The caller did not provide an explicit, valid reconciliation scope."""


class ReconciliationRootError(ValueError):
    """A requested root is missing, trashed, or not a Drive folder."""


@dataclass(frozen=True)
class DriveObject:
    object_id: str
    relative_path: str
    size: int
    modified_time: str
    checksum: str | None
    mime_type: str


@dataclass(frozen=True)
class Inventory:
    files: dict[str, DriveObject]
    unresolved: tuple[dict[str, Any], ...]
    bytes_total: int
    checksum_objects: int
    object_count: int


def _validate_scope(account: str, source_root_id: str, canonical_root_id: str) -> tuple[str, str, str]:
    account = account.strip()
    source_root_id = source_root_id.strip()
    canonical_root_id = canonical_root_id.strip()
    if not _ACCOUNT_RE.fullmatch(account):
        raise ReconciliationInputError("account must be one explicit Google email address")
    if not _ROOT_ID_RE.fullmatch(source_root_id):
        raise ReconciliationInputError("source_root_id must be a URL-safe Drive ID")
    if not _ROOT_ID_RE.fullmatch(canonical_root_id):
        raise ReconciliationInputError("canonical_root_id must be a URL-safe Drive ID")
    if source_root_id == canonical_root_id:
        raise ReconciliationInputError("source_root_id and canonical_root_id must differ")
    return account, source_root_id, canonical_root_id


def validate_reconciliation_scope(
    account: str, source_root_id: str, canonical_root_id: str
) -> tuple[str, str, str]:
    """Validate and normalize the explicit account and two-root scope."""
    return _validate_scope(account, source_root_id, canonical_root_id)


def _as_mapping(value: Any, context: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"malformed Drive response for {context}: expected an object")
    return value


def _as_string(value: Any, field: str, *, required: bool = True) -> str:
    if value is None and not required:
        return ""
    if not isinstance(value, str) or (required and not value):
        raise ValueError(f"malformed Drive metadata: {field} must be a non-empty string")
    return value


def _normalise_modified_time(value: Any) -> str:
    raw = _as_string(value, "modifiedTime")
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("malformed Drive metadata: modifiedTime is not RFC3339") from exc
    if parsed.tzinfo is None:
        raise ValueError("malformed Drive metadata: modifiedTime must include a timezone")
    return parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _normalise_name(value: Any) -> str:
    name = _as_string(value, "name")
    if name in {".", ".."} or "/" in name or "\\" in name or any(ord(c) < 32 for c in name):
        raise ValueError("malformed Drive metadata: name is not a safe path segment")
    return name


def _normalise_size(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise ValueError("malformed Drive metadata: size must be a non-negative integer")
    try:
        size = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("malformed Drive metadata: size must be a non-negative integer") from exc
    if size < 0:
        raise ValueError("malformed Drive metadata: size must be a non-negative integer")
    return size


def _read_root(drive_service: Any, root_id: str, label: str) -> Mapping[str, Any]:
    response = _as_mapping(
        drive_service.files().get(fileId=root_id, fields=_ROOT_FIELDS).execute(),
        f"{label} root",
    )
    if response.get("id") != root_id:
        raise ReconciliationRootError(f"{label} root {root_id} was not returned by Drive")
    if response.get("mimeType") != FOLDER_MIME_TYPE:
        raise ReconciliationRootError(f"{label} root {root_id} is not a Drive folder")
    if response.get("trashed") is True:
        raise ReconciliationRootError(f"{label} root {root_id} is trashed")
    return response


def _list_children(drive_service: Any, parent_id: str) -> list[Mapping[str, Any]]:
    children: list[Mapping[str, Any]] = []
    page_token: str | None = None
    seen_tokens: set[str] = set()
    while True:
        kwargs: dict[str, Any] = {
            "q": f"'{parent_id}' in parents and trashed = false",
            "pageSize": 1_000,
            "fields": _FILE_FIELDS,
            "orderBy": "name, id",
        }
        if page_token is not None:
            kwargs["pageToken"] = page_token
        response = _as_mapping(drive_service.files().list(**kwargs).execute(), f"children of {parent_id}")
        raw_files = response.get("files", [])
        if not isinstance(raw_files, list):
            raise ValueError(f"malformed Drive response for children of {parent_id}: files is not a list")
        for item in raw_files:
            children.append(_as_mapping(item, f"children of {parent_id}"))
        next_token = response.get("nextPageToken")
        if next_token in (None, ""):
            return children
        if not isinstance(next_token, str) or next_token in seen_tokens:
            raise ValueError(f"malformed Drive response for children of {parent_id}: invalid page token")
        seen_tokens.add(next_token)
        page_token = next_token


def _inventory_root(drive_service: Any, root_id: str, label: str) -> Inventory:
    files: dict[str, DriveObject] = {}
    unresolved: list[dict[str, Any]] = []
    queue: list[tuple[str, str, int]] = [(root_id, "", 0)]
    seen_ids: dict[str, str] = {root_id: ""}
    checksum_objects = 0
    bytes_total = 0
    object_count = 0

    while queue:
        parent_id, parent_path, depth = queue.pop(0)
        if depth > _MAX_DEPTH:
            unresolved.append({"root": label, "path": parent_path, "reason": "max_depth_exceeded"})
            continue
        for item in _list_children(drive_service, parent_id):
            try:
                object_id = _as_string(item.get("id"), "id")
                name = _normalise_name(item.get("name"))
                mime_type = _as_string(item.get("mimeType"), "mimeType")
                parents = item.get("parents")
                if not isinstance(parents, list) or not all(isinstance(p, str) and p for p in parents):
                    raise ValueError("parents must be a list of Drive IDs")
                if parents != [parent_id]:
                    unresolved.append(
                        {"root": label, "path": name, "reason": "scope_escape", "object_id": object_id}
                    )
                    continue
                if item.get("trashed") is True:
                    unresolved.append(
                        {"root": label, "path": name, "reason": "trashed_object", "object_id": object_id}
                    )
                    continue
                relative_path = f"{parent_path}/{name}" if parent_path else name
                previous_path = seen_ids.get(object_id)
                if previous_path is not None:
                    unresolved.append(
                        {
                            "root": label,
                            "path": relative_path,
                            "reason": "duplicate_or_cycle",
                            "object_id": object_id,
                            "first_path": previous_path,
                        }
                    )
                    continue
                seen_ids[object_id] = relative_path
                if mime_type == SHORTCUT_MIME_TYPE:
                    unresolved.append(
                        {"root": label, "path": relative_path, "reason": "shortcut_not_followed", "object_id": object_id}
                    )
                    continue
                if mime_type == FOLDER_MIME_TYPE:
                    queue.append((object_id, relative_path, depth + 1))
                    continue
                size = _normalise_size(item.get("size"))
                modified_time = _normalise_modified_time(item.get("modifiedTime"))
                checksum = item.get("md5Checksum")
                if checksum is not None and (not isinstance(checksum, str) or not checksum):
                    raise ValueError("md5Checksum must be a non-empty string when present")
                if checksum:
                    checksum_objects += 1
                if relative_path in files:
                    unresolved.append(
                        {"root": label, "path": relative_path, "reason": "duplicate_path", "object_id": object_id}
                    )
                    continue
                files[relative_path] = DriveObject(
                    object_id=object_id,
                    relative_path=relative_path,
                    size=size,
                    modified_time=modified_time,
                    checksum=checksum,
                    mime_type=mime_type,
                )
                bytes_total += size
                object_count += 1
            except ValueError as exc:
                unresolved.append({"root": label, "reason": "malformed_metadata", "detail": str(exc)})

    return Inventory(
        files=files,
        unresolved=tuple(sorted(unresolved, key=lambda issue: json.dumps(issue, sort_keys=True))),
        bytes_total=bytes_total,
        checksum_objects=checksum_objects,
        object_count=object_count,
    )


def _start_page_token(drive_service: Any) -> str:
    response = _as_mapping(
        drive_service.changes().getStartPageToken(fields="startPageToken").execute(),
        "start page token",
    )
    token = response.get("startPageToken")
    if not isinstance(token, str) or not token:
        raise ValueError("malformed Drive response: startPageToken is missing")
    return token


def _changes_after(drive_service: Any, page_token: str) -> list[Mapping[str, Any]]:
    response = _as_mapping(
        drive_service.changes()
        .list(pageToken=page_token, spaces="drive", pageSize=1_000, fields=_CHANGE_FIELDS)
        .execute(),
        "Drive changes",
    )
    changes = response.get("changes", [])
    if not isinstance(changes, list):
        raise ValueError("malformed Drive response: changes is not a list")
    return [_as_mapping(change, "Drive changes") for change in changes]


def _equivalent(source: DriveObject, canonical: DriveObject) -> tuple[bool, str | None]:
    if source.size != canonical.size:
        return False, "size_mismatch"
    if source.modified_time != canonical.modified_time:
        return False, "modified_time_mismatch"
    if source.checksum and canonical.checksum and source.checksum != canonical.checksum:
        return False, "checksum_mismatch"
    return True, None


def _digest_payload(receipt: Mapping[str, Any]) -> str:
    encoded = json.dumps(receipt, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    return hashlib.sha256(encoded).hexdigest()


def reconcile_drive_roots(
    drive_service: Any,
    *,
    account: str,
    source_root_id: str,
    canonical_root_id: str,
) -> dict[str, Any]:
    """Return a deterministic read-only proof receipt for two Drive roots."""
    account, source_root_id, canonical_root_id = _validate_scope(
        account, source_root_id, canonical_root_id
    )
    try:
        snapshot_start = _start_page_token(drive_service)
        _read_root(drive_service, source_root_id, "source")
        _read_root(drive_service, canonical_root_id, "canonical")
        source = _inventory_root(drive_service, source_root_id, "source")
        canonical = _inventory_root(drive_service, canonical_root_id, "canonical")
        snapshot_end = _start_page_token(drive_service)
        observed_changes = _changes_after(drive_service, snapshot_start)
    except ReconciliationRootError:
        raise
    except Exception as exc:
        # A provider failure cannot authorize a later cleanup.  Return a
        # durable, explicit unresolved receipt instead of guessing counts.
        unavailable_snapshot: dict[str, Any] = {"stable": False}
        unavailable_snapshot["start_page_token"] = None
        unavailable_snapshot["end_page_token"] = None
        base = {
            "schema_version": SCHEMA_VERSION,
            "operation": "drive_tree_reconciliation",
            "read_only": True,
            "mutation_applied": False,
            "credential_exposure": "none",
            "account": account,
            "source_root_id": source_root_id,
            "canonical_root_id": canonical_root_id,
            "snapshot": unavailable_snapshot,
            "counts": {"matched": 0, "unmatched_unique": 0, "unresolved": 1},
            "bytes": {"matched": 0, "unmatched_unique": 0, "unresolved": 0},
            "checksum_coverage": {"source_objects": 0, "canonical_objects": 0, "both_sides": 0},
            "issues": [{"reason": "provider_error", "detail": str(exc)}],
        }
        digest = _digest_payload(base)
        return base | {"status": "UNRESOLVED", "proof_digest": digest, "proof_id": f"DRP-{digest[:16]}"}

    matched = 0
    matched_bytes = 0
    unmatched_unique = 0
    unmatched_bytes = 0
    comparison_unresolved = 0
    unresolved_bytes = 0
    issues = list(source.unresolved) + list(canonical.unresolved)
    both_checksums = 0
    for path, source_object in source.files.items():
        canonical_object = canonical.files.get(path)
        if canonical_object is None:
            unmatched_unique += 1
            unmatched_bytes += source_object.size
            continue
        if source_object.checksum and canonical_object.checksum:
            both_checksums += 1
        equal, reason = _equivalent(source_object, canonical_object)
        if equal:
            matched += 1
            matched_bytes += source_object.size
        else:
            comparison_unresolved += 1
            unresolved_bytes += source_object.size
            issues.append({"path": path, "reason": reason or "not_equivalent"})

    canonical_only = sorted(set(canonical.files) - set(source.files))
    snapshot_stable = snapshot_start == snapshot_end and not observed_changes
    if not snapshot_stable:
        comparison_unresolved += 1
        issues.append(
            {
                "reason": "snapshot_changed",
                "changes_after_start": len(observed_changes),
                "start_page_token": snapshot_start,
                "end_page_token": snapshot_end,
            }
        )
    issues = sorted(issues, key=lambda issue: json.dumps(issue, sort_keys=True))
    # Comparison mismatches are already represented in ``issues``; provider
    # inventory issues and a changed snapshot are separate unresolved objects.
    unresolved = len(source.unresolved) + len(canonical.unresolved) + comparison_unresolved
    base = {
        "schema_version": SCHEMA_VERSION,
        "operation": "drive_tree_reconciliation",
        "read_only": True,
        "mutation_applied": False,
        "credential_exposure": "none",
        "account": account,
        "source_root_id": source_root_id,
        "canonical_root_id": canonical_root_id,
        "snapshot": {
            "start_page_token": snapshot_start,
            "end_page_token": snapshot_end,
            "stable": snapshot_stable,
            "changes_after_start": len(observed_changes),
        },
        "counts": {
            "source_objects": source.object_count,
            "canonical_objects": canonical.object_count,
            "matched": matched,
            "unmatched_unique": unmatched_unique,
            "unresolved": unresolved,
            "canonical_only": len(canonical_only),
        },
        "bytes": {
            "source": source.bytes_total,
            "canonical": canonical.bytes_total,
            "matched": matched_bytes,
            "unmatched_unique": unmatched_bytes,
            "unresolved": unresolved_bytes,
        },
        "checksum_coverage": {
            "source_objects": source.checksum_objects,
            "canonical_objects": canonical.checksum_objects,
            "both_sides": both_checksums,
        },
        "issues": issues,
    }
    digest = _digest_payload(base)
    status = "ZERO_UNIQUE_PROVEN" if unmatched_unique == 0 and unresolved == 0 else "UNRESOLVED"
    return base | {"status": status, "proof_digest": digest, "proof_id": f"DRP-{digest[:16]}"}
