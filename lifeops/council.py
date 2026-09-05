from __future__ import annotations

import json
import os
import subprocess  # nosec B404 - fixed argv, no shell, bounded local probe.
import uuid
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from lifeops.action_envelope import _contains_secret_key

try:
    import fcntl
except ImportError:  # pragma: no cover - LifeOps currently targets macOS/Linux.
    fcntl = None  # type: ignore[assignment]


COUNCIL_SCHEMA = "lifeops.council.v1"
SURFACES_SCHEMA = "lifeops.council_surfaces.v1"
COUNCIL_STATES = frozenset({"QUEUED", "CLAIMED", "RESULTS", "DONE", "FAILED"})
QuotaRunner = Callable[[Sequence[str]], str]


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def default_council_path() -> Path:
    return Path(os.getenv("LIFEOPS_COUNCIL_PATH", "state/lifeops-council.jsonl")).expanduser()


def default_surfaces_path() -> Path:
    return Path(
        os.getenv("LIFEOPS_COUNCIL_SURFACES_PATH", "state/lifeops-council-surfaces.json")
    ).expanduser()


def _run_quota_command(argv: Sequence[str]) -> str:
    completed = subprocess.run(  # nosec B603 - shell is disabled and argv is local.
        list(argv),
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip() or "command failed"
        raise RuntimeError(f"{' '.join(argv)}: {detail}")
    return completed.stdout


@dataclass(frozen=True)
class CouncilSurface:
    surface_id: str
    provider: str
    surface: str
    capabilities: tuple[str, ...]
    marginal_cost: float | None
    subscription_sunk_cost: bool
    quota_remaining: int | None
    quota_reset_at: str | None
    rate_limit_type: str
    quality: float
    latency: str
    automation_level: str
    availability: str
    quota_status: str
    best_for: str
    status_source: str
    last_verified_at: str | None = None
    automatic_enabled: bool = True

    def as_dict(self) -> dict[str, Any]:
        return asdict(self) | {"capabilities": list(self.capabilities)}


DEFAULT_SURFACES: tuple[CouncilSurface, ...] = (
    CouncilSurface(
        "perplexity/best",
        "perplexity",
        "Best",
        ("research.search", "research.synthesis"),
        0.0,
        True,
        None,
        None,
        "account_probe_required",
        0.92,
        "medium",
        "interactive",
        "unknown",
        "unknown",
        "source-backed web research and landscape scans",
        "account_probe_required",
    ),
    CouncilSurface(
        "perplexity/research",
        "perplexity",
        "Research",
        ("research.search", "research.synthesis"),
        0.0,
        True,
        None,
        None,
        "account_probe_required",
        0.95,
        "slow",
        "interactive",
        "unknown",
        "unknown",
        "deep research when the question warrants premium depth",
        "account_probe_required",
    ),
    CouncilSurface(
        "perplexity/mac-local-mcp",
        "perplexity",
        "Perplexity Mac app / local MCP",
        ("research.search", "research.synthesis"),
        0.0,
        True,
        None,
        None,
        "app_and_connector_probe_required",
        0.92,
        "medium",
        "local_mcp",
        "unknown",
        "unknown",
        "subscription research through the signed-in Mac app and curated local MCP tools",
        "app_and_connector_probe_required",
        automatic_enabled=False,
    ),
    CouncilSurface(
        "chatgpt/sol",
        "chatgpt",
        "ChatGPT / Sol",
        ("reasoning.synthesis", "research.synthesis", "reasoning.critique"),
        0.0,
        True,
        None,
        None,
        "account_probe_required",
        0.93,
        "medium",
        "interactive",
        "unknown",
        "unknown",
        "cross-model synthesis, critique, and final decision framing",
        "account_probe_required",
        automatic_enabled=False,
    ),
    CouncilSurface(
        "chatgpt/codex",
        "chatgpt",
        "Codex",
        ("code.implement", "reasoning.critique"),
        0.0,
        True,
        None,
        None,
        "account_probe_required",
        0.94,
        "medium",
        "interactive",
        "unknown",
        "unknown",
        "repository and implementation work through the existing Bridge boundary",
        "account_probe_required",
    ),
    CouncilSurface(
        "tokenrouter/local",
        "local",
        "TokenRouter / local",
        ("classification", "reasoning.critique", "research.synthesis"),
        None,
        False,
        None,
        None,
        "local_config_required",
        0.65,
        "fast",
        "local",
        "unknown",
        "unknown",
        "classification, cheap first-pass critique, and transformations",
        "local_probe_required",
    ),
)


class CouncilSurfaceRegistry:
    def __init__(
        self,
        path: Path | None = None,
        surfaces: tuple[CouncilSurface, ...] = DEFAULT_SURFACES,
    ) -> None:
        self.path = path or default_surfaces_path()
        self.surfaces = surfaces
        self.snapshot: dict[str, Any] | None = None

    def load(self) -> dict[str, Any]:
        if self.snapshot is None:
            if self.path.exists():
                self.snapshot = json.loads(self.path.read_text(encoding="utf-8"))
            else:
                self.snapshot = {
                    "schema_version": SURFACES_SCHEMA,
                    "synced_at": None,
                    "surfaces": [surface.as_dict() for surface in self.surfaces],
                    "readiness": "unprobed",
                }
        if not isinstance(self.snapshot, dict):
            raise ValueError("council surface registry must be an object")
        return self.snapshot

    def sync_static(self) -> dict[str, Any]:
        """Persist the economic schema without claiming provider availability."""
        self.snapshot = {
            "schema_version": SURFACES_SCHEMA,
            "synced_at": _now(),
            "surfaces": [surface.as_dict() for surface in self.surfaces],
            "readiness": "unprobed",
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.snapshot, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return self.snapshot

    def sync_quota(
        self,
        *,
        quota_command: str = "quota-axi",
        runner: QuotaRunner | None = None,
    ) -> dict[str, Any]:
        """Ingest redacted local quota metadata; never stores credentials."""
        snapshot = self.load()
        run = runner or _run_quota_command
        errors: list[str] = []
        providers: list[dict[str, Any]] = []
        try:
            raw = run((quota_command, "--json"))
            payload = json.loads(raw)
            if not isinstance(payload, dict) or not isinstance(payload.get("providers"), list):
                raise ValueError("quota-axi JSON must contain a providers array")
            providers = [provider for provider in payload["providers"] if isinstance(provider, dict)]
        except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
            errors.append(str(exc))

        by_provider = {
            str(provider.get("provider")): provider
            for provider in providers
            if provider.get("provider")
        }
        codex = by_provider.get("codex")
        codex_state = codex.get("state", {}).get("status") if codex else None
        codex_windows = codex.get("windows", []) if codex else []
        valid_windows = [
            window
            for window in codex_windows
            if isinstance(window, dict) and isinstance(window.get("percentRemaining"), (int, float))
        ]
        codex_remaining = min((int(window["percentRemaining"]) for window in valid_windows), default=None)
        codex_reset = next(
            (str(window["resetsAt"]) for window in valid_windows if window.get("resetsAt")),
            None,
        )
        codex_quota_ready = bool(
            codex
            and codex_state == "fresh"
            and codex_remaining is not None
            and codex_remaining > 0
        )
        for surface in snapshot.get("surfaces", []):
            if surface.get("surface_id") != "chatgpt/codex" or not codex:
                continue
            surface.update(
                {
                    "availability": surface.get("availability", "unknown"),
                    "quota_status": "ready" if codex_quota_ready else "not_ready",
                    "quota_remaining": codex_remaining,
                    "quota_reset_at": codex_reset,
                    "rate_limit_type": "quota-axi",
                    "status_source": "quota-axi; execution_probe_required",
                    "last_verified_at": _now(),
                }
            )
        snapshot["quota_probe"] = {
            "command": quota_command,
            "verified_at": _now(),
            "provider_count": len(providers),
            "providers": [
                {
                    "provider": provider.get("provider"),
                    "plan": provider.get("plan"),
                    "status": provider.get("state", {}).get("status"),
                }
                for provider in providers
            ],
            "errors": errors,
        }
        snapshot["readiness"] = "probed" if not errors else "degraded"
        self.snapshot = snapshot
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(snapshot, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return snapshot

    def all(self) -> list[dict[str, Any]]:
        return list(self.load().get("surfaces", []))

    def get(self, surface_id: str) -> dict[str, Any]:
        for surface in self.all():
            if surface.get("surface_id") == surface_id:
                return surface
        raise LookupError(f"unknown council surface: {surface_id}")


class CouncilRouter:
    """Rank workers economically, while refusing to invent availability."""

    def __init__(self, registry: CouncilSurfaceRegistry) -> None:
        self.registry = registry

    def rank(
        self,
        capability: str,
        *,
        mode: str = "normal",
        require_available: bool = False,
    ) -> list[dict[str, Any]]:
        candidates = [
            dict(surface)
            for surface in self.registry.all()
            if capability in surface.get("capabilities", [])
        ]
        for surface in candidates:
            subscription_bonus = 20 if surface.get("subscription_sunk_cost") else 0
            quality_score = int(float(surface.get("quality", 0.0)) * 100)
            mode_bonus = 0
            if capability == "research.search" and (
                mode == "normal" and surface.get("surface_id") == "perplexity/best"
                or mode == "deep" and surface.get("surface_id") == "perplexity/research"
            ):
                mode_bonus = 5
            availability = surface.get("availability")
            automatic_enabled = surface.get("automatic_enabled", True)
            surface["eligible_for_automatic"] = (
                automatic_enabled and availability == "available"
            )
            surface["selection_reason"] = (
                "manual-only by policy; interactive handoff only"
                if not automatic_enabled
                else "available and subscription-preferred"
                if availability == "available" and surface.get("subscription_sunk_cost")
                else "available"
                if availability == "available"
                else "quota is known but execution is unproven; interactive handoff only"
                if availability == "unknown" and surface.get("quota_status") == "ready"
                else "availability is unproven; interactive handoff only"
                if availability == "unknown"
                else "not available"
            )
            surface["economic_score"] = quality_score + subscription_bonus + mode_bonus
        if require_available:
            candidates = [surface for surface in candidates if surface["eligible_for_automatic"]]
        return sorted(
            candidates,
            key=lambda surface: (-int(surface["eligible_for_automatic"]), -int(surface["economic_score"]), surface["surface_id"]),
        )


@dataclass(frozen=True)
class CouncilJob:
    job_id: str
    question: str
    priority: int
    mode: str
    requested_capabilities: tuple[str, ...]
    lanes: tuple[str, ...]
    max_rounds: int
    state: str
    created_at: str
    claimed_by: str | None = None
    claimed_surface: str | None = None
    claimed_at: str | None = None
    result_count: int = 0

    def as_dict(self) -> dict[str, Any]:
        return asdict(self) | {
            "requested_capabilities": list(self.requested_capabilities),
            "lanes": list(self.lanes),
        }


class CouncilStore:
    """Append-only council queue with idempotent local claims."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or default_council_path()

    @contextmanager
    def _locked(self) -> Iterator[Any]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a+", encoding="utf-8") as handle:
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield handle
            finally:
                if fcntl is not None:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    @staticmethod
    def _events(handle: Any) -> list[dict[str, Any]]:
        handle.seek(0)
        events: list[dict[str, Any]] = []
        for line in handle:
            if line.strip():
                events.append(json.loads(line))
        return events

    @staticmethod
    def _state(events: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        jobs: dict[str, dict[str, Any]] = {}
        for event in events:
            event_type = event.get("event")
            job_id = event.get("job_id")
            if event_type == "job_created":
                job = dict(event["job"])
                jobs[job["job_id"]] = job
            elif job_id in jobs and event_type == "job_claimed":
                jobs[job_id].update(
                    {
                        "state": "CLAIMED",
                        "claimed_by": event["worker_id"],
                        "claimed_surface": event["surface_id"],
                        "claimed_at": event["claimed_at"],
                    }
                )
            elif job_id in jobs and event_type == "result_submitted":
                jobs[job_id]["result_count"] = int(jobs[job_id].get("result_count", 0)) + 1
                jobs[job_id]["state"] = "RESULTS"
        return jobs

    @staticmethod
    def _write_event(handle: Any, event: dict[str, Any]) -> None:
        handle.seek(0, 2)
        handle.write(json.dumps(event, sort_keys=True) + "\n")
        handle.flush()

    def create(
        self,
        question: str,
        *,
        priority: int = 50,
        mode: str = "decision",
        requested_capabilities: tuple[str, ...] = ("research.search", "research.synthesis", "reasoning.critique"),
        lanes: tuple[str, ...] = ("subscription", "api_local"),
        max_rounds: int = 3,
    ) -> CouncilJob:
        if not question.strip():
            raise ValueError("council question must not be empty")
        if max_rounds < 1:
            raise ValueError("council max_rounds must be at least 1")
        job = CouncilJob(
            job_id=_new_id("C"),
            question=question.strip(),
            priority=int(priority),
            mode=mode,
            requested_capabilities=tuple(requested_capabilities),
            lanes=tuple(lanes),
            max_rounds=int(max_rounds),
            state="QUEUED",
            created_at=_now(),
        )
        with self._locked() as handle:
            self._write_event(handle, {"event": "job_created", "job": job.as_dict(), "recorded_at": _now()})
        return job

    def list_jobs(self) -> list[CouncilJob]:
        with self._locked() as handle:
            jobs = self._state(self._events(handle))
        return [CouncilJob(**job) for job in sorted(jobs.values(), key=lambda item: item["created_at"])]

    def get(self, job_id: str) -> CouncilJob | None:
        return next((job for job in self.list_jobs() if job.job_id == job_id), None)

    def claim_next(self, worker_id: str, *, surface_id: str) -> CouncilJob | None:
        if not worker_id.strip() or not surface_id.strip():
            raise ValueError("worker_id and surface_id must not be empty")
        with self._locked() as handle:
            jobs = self._state(self._events(handle))
            queued = [job for job in jobs.values() if job["state"] == "QUEUED"]
            if not queued:
                return None
            selected = sorted(queued, key=lambda item: (-int(item["priority"]), item["created_at"]))[0]
            event = {
                "event": "job_claimed",
                "job_id": selected["job_id"],
                "worker_id": worker_id,
                "surface_id": surface_id,
                "claimed_at": _now(),
                "recorded_at": _now(),
            }
            self._write_event(handle, event)
            selected = dict(selected)
            selected.update(
                {
                    "state": "CLAIMED",
                    "claimed_by": worker_id,
                    "claimed_surface": surface_id,
                    "claimed_at": event["claimed_at"],
                }
            )
        return CouncilJob(**selected)

    def submit_result(
        self,
        job_id: str,
        *,
        worker_id: str,
        surface_id: str,
        summary: str,
        evidence: list[dict[str, Any]] | None = None,
        claims: list[dict[str, Any]] | None = None,
        disagreement: bool = False,
    ) -> dict[str, Any]:
        if not summary.strip():
            raise ValueError("council result summary must not be empty")
        result = {
            "result_id": _new_id("result"),
            "job_id": job_id,
            "worker_id": worker_id,
            "surface_id": surface_id,
            "summary": summary.strip(),
            "evidence": evidence or [],
            "claims": claims or [],
            "disagreement": bool(disagreement),
            "submitted_at": _now(),
        }
        if _contains_secret_key(result):
            raise ValueError("council result must not contain secret-looking fields")
        with self._locked() as handle:
            jobs = self._state(self._events(handle))
            job = jobs.get(job_id)
            if job is None:
                raise LookupError(f"unknown council job: {job_id}")
            if job["state"] not in {"CLAIMED", "RESULTS"}:
                raise ValueError(f"council job is not claimable for results: {job['state']}")
            if job.get("claimed_by") != worker_id or job.get("claimed_surface") != surface_id:
                raise PermissionError("result worker and surface do not match the claim")
            self._write_event(handle, {"event": "result_submitted", **result, "recorded_at": _now()})
        return result

    def raw_events(self) -> list[dict[str, Any]]:
        with self._locked() as handle:
            return self._events(handle)
