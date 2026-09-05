"""Pure multi-stop route planning primitives.

The planner deliberately does not know about Google Calendar, Apple Calendar,
or Apple Reminders. It receives a travel-time function and returns a
reviewable route snapshot. Calendar supplies commitments; notification and
reminder surfaces deliver alerts.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable


@dataclass(frozen=True)
class RouteStop:
    """An ordered destination in a route."""

    name: str
    location: str
    dwell_minutes: int = 0


TravelTime = Callable[[str, str, str, datetime], dict | None]


def _parse_arrival_time(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        return value
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("arrival_time must include a timezone offset")
    return parsed


def plan_multi_stop_route(
    origin: RouteStop,
    stops: list[RouteStop],
    arrival_time: str | datetime,
    travel_time: TravelTime,
    *,
    mode: str = "driving",
    buffer_minutes: int = 10,
) -> dict:
    """Calculate a route snapshot and the latest safe departure time.

    Stops must be ordered from first stop to final commitment. Dwell time
    applies after a stop and before the next leg. The travel-time callback is
    called once per leg, so callers can use a live Maps provider or a fixture.
    """
    if not origin.location.strip():
        raise ValueError("origin.location is required")
    if not stops:
        raise ValueError("at least one destination stop is required")
    if buffer_minutes < 0:
        raise ValueError("buffer_minutes must be non-negative")
    if any(not stop.location.strip() for stop in stops):
        raise ValueError("every route stop requires a location")
    if any(stop.dwell_minutes < 0 for stop in stops):
        raise ValueError("dwell_minutes must be non-negative")

    target_arrival = _parse_arrival_time(arrival_time)
    points = [origin, *stops]
    legs: list[dict] = []
    total_travel_minutes = 0
    total_dwell_minutes = sum(stop.dwell_minutes for stop in stops[:-1])

    for current, destination in zip(points, points[1:]):
        result = travel_time(current.location, destination.location, mode, target_arrival)
        if not result:
            raise ValueError(f"travel time unavailable for {current.name} -> {destination.name}")
        duration_seconds = int(result.get("duration_seconds", 0))
        if duration_seconds <= 0:
            raise ValueError(f"travel time missing for {current.name} -> {destination.name}")
        travel_minutes = max(1, (duration_seconds + 59) // 60)
        total_travel_minutes += travel_minutes
        legs.append(
            {
                "origin": current.name,
                "origin_location": current.location,
                "destination": destination.name,
                "destination_location": destination.location,
                "travel_minutes": travel_minutes,
                "duration_text": str(result.get("duration_text", "")),
                "distance_text": str(result.get("distance_text", "")),
                "dwell_after_minutes": destination.dwell_minutes
                if destination is not stops[-1]
                else 0,
            }
        )

    total_minutes = total_travel_minutes + total_dwell_minutes + buffer_minutes
    departure_time = target_arrival - timedelta(minutes=total_minutes)
    cursor = departure_time
    for leg in legs:
        leg["depart_at"] = cursor.isoformat()
        cursor += timedelta(minutes=leg["travel_minutes"])
        leg["arrive_at"] = cursor.isoformat()
        cursor += timedelta(minutes=int(leg["dwell_after_minutes"]))

    return {
        "read_only": True,
        "mode": mode,
        "arrival_time": target_arrival.isoformat(),
        "departure_time": departure_time.isoformat(),
        "buffer_minutes": buffer_minutes,
        "total_travel_minutes": total_travel_minutes,
        "total_dwell_minutes": total_dwell_minutes,
        "total_route_minutes": total_minutes,
        "origin": {"name": origin.name, "location": origin.location},
        "stops": [
            {
                "name": stop.name,
                "location": stop.location,
                "dwell_minutes": stop.dwell_minutes,
            }
            for stop in stops
        ],
        "legs": legs,
        "refresh_before_departure": True,
    }
