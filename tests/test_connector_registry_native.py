from unittest.mock import patch


def test_imessage_status_reports_inbox_native_reader_without_imsg():
    from connector_registry import CONNECTORS, connector_status

    imessage = next(item for item in CONNECTORS if item.id == "imessage")
    with patch("connector_registry.shutil.which", return_value=None):
        result = connector_status(imessage)

    assert result["installed"] is False
    assert result["auth_state"] == "native"
    assert result["native_read_available"] is True
    assert result["native_read_path"] == "Inbox services.imsg_* SQLite reader"
    assert result["read_ready"] is True
    assert result["remediation"][0].startswith("Inbox's built-in iMessage reader")
