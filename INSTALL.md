# Install and connect

Use uv with Python 3.10 or newer. From this checkout, `uv tool install .` installs
`roadtrip-mcp`. Configure a stdio MCP client to launch it with no arguments.
To run directly from a pinned revision instead, supply the reviewed fork commit:

    uvx --from "git+https://github.com/Rubio-Enterprises/roadtrip-skill@$COMMIT" roadtrip-mcp

## Gateway deployment

    roadtrip-mcp --http --host 0.0.0.0 --port 8000 --allowed-host roadtrip-mcp

Without overrides the HTTP bind address is 127.0.0.1:8000. Restrict inbound access to
an authenticating gateway; the server does not authenticate clients. Pass the name the
gateway forwards as `Host` to `--allowed-host` (repeatable). Connect to `/mcp` using
Streamable HTTP. The endpoint is stateless; unlisted non-loopback hosts receive 421.
`GET /health` accepts any Host and returns 200 with `{"status":"ok"}`.

## Server-side environment

| Variable | Effect when absent |
| --- | --- |
| `TOMTOM_API_KEY` | `route` uses OSRM, or estimates if routing is unavailable. |
| `GOOGLE_ROUTES_API_KEY` | `route_legs` returns an error; there is no substitute engine. Google bills per request. |
| `NPS_API_KEY` | `park_info` returns search queries for official park information. |
| `OCM_API_KEY` | Charger lookup attempts Open Charge Map without a personal key; availability is limited. |

Check the connection by listing tools and calling `fuel_cost` with miles 100, MPG 25
and price per US gallon 5. The estimated cost should be 20; no network or key is needed.
