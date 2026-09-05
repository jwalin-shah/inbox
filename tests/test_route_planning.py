from __future__ import annotations

from datetime import datetime

import pytest

from route_planning import RouteStop, plan_multi_stop_route


def test_multi_stop_route_returns_one_departure_and_timed_legs() -> None:
    calls: list[tuple[str, str, str]] = []

    def travel_time(origin: str, destination: str, mode: str, arrival: datetime) -> dict:
        calls.append((origin, destination, mode))
        minutes = {("home", "harsh address"): 20, ("harsh address", "practice address"): 15}[
            (origin, destination)
        ]
        return {
            "duration_seconds": minutes * 60,
            "duration_text": f"{minutes} mins",
            "distance_text": "5 mi",
        }

    result = plan_multi_stop_route(
        RouteStop("Home", "home"),
        [
            RouteStop("Harsh", "harsh address", dwell_minutes=5),
            RouteStop("Practice", "practice address"),
        ],
        "2026-08-27T17:40:00-07:00",
        travel_time,
        buffer_minutes=10,
    )

    assert calls == [
        ("home", "harsh address", "driving"),
        ("harsh address", "practice address", "driving"),
    ]
    assert result["departure_time"] == "2026-08-27T16:50:00-07:00"
    assert result["total_travel_minutes"] == 35
    assert result["total_dwell_minutes"] == 5
    assert result["legs"][0]["depart_at"] == "2026-08-27T16:50:00-07:00"
    assert result["legs"][0]["arrive_at"] == "2026-08-27T17:10:00-07:00"
    assert result["legs"][1]["depart_at"] == "2026-08-27T17:15:00-07:00"
    assert result["legs"][1]["arrive_at"] == "2026-08-27T17:30:00-07:00"
    assert result["refresh_before_departure"] is True


@pytest.mark.parametrize(
    "origin,stops,error",
    [
        (RouteStop("Home", ""), [RouteStop("Practice", "practice")], "origin.location"),
        (RouteStop("Home", "home"), [], "at least one destination"),
        (RouteStop("Home", "home"), [RouteStop("Practice", "")], "every route stop"),
    ],
)
def test_multi_stop_route_rejects_incomplete_route(
    origin: RouteStop, stops: list[RouteStop], error: str
) -> None:
    with pytest.raises(ValueError, match=error):
        plan_multi_stop_route(
            origin,
            stops,
            "2026-08-27T17:40:00-07:00",
            lambda *_: {"duration_seconds": 60},
        )
