from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from lifeops.action_envelope import ActionEnvelope, TraceStore
from lifeops.capability_registry import CapabilityRegistry
from lifeops.council import CouncilRouter, CouncilStore, CouncilSurfaceRegistry
from lifeops.executors.openclaw import OpenClawExecutionAdapter, OpenClawExecutionError


def _registry_path() -> Path:
    return Path(os.getenv("LIFEOPS_REGISTRY_PATH", "state/lifeops-capabilities.json"))


def _print(payload: Any) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


def _council_store() -> CouncilStore:
    return CouncilStore()


def _council_surface_registry() -> CouncilSurfaceRegistry:
    registry = CouncilSurfaceRegistry()
    if not registry.path.exists():
        registry.sync_static()
    return registry


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="LifeOps capability coordination CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    capabilities = subparsers.add_parser("capabilities")
    capability_sub = capabilities.add_subparsers(dest="capability_command", required=True)
    sync = capability_sub.add_parser("sync", help="read OpenClaw inventories into LifeOps metadata")
    sync.add_argument("--openclaw-command", default="openclaw")

    routes = subparsers.add_parser("routes", help="show deterministic route candidates")
    routes.add_argument("capability")

    execute = subparsers.add_parser("execute", help="plan or explicitly attempt a capability")
    execute.add_argument("capability")
    execute.add_argument("--title", required=True)
    execute.add_argument("--due")
    execute.add_argument("--notes")
    execute.add_argument("--route")
    execute.add_argument("--live", action="store_true")

    trace = subparsers.add_parser("trace", help="read one local action trace")
    trace.add_argument("command_id")

    council = subparsers.add_parser("council", help="coordinate research and reasoning workers")
    council_sub = council.add_subparsers(dest="council_command", required=True)
    council_sub.add_parser("surfaces", help="show subscription/API/local surface economics")
    council_sub.add_parser("surface-sync", help="write the static surface catalog without probing providers")
    council_quota = council_sub.add_parser("quota-sync", help="read local quota-axi metadata into surface state")
    council_quota.add_argument("--quota-command", default="quota-axi")
    council_routes = council_sub.add_parser("routes", help="rank council surfaces for a capability")
    council_routes.add_argument("capability", nargs="?", default="research.search")
    council_routes.add_argument("--mode", choices=("normal", "deep"), default="normal")
    council_create = council_sub.add_parser("create", help="enqueue a council question")
    council_create.add_argument("--question", required=True)
    council_create.add_argument("--priority", type=int, default=50)
    council_create.add_argument("--mode", default="decision")
    council_create.add_argument("--max-rounds", type=int, default=3)
    council_claim = council_sub.add_parser("claim", help="claim the highest-priority queued council job")
    council_claim.add_argument("--worker", required=True)
    council_claim.add_argument("--surface", required=True)
    council_show = council_sub.add_parser("show", help="read a council job")
    council_show.add_argument("job_id")
    council_result = council_sub.add_parser("result", help="append a structured council result")
    council_result.add_argument("job_id")
    council_result.add_argument("--worker", required=True)
    council_result.add_argument("--surface", required=True)
    council_result.add_argument("--summary", required=True)
    council_result.add_argument("--evidence-json", default="[]")
    council_result.add_argument("--claims-json", default="[]")
    council_result.add_argument("--disagreement", action="store_true")
    council_sub.add_parser("status", help="show queue state and event count")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    registry = CapabilityRegistry(_registry_path())

    if args.command == "capabilities" and args.capability_command == "sync":
        _print(registry.sync(openclaw_command=args.openclaw_command))
        return 0

    if args.command == "routes":
        _print({"capability": args.capability, "routes": registry.route_candidates(args.capability)})
        return 0

    if args.command == "trace":
        record = TraceStore().get(args.command_id)
        if record is None:
            _print({"status": "NOT_FOUND", "command_id": args.command_id})
            return 1
        _print(record)
        return 0

    if args.command == "council":
        surface_registry = _council_surface_registry()
        store = _council_store()
        if args.council_command == "surfaces":
            _print(surface_registry.load())
            return 0
        if args.council_command == "surface-sync":
            _print(surface_registry.sync_static())
            return 0
        if args.council_command == "quota-sync":
            _print(surface_registry.sync_quota(quota_command=args.quota_command))
            return 0
        if args.council_command == "routes":
            ranked = CouncilRouter(surface_registry).rank(args.capability, mode=args.mode)
            _print(
                {
                    "capability": args.capability,
                    "mode": args.mode,
                    "ranked": ranked,
                    "automatic_selection": next(
                        (surface for surface in ranked if surface["eligible_for_automatic"]),
                        None,
                    ),
                }
            )
            return 0
        if args.council_command == "create":
            job = store.create(
                args.question,
                priority=args.priority,
                mode=args.mode,
                max_rounds=args.max_rounds,
            )
            _print(job.as_dict())
            return 0
        if args.council_command == "claim":
            try:
                surface_registry.get(args.surface)
                job = store.claim_next(args.worker, surface_id=args.surface)
            except LookupError as exc:
                _print({"status": "BLOCKED", "reason": str(exc)})
                return 2
            if job is None:
                _print({"status": "EMPTY", "worker": args.worker})
                return 1
            _print(job.as_dict())
            return 0
        if args.council_command == "show":
            job = store.get(args.job_id)
            if job is None:
                _print({"status": "NOT_FOUND", "job_id": args.job_id})
                return 1
            _print(job.as_dict())
            return 0
        if args.council_command == "result":
            try:
                evidence = json.loads(args.evidence_json)
                claims = json.loads(args.claims_json)
                if not isinstance(evidence, list) or not isinstance(claims, list):
                    raise ValueError("evidence and claims must be JSON arrays")
                result = store.submit_result(
                    args.job_id,
                    worker_id=args.worker,
                    surface_id=args.surface,
                    summary=args.summary,
                    evidence=evidence,
                    claims=claims,
                    disagreement=args.disagreement,
                )
            except (json.JSONDecodeError, LookupError, PermissionError, ValueError) as exc:
                _print({"status": "BLOCKED", "reason": str(exc)})
                return 2
            _print(result)
            return 0
        if args.council_command == "status":
            jobs = [job.as_dict() for job in store.list_jobs()]
            states = sorted({job["state"] for job in jobs})
            counts = {state: sum(job["state"] == state for job in jobs) for state in states}
            _print(
                {
                    "schema_version": "lifeops.council.v1",
                    "counts": counts,
                    "jobs": jobs,
                    "event_count": len(store.raw_events()),
                }
            )
            return 0

    if args.command == "execute":
        try:
            if args.route is None:
                route = registry.resolve(args.capability, require_available=args.live)
            else:
                route = next(
                    (
                        candidate
                        for candidate in registry.route_candidates(args.capability)
                        if candidate.get("route_id") == args.route
                    ),
                    None,
                )
                if route is None:
                    raise LookupError(
                        f"route is not registered for {args.capability}: {args.route}"
                    )
                if args.live and route.get("available") is not True:
                    raise LookupError(f"route is not proven available: {args.route}")
        except LookupError as exc:
            _print({"status": "BLOCKED", "reason": str(exc)})
            return 2
        envelope = ActionEnvelope.create(
            capability=args.capability,
            target="personal",
            inputs={key: value for key, value in {"title": args.title, "due": args.due, "notes": args.notes}.items() if value is not None},
            risk=str(route["risk"]),
            route=str(route["route_id"] if args.route is None else args.route),
            expected_postcondition="task exists exactly once",
        )
        try:
            result = OpenClawExecutionAdapter().execute(envelope, live=args.live)
        except OpenClawExecutionError as exc:
            result = {"status": "BLOCKED", "command_id": envelope.command_id, "reason": str(exc)}
            TraceStore().append(envelope, result)
            _print({"envelope": envelope.to_dict(), "result": result})
            return 2
        TraceStore().append(envelope, result)
        _print({"envelope": envelope.to_dict(), "result": result})
        return 0

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
