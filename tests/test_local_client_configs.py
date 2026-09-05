from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load(name: str) -> dict:
    return json.loads((ROOT / name).read_text())


def test_pi_config_disables_broader_inbox_servers() -> None:
    servers = _load(".pi/mcp.json")["mcpServers"]

    assert servers["inbox"]["disabled"] is True
    assert servers["inbox-readonly"]["disabled"] is True
    assert servers["lifeops-worker"]["directTools"] == [
        "evidence_packet",
        "system_audit",
    ]


def test_shared_configs_register_the_restricted_worker_without_a_token() -> None:
    for name in (".mcp.json", ".cursor/mcp.json"):
        servers = _load(name)["mcpServers"]
        readonly = servers["lifeops-readonly"]
        assert readonly["env"] == {"LIFEOPS_MCP_PROFILE": "read_only"}
        assert "INBOX_SERVER_TOKEN" not in json.dumps(readonly)
        worker = servers["lifeops-worker"]
        assert worker["command"] == "/bin/bash"
        assert worker["args"] == [
            "/Users/jwalinshah/projects/inbox-lifeops-mcp-v0/scripts/run_lifeops_mcp_v0_worker_stdio.sh"
        ]
        assert "INBOX_SERVER_TOKEN" not in json.dumps(worker)
