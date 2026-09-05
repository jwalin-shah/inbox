from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import lifeops_mcp


def test_multi_stop_route_uses_read_only_inbox_route_endpoint() -> None:
    async def run() -> dict:
        with patch.object(
            lifeops_mcp,
            "_request",
            new=AsyncMock(return_value={"read_only": True, "departure_time": "2026-08-27T16:50:00-07:00"}),
        ) as request:
            result = await lifeops_mcp.multi_stop_route(
                stops=[{"name": "Practice", "location": "Practice address"}],
                arrival_time="2026-08-27T17:40:00-07:00",
                origin="Home",
            )
            request.assert_awaited_once_with(
                "POST",
                "/maps/route",
                body={
                    "origin": "Home",
                    "origin_name": "Origin",
                    "stops": [{"name": "Practice", "location": "Practice address"}],
                    "arrival_time": "2026-08-27T17:40:00-07:00",
                    "mode": "driving",
                    "buffer_minutes": 10,
                },
            )
            return result

    assert asyncio.run(run())["read_only"] is True
