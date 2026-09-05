"""Deterministic gas station ranking (the DECISION layer).

External services only supply facts — stations, prices, route distance/time.
This module reasons over those facts and picks a single recommendation. No
LLM participates in the choice, so the same inputs always produce the same
output (stable sort, no network jitter in the ranking itself).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from gas_context import RegionalFuelPriceContext
from gas_models import (
    FUEL_TYPES,
    FuelPrice,
    GasPreferences,
    GasStation,
    RouteLeg,
    load_gas_preferences,
)
from gas_providers import (
    FuelPriceProvider,
    GooglePlacesFuelProvider,
    GoogleRoutesProvider,
    RouteProvider,
)

# Acceptable-age is configurable on ``GasPreferences`` (``max_price_age_hours``,
# default 72h) — it is no longer a module constant so it can be tuned per user.
_FALLBACK_MPH = 30.0

# Per-call routing budget: ``find_best_gas`` routes only the union of the K
# cheapest and M nearest eligible stations (the only ones that can plausibly win
# the effective-cost ranking) and surfaces the rest without a detour score. This
# bounds the Google Routes call count independently of the Places result count.
_ROUTE_BUDGET_CHEAPEST = 8
_ROUTE_BUDGET_NEAREST = 5

_Result = dict[str, Any]


@dataclass
class _Candidate:
    station: GasStation
    fuel_price: FuelPrice
    age_minutes: int | None
    distance_miles: float
    drive_minutes: float
    detour_miles: float
    detour_minutes: float
    fill_cost: Decimal
    detour_fuel_cost: Decimal
    time_penalty: Decimal
    effective_cost: Decimal


# ── Location resolution ──────────────────────────────────────────────────────


def _parse_latlng(value: str | None) -> tuple[float, float] | None:
    if not value:
        return None
    parts = [p.strip() for p in str(value).split(",")]
    if len(parts) != 2:
        return None
    try:
        return round(float(parts[0]), 6), round(float(parts[1]), 6)
    except ValueError:
        return None


def _resolve_origin_latlng(origin: str | None, prefs: GasPreferences) -> tuple[float, float] | None:
    """Origin must resolve to coordinates (the only thing Places search accepts).

    Supported: explicit ``"lat,lng"``, ``"home"``, ``"work"`` (from config). A
    bare address cannot be searched without geocoding, which is out of scope
    for V1 — that returns ``None`` so the caller surfaces NEEDS_ORIGIN.
    """
    if not origin:
        return None
    value = str(origin).strip()
    direct = _parse_latlng(value)
    if direct:
        return direct
    key = value.lower()
    if key in {"home", "work"}:
        configured = prefs.home if key == "home" else prefs.work
        return _parse_latlng(configured)
    return None


def _route_spot(value: str | None, prefs: GasPreferences) -> dict[str, Any] | None:
    """Build a neutral routing spot for a destination (address or coordinate).

    Returns ``None`` only when no destination is supplied, which the caller
    interprets as the "near me" mode.
    """
    if not value:
        return None
    text = str(value).strip()
    latlng = _parse_latlng(text)
    if latlng:
        return {"latitude": latlng[0], "longitude": latlng[1]}
    key = text.lower()
    if key in {"home", "work"}:
        configured = prefs.home if key == "home" else prefs.work
        if configured:
            return _route_spot(configured, prefs)
        return {"address": text}
    return {"address": text}


def _station_spot(station: GasStation) -> dict[str, Any]:
    return {"latitude": station.latitude, "longitude": station.longitude}


def _haversine_miles(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Straight-line distance fallback when routing is unavailable."""
    r = 3958.7613  # Earth mean radius, miles
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


# ── Freshness ────────────────────────────────────────────────────────────────


def _age_minutes(updated_at: datetime | None, now: datetime) -> int | None:
    if updated_at is None or updated_at.tzinfo is None:
        return None
    return max(0, int((now - updated_at).total_seconds() // 60))


def _is_stale(age_minutes: int | None, max_age_minutes: float) -> bool:
    return age_minutes is not None and age_minutes > max_age_minutes


# ── Scoring (pure) ───────────────────────────────────────────────────────────


def _score_candidate(
    station: GasStation,
    price: FuelPrice,
    *,
    distance_miles: float,
    drive_minutes: float,
    detour_miles: float,
    detour_minutes: float,
    age_minutes: int | None,
    gallons: float,
    prefs: GasPreferences,
) -> _Candidate:
    fill_cost = price.price * Decimal(str(gallons))
    mpg = Decimal(str(prefs.vehicle_mpg)) if prefs.vehicle_mpg > 0 else Decimal(1)
    detour_fuel_cost = (Decimal(str(detour_miles)) / mpg) * price.price
    time_penalty = Decimal(str(detour_minutes)) * prefs.value_per_minute
    return _Candidate(
        station=station,
        fuel_price=price,
        age_minutes=age_minutes,
        distance_miles=round(distance_miles, 2),
        drive_minutes=round(drive_minutes, 2),
        detour_miles=round(detour_miles, 2),
        detour_minutes=round(detour_minutes, 2),
        fill_cost=fill_cost,
        detour_fuel_cost=detour_fuel_cost,
        time_penalty=time_penalty,
        effective_cost=fill_cost + detour_fuel_cost + time_penalty,
    )


def _preferred(candidate: _Candidate, prefs: GasPreferences) -> bool:
    name = candidate.station.name.lower()
    return any(brand and brand.lower() in name for brand in prefs.preferred_brands)


def _rank_key(candidate: _Candidate, prefs: GasPreferences):
    # (effective cost, preferred-brand tie-break, cheaper fuel, stable id)
    return (
        candidate.effective_cost,
        0 if _preferred(candidate, prefs) else 1,
        candidate.fuel_price.price,
        candidate.station.provider_id or candidate.station.name,
    )


def select_best(
    candidates: list[_Candidate],
    prefs: GasPreferences,
    max_detour_minutes: float | None,
) -> tuple[_Candidate | None, list[_Candidate], list[_Candidate], list[_Candidate]]:
    """Split into within-limit vs over-limit, then rank.

    Returns ``(recommended, within_rest, over_limit, ordered_all)`` where
    recommended is ``None`` when no candidate respects the detour limit.
    """
    limit = prefs.max_detour_minutes if max_detour_minutes is None else max_detour_minutes
    ordered = sorted(candidates, key=lambda c: _rank_key(c, prefs))
    if limit is None:
        return ordered[0], ordered[1:], [], ordered
    within = [c for c in ordered if c.detour_minutes <= limit]
    over = [c for c in ordered if c.detour_minutes > limit]
    if not within:
        return None, [], over, ordered
    return within[0], within[1:], over, ordered


# ── Routing budget ────────────────────────────────────────────────────────────


def _pick_route_candidates(
    eligible: list[tuple[GasStation, FuelPrice, int | None]],
    origin_latlng: tuple[float, float],
) -> tuple[list[tuple[GasStation, FuelPrice, int | None]], list[tuple[GasStation, FuelPrice, int | None]]]:
    """Bound the stations we actually route (the Google-cost multiplier).

    Only a cheap or nearby station can win the effective-cost ranking, so we
    route the union of the ``_ROUTE_BUDGET_CHEAPEST`` cheapest and
    ``_ROUTE_BUDGET_NEAREST`` nearest (straight-line miles) and return the rest
    as ``skipped``. Deterministic: the routed list is sorted by straight-line
    distance, with price then provider id as tie-breaks.
    """
    if len(eligible) <= _ROUTE_BUDGET_CHEAPEST + _ROUTE_BUDGET_NEAREST:
        return eligible, []

    def distance(e: tuple[GasStation, FuelPrice, int | None]) -> float:
        station = e[0]
        return _haversine_miles(
            origin_latlng[0], origin_latlng[1], station.latitude, station.longitude
        )

    def id_of(e: tuple[GasStation, FuelPrice, int | None]) -> str:
        return e[0].provider_id or e[0].name

    nearest = sorted(eligible, key=lambda e: (distance(e), e[1].price, id_of(e)))[
        : _ROUTE_BUDGET_NEAREST
    ]
    cheapest = sorted(eligible, key=lambda e: (e[1].price, distance(e), id_of(e)))[
        : _ROUTE_BUDGET_CHEAPEST
    ]

    picked: dict[str, tuple[GasStation, FuelPrice, int | None]] = {}
    for e in nearest + cheapest:
        picked[id_of(e)] = e
    to_route = sorted(picked.values(), key=lambda e: (distance(e), e[1].price, id_of(e)))
    routed_ids = {id_of(e) for e in to_route}
    skipped = [e for e in eligible if id_of(e) not in routed_ids]
    return to_route, skipped


# ── Serialization ────────────────────────────────────────────────────────────


def _money(value: Decimal, digits: int = 2) -> float:
    return round(float(value), digits)


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt is not None else None


def _reason_not_selected(recommended: _Candidate, candidate: _Candidate, limit: float | None) -> str:
    if limit is not None and candidate.detour_minutes > limit:
        return f"Exceeds detour limit of {limit:.1f} minutes."
    fuel_diff = candidate.fill_cost - recommended.fill_cost
    detour_diff = candidate.detour_minutes - recommended.detour_minutes
    if fuel_diff < 0:
        return (
            f"Saves ${_money(-fuel_diff):.2f} in fuel but adds "
            f"{detour_diff:.1f} minutes of detour."
        )
    return f"${_money(fuel_diff):.2f} more in fuel than the recommended station."


def _serialize_candidate(
    candidate: _Candidate,
    fuel_type: str,
    recommended: _Candidate | None,
    limit: float | None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "station_id": candidate.station.provider_id,
        "name": candidate.station.name,
        "address": candidate.station.address,
        "fuel_type": fuel_type,
        "price": _money(candidate.fuel_price.price, 3),
        "price_updated_at": _iso(candidate.fuel_price.updated_at),
        "price_age_minutes": candidate.age_minutes,
        "distance_miles": candidate.distance_miles,
        "drive_minutes": candidate.drive_minutes,
        "detour_minutes": candidate.detour_minutes,
        "detour_miles": candidate.detour_miles,
        "estimated_fill_cost": _money(candidate.fill_cost),
        "effective_cost": _money(candidate.effective_cost),
        "maps_uri": candidate.station.maps_uri,
    }
    if recommended is not None and candidate is not recommended:
        result["reason_not_selected"] = _reason_not_selected(recommended, candidate, limit)
    return result


def _serialize_station(station: GasStation) -> dict[str, Any]:
    return {
        "provider": station.provider,
        "provider_id": station.provider_id,
        "name": station.name,
        "address": station.address,
        "latitude": station.latitude,
        "longitude": station.longitude,
        "fuel_prices": [
            {
                "fuel_type": fp.fuel_type,
                "price": _money(fp.price, 3),
                "currency": fp.currency,
                "updated_at": _iso(fp.updated_at),
            }
            for fp in station.fuel_prices
        ],
        "maps_uri": station.maps_uri,
    }


def _serialize_skipped(
    entry: tuple[GasStation, FuelPrice, int | None],
    fuel_type: str,
) -> dict[str, Any]:
    station, price, age = entry
    return {
        "station_id": station.provider_id,
        "name": station.name,
        "address": station.address,
        "fuel_type": fuel_type,
        "price": _money(price.price, 3),
        "price_age_minutes": age,
        "maps_uri": station.maps_uri,
        "reason_not_selected": "Not route-scored: outside the per-call routing budget.",
    }


def _base_metadata(degraded: bool = False) -> dict[str, Any]:
    return {
        "price_provider": "google_places",
        "route_provider": "google_routes",
        "degraded": degraded,
    }


def _error_result(status: str, reason: str, extra: dict[str, Any] | None = None) -> _Result:
    result: _Result = {
        "status": status,
        "recommended": None,
        "alternatives": [],
        "decision": {"reason": reason},
        "metadata": _base_metadata(),
    }
    if extra:
        result["metadata"].update(extra)
    return result


# ── Orchestration ────────────────────────────────────────────────────────────


def _compute_travel(
    route_provider: RouteProvider,
    origin: dict[str, Any],
    destination: dict[str, Any] | None,
    station: GasStation,
    baseline: RouteLeg | None,
    origin_latlng: tuple[float, float],
) -> tuple[tuple[float, float, float, float] | None, bool]:
    """Return ((distance_miles, drive_minutes, detour_miles, detour_minutes) | None, fallback).

    Near-me mode detours by the whole origin→station leg; on-the-way mode
    routes origin→station→destination and subtracts the baseline. ``fallback``
    is True when routing failed and straight-line distance was used instead.
    """
    station_spot = _station_spot(station)
    if destination is None:
        leg = route_provider.route(origin, station_spot)
        if leg is None:
            # Degraded fallback: straight-line distance + naive drive time.
            distance = _haversine_miles(*origin_latlng, station.latitude, station.longitude)
            minutes = distance / _FALLBACK_MPH * 60.0
            return (distance, minutes, distance, minutes), True
        return (
            leg.distance_miles,
            leg.duration_minutes,
            leg.distance_miles,
            leg.duration_minutes,
        ), False

    via = route_provider.route(origin, destination, intermediates=[station_spot])
    if via is None:
        return None, True
    base_dur = baseline.duration_seconds if baseline else 0.0
    base_dist = baseline.distance_meters if baseline else 0.0
    detour_seconds = max(0.0, via.duration_seconds - base_dur)
    detour_miles = max(0.0, via.distance_meters - base_dist) / 1609.344
    return (via.distance_miles, via.duration_minutes, detour_miles, detour_seconds / 60.0), False


def find_best_gas(
    origin: str | None = None,
    destination: str | None = None,
    fuel_type: str = "regular",
    gallons_needed: float | None = None,
    max_detour_minutes: float | None = None,
    *,
    api_key: str | None = None,
    preferences: GasPreferences | None = None,
    place_provider: FuelPriceProvider | None = None,
    route_provider: RouteProvider | None = None,
    now: datetime | None = None,
    regional_context: RegionalFuelPriceContext | None = None,
) -> _Result:
    prefs = preferences or load_gas_preferences()
    ft = fuel_type or prefs.fuel_type
    if ft not in FUEL_TYPES:
        ft = prefs.fuel_type
    now = now or datetime.now(UTC)

    origin_latlng = _resolve_origin_latlng(origin, prefs)
    if origin_latlng is None:
        return _error_result(
            "NEEDS_ORIGIN",
            "Origin required as 'lat,lng', 'home', or 'work' (a bare address "
            "cannot be searched without geocoding).",
        )
    origin_spot = {"latitude": origin_latlng[0], "longitude": origin_latlng[1]}
    destination_spot = _route_spot(destination, prefs)

    pp = place_provider or GooglePlacesFuelProvider(api_key)
    stations = pp.nearby_stations(origin_latlng[0], origin_latlng[1], prefs.search_radius_meters, ft)

    total = len(stations)
    if total == 0:
        return _error_result(
            "NO_PRICE_DATA",
            "No gas stations found nearby.",
            {"candidates_found": 0, "candidates_with_prices": 0, "candidates_routed": 0},
        )

    eligible: list[tuple[GasStation, FuelPrice, int | None]] = []
    stale: list[tuple[GasStation, FuelPrice, int | None]] = []
    missing_price = 0
    for station in stations:
        price = station.price_for(ft)
        if price is None or price.price <= 0:
            missing_price += 1
            continue
        age = _age_minutes(price.updated_at, now)
        if _is_stale(age, prefs.max_price_age_minutes):
            stale.append((station, price, age))
        else:
            eligible.append((station, price, age))

    if not eligible and not stale:
        return _error_result(
            "NO_PRICE_DATA",
            f"No '{ft}' fuel prices available for nearby stations.",
            {
                "candidates_found": total,
                "candidates_with_prices": 0,
                "candidates_routed": 0,
                "missing_price": missing_price,
            },
        )
    if not eligible:
        return _error_result(
            "NO_PRICE_DATA",
            f"Only stale (> {prefs.max_price_age_hours:g}h) '{ft}' prices available.",
            {
                "candidates_found": total,
                "candidates_with_prices": len(stale),
                "candidates_routed": 0,
                "stale_excluded": len(stale),
                "missing_price": missing_price,
            },
        )

    to_route, skipped = _pick_route_candidates(eligible, origin_latlng)

    rp = route_provider or GoogleRoutesProvider(api_key)
    baseline = rp.route(origin_spot, destination_spot) if destination_spot is not None else None

    gallons = float(gallons_needed) if (gallons_needed and gallons_needed > 0) else prefs.gallons_default
    degraded = False
    candidates: list[_Candidate] = []
    for station, price, age in to_route:
        travel, used_fallback = _compute_travel(
            rp, origin_spot, destination_spot, station, baseline, origin_latlng
        )
        if travel is None:
            degraded = True
            continue
        if used_fallback:
            degraded = True
        distance_miles, drive_minutes, detour_miles, detour_minutes = travel
        candidates.append(
            _score_candidate(
                station,
                price,
                distance_miles=distance_miles,
                drive_minutes=drive_minutes,
                detour_miles=detour_miles,
                detour_minutes=detour_minutes,
                age_minutes=age,
                gallons=gallons,
                prefs=prefs,
            )
        )

    if not candidates:
        return _error_result(
            "DEGRADED" if degraded else "NO_PRICE_DATA",
            "Routing unavailable for nearby stations; could not rank a recommendation.",
            {
                "candidates_found": total,
                "candidates_with_prices": len(eligible) + len(stale),
                "candidates_routed": 0,
                "missing_price": missing_price,
                "routes_skipped_by_budget": len(skipped),
            },
        )

    regional = regional_context.weekly_average() if regional_context is not None else None

    recommended, within_rest, over, ordered = select_best(
        candidates, prefs, max_detour_minutes
    )
    limit = prefs.max_detour_minutes if max_detour_minutes is None else max_detour_minutes

    if recommended is None:
        alternatives = [_serialize_candidate(c, ft, None, limit) for c in ordered] + [
            _serialize_skipped(e, ft) for e in skipped
        ]
        result: _Result = {
            "status": "DEGRADED",
            "recommended": None,
            "alternatives": alternatives,
            "decision": {"reason": f"No station within {limit:.1f}-minute detour limit."},
            "metadata": {
                **_base_metadata(degraded=True),
                "candidates_found": total,
                "candidates_with_prices": len(eligible) + len(stale),
                "candidates_routed": len(candidates),
                "stale_excluded": len(stale),
                "missing_price": missing_price,
                "routes_skipped_by_budget": len(skipped),
            },
        }
        if regional is not None:
            result["context"] = {"regional_average": regional}
        return result

    alternatives = (
        [_serialize_candidate(c, ft, recommended, limit) for c in within_rest]
        + [_serialize_candidate(c, ft, recommended, limit) for c in over]
        + [
            {
                "station_id": s.provider_id,
                "name": s.name,
                "address": s.address,
                "fuel_type": ft,
                "price": _money(p.price, 3),
                "price_age_minutes": a,
                "maps_uri": s.maps_uri,
                "reason_not_selected": f"Price is over {prefs.max_price_age_hours:g}h old.",
            }
            for s, p, a in stale
        ]
        + [_serialize_skipped(e, ft) for e in skipped]
    )

    result: _Result = {
        "status": "DEGRADED" if degraded else "OK",
        "recommended": _serialize_candidate(recommended, ft, None, limit),
        "alternatives": alternatives,
        "decision": {
            "reason": (
                f"{recommended.station.name} selected: lowest effective cost "
                f"(${_money(recommended.effective_cost):.2f}) across fuel, "
                f"detour fuel, and detour time."
            )
        },
        "metadata": {
            **_base_metadata(degraded=degraded),
            "candidates_found": total,
            "candidates_with_prices": len(eligible) + len(stale),
            "candidates_routed": len(candidates),
            "stale_excluded": len(stale),
            "missing_price": missing_price,
            "routes_skipped_by_budget": len(skipped),
        },
    }
    if regional is not None:
        result["context"] = {"regional_average": regional}
    return result


def find_nearby_gas_prices(
    latitude: float,
    longitude: float,
    fuel_type: str = "regular",
    radius_meters: float | None = None,
    *,
    api_key: str | None = None,
    preferences: GasPreferences | None = None,
    place_provider: FuelPriceProvider | None = None,
) -> _Result:
    """Phase-1 primitive: nearby stations and their normalized prices."""
    prefs = preferences or load_gas_preferences()
    ft = fuel_type or prefs.fuel_type
    radius = float(radius_meters) if (radius_meters and radius_meters > 0) else prefs.search_radius_meters
    pp = place_provider or GooglePlacesFuelProvider(api_key)
    stations = pp.nearby_stations(latitude, longitude, radius, ft)

    if not stations:
        return _error_result(
            "NO_PRICE_DATA",
            "No gas stations found nearby.",
            {"candidates_found": 0},
        )

    return {
        "status": "OK",
        "origin": {"latitude": latitude, "longitude": longitude},
        "radius_meters": radius,
        "stations": [_serialize_station(s) for s in stations],
        "metadata": {
            **_base_metadata(),
            "candidates_found": len(stations),
        },
    }