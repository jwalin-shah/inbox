#!/usr/bin/env python3
"""Verify a LifeOps stdio profile without reading personal source data."""

from __future__ import annotations

import argparse
import json
import os
import selectors
import subprocess
import sys
from pathlib import Path
from typing import Any

PROTOCOL_VERSION = "2025-06-18"
ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LAUNCHER = ROOT / "scripts" / "run_lifeops_mcp_v0_stdio.sh"
REQUIRED_READ_TOOLS = {
    "evidence_packet",
    "fetch",
    "life_context",
    "search",
    "system_audit",
    "triage_all",
}
FORBIDDEN_TOOLS = {
    "approve_pending_action",
    "capture_observation",
    "execute_approved_action",
    "propose_create_task",
    "propose_person_identity_link",
    "propose_person_note",
    "propose_person_relationship",
    "propose_task_from_candidate",
    "propose_update_calendar_event",
}


class VerificationError(RuntimeError):
    """Raised when the profile violates its stdio contract."""


def _read_json_line(process: subprocess.Popen[str], *, timeout: float) -> dict[str, Any]:
    if process.stdout is None:
        raise VerificationError("profile stdout is unavailable")
    selector = selectors.DefaultSelector()
    try:
        selector.register(process.stdout, selectors.EVENT_READ)
        if not selector.select(timeout):
            raise VerificationError(f"profile response timed out after {timeout:g}s")
        line = process.stdout.readline()
    finally:
        selector.close()
    if not line:
        raise VerificationError("profile exited before returning a response")
    try:
        value = json.loads(line)
    except json.JSONDecodeError as exc:
        raise VerificationError("profile returned invalid JSON-RPC") from exc
    if not isinstance(value, dict):
        raise VerificationError("profile returned a non-object JSON-RPC value")
    return value


def _request(
    process: subprocess.Popen[str],
    method: str,
    params: dict[str, Any] | None,
    *,
    request_id: int | None,
    timeout: float,
) -> dict[str, Any]:
    if process.stdin is None:
        raise VerificationError("profile stdin is unavailable")
    payload: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
    if request_id is not None:
        payload["id"] = request_id
    if params is not None:
        payload["params"] = params
    process.stdin.write(json.dumps(payload, separators=(",", ":")) + "\n")
    process.stdin.flush()
    if request_id is None:
        return {}
    response = _read_json_line(process, timeout=timeout)
    if response.get("id") != request_id:
        raise VerificationError(f"profile returned the wrong response id for {method}")
    if "error" in response:
        raise VerificationError(f"profile {method} returned a JSON-RPC error")
    result = response.get("result")
    if not isinstance(result, dict):
        raise VerificationError(f"profile {method} returned no object result")
    return result


def _read_only_annotation(tool: dict[str, Any]) -> bool:
    annotations = tool.get("annotations")
    if not isinstance(annotations, dict):
        return False
    return annotations.get("read_only_hint") is True or annotations.get("readOnlyHint") is True


def validate_tools(result: dict[str, Any]) -> dict[str, Any]:
    tools = result.get("tools")
    if not isinstance(tools, list):
        raise VerificationError("profile tools/list omitted tools")
    by_name = {
        tool.get("name"): tool
        for tool in tools
        if isinstance(tool, dict) and isinstance(tool.get("name"), str)
    }
    names = set(by_name)
    missing = sorted(REQUIRED_READ_TOOLS - names)
    if missing:
        raise VerificationError("required read tools missing: " + ",".join(missing))
    forbidden = sorted(FORBIDDEN_TOOLS & names)
    if forbidden:
        raise VerificationError("forbidden write tools present: " + ",".join(forbidden))
    non_read_only = sorted(name for name, tool in by_name.items() if not _read_only_annotation(tool))
    if non_read_only:
        raise VerificationError("non-read-only tools present: " + ",".join(non_read_only))
    return {
        "tool_count": len(names),
        "required_tools": sorted(REQUIRED_READ_TOOLS),
        "forbidden_tools_present": [],
        "non_read_only_tools": [],
    }


def verify(*, launcher: Path, timeout: float) -> dict[str, Any]:
    environment = os.environ.copy()
    environment["LIFEOPS_MCP_PROFILE"] = "read_only"
    process = subprocess.Popen(
        ["/bin/bash", str(launcher)],
        cwd=ROOT,
        env=environment,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        bufsize=1,
    )
    try:
        initialized = _request(
            process,
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "lifeops-profile-verifier", "version": "1"},
            },
            request_id=1,
            timeout=timeout,
        )
        if initialized.get("protocolVersion") != PROTOCOL_VERSION:
            raise VerificationError("profile negotiated an unexpected protocol version")
        _request(process, "notifications/initialized", None, request_id=None, timeout=timeout)
        tools = validate_tools(_request(process, "tools/list", {}, request_id=2, timeout=timeout))
        return {"protocol_version": initialized["protocolVersion"], **tools}
    finally:
        if process.stdin is not None:
            process.stdin.close()
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--launcher", type=Path, default=DEFAULT_LAUNCHER)
    parser.add_argument("--timeout", type=float, default=30.0)
    args = parser.parse_args(argv)
    try:
        summary = verify(launcher=args.launcher, timeout=args.timeout)
    except (OSError, VerificationError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
