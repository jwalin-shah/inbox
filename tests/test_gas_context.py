from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import httpx

import gas_context
from gas_context import RegionalFuelPriceContext, _parse_eia_series

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self):
        return self._payload


def test_parse_eia_series_newest_wins() -> None:
    price, period = _parse_eia_series(_load("eia_response.json"))
    assert period == "2026-08-11"
    assert price == Decimal("4.876")


def test_parse_eia_series_skips_invalid_and_out_of_range() -> None:
    data = {
        "response": {
            "data": [
                {"period": "2026-08-11", "value": "4.50"},
                {"period": "2026-08-12", "value": "N/A"},
                {"period": "2026-08-13", "value": "99.99"},
            ]
        }
    }
    price, period = _parse_eia_series(data)
    assert period == "2026-08-11"
    assert price == Decimal("4.50")


def test_parse_eia_series_empty() -> None:
    assert _parse_eia_series({"response": {"data": []}}) is None
    assert _parse_eia_series({"response": {}}) is None
    assert _parse_eia_series([]) is None


def test_weekly_average_no_key_returns_none() -> None:
    assert RegionalFuelPriceContext(None).weekly_average() is None


def test_weekly_average_calls_eia_get(monkeypatch) -> None:
    captured: dict = {}

    def fake_get(url, **kwargs):
        captured["url"] = url
        captured["params"] = kwargs.get("params")
        return _FakeResponse(_load("eia_response.json"))

    monkeypatch.setattr(gas_context.egress_audit, "get", fake_get)

    result = RegionalFuelPriceContext(api_key="k").weekly_average()

    assert result == {
        "source": "eia",
        "series": "PET.EMM_EPMR_PTE_NUS_DPG.W",
        "price_usd_per_gallon": 4.876,
        "period": "2026-08-11",
    }
    assert captured["url"] == "https://api.eia.gov/v2/seriesid/PET.EMM_EPMR_PTE_NUS_DPG.W"
    assert captured["params"]["api_key"] == "k"
    assert captured["params"]["data[0]"] == "value"


def test_weekly_average_fails_closed(monkeypatch) -> None:
    def boom(url, **kwargs):
        raise httpx.ConnectError("down")

    monkeypatch.setattr(gas_context.egress_audit, "get", boom)
    assert RegionalFuelPriceContext(api_key="k").weekly_average() is None