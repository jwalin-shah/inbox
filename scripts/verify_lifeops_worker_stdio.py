#!/usr/bin/env python3
"""Verify the restricted LifeOps worker over stdio without printing personal data."""

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
EXPECTED_TOOLS = {"evidence_packet", "system_audit"}
FORBIDDEN_SCOPE_FLAGS = (
    "provider_writes",
    "worker_control",
    "secret_access",
    "raw_event_mutation",
)
ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LAUNCHER = ROOT / "scripts" / "run_lifeops_mcp_v0_worker_stdio.sh"


class VerificationError(RuntimeError):
    """Raised when the restricted worker violates its stdio contract."""


def _read_json_line(process: subprocess.Popen[str], *, timeout: float) -> dict[str, Any]:
    if process.stdout is None:
        raise VerificationError("worker stdout is unavailable")
    selector = selectors.DefaultSelector()
    try:
        selector.register(process.stdout, selectors.EVENT_READ)
        events = selector.select(timeout)
        if not events:
            raise VerificationError(f"worker response timed out after {timeout:g}s")
        line = process.stdout.readline()
    finally:
        selector.close()
    if not line:
        raise VerificationError("worker exited before returning a response")
    try:
        value = json.loads(line)
    except json.JSONDecodeError as exc:
        raise VerificationError("worker returned invalid JSON-RPC") from exc
    if not isinstance(value, dict):
        raise VerificationError("worker returned a non-object JSON-RPC value")
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
        raise VerificationError("worker stdin is unavailable")
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
        raise VerificationError(f"worker returned the wrong response id for {method}")
    if "error" in response:
        raise VerificationError(f"worker {method} returned a JSON-RPC error")
    result = response.get("result")
    if not isinstance(result, dict):
        raise VerificationError(f"worker {method} returned no object result")
    return result


def _structured_content(result: dict[str, Any]) -> dict[str, Any]:
    structured = result.get("structuredContent")
    if isinstance(structured, dict):
        return structured
    content = result.get("content")
    if isinstance(content, list):
        for item in content:
            if not isinstance(item, dict) or item.get("type") != "text":
                continue
            text = item.get("text")
            if not isinstance(text, str):
                continue
            try:
                value = json.loads(text)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                return value
    raise VerificationError("worker evidence packet returned no structured object")


def _validate_tools(result: dict[str, Any]) -> dict[str, Any]:
    tools = result.get("tools")
    if not isinstance(tools, list):
        raise VerificationError("worker tools/list omitted tools")
    names = {
        tool.get("name")
        for tool in tools
        if isinstance(tool, dict) and isinstance(tool.get("name"), str)
    }
    if names != EXPECTED_TOOLS:
        raise VerificationError(
            "worker tool set changed: " + ",".join(sorted(names))
        )
    for tool in tools:
        if not isinstance(tool, dict):
            continue
        annotations = tool.get("annotations")
        if not isinstance(annotations, dict):
            raise VerificationError(f"worker tool {tool.get('name')} lacks annotations")
        if not (
            annotations.get("read_only_hint") is True
            or annotations.get("readOnlyHint") is True
        ):
            raise VerificationError(f"worker tool {tool.get('name')} is not read-only")
    return {"tool_count": len(tools), "tools": sorted(names)}


def verify(
    *,
    launcher: Path,
    account: str,
    timeout: float,
) -> dict[str, Any]:
    clean_account = account.strip()
    if not clean_account:
        raise VerificationError("an exact account is required")
    environment = os.environ.copy()
    environment["LIFEOPS_WORKER_ACCOUNT_ALLOWLIST"] = clean_account
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
                "clientInfo": {"name": "lifeops-worker-verifier", "version": "1"},
            },
            request_id=1,
            timeout=timeout,
        )
        if initialized.get("protocolVersion") != PROTOCOL_VERSION:
            raise VerificationError("worker negotiated an unexpected protocol version")
        _request(process, "notifications/initialized", None, request_id=None, timeout=timeout)
        tool_summary = _validate_tools(
            _request(process, "tools/list", {}, request_id=2, timeout=timeout)
        )
        packet_result = _request(
            process,
            "tools/call",
            {
                "name": "evidence_packet",
                "arguments": {
                    "account": clean_account,
                    "consumer": "other",
                    "purpose": "stdio runtime verification",
                    "sections": ["attention"],
                    "limit": 1,
                    "calendar_days": 1,
                },
            },
            request_id=3,
            timeout=max(timeout, 90.0),
        )
        packet = _structured_content(packet_result)
        if packet.get("schema_version") != "lifeops.evidence_packet.v1":
            raise VerificationError("worker packet schema is not lifeops.evidence_packet.v1")
        if packet.get("read_only") is not True:
            raise VerificationError("worker packet did not prove read_only=true")
        scope = packet.get("scope")
        if not isinstance(scope, dict):
            raise VerificationError("worker packet omitted scope")
        unsafe = [name for name in FORBIDDEN_SCOPE_FLAGS if scope.get(name) is not False]
        if unsafe:
            raise VerificationError("worker packet is not read-only: " + ",".join(unsafe))
        return {
            "protocol_version": initialized["protocolVersion"],
            **tool_summary,
            "packet": {
                "schema_version": packet["schema_version"],
                "read_only": packet["read_only"],
                **{name: scope[name] for name in FORBIDDEN_SCOPE_FLAGS},
            },
        }
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
    parser.add_argument("--account", default=os.environ.get("LIFEOPS_VERIFY_ACCOUNT", ""))
    parser.add_argument("--timeout", type=float, default=30.0)
    args = parser.parse_args(argv)
    try:
        summary = verify(launcher=args.launcher, account=args.account, timeout=args.timeout)
    except (OSError, VerificationError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
