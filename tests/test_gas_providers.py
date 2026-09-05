from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import httpx

import gas_providers
from gas_models import FuelPrice, GasStation, RouteLeg
from gas_providers import (
    CompositeFuelPriceProvider,
    FuelPriceProvider,
    GooglePlacesFuelProvider,
    GoogleRoutesProvider,
    _parse_duration,
    _to_google_spot,
)

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


def test_parse_duration() -> None:
    assert _parse_duration("240s") == 240.0
    assert _parse_duration(300) == 300.0
    assert _parse_duration(None) is None
    assert _parse_duration("nonsense") is None


def test_to_google_spot() -> None:
    assert _to_google_spot({"latitude": 1.0, "longitude": 2.0}) == {
        "location": {"latLng": {"latitude": 1.0, "longitude": 2.0}}
    }
    assert _to_google_spot({"address": "x"}) == {"address": "x"}


def test_nearby_stations_normalize_google_response(monkeypatch) -> None:
    payload = _load("places_gas_response.json")
    captured: dict = {}

    def fake_post(url, **kwargs):
        captured["url"] = url
        captured["headers"] = kwargs.get("headers")
        captured["body"] = kwargs.get("json")
        captured["timeout"] = kwargs.get("timeout")
        return _FakeResponse(payload)

    monkeypatch.setattr(gas_providers.egress_audit, "post", fake_post)

    stations = GooglePlacesFuelProvider(api_key="k").nearby_stations(37.5, -121.9, 10000.0, "regular")

    assert len(stations) == 4
    by_id = {s.provider_id: s for s in stations}

    arco = by_id["ChIJARCO"]
    assert arco.name == "ARCO"
    assert arco.provider == "google"
    assert arco.price_for("regular").price == Decimal("4.47")
    assert arco.price_for("regular").fuel_type == "regular"
    assert arco.price_for("regular").currency == "USD"
    assert arco.price_for("premium") is not None
    assert arco.maps_uri and "destination_place_id=ChIJARCO" in arco.maps_uri

    assert by_id["ChIJSTALE"].price_for("regular").price == Decimal("3.999")
    assert by_id["ChIJNOPRICE"].fuel_prices == []

    assert captured["url"] == "https://places.googleapis.com/v1/places:searchNearby"
    assert captured["headers"]["X-Goog-FieldMask"]
    assert captured["headers"]["X-Goog-Api-Key"] == "k"
    assert captured["body"]["includedTypes"] == ["gas_station"]
    assert captured["body"]["locationRestriction"]["circle"]["radius"] == 10000.0


def test_nearby_stations_no_key_returns_empty() -> None:
    assert GooglePlacesFuelProvider(None).nearby_stations(1, 2, 1000, "regular") == []


def test_nearby_stations_fails_closed(monkeypatch) -> None:
    def boom(url, **kwargs):
        raise httpx.ConnectError("down")

    monkeypatch.setattr(gas_providers.egress_audit, "post", boom)
    assert GooglePlacesFuelProvider(api_key="k").nearby_stations(1, 2, 1000, "regular") == []


def test_routes_provider_parses_leg(monkeypatch) -> None:
    payload = _load("routes_response.json")
    monkeypatch.setattr(gas_providers.egress_audit, "post", lambda url, **kw: _FakeResponse(payload))
    leg = GoogleRoutesProvider(api_key="k").route(
        {"latitude": 1.0, "longitude": 2.0}, {"address": "SFO"}
    )
    assert leg == RouteLeg(distance_meters=1770.0, duration_seconds=240.0)
    assert leg.distance_miles == 1770 / 1609.344
    assert leg.duration_minutes == 4.0


def test_routes_provider_no_key_returns_none() -> None:
    assert GoogleRoutesProvider(None).route({}, {}) is None


def test_routes_provider_fails_closed(monkeypatch) -> None:
    def boom(url, **kwargs):
        raise httpx.ConnectError("down")

    monkeypatch.setattr(gas_providers.egress_audit, "post", boom)
    assert GoogleRoutesProvider(api_key="k").route({}, {}) is None


# ── Composite (freshest-wins) ────────────────────────────────────────────────


class _StationsProvider(FuelPriceProvider):
    def __init__(self, stations: list[GasStation]) -> None:
        self._stations = stations

    def nearby_stations(self, latitude, longitude, radius_meters, fuel_type="regular"):
        return list(self._stations)


def _station(
    pid: str,
    lat: float,
    lng: float,
    regular: float | None = None,
    updated_at: datetime | None = None,
) -> GasStation:
    prices = (
        [FuelPrice("regular", Decimal(str(regular)), "USD", updated_at)]
        if regular is not None
        else []
    )
    return GasStation(
        provider="test",
        provider_id=pid,
        name=pid,
        address="",
        latitude=lat,
        longitude=lng,
        fuel_prices=prices,
        maps_uri=None,
    )


def test_composite_fresher_wins() -> None:
    t0 = datetime(2026, 8, 18, 0, 0, tzinfo=UTC)
    t1 = datetime(2026, 8, 18, 12, 0, tzinfo=UTC)
    a = _station("A", 37.5, -121.9, regular=4.80, updated_at=t0)
    b = _station("B", 37.5, -121.9, regular=4.75, updated_at=t1)
    comp = CompositeFuelPriceProvider([_StationsProvider([a]), _StationsProvider([b])])
    out = comp.nearby_stations(37.5, -121.9, 10000, "regular")
    assert len(out) == 1
    assert out[0].price_for("regular").price == Decimal("4.75")
    assert out[0].provider_id == "B"


def test_composite_cheaper_wins_on_same_freshness() -> None:
    t = datetime(2026, 8, 18, 0, 0, tzinfo=UTC)
    a = _station("A", 37.5, -121.9, regular=4.80, updated_at=t)
    b = _station("B", 37.5, -121.9, regular=4.75, updated_at=t)
    comp = CompositeFuelPriceProvider([_StationsProvider([a]), _StationsProvider([b])])
    out = comp.nearby_stations(37.5, -121.9, 10000, "regular")
    assert out[0].price_for("regular").price == Decimal("4.75")


def test_composite_missing_timestamp_never_beats_stamped() -> None:
    t1 = datetime(2026, 8, 18, 12, 0, tzinfo=UTC)
    a = _station("A", 37.5, -121.9, regular=4.60, updated_at=None)
    b = _station("B", 37.5, -121.9, regular=4.99, updated_at=t1)
    comp = CompositeFuelPriceProvider([_StationsProvider([a]), _StationsProvider([b])])
    out = comp.nearby_stations(37.5, -121.9, 10000, "regular")
    assert out[0].price_for("regular").price == Decimal("4.99")


def test_composite_distinct_stations_pass_through() -> None:
    a = _station("A", 37.5, -121.9, regular=4.80)
    b = _station("B", 37.6, -121.8, regular=4.75)
    comp = CompositeFuelPriceProvider([_StationsProvider([a]), _StationsProvider([b])])
    assert len(comp.nearby_stations(37.5, -121.9, 10000, "regular")) == 2


def test_composite_deterministic() -> None:
    t0 = datetime(2026, 8, 18, 0, 0, tzinfo=UTC)
    t1 = datetime(2026, 8, 18, 12, 0, tzinfo=UTC)
    a = _station("A", 37.5, -121.9, regular=4.80, updated_at=t0)
    b = _station("B", 37.5, -121.9, regular=4.75, updated_at=t1)
    comp = CompositeFuelPriceProvider([_StationsProvider([a]), _StationsProvider([b])])

    def snap():
        return [(s.provider_id, str(s.price_for("regular").price)) for s in comp.nearby_stations(37.5, -121.9, 10000, "regular")]

    assert snap() == snap()


def test_composite_no_providers_returns_empty() -> None:
    assert CompositeFuelPriceProvider([]).nearby_stations(37.5, -121.9, 10000, "regular") == []