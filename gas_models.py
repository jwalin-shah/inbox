"""Pure data models for the gas price + routing feature.

Kept Google-agnostic so the scorer and MCP surface never depend on Google's
wire format. Mirrors ``service_models.py``: dataclasses with at most small
derived helpers, no network or I/O beyond preference loading.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).parent
GAS_CONFIG_FILE = BASE_DIR / "config" / "gas.json"

# Normalized fuel types Inbox reasons over. Anything else flows through
# untouched but is simply not selectable for scoring unless the caller asks
# for that exact normalized type.
FUEL_TYPES = {"regular", "midgrade", "premium", "diesel"}

# Google Places `fuelOptions` reports fuel type as a proto enum name. We
# collapse those names into our normalized vocabulary so the rest of Inbox
# never sees Google's spelling.
GOOGLE_FUEL_TYPE_MAP = {
    "REGULAR_UNLEADED": "regular",
    "MIDGRADE": "midgrade",
    "PREMIUM": "premium",
    "DIESEL": "diesel",
    "TRUCK_DIESEL": "diesel",
    "SP91": "regular",
    "SP91_E10": "regular",
    "SP92": "premium",
    "SP95": "premium",
    "SP95_E10": "premium",
    "SP98": "premium",
    "SP99": "premium",
    "SP100": "premium",
    "E85": "regular",
}


@dataclass(frozen=True)
class FuelPrice:
    """One normalized fuel price at one station."""

    fuel_type: str
    price: Decimal
    currency: str
    updated_at: datetime | None = None


@dataclass(frozen=True)
class GasStation:
    """A normalized gas station, independent of the upstream provider."""

    provider: str
    provider_id: str
    name: str
    address: str
    latitude: float
    longitude: float
    fuel_prices: list[FuelPrice] = field(default_factory=list)
    maps_uri: str | None = None

    def price_for(self, fuel_type: str) -> FuelPrice | None:
        for fp in self.fuel_prices:
            if fp.fuel_type == fuel_type:
                return fp
        return None


@dataclass(frozen=True)
class RouteLeg:
    """Distance + duration for one leg of a route."""

    distance_meters: float
    duration_seconds: float

    @property
    def distance_miles(self) -> float:
        return self.distance_meters / 1609.344

    @property
    def duration_minutes(self) -> float:
        return self.duration_seconds / 60.0


@dataclass(frozen=True)
class GasPreferences:
    """User-tunable gas policy. Defaults are safe; env/config override them."""

    fuel_type: str = "regular"
    search_radius_miles: float = 8.0
    max_detour_minutes: float = 10.0
    gallons_default: float = 10.0
    time_value_per_hour: float = 15.0
    vehicle_mpg: float = 25.0
    home: str = ""
    work: str = ""
    preferred_brands: tuple[str, ...] = ()
    # A price older than this is excluded from the recommendation (still listed
    # as an alternative). Hours, not minutes, so users reason in "days".
    max_price_age_hours: float = 72.0
    # EIA series for the optional regional-average context (empty → default).
    eia_series: str = ""

    @property
    def search_radius_meters(self) -> float:
        return self.search_radius_miles * 1609.344

    @property
    def value_per_minute(self) -> Decimal:
        return Decimal(str(self.time_value_per_hour)) / Decimal(60)

    @property
    def max_price_age_minutes(self) -> float:
        return self.max_price_age_hours * 60.0


def _as_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_str(value: Any, default: str) -> str:
    if value is None:
        return default
    return str(value).strip()


def _as_brands(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        parts = [p.strip() for p in value.split(",") if p.strip()]
    elif isinstance(value, (list, tuple)):
        parts = [str(p).strip() for p in value if str(p).strip()]
    else:
        parts = []
    return tuple(parts)


def _preference(
    data: dict[str, Any],
    env: Mapping[str, str],
    *,
    env_name: str,
    key: str,
    default: Any,
) -> Any:
    """env wins over config file wins over default."""
    if env.get(env_name, "").strip():
        return env[env_name].strip()
    if key in data:
        return data[key]
    return default


def load_gas_preferences(
    *,
    path: Path | None = None,
    env: dict[str, str] | None = None,
) -> GasPreferences:
    """Load gas preferences from env, then ``config/gas.json``, then defaults.

    ``env`` is only injected for tests; production reads ``os.environ``.
    """
    environ = os.environ if env is None else env
    config_data: dict[str, Any] = {}
    cfg_path = path if path is not None else GAS_CONFIG_FILE
    if cfg_path.exists():
        try:
            loaded = json.loads(cfg_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                config_data = loaded
        except (OSError, ValueError):
            config_data = {}

    def get_float(key: str, env_name: str, default: float) -> float:
        return _as_float(_preference(config_data, environ, env_name=env_name, key=key, default=default), default)

    fuel_type = _as_str(
        _preference(config_data, environ, env_name="INBOX_GAS_FUEL_TYPE", key="fuel_type", default="regular"),
        "regular",
    )
    fuel_type = fuel_type if fuel_type in FUEL_TYPES else "regular"

    home = _as_str(_preference(config_data, environ, env_name="INBOX_GAS_HOME", key="home", default=""), "")
    work = _as_str(_preference(config_data, environ, env_name="INBOX_GAS_WORK", key="work", default=""), "")

    return GasPreferences(
        fuel_type=fuel_type,
        search_radius_miles=get_float("search_radius_miles", "INBOX_GAS_SEARCH_RADIUS_MILES", 8.0),
        max_detour_minutes=get_float("max_detour_minutes", "INBOX_GAS_MAX_DETOUR_MINUTES", 10.0),
        gallons_default=get_float("gallons_default", "INBOX_GAS_GALLONS_DEFAULT", 10.0),
        time_value_per_hour=get_float("time_value_per_hour", "INBOX_GAS_TIME_VALUE_PER_HOUR", 15.0),
        vehicle_mpg=get_float("vehicle_mpg", "INBOX_GAS_VEHICLE_MPG", 25.0),
        home=home,
        work=work,
        preferred_brands=_as_brands(
            _preference(config_data, environ, env_name="INBOX_GAS_PREFERRED_BRANDS", key="preferred_brands", default=())
        ),
        max_price_age_hours=get_float("max_price_age_hours", "INBOX_GAS_MAX_PRICE_AGE_HOURS", 72.0),
        eia_series=_as_str(
            _preference(config_data, environ, env_name="INBOX_GAS_EIA_SERIES", key="eia_series", default=""),
            "",
        ),
    )


def money_to_decimal(money: dict[str, Any] | None) -> Decimal | None:
    """Convert a Google ``Money`` object (units + nanos) to a Decimal.

    $4.47 → units=4, nanos=470000000 → Decimal("4.47").
    """
    if not isinstance(money, dict):
        return None
    try:
        units = int(money.get("units") or 0)
        nanos = int(money.get("nanos") or 0)
    except (TypeError, ValueError):
        return None
    try:
        return Decimal(units) + Decimal(nanos) / Decimal(1_000_000_000)
    except InvalidOperation:
        return None


def parse_google_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None