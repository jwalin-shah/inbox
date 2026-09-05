"""Provider adapters for the gas feature.

Two adapters over Google's wire APIs:

  • ``GooglePlacesFuelProvider`` — DATA: nearby stations + normalized prices.
  • ``GoogleRoutesProvider`` — ROUTING: distance/duration for one leg.

Both are narrowly constructed around a single API key and fail closed
(return empty / ``None``) when the key is absent, the host is not allowlisted,
or the call fails. These are the only modules that know Google's request and
response shape; everything downstream consumes the normalized models.
"""

from __future__ import annotations

import abc
from datetime import datetime
from typing import Any

from loguru import logger

import egress_audit
from gas_models import (
    GOOGLE_FUEL_TYPE_MAP,
    FuelPrice,
    GasStation,
    RouteLeg,
    money_to_decimal,
    parse_google_timestamp,
)

PLACES_BASE_URL = "https://places.googleapis.com/v1/places:searchNearby"
ROUTES_BASE_URL = "https://routes.googleapis.com/directions/v2:computeRoutes"
_PLACES_FIELD_MASK = (
    "places.id,places.displayName,places.formattedAddress,"
    "places.location,places.fuelOptions,places.googleMapsLinks"
)
_ROUTES_FIELD_MASK = "routes.distanceMeters,routes.duration"
_TIMEOUT_SECONDS = 15.0
_MAX_RESULTS = 20


class RouteProvider(abc.ABC):
    """Routing adapter. Spot dicts are neutral:

    ``{"latitude": float, "longitude": float}`` or ``{"address": str}``.
    """

    @abc.abstractmethod
    def route(
        self,
        origin: dict[str, Any],
        destination: dict[str, Any],
        intermediates: list[dict[str, Any]] | None = None,
    ) -> RouteLeg | None: ...


class FuelPriceProvider(abc.ABC):
    @abc.abstractmethod
    def nearby_stations(
        self,
        latitude: float,
        longitude: float,
        radius_meters: float,
        fuel_type: str,
    ) -> list[GasStation]: ...


class GooglePlacesFuelProvider(FuelPriceProvider):
    """Nearby Search over the Places API (New), normalized to ``GasStation``."""

    def __init__(self, api_key: str | None = None) -> None:
        self._api_key = (api_key or "").strip()

    def nearby_stations(
        self,
        latitude: float,
        longitude: float,
        radius_meters: float,
        fuel_type: str = "regular",
    ) -> list[GasStation]:
        if not self._api_key:
            return []
        body = {
            "includedTypes": ["gas_station"],
            "maxResultCount": _MAX_RESULTS,
            "locationRestriction": {
                "circle": {
                    "center": {"latitude": latitude, "longitude": longitude},
                    "radius": float(radius_meters),
                }
            },
        }
        headers = {
            "Content-Type": "application/json",
            "X-Goog-Api-Key": self._api_key,
            "X-Goog-FieldMask": _PLACES_FIELD_MASK,
        }
        try:
            resp = egress_audit.post(
                PLACES_BASE_URL,
                headers=headers,
                json=body,
                timeout=_TIMEOUT_SECONDS,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception:  # noqa: BLE001 — fail closed; caller degrades gracefully
            logger.exception("GooglePlacesFuelProvider.nearby_stations failed")
            return []

        stations: list[GasStation] = []
        for place in data.get("places", []) if isinstance(data, dict) else []:
            station = _parse_place(place)
            if station is not None:
                stations.append(station)
        return stations


class GoogleRoutesProvider(RouteProvider):
    """Compute Routes over the Routes API, normalized to ``RouteLeg``."""

    def __init__(self, api_key: str | None = None) -> None:
        self._api_key = (api_key or "").strip()

    def route(
        self,
        origin: dict[str, Any],
        destination: dict[str, Any],
        intermediates: list[dict[str, Any]] | None = None,
    ) -> RouteLeg | None:
        if not self._api_key:
            return None
        body: dict[str, Any] = {
            "origin": _to_google_spot(origin),
            "destination": _to_google_spot(destination),
            "travelMode": "DRIVE",
            "routingPreference": "TRAFFIC_AWARE",
        }
        if intermediates:
            body["intermediates"] = [_to_google_spot(i) for i in intermediates]
        headers = {
            "Content-Type": "application/json",
            "X-Goog-Api-Key": self._api_key,
            "X-Goog-FieldMask": _ROUTES_FIELD_MASK,
        }
        try:
            resp = egress_audit.post(
                ROUTES_BASE_URL,
                headers=headers,
                json=body,
                timeout=_TIMEOUT_SECONDS,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception:  # noqa: BLE001 — fail closed; caller degrades gracefully
            logger.exception("GoogleRoutesProvider.route failed")
            return None

        routes = data.get("routes") if isinstance(data, dict) else None
        if not routes or not isinstance(routes[0], dict):
            return None
        first = routes[0]
        meters = first.get("distanceMeters")
        seconds = _parse_duration(first.get("duration"))
        if meters is None or seconds is None:
            return None
        try:
            return RouteLeg(distance_meters=float(meters), duration_seconds=float(seconds))
        except (TypeError, ValueError):
            return None


# ── Composite (freshest-wins across providers) ────────────────────────────────

_MERGE_COORD_DECIMALS = 4  # ≈ 11 m bucket treated as "the same physical pump"


def _merge_key(station: GasStation) -> tuple[float, float]:
    """Co-location bucket: identical rounded coordinates → same station."""
    return (
        round(station.latitude, _MERGE_COORD_DECIMALS),
        round(station.longitude, _MERGE_COORD_DECIMALS),
    )


def _fresher(x: FuelPrice, y: FuelPrice) -> bool:
    """``True`` when ``x`` beats ``y``: most recent ``updated_at`` first, then cheaper."""
    if x.updated_at is None and y.updated_at is None:
        return x.price < y.price
    if x.updated_at is None:
        return False  # a missing timestamp never outranks a stamped one
    if y.updated_at is None:
        return True
    if x.updated_at > y.updated_at:
        return True
    if x.updated_at < y.updated_at:
        return False
    return x.price < y.price


def _freshest_ts(station: GasStation) -> datetime | None:
    stamps = [fp.updated_at for fp in station.fuel_prices if fp.updated_at is not None]
    return max(stamps) if stamps else None


def _merge_stations(a: GasStation, b: GasStation) -> GasStation:
    """Merge two co-located stations, keeping the freshest price per fuel type."""
    prices: dict[str, FuelPrice] = {}
    for fp in a.fuel_prices + b.fuel_prices:
        if fp.fuel_type not in prices or _fresher(fp, prices[fp.fuel_type]):
            prices[fp.fuel_type] = fp
    ts_a, ts_b = _freshest_ts(a), _freshest_ts(b)
    winner = b if ts_b is not None and (ts_a is None or ts_b > ts_a) else a
    return GasStation(
        provider=winner.provider,
        provider_id=winner.provider_id,
        name=winner.name,
        address=winner.address,
        latitude=winner.latitude,
        longitude=winner.longitude,
        fuel_prices=list(prices.values()),
        maps_uri=winner.maps_uri,
    )


class CompositeFuelPriceProvider(FuelPriceProvider):
    """Fan out to N providers and merge co-located stations, freshest-wins.

    Deterministic: provider order (the caller's list) is the stable priority.
    A price with the most recent ``updated_at`` wins per fuel type; ties break
    toward the cheaper price. Stations reported by a single provider, or at
    distinct coordinates, pass through unchanged.
    """

    def __init__(self, providers: list[FuelPriceProvider]) -> None:
        self._providers = list(providers)

    def nearby_stations(
        self,
        latitude: float,
        longitude: float,
        radius_meters: float,
        fuel_type: str = "regular",
    ) -> list[GasStation]:
        merged: dict[tuple[float, float], GasStation] = {}
        for provider in self._providers:
            for station in provider.nearby_stations(latitude, longitude, radius_meters, fuel_type):
                key = _merge_key(station)
                if key in merged:
                    merged[key] = _merge_stations(merged[key], station)
                else:
                    merged[key] = station
        return list(merged.values())


def location_spec(latitude: float, longitude: float) -> dict[str, Any]:
    """Google wire spot for a coordinate."""
    return {"location": {"latLng": {"latitude": latitude, "longitude": longitude}}}


def address_spec(text: str) -> dict[str, Any]:
    """Google wire spot for a free-form address."""
    return {"address": text}


def _to_google_spot(spot: dict[str, Any]) -> dict[str, Any]:
    """Convert a neutral spot dict (``{"latitude","longitude"}`` | ``{"address"}``)
    into Google's wire format. Unknown shapes pass through unchanged.
    """
    if "latitude" in spot and "longitude" in spot:
        return location_spec(spot["latitude"], spot["longitude"])
    if "address" in spot:
        return address_spec(str(spot["address"]))
    return spot


def _parse_duration(value: Any) -> float | None:
    """Routes duration is a string like ``"1234s"``; accept a bare number too."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if text.endswith("s") and text[:-1].lstrip("-").isdigit():
        return float(text[:-1])
    return None


def _parse_place(place: Any) -> GasStation | None:
    if not isinstance(place, dict):
        return None
    location = place.get("location") or {}
    latitude = location.get("latitude")
    longitude = location.get("longitude")
    if latitude is None or longitude is None:
        return None
    try:
        latitude = float(latitude)
        longitude = float(longitude)
    except (TypeError, ValueError):
        return None

    display = place.get("displayName") or {}
    name = display.get("text", "") or ""
    address = place.get("formattedAddress", "") or ""
    provider_id = place.get("id") or f"{latitude},{longitude}"

    # Places v1 reports ``fuelOptions`` as an OBJECT: ``{"fuelPrices": [...]}``.
    # The bare-list form is kept only as a defensive fallback.
    fuel_prices: list[FuelPrice] = []
    fuel_options = place.get("fuelOptions")
    if isinstance(fuel_options, dict):
        options = fuel_options.get("fuelPrices") or []
    elif isinstance(fuel_options, list):
        options = fuel_options
    else:
        options = []
    for option in options:
        fp = _parse_fuel_price(option)
        if fp is not None:
            fuel_prices.append(fp)

    links = place.get("googleMapsLinks") or {}
    maps_uri = links.get("directionsUri") or links.get("placeUri") or None

    return GasStation(
        provider="google",
        provider_id=str(provider_id),
        name=name,
        address=address,
        latitude=latitude,
        longitude=longitude,
        fuel_prices=fuel_prices,
        maps_uri=maps_uri,
    )


def _parse_fuel_price(option: Any) -> FuelPrice | None:
    if not isinstance(option, dict):
        return None
    fuel_type = GOOGLE_FUEL_TYPE_MAP.get(option.get("type", ""))
    if fuel_type is None:
        return None
    money = option.get("price") or {}
    price = money_to_decimal(money) if isinstance(money, dict) else None
    if price is None or price <= 0:
        return None
    return FuelPrice(
        fuel_type=fuel_type,
        price=price,
        currency=(money.get("currencyCode") if isinstance(money, dict) else "") or "USD",
        updated_at=parse_google_timestamp(option.get("updateTime")),
    )