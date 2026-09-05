from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from gas_models import FuelPrice, GasPreferences, GasStation, RouteLeg
from gas_optimizer import (
    _pick_route_candidates,
    _score_candidate,
    find_best_gas,
    find_nearby_gas_prices,
    select_best,
)
from gas_providers import FuelPriceProvider, RouteProvider

NOW = datetime(2026, 8, 18, 18, 0, 0, tzinfo=UTC)
PREFS = GasPreferences(
    gallons_default=10,
    time_value_per_hour=15,
    vehicle_mpg=25,
)


def fresh(when: datetime = NOW) -> datetime:
    return when - timedelta(minutes=30)


def make_station(
    pid: str,
    name: str,
    lat: float = 37.5,
    lng: float = -121.9,
    regular: float | None = None,
    updated_at: datetime | None = None,
) -> GasStation:
    prices = []
    if regular is not None:
        prices.append(FuelPrice("regular", Decimal(str(regular)), "USD", updated_at))
    return GasStation(
        provider="google",
        provider_id=pid,
        name=name,
        address="",
        latitude=lat,
        longitude=lng,
        fuel_prices=prices,
        maps_uri=None,
    )


class FakePlaces(FuelPriceProvider):
    def __init__(self, stations: list[GasStation]):
        self._stations = stations

    def nearby_stations(self, latitude, longitude, radius_meters, fuel_type):
        return list(self._stations)


class FakeRoutes(RouteProvider):
    def __init__(self, fn):
        self._fn = fn

    def route(self, origin, destination, intermediates=None):
        return self._fn(origin, destination, intermediates)


def candidate(station: GasStation, detour_minutes: float, gallons: float = 10):
    return _score_candidate(
        station,
        station.price_for("regular"),
        distance_miles=detour_minutes,
        drive_minutes=detour_minutes,
        detour_miles=detour_minutes / 3.0,
        detour_minutes=detour_minutes,
        age_minutes=20,
        gallons=gallons,
        prefs=PREFS,
    )


# ── Pure ranking tests ───────────────────────────────────────────────────────


def test_cheapest_wins_when_equally_close() -> None:
    arco = make_station("A", "ARCO", regular=4.47, updated_at=fresh())
    costco = make_station("B", "Costco", regular=4.29, updated_at=fresh())
    rec, rest, over, _ = select_best(
        [candidate(arco, 2.0), candidate(costco, 2.0)], PREFS, None
    )
    assert rec is not None and rec.station.provider_id == "B"
    assert [c.station.provider_id for c in rest] == ["A"]
    assert over == []


def test_slightly_more_expensive_wins_when_detour_large() -> None:
    arco = make_station("A", "ARCO", regular=4.47, updated_at=fresh())
    costco = make_station("B", "Costco", regular=4.29, updated_at=fresh())
    rec, _, _, _ = select_best(
        [candidate(arco, 2.4), candidate(costco, 13.0)], PREFS, None
    )
    assert rec is not None and rec.station.provider_id == "A"


def test_max_detour_respected() -> None:
    arco = make_station("A", "ARCO", regular=4.47, updated_at=fresh())
    costco = make_station("B", "Costco", regular=4.29, updated_at=fresh())
    rec, rest, over, _ = select_best(
        [candidate(arco, 2.4), candidate(costco, 13.0)], PREFS, 1.0
    )
    assert rec is None
    assert rest == []
    assert len(over) == 2


def test_preferred_brand_breaks_tie() -> None:
    arco = make_station("A", "ARCO", regular=4.29, updated_at=fresh())
    costco = make_station("B", "Costco Gasoline", regular=4.29, updated_at=fresh())
    prefs = GasPreferences(
        gallons_default=10,
        time_value_per_hour=15,
        vehicle_mpg=25,
        preferred_brands=("costco",),
    )
    rec, _, _, _ = select_best([candidate(arco, 2.0), candidate(costco, 2.0)], prefs, None)
    assert rec is not None and rec.station.provider_id == "B"


# ── End-to-end orchestration with injected providers ─────────────────────────


def _equal_detour_routes(detour_minutes: float) -> FakeRoutes:
    seconds = detour_minutes * 60.0
    return FakeRoutes(lambda o, d, i: RouteLeg(distance_meters=seconds * 13.4, duration_seconds=seconds))


def test_find_best_gas_deterministic() -> None:
    stations = [
        make_station("A", "ARCO", regular=4.47, updated_at=fresh()),
        make_station("B", "Costco", regular=4.29, updated_at=fresh()),
    ]

    def run():
        return find_best_gas(
            origin="37.5,-121.9",
            preferences=PREFS,
            place_provider=FakePlaces(stations),
            route_provider=_equal_detour_routes(2.0),
            now=NOW,
        )

    assert run() == run()


def test_find_best_gas_needs_origin() -> None:
    result = find_best_gas(
        origin=None,
        preferences=PREFS,
        place_provider=FakePlaces([]),
        route_provider=FakeRoutes(lambda o, d, i: None),
        now=NOW,
    )
    assert result["status"] == "NEEDS_ORIGIN"
    assert result["recommended"] is None


def test_find_best_gas_no_price_data() -> None:
    result = find_best_gas(
        origin="37.5,-121.9",
        preferences=PREFS,
        place_provider=FakePlaces([make_station("X", "Empty")]),
        route_provider=FakeRoutes(lambda o, d, i: None),
        now=NOW,
    )
    assert result["status"] == "NO_PRICE_DATA"


def test_stale_price_excluded_from_recommendation() -> None:
    fresh_station = make_station("F", "FreshFuel", regular=4.00, updated_at=fresh())
    stale_station = make_station(
        "S", "OldTown", regular=3.00, updated_at=NOW - timedelta(hours=73)
    )
    result = find_best_gas(
        origin="37.5,-121.9",
        preferences=PREFS,
        place_provider=FakePlaces([fresh_station, stale_station]),
        route_provider=_equal_detour_routes(2.0),
        now=NOW,
    )
    assert result["status"] == "OK"
    assert result["recommended"]["station_id"] == "F"
    assert [a["station_id"] for a in result["alternatives"]] == ["S"]
    assert result["metadata"]["stale_excluded"] == 1


def test_all_stale_returns_no_price_data() -> None:
    result = find_best_gas(
        origin="37.5,-121.9",
        preferences=PREFS,
        place_provider=FakePlaces(
            [make_station("S", "OldTown", regular=3.00, updated_at=NOW - timedelta(hours=73))]
        ),
        route_provider=FakeRoutes(lambda o, d, i: None),
        now=NOW,
    )
    assert result["status"] == "NO_PRICE_DATA"


def test_price_within_72h_is_eligible_by_default() -> None:
    # 30h is over the old 24h cutoff but under the new 72h default → eligible.
    oldish = make_station("O", "Oldish", regular=3.00, updated_at=NOW - timedelta(hours=30))
    result = find_best_gas(
        origin="37.5,-121.9",
        preferences=PREFS,
        place_provider=FakePlaces([oldish]),
        route_provider=_equal_detour_routes(2.0),
        now=NOW,
    )
    assert result["status"] == "OK"
    assert result["recommended"]["station_id"] == "O"
    assert result["metadata"]["stale_excluded"] == 0


def test_custom_max_age_hours_still_enforced() -> None:
    prefs = GasPreferences(
        gallons_default=10,
        time_value_per_hour=15,
        vehicle_mpg=25,
        max_price_age_hours=24,
    )
    oldish = make_station("O", "Oldish", regular=3.00, updated_at=NOW - timedelta(hours=30))
    result = find_best_gas(
        origin="37.5,-121.9",
        preferences=prefs,
        place_provider=FakePlaces([oldish]),
        route_provider=FakeRoutes(lambda o, d, i: None),
        now=NOW,
    )
    assert result["status"] == "NO_PRICE_DATA"


class _FakeContext:
    def __init__(self, value):
        self._value = value

    def weekly_average(self):
        return self._value


def test_find_best_gas_attaches_regional_context() -> None:
    station = make_station("F", "FreshFuel", regular=4.00, updated_at=fresh())
    result = find_best_gas(
        origin="37.5,-121.9",
        preferences=PREFS,
        place_provider=FakePlaces([station]),
        route_provider=_equal_detour_routes(2.0),
        now=NOW,
        regional_context=_FakeContext(
            {"source": "eia", "price_usd_per_gallon": 4.87, "period": "2026-08-11"}
        ),
    )
    assert result["context"]["regional_average"]["price_usd_per_gallon"] == 4.87


def test_find_best_gas_omits_context_when_absent() -> None:
    station = make_station("F", "FreshFuel", regular=4.00, updated_at=fresh())
    result = find_best_gas(
        origin="37.5,-121.9",
        preferences=PREFS,
        place_provider=FakePlaces([station]),
        route_provider=_equal_detour_routes(2.0),
        now=NOW,
    )
    assert "context" not in result


def test_missing_regular_excluded() -> None:
    premium_only = GasStation(
        provider="google",
        provider_id="P",
        name="PremiumOnly",
        address="",
        latitude=37.5,
        longitude=-121.9,
        fuel_prices=[FuelPrice("premium", Decimal("5.00"), "USD", fresh())],
        maps_uri=None,
    )
    result = find_best_gas(
        origin="37.5,-121.9",
        preferences=PREFS,
        place_provider=FakePlaces([premium_only]),
        route_provider=FakeRoutes(lambda o, d, i: None),
        now=NOW,
    )
    assert result["status"] == "NO_PRICE_DATA"


def test_route_failure_degrades_to_straight_line() -> None:
    station = make_station("F", "FreshFuel", lat=37.501, lng=-121.912, regular=4.00, updated_at=fresh())
    result = find_best_gas(
        origin="37.5,-121.9",
        preferences=PREFS,
        place_provider=FakePlaces([station]),
        route_provider=FakeRoutes(lambda o, d, i: None),
        now=NOW,
    )
    assert result["status"] == "DEGRADED"
    assert result["metadata"]["degraded"] is True
    assert result["recommended"]["station_id"] == "F"
    assert result["recommended"]["distance_miles"] > 0


def test_on_the_way_detour_subtracts_baseline() -> None:
    def route_fn(origin, destination, intermediates=None):
        if intermediates:
            return RouteLeg(distance_meters=33796.2, duration_seconds=1920.0)  # 21 mi, 32 min
        return RouteLeg(distance_meters=32186.9, duration_seconds=1800.0)  # 20 mi, 30 min

    station = make_station("F", "FreshFuel", regular=4.00, updated_at=fresh())
    result = find_best_gas(
        origin="37.5,-121.9",
        destination="San Mateo",
        preferences=PREFS,
        place_provider=FakePlaces([station]),
        route_provider=FakeRoutes(route_fn),
        now=NOW,
    )
    assert result["recommended"]["detour_minutes"] == 2.0
    assert result["recommended"]["drive_minutes"] == 32.0
    assert result["recommended"]["detour_miles"] == 1.0


def test_gallons_needed_override() -> None:
    station = make_station("F", "FreshFuel", regular=4.00, updated_at=fresh())
    result = find_best_gas(
        origin="37.5,-121.9",
        gallons_needed=5,
        preferences=PREFS,
        place_provider=FakePlaces([station]),
        route_provider=_equal_detour_routes(2.0),
        now=NOW,
    )
    assert result["recommended"]["estimated_fill_cost"] == 20.0


# ── Routing budget ────────────────────────────────────────────────────────────


def test_pick_route_candidates_keeps_far_cheap_and_near_expensive() -> None:
    def entry(pid: str, lat: float, price: float):
        st = make_station(pid, pid, lat=lat, regular=price, updated_at=fresh())
        return st, st.price_for("regular"), 30

    entries = [
        entry("NEAR_EXPENSIVE", 37.5001, 5.00),
        entry("FAR_CHEAP", 37.55, 2.90),
    ]
    entries += [entry(f"MID{i}", 37.5 + 0.005 * (i + 1), 4.00 + 0.01 * i) for i in range(20)]

    to_route, skipped = _pick_route_candidates(entries, (37.5, -121.9))
    routed = {e[0].provider_id for e in to_route}
    skipped_ids = {e[0].provider_id for e in skipped}

    assert "NEAR_EXPENSIVE" in routed  # nearest is always routed
    assert "FAR_CHEAP" in routed       # cheapest is always routed, even 3+ mi away
    assert "NEAR_EXPENSIVE" not in skipped_ids
    assert len(to_route) <= 13         # 8 cheapest ∪ 5 nearest
    assert len(to_route) + len(skipped) == len(entries)


def test_find_best_gas_routes_bounded_subset_and_surfaces_skipped() -> None:
    stations = [
        make_station(
            f"S{i}",
            f"Station {i}",
            lat=37.5 + i * 0.005,
            regular=3.00 + i * 0.05,
            updated_at=fresh(),
        )
        for i in range(20)
    ]
    calls: list[tuple] = []

    def route_fn(origin, destination, intermediates=None):
        calls.append((origin, destination, intermediates))
        return RouteLeg(distance_meters=1609.34, duration_seconds=120.0)

    result = find_best_gas(
        origin="37.5,-121.9",
        preferences=PREFS,
        place_provider=FakePlaces(stations),
        route_provider=FakeRoutes(route_fn),
        now=NOW,
    )

    assert result["status"] == "OK"
    assert result["metadata"]["candidates_routed"] == 8       # nearest 5 ⊂ cheapest 8
    assert result["metadata"]["routes_skipped_by_budget"] == 12
    assert len(calls) == result["metadata"]["candidates_routed"]  # no extra Routes calls
    assert result["recommended"]["station_id"] == "S0"

    skipped_alts = [
        a for a in result["alternatives"]
        if a.get("reason_not_selected", "").startswith("Not route-scored")
    ]
    assert len(skipped_alts) == 12
    assert all(a["price_age_minutes"] is not None for a in skipped_alts)


# ── Phase-1 primitive ────────────────────────────────────────────────────────


def test_find_nearby_gas_prices_returns_stations() -> None:
    station = make_station("A", "ARCO", regular=4.47, updated_at=fresh())
    result = find_nearby_gas_prices(
        37.5,
        -121.9,
        preferences=PREFS,
        place_provider=FakePlaces([station]),
    )
    assert result["status"] == "OK"
    assert result["stations"][0]["provider_id"] == "A"
    assert result["stations"][0]["fuel_prices"][0]["price"] == 4.47


def test_find_nearby_gas_prices_empty() -> None:
    result = find_nearby_gas_prices(
        37.5, -121.9, preferences=PREFS, place_provider=FakePlaces([])
    )
    assert result["status"] == "NO_PRICE_DATA"