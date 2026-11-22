# RoadTrip Navigator MCP server

Read-only road-trip data and planning guidance over stdio or stateless Streamable HTTP.

This fork dropped the itinerary page because trips are kept in TREK.
The page is available in [Waybox AI's original project](https://github.com/Waybox-AI/roadtrip-skill).

## Install and run

From the repository root, install and configure your MCP host to launch `roadtrip-mcp`:

    uv tool install .
    roadtrip-mcp

For a gateway, use `roadtrip-mcp --http`. The endpoint is `/mcp` and the liveness
probe is `GET /health`. There is no built-in authentication; see the
[installation guide](https://github.com/Rubio-Enterprises/roadtrip-skill/blob/main/INSTALL.md)
for network configuration and server-side keys.

## Tools

| Question | Tools |
| --- | --- |
| Is this place real? How far is the drive? Which road does Google take? | `validate_place`, `route`, `route_legs` |
| What's forecast, or typical for the season? | `weather_forecast`, `weather_climatology` |
| What does entry cost and when should we book? | `park_info`, `reservation_countdown` |
| Where can we charge, and will we make the next stop? | `chargers_near`, `ev_corridor` |
| What do we need at the border and on return? | `border_crossing`, `customs_exemption` |
| What should we budget? | `fuel_cost`, `lodging_quote` |
| How should we plan or verify the trip? | `get_planning_guide` (topics: `workflow`, `tools`) |

Read `source` before using a figure. For `fallback`, follow the supplied search
queries and sources. Without a Google key, `route_legs` reports an error instead
of substituting a different engine.

The `plan_road_trip` prompt accepts an optional `request`. The same workflow and
tool guide are available as resources at `roadtrip://skill.md` and `roadtrip://reference.md`.
