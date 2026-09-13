"""Safe, deterministic tests for the read-only Drive reconciliation proof."""

from __future__ import annotations

import os
import re
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from drive_reconciliation import (
    ReconciliationInputError,
    ReconciliationRootError,
    reconcile_drive_roots,
)

ACCOUNT = "jshah1331@gmail.com"
SOURCE_ROOT = "source-root"
CANONICAL_ROOT = "canonical-root"
FOLDER_MIME = "application/vnd.google-apps.folder"
SHORTCUT_MIME = "application/vnd.google-apps.shortcut"
FILE_TIME = "2026-09-12T20:00:00Z"
pytestmark = pytest.mark.safe


class _Request:
    def __init__(self, value):
        self.value = value

    def execute(self):
        return self.value


class _Files:
    def __init__(self, service):
        self.service = service

    def get(self, **kwargs):
        self.service.read_calls.append(("files.get", kwargs))
        return _Request(self.service.roots.get(kwargs["fileId"], {}))

    def list(self, **kwargs):
        self.service.read_calls.append(("files.list", kwargs))
        match = re.search(r"'([^']+)' in parents", kwargs["q"])
        assert match
        parent_id = match.group(1)
        return _Request({"files": self.service.children.get(parent_id, [])})


class _Changes:
    def __init__(self, service):
        self.service = service

    def getStartPageToken(self, **kwargs):
        self.service.read_calls.append(("changes.getStartPageToken", kwargs))
        return _Request({"startPageToken": self.service.tokens.pop(0)})

    def list(self, **kwargs):
        self.service.read_calls.append(("changes.list", kwargs))
        return _Request({"changes": self.service.change_items})


class FakeDriveService:
    """Small provider double that exposes only the read surface used by the adapter."""

    def __init__(self, *, changed: bool = False, malformed_file: bool = False):
        source_file = {
            "id": "source-file",
            "name": "photo.jpg",
            "mimeType": "image/jpeg",
            "modifiedTime": FILE_TIME,
            "size": 12,
            "md5Checksum": "checksum-1",
            "parents": [SOURCE_ROOT],
            "trashed": False,
        }
        canonical_file = source_file | {"id": "canonical-file", "parents": [CANONICAL_ROOT]}
        if malformed_file:
            source_file = source_file | {"size": "not-a-size"}
        self.roots = {
            SOURCE_ROOT: {"id": SOURCE_ROOT, "name": "WD", "mimeType": FOLDER_MIME, "trashed": False},
            CANONICAL_ROOT: {
                "id": CANONICAL_ROOT,
                "name": "WD canonical",
                "mimeType": FOLDER_MIME,
                "trashed": False,
            },
        }
        self.children = {SOURCE_ROOT: [source_file], CANONICAL_ROOT: [canonical_file]}
        self.tokens = ["token-start", "token-end" if changed else "token-start"]
        self.change_items = [{"fileId": "changed-file", "removed": False}] if changed else []
        self.read_calls = []
        self.mutation_calls = []

    def files(self):
        return _Files(self)

    def changes(self):
        return _Changes(self)

    def __getattr__(self, name):
        if name in {"create", "update", "delete", "copy", "permissions"}:
            self.mutation_calls.append(name)
            raise AssertionError(f"unexpected Drive mutation helper: {name}")
        raise AttributeError(name)


def _proof(service: FakeDriveService) -> dict:
    return reconcile_drive_roots(
        service,
        account=ACCOUNT,
        source_root_id=SOURCE_ROOT,
        canonical_root_id=CANONICAL_ROOT,
    )


def test_zero_unique_proof_is_deterministic_and_read_only():
    first = _proof(FakeDriveService())
    second = _proof(FakeDriveService())

    assert first == second
    assert first["status"] == "ZERO_UNIQUE_PROVEN"
    assert first["read_only"] is True
    assert first["mutation_applied"] is False
    assert first["credential_exposure"] == "none"
    assert first["counts"] == {
        "source_objects": 1,
        "canonical_objects": 1,
        "matched": 1,
        "unmatched_unique": 0,
        "unresolved": 0,
        "canonical_only": 0,
    }
    assert first["bytes"]["matched"] == 12
    assert first["account"] == ACCOUNT
    assert first["source_root_id"] == SOURCE_ROOT
    assert first["canonical_root_id"] == CANONICAL_ROOT
    assert first["snapshot"] == {
        "start_page_token": "token-start",
        "end_page_token": "token-start",
        "stable": True,
        "changes_after_start": 0,
    }
    assert first["proof_id"] == f"DRP-{first['proof_digest'][:16]}"


def test_nested_children_are_reconciled_by_relative_path():
    service = FakeDriveService()
    source_folder = {
        "id": "source-folder",
        "name": "nested",
        "mimeType": FOLDER_MIME,
        "parents": [SOURCE_ROOT],
        "trashed": False,
    }
    canonical_folder = source_folder | {"id": "canonical-folder", "parents": [CANONICAL_ROOT]}
    nested_source = {
        "id": "nested-source-file",
        "name": "inside.txt",
        "mimeType": "text/plain",
        "modifiedTime": FILE_TIME,
        "size": 7,
        "md5Checksum": "nested-checksum",
        "parents": ["source-folder"],
        "trashed": False,
    }
    nested_canonical = nested_source | {"id": "nested-canonical-file", "parents": ["canonical-folder"]}
    service.children[SOURCE_ROOT].append(source_folder)
    service.children[CANONICAL_ROOT].append(canonical_folder)
    service.children["source-folder"] = [nested_source]
    service.children["canonical-folder"] = [nested_canonical]

    result = _proof(service)

    assert result["status"] == "ZERO_UNIQUE_PROVEN"
    assert result["counts"]["matched"] == 2
    assert result["bytes"]["matched"] == 19


def test_missing_canonical_object_is_counted_as_unmatched_unique():
    service = FakeDriveService()
    service.children[SOURCE_ROOT].append(
        {
            "id": "source-only",
            "name": "source-only.bin",
            "mimeType": "application/octet-stream",
            "modifiedTime": FILE_TIME,
            "size": 5,
            "md5Checksum": "source-only-checksum",
            "parents": [SOURCE_ROOT],
            "trashed": False,
        }
    )

    result = _proof(service)

    assert result["status"] == "UNRESOLVED"
    assert result["counts"]["unmatched_unique"] == 1
    assert result["bytes"]["unmatched_unique"] == 5


def test_invalid_scope_and_roots_fail_closed():
    with pytest.raises(ReconciliationInputError):
        reconcile_drive_roots(
            FakeDriveService(),
            account="",
            source_root_id=SOURCE_ROOT,
            canonical_root_id=CANONICAL_ROOT,
        )
    with pytest.raises(ReconciliationInputError):
        reconcile_drive_roots(
            FakeDriveService(),
            account=ACCOUNT,
            source_root_id="source/root",
            canonical_root_id=CANONICAL_ROOT,
        )

    service = FakeDriveService()
    service.roots[SOURCE_ROOT] = {"id": SOURCE_ROOT, "mimeType": "text/plain", "trashed": False}
    with pytest.raises(ReconciliationRootError):
        _proof(service)


def test_scope_escape_and_shortcuts_are_unresolved_and_never_traversed():
    service = FakeDriveService()
    service.children[SOURCE_ROOT] = [
        {
            "id": "escaped",
            "name": "escaped.txt",
            "mimeType": "text/plain",
            "modifiedTime": FILE_TIME,
            "size": 4,
            "parents": ["outside-root"],
            "trashed": False,
        },
        {
            "id": "shortcut",
            "name": "shortcut",
            "mimeType": SHORTCUT_MIME,
            "parents": [SOURCE_ROOT],
            "shortcutDetails": {"targetId": "outside-folder"},
            "trashed": False,
        },
    ]

    result = _proof(service)

    assert result["status"] == "UNRESOLVED"
    assert result["counts"]["unresolved"] == 2
    assert {issue["reason"] for issue in result["issues"]} == {
        "scope_escape",
        "shortcut_not_followed",
    }
    listed_parents = [call[1].get("q", "") for call in service.read_calls if call[0] == "files.list"]
    assert all("outside-folder" not in query for query in listed_parents)


def test_changed_snapshot_and_malformed_metadata_never_prove_uniqueness():
    changed = _proof(FakeDriveService(changed=True))
    malformed = _proof(FakeDriveService(malformed_file=True))

    assert changed["status"] == "UNRESOLVED"
    assert changed["snapshot"]["stable"] is False
    assert any(issue["reason"] == "snapshot_changed" for issue in changed["issues"])
    assert malformed["status"] == "UNRESOLVED"
    assert any(issue["reason"] == "malformed_metadata" for issue in malformed["issues"])


def test_provider_double_has_no_mutation_calls():
    service = FakeDriveService()
    result = _proof(service)

    assert result["status"] == "ZERO_UNIQUE_PROVEN"
    assert service.mutation_calls == []
    assert {name for name, _ in service.read_calls} <= {
        "files.get",
        "files.list",
        "changes.getStartPageToken",
        "changes.list",
    }


@pytest.fixture()
def api_client():
    with (
        patch.dict(os.environ, {"INBOX_SERVER_TOKEN": ""}, clear=False),
        patch("inbox_server.init_contacts", return_value=0),
        patch("inbox_server.google_auth_all", return_value=({}, {}, {}, {}, {}, {})),
        patch("inbox_server.load_voice_config", return_value={"ambient_autostart": False}),
    ):
        from inbox_server import app

        with TestClient(app) as client:
            yield client


def test_source_registry_route_is_available_and_does_not_probe(api_client):
    response = api_client.get("/sources/registry")

    assert response.status_code == 200
    payload = response.json()
    assert payload["registry_version"] == "lifeops.source_registry.v1"
    assert any(source["source_id"] == "google_drive" for source in payload["sources"])


def test_http_proof_requires_explicit_account_and_rejects_extra_fields(api_client):
    with patch("inbox_server._get_drive_service_for_account") as resolve:
        missing_account = api_client.post(
            "/drive/reconciliation/proof",
            json={"source_root_id": SOURCE_ROOT, "canonical_root_id": CANONICAL_ROOT},
        )
    assert missing_account.status_code == 422
    resolve.assert_not_called()

    extra_field = api_client.post(
        "/drive/reconciliation/proof",
        json={
            "account": ACCOUNT,
            "source_root_id": SOURCE_ROOT,
            "canonical_root_id": CANONICAL_ROOT,
            "delete_after_proof": True,
        },
    )
    assert extra_field.status_code == 422


def test_http_proof_routes_by_exact_account_without_exposing_credentials(api_client):
    service = FakeDriveService()
    with patch("inbox_server._get_drive_service_for_account", return_value=(ACCOUNT, service)) as resolve:
        response = api_client.post(
            "/drive/reconciliation/proof",
            json={
                "account": ACCOUNT,
                "source_root_id": SOURCE_ROOT,
                "canonical_root_id": CANONICAL_ROOT,
            },
        )

    assert response.status_code == 200
    assert response.json()["status"] == "ZERO_UNIQUE_PROVEN"
    resolve.assert_called_once_with(ACCOUNT)
    assert response.json()["credential_exposure"] == "none"
    assert all(secret not in response.text.lower() for secret in ("access_token", "client_secret", "refresh_token"))
