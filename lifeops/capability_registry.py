from __future__ import annotations

import json
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REGISTRY_SCHEMA = "lifeops.capability_registry.v1"
CommandRunner = Callable[[Sequence[str]], str]


def _now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass(frozen=True)
class CapabilityRoute:
    capability: str
    route_id: str
    provider: str
    transport: str
    risk: str
    priority: int
    required_mcp_server: str | None = None
    installed: bool | None = None
    authenticated: bool | None = None
    available: bool | None = None
    notes: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


DEFAULT_ROUTES: tuple[CapabilityRoute, ...] = (
    CapabilityRoute(
        "task.create",
        "openclaw/inbox_tasks_approval",
        "google_tasks",
        "mcp",
        "R1",
        10,
        required_mcp_server="inbox_tasks_approval",
        notes="Configured OpenClaw Inbox task surface; live lease handoff remains unproven.",
    ),
    CapabilityRoute(
        "task.create",
        "openclaw/apple_reminders",
        "apple_reminders",
        "mcp",
        "R1",
        20,
        required_mcp_server="apple_reminders",
        notes="Fallback candidate; requires an explicit OpenClaw route and read-back proof.",
    ),
    CapabilityRoute(
        "task.create",
        "openclaw/agent_gemini",
        "gemini",
        "agent",
        "R1",
        30,
        notes="Provider-backed agent fallback; availability is never inferred from model config.",
    ),
    CapabilityRoute(
        "task.create",
        "openclaw/browser_google_tasks",
        "browser",
        "browser",
        "R1",
        40,
        notes="Last-resort browser route; requires a separate authenticated read-back proof.",
    ),
)


def _run_command(argv: Sequence[str]) -> str:
    completed = subprocess.run(
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


def _load_json(raw: str, label: str) -> dict[str, Any] | list[Any]:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"OpenClaw {label} returned invalid JSON: {exc}") from exc
    if not isinstance(value, (dict, list)):
        raise RuntimeError(f"OpenClaw {label} JSON must be an object or array")
    return value


class CapabilityRegistry:
    def __init__(self, path: Path, routes: tuple[CapabilityRoute, ...] = DEFAULT_ROUTES) -> None:
        self.path = path
        self.routes = routes
        self.snapshot: dict[str, Any] | None = None

    def sync(self, *, openclaw_command: str = "openclaw", runner: CommandRunner | None = None) -> dict[str, Any]:
        run = runner or _run_command
        errors: list[str] = []
        plugins: list[dict[str, Any]] = []
        mcp_servers: dict[str, Any] = {}
        version = "unknown"

        try:
            version = run((openclaw_command, "--version")).strip()
        except (OSError, RuntimeError) as exc:
            errors.append(str(exc))
        try:
            raw_plugins = _load_json(run((openclaw_command, "plugins", "list", "--json")), "plugins list")
            if isinstance(raw_plugins, dict):
                plugins = [
                    {
                        "id": item.get("id"),
                        "status": item.get("status"),
                        "enabled": item.get("enabled"),
                        "tool_names": item.get("toolNames", []),
                    }
                    for item in raw_plugins.get("plugins", [])
                    if isinstance(item, dict) and item.get("id")
                ]
        except (OSError, RuntimeError) as exc:
            errors.append(str(exc))
        try:
            raw_mcp = _load_json(run((openclaw_command, "mcp", "list", "--json")), "mcp list")
            if isinstance(raw_mcp, dict):
                mcp_servers = {
                    str(name): {"configured": True}
                    for name in raw_mcp
                }
        except (OSError, RuntimeError) as exc:
            errors.append(str(exc))

        synced_routes: list[dict[str, Any]] = []
        for route in self.routes:
            installed = route.installed
            if route.required_mcp_server is not None:
                installed = route.required_mcp_server in mcp_servers
            synced_routes.append(
                asdict(
                    CapabilityRoute(
                        **{
                            **route.as_dict(),
                            "installed": installed,
                            "authenticated": route.authenticated,
                            "available": route.available,
                        }
                    )
                )
            )
        self.snapshot = {
            "schema_version": REGISTRY_SCHEMA,
            "synced_at": _now(),
            "openclaw": {
                "command": openclaw_command,
                "version": version,
                "plugin_count": len(plugins),
                "plugins": plugins,
                "mcp_servers": mcp_servers,
            },
            "routes": synced_routes,
            "errors": errors,
            "readiness": "degraded" if errors else "configured_only",
        }
        self.save()
        return self.snapshot

    def save(self) -> None:
        if self.snapshot is None:
            raise ValueError("capability registry has not been synchronized")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.snapshot, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def load(self) -> dict[str, Any]:
        if self.snapshot is None:
            if not self.path.exists():
                self.snapshot = {
                    "schema_version": REGISTRY_SCHEMA,
                    "synced_at": None,
                    "openclaw": {"command": "openclaw", "version": "unknown", "plugin_count": 0, "plugins": [], "mcp_servers": {}},
                    "routes": [route.as_dict() for route in self.routes],
                    "errors": ["registry has not been synchronized"],
                    "readiness": "unknown",
                }
            else:
                self.snapshot = json.loads(self.path.read_text(encoding="utf-8"))
        snapshot = self.snapshot
        if snapshot is None:
            raise RuntimeError("capability registry failed to load")
        return snapshot

    def route_candidates(self, capability: str) -> list[dict[str, Any]]:
        snapshot = self.load()
        return sorted(
            [route for route in snapshot.get("routes", []) if route.get("capability") == capability],
            key=lambda route: int(route.get("priority", 999)),
        )

    def resolve(self, capability: str, *, require_available: bool = False) -> dict[str, Any]:
        candidates = self.route_candidates(capability)
        if not candidates:
            raise LookupError(f"no route candidates for capability: {capability}")
        if require_available:
            candidates = [route for route in candidates if route.get("available") is True]
            if not candidates:
                raise LookupError(f"no proven available route for capability: {capability}")
        else:
            candidates = [route for route in candidates if route.get("available") is not False]
            if not candidates:
                raise LookupError(f"all routes are unavailable for capability: {capability}")
        return candidates[0]
