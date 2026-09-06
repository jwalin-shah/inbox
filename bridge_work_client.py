"""Thin Bridge intake client for the Inbox MCP control plane (PR-2B).

Calls only the existing Bridge CLI handshake:

    bridge ingest - --repo <dir>

This is intake, not execution. It never invokes spawn, promote-approval,
deliver, or any other Bridge verb. argv is allowlisted; shell=False.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

BRIDGE_BIN_ENV = "INBOX_BRIDGE_BIN"
BRIDGE_REPO_ENV = "INBOX_BRIDGE_REPO"
CONTRACT_VERSION = "bridge.contracts.v1"
INGEST_TIMEOUT_SEC = 30
ALLOWED_VERBS = frozenset({"ingest"})


class BridgeIngestError(RuntimeError):
    """Bridge intake failed closed (reject, missing config, or bad output)."""


@dataclass(frozen=True)
class BridgeIngestReceipt:
    """Ids/paths returned by Bridge ingest. Never an execution grant."""

    result_id: str
    work_packet_id: str
    status: str
    summary: str
    intake_path: str

    @property
    def ok(self) -> bool:
        return self.status == "accepted_for_intake" and bool(self.intake_path)


class BridgeWorkClientProtocol(Protocol):
    def ingest_event(self, envelope: dict[str, Any]) -> BridgeIngestReceipt: ...


def _resolve_bridge_bin(configured: str | None = None) -> Path:
    raw = (configured if configured is not None else os.getenv(BRIDGE_BIN_ENV, "")).strip()
    if raw:
        path = Path(raw).expanduser()
    else:
        found = shutil.which("bridge")
        if not found:
            raise BridgeIngestError("bridge_binary_missing")
        path = Path(found)
    if not path.is_file():
        raise BridgeIngestError("bridge_binary_missing")
    # Fail closed: refuse relative / PATH-injected names that are not "bridge".
    if path.name != "bridge":
        raise BridgeIngestError("bridge_binary_not_allowlisted")
    return path.resolve()


def _resolve_bridge_repo(configured: str | None = None) -> Path:
    raw = (configured if configured is not None else os.getenv(BRIDGE_REPO_ENV, "")).strip()
    if not raw:
        raise BridgeIngestError("bridge_repo_missing")
    path = Path(raw).expanduser()
    if not path.is_dir():
        raise BridgeIngestError("bridge_repo_missing")
    return path.resolve()


def build_ingest_argv(*, bridge_bin: Path, repo: Path) -> list[str]:
    """Fixed argv for Bridge intake. No user-controlled verbs or flags."""
    if bridge_bin.name != "bridge":
        raise BridgeIngestError("bridge_binary_not_allowlisted")
    if not bridge_bin.is_absolute():
        raise BridgeIngestError("bridge_binary_not_allowlisted")
    if not repo.is_absolute() or not repo.is_dir():
        raise BridgeIngestError("bridge_repo_missing")
    argv = [str(bridge_bin), "ingest", "-", "--repo", str(repo)]
    if argv[1] not in ALLOWED_VERBS:
        raise BridgeIngestError("bridge_verb_not_allowlisted")
    return argv


def build_submit_work_envelope(
    *,
    work_id: str,
    summary: str,
    evidence_refs: list[dict[str, Any]],
    occurred_at: str,
) -> dict[str, Any]:
    """Map control-plane submit_work into Bridge EventEnvelope v1."""
    text = (summary or "").strip()
    if not text:
        text = f"submit_work {work_id}"
    # Evidence refs stay in metadata as opaque strings — not policy fields.
    metadata = {
        "work_id": work_id,
        "evidence_ref_count": str(len(evidence_refs)),
    }
    return {
        "version": CONTRACT_VERSION,
        "id": f"inbox:control_plane:{work_id}",
        "kind": "inbox.control_plane.submit_work",
        "source": "inbox",
        "external_id": work_id,
        "occurred_at": occurred_at,
        "payload": {
            "text": text,
            "external_ref": work_id,
            "metadata": metadata,
        },
    }


def _parse_result_bundle(stdout: str) -> BridgeIngestReceipt:
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise BridgeIngestError("bridge_result_unparseable") from exc
    if not isinstance(payload, dict):
        raise BridgeIngestError("bridge_result_unparseable")
    status = str(payload.get("status") or "").strip()
    receipt = BridgeIngestReceipt(
        result_id=str(payload.get("id") or "").strip(),
        work_packet_id=str(payload.get("work_packet_id") or "").strip(),
        status=status,
        summary=str(payload.get("summary") or "").strip(),
        intake_path=str(payload.get("intake_path") or "").strip(),
    )
    if not receipt.ok:
        raise BridgeIngestError("bridge_rejected")
    if payload.get("verification_receipt"):
        # Intake must never carry execution evidence.
        raise BridgeIngestError("bridge_claimed_execution")
    return receipt


class BridgeWorkClient:
    """Allowlisted subprocess caller for `bridge ingest` only."""

    def __init__(self, *, bridge_bin: Path | None = None, repo: Path | None = None) -> None:
        self._bridge_bin = bridge_bin
        self._repo = repo

    @classmethod
    def from_env(cls) -> BridgeWorkClient:
        return cls()

    def ingest_event(self, envelope: dict[str, Any]) -> BridgeIngestReceipt:
        bridge_bin = self._bridge_bin or _resolve_bridge_bin()
        repo = self._repo or _resolve_bridge_repo()
        argv = build_ingest_argv(bridge_bin=bridge_bin, repo=repo)
        try:
            completed = subprocess.run(
                argv,
                input=json.dumps(envelope, separators=(",", ":"), sort_keys=True),
                capture_output=True,
                text=True,
                shell=False,
                timeout=INGEST_TIMEOUT_SEC,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise BridgeIngestError("bridge_ingest_timeout") from exc
        except OSError as exc:
            raise BridgeIngestError("bridge_ingest_failed") from exc
        if completed.returncode != 0:
            raise BridgeIngestError("bridge_rejected")
        return _parse_result_bundle(completed.stdout)
