"""Regional fuel-price context (EIA weekly average) for the gas feature.

Distinct from ``gas_providers.py`` (station/route wire adapters): this supplies
a national (or state) *average* so the recommended price can be compared to the
market — "ARCO $5.24 vs the $4.88 U.S. weekly average". Fail-closed: an absent
key or a bad response yields ``None``, never an invented number.

The series is tunable (``eia_series`` config key / ``INBOX_GAS_EIA_SERIES``) so a
state-level series can be substituted. The default is EIA's U.S. regular,
all-formulations, weekly retail gasoline price ($/gal); verify the exact series
against eia.gov the first time a live ``EIA_API_KEY`` is provided.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from loguru import logger

import egress_audit

EIA_BASE_URL = "https://api.eia.gov/v2/seriesid/{series}"
DEFAULT_SERIES = "PET.EMM_EPMR_PTE_NUS_DPG.W"  # U.S. regular, all formulations, weekly, $/gal

# Plausibility gate on a dollars-per-gallon weekly average.
_MIN_USD_PER_GALLON = Decimal("0.5")
_MAX_USD_PER_GALLON = Decimal("20.0")


class RegionalFuelPriceContext:
    """Fail-closed EIA weekly-average provider."""

    def __init__(self, api_key: str | None = None, series: str = DEFAULT_SERIES) -> None:
        self._api_key = (api_key or "").strip()
        self._series = (series or DEFAULT_SERIES).strip() or DEFAULT_SERIES

    def weekly_average(self) -> dict[str, Any] | None:
        """Return the most recent weekly average, or ``None`` (fail-closed)."""
        if not self._api_key:
            return None
        url = EIA_BASE_URL.format(series=self._series)
        try:
            resp = egress_audit.get(
                url,
                params={"api_key": self._api_key, "data[0]": "value"},
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception:  # noqa: BLE001 — fail closed; caller omits context
            logger.exception("RegionalFuelPriceContext.weekly_average failed")
            return None

        parsed = _parse_eia_series(data)
        if parsed is None:
            return None
        price, period = parsed
        return {
            "source": "eia",
            "series": self._series,
            "price_usd_per_gallon": float(price),
            "period": period,
        }


def _parse_eia_series(data: Any) -> tuple[Decimal, str] | None:
    """Extract the newest plausibly-priced point from an EIA v2 series response.

    Returns ``(price, period)`` for the point with the latest ``period`` among
    those inside the sanity band; ``None`` when nothing qualifies.
    """
    if not isinstance(data, dict):
        return None
    response = data.get("response")
    points = response.get("data") if isinstance(response, dict) else None
    if not isinstance(points, list) or not points:
        return None

    best: tuple[str, Decimal] | None = None
    for row in points:
        if not isinstance(row, dict):
            continue
        period = row.get("period")
        raw = row.get("value")
        if not isinstance(period, str):
            continue
        try:
            price = Decimal(str(raw))
        except (InvalidOperation, TypeError, ValueError):
            continue
        if not (_MIN_USD_PER_GALLON <= price <= _MAX_USD_PER_GALLON):
            continue
        if best is None or period > best[0]:
            best = (period, price)
    if best is None:
        return None
    return best[1], best[0]