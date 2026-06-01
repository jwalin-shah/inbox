from unittest.mock import patch

from capability_inventory import build_capability_inventory, module_summary


def test_inventory_builds_without_provider_or_connector_execution():
    with patch("subprocess.run") as run:
        inventory = build_capability_inventory()

    run.assert_not_called()
    assert inventory["schema_version"] == "inbox.capability_inventory.v1"
    assert inventory["invariants"]["provider_calls"] is False
    assert inventory["invariants"]["connector_binaries_executed"] is False
    assert inventory["summary"]["capabilities"] >= len(inventory["modules"])


def test_mutating_capabilities_require_approval_policy():
    inventory = build_capability_inventory()
    mutating = [
        cap
        for cap in inventory["capabilities"]
        if cap["category"] in {"external_write", "delete", "publish", "pay", "submit"}
    ]

    assert mutating
    assert all(cap["approval"]["required"] is True for cap in mutating)
    assert all(cap["exposure"]["mcp_readonly"] is False for cap in mutating)
    assert all(cap["risk"] in {"high", "critical"} for cap in mutating)


def test_memory_extract_is_local_write_not_provider_write():
    inventory = build_capability_inventory()
    by_id = {cap["id"]: cap for cap in inventory["capabilities"]}

    cap = by_id["mcp.extract_and_save_memory"]
    assert cap["category"] == "local_write"
    assert cap["risk"] == "medium"
    assert cap["approval"]["mode"] == "explicit_local_write_exception"


def test_readonly_mcp_capability_inventory_is_visible_and_safe():
    inventory = build_capability_inventory()
    by_id = {cap["id"]: cap for cap in inventory["capabilities"]}

    cap = by_id["mcp.get_capability_inventory"]
    assert cap["category"] == "read"
    assert cap["route"] == {"method": "GET", "path": "/capabilities"}
    assert cap["approval"]["required"] is False
    assert cap["exposure"]["mcp_readonly"] is True
    assert cap["exposure"]["agent_safe"] is True


def test_connector_modules_do_not_expose_secret_storage():
    inventory = build_capability_inventory()
    connector_modules = [module for module in inventory["modules"] if module["id"].startswith("connector.")]

    assert connector_modules
    for module in connector_modules:
        assert "token" not in str(module["storage_refs"]).lower()
        assert all(ref["secret"] is False for ref in module["storage_refs"])


def test_every_module_capability_id_resolves_to_a_capability_object():
    inventory = build_capability_inventory()
    capability_ids = {cap["id"] for cap in inventory["capabilities"]}

    missing = {
        module["id"]: sorted(set(module["capabilities"]) - capability_ids)
        for module in inventory["modules"]
        if set(module["capabilities"]) - capability_ids
    }

    assert missing == {}


def test_connector_external_writes_are_deferred_and_not_exposed():
    inventory = build_capability_inventory()
    deferred = [
        cap
        for cap in inventory["capabilities"]
        if cap["id"].startswith("connector.") and cap["id"].endswith(".external_write_deferred")
    ]

    assert deferred
    for cap in deferred:
        assert cap["category"] == "external_write"
        assert cap["readiness"] == "deferred"
        assert cap["approval"]["required"] is True
        assert cap["approval"]["server_lease_required"] is True
        assert cap["route"] is None
        assert cap["command"] is None
        assert cap["exposure"]["rest"] is False
        assert cap["exposure"]["mcp_readonly"] is False
        assert cap["exposure"]["mcp_full"] is False
        assert cap["exposure"]["agent_safe"] is False


def test_module_summary_is_compact():
    summary = module_summary()

    assert "capabilities" not in summary["modules"][0]
    assert summary["summary"]["modules"] == len(summary["modules"])
