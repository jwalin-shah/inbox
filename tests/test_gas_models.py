from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal

from gas_models import (
    GasPreferences,
    load_gas_preferences,
    money_to_decimal,
    parse_google_timestamp,
)


def test_load_gas_preferences_defaults(tmp_path) -> None:
    prefs = load_gas_preferences(path=tmp_path / "missing.json", env={})
    assert prefs == GasPreferences()


def test_load_gas_preferences_env_override(tmp_path) -> None:
    prefs = load_gas_preferences(
        path=tmp_path / "missing.json",
        env={
            "INBOX_GAS_FUEL_TYPE": "premium",
            "INBOX_GAS_GALLONS_DEFAULT": "12",
            "INBOX_GAS_HOME": "37.5,-121.9",
            "INBOX_GAS_PREFERRED_BRANDS": "Costco, ARCO",
        },
    )
    assert prefs.fuel_type == "premium"
    assert prefs.gallons_default == 12.0
    assert prefs.home == "37.5,-121.9"
    assert prefs.preferred_brands == ("Costco", "ARCO")


def test_load_gas_preferences_from_file(tmp_path) -> None:
    path = tmp_path / "gas.json"
    path.write_text(
        json.dumps({"fuel_type": "diesel", "max_detour_minutes": 4, "vehicle_mpg": 30}),
        encoding="utf-8",
    )
    prefs = load_gas_preferences(path=path, env={})
    assert prefs.fuel_type == "diesel"
    assert prefs.max_detour_minutes == 4.0
    assert prefs.vehicle_mpg == 30.0


def test_load_gas_preferences_bad_fuel_type_falls_back(tmp_path) -> None:
    path = tmp_path / "gas.json"
    path.write_text(json.dumps({"fuel_type": "rocket_fuel"}), encoding="utf-8")
    prefs = load_gas_preferences(path=path, env={})
    assert prefs.fuel_type == "regular"


def test_money_to_decimal() -> None:
    assert money_to_decimal({"units": "4", "nanos": 470000000}) == Decimal("4.47")
    assert money_to_decimal({"units": "0", "nanos": 0}) == Decimal("0")
    assert money_to_decimal(None) is None
    assert money_to_decimal({"units": "abc", "nanos": 0}) is None


def test_parse_google_timestamp() -> None:
    dt = parse_google_timestamp("2026-08-18T17:20:00Z")
    assert dt == datetime(2026, 8, 18, 17, 20, 0, tzinfo=UTC)
    assert parse_google_timestamp(None) is None
    assert parse_google_timestamp("not-a-time") is None