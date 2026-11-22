# RoadTrip Navigator — MCP server

The [RoadTrip Navigator skill](../SKILL.md)'s deterministic capabilities,
served over the [Model Context Protocol](https://modelcontextprotocol.io) so
**any** MCP host — Claude Code, OpenAI Codex CLI, Google Gemini CLI, Cursor,
VS Code, … — can call them as typed tools. No shell access, Python setup, or
repo checkout required on the agent's side.

15 tools in three groups:

| Group | Tools |
|---|---|
| Live data & rules | `validate_place` · `route` · `route_legs` · `weather_forecast` · `weather_climatology` · `park_info` · `reservation_countdown` · `chargers_near` · `ev_corridor` · `border_crossing` · `customs_exemption` · `fuel_cost` · `lodging_quote` |
| Renderer | `render_trip` — tripData JSON → the skill's single-file HTML itinerary page |
| Knowledge | `get_planning_guide` — the skill's workflow / tripData schema / tool-usage guide, tool-shaped so it reaches hosts without skill support (also registered as the `plan_road_trip` MCP prompt and the `roadtrip://skill.md` / `roadtrip://reference.md` resources for hosts that support those primitives) |

Every data tool follows the skill's **fallback contract**: when a live source
is unreachable it returns `{"source": "fallback", "searchQueries": [...]}`
instead of failing — run those queries with your agent's own web search.

## Install

One command per host (needs [uv](https://docs.astral.sh/uv/) — or substitute
`pipx run`):

```bash
# Claude Code
claude mcp add roadtrip -- uvx --from git+https://github.com/Waybox-AI/roadtrip-skill roadtrip-mcp

# OpenAI Codex CLI
codex mcp add roadtrip -- uvx --from git+https://github.com/Waybox-AI/roadtrip-skill roadtrip-mcp

# Google Gemini CLI
gemini mcp add roadtrip uvx --from git+https://github.com/Waybox-AI/roadtrip-skill roadtrip-mcp
```

> **Codex note:** interactive `codex` sessions ask you to approve each MCP tool
> call. Non-interactive `codex exec` runs cannot ask and auto-reject MCP calls
> (reported as "user cancelled") — pass
> `--dangerously-bypass-approvals-and-sandbox` for unattended runs.

From a local checkout (contributors), point the same hosts at:

```bash
python3 -m mcp_server.server   # run from the repo root
```

### Serve over HTTP (hosted, behind a gateway)

With no arguments the server speaks stdio, as above. To host it, start it over
[Streamable HTTP](https://modelcontextprotocol.io/specification/2025-06-18/basic/transports#streamable-http):

```bash
roadtrip-mcp --http --host 0.0.0.0 --port 8000 --allowed-host roadtrip-mcp
```

| | |
|---|---|
| Endpoint | `POST /mcp`. Stateless: no session is issued, so any replica can answer any request. |
| Probe | `GET /health` returns `200` and `{"status": "ok"}`. It answers whatever the `Host` header, so an orchestrator can probe by address. |
| `--host`, `--port` | Address and port to bind. Defaults `127.0.0.1` and `8000`. |
| `--allowed-host NAME` | A `Host` header value `/mcp` answers besides loopback: the name the gateway calls the server by. Repeatable. `NAME` matches with any port or none; `NAME:PORT` matches that port only. Any other `Host` gets `421`. |
| Authentication | None. Put it behind a gateway and let the network make that gateway the only caller. |
| Keys | The same environment variables as below. |

`render_trip` does not work over HTTP: a page written on the server would
never reach the caller. It returns an error that says to render where the skill
is installed, with `python3 assets/generate.py tripData.json -o trip.html`.

### Optional API keys (server-side env)

Everything but `route_legs` works without keys; these tools get better with them:

| Env var | Tool | Without it |
|---|---|---|
| `TOMTOM_API_KEY` ([free tier](https://developer.tomtom.com/)) | `route` | OSRM public server: right miles, drive times about 19–34% long |
| `GOOGLE_ROUTES_API_KEY` ([Routes API](https://developers.google.com/maps/documentation/routes), billed per request with a free monthly allowance) | `route_legs` | the tool returns an error: no other engine gives Google's choice of road |
| `NPS_API_KEY` ([free](https://www.nps.gov/subjects/developer/)) | `park_info` | web-search fallback |
| `OCM_API_KEY` ([free](https://openchargemap.org/site/developerinfo)) | `chargers_near` | demo quota, may throttle |

## Pairs with the skill

The MCP server carries the **execution layer** (typed tools, renderer). The
skill markdown carries the **planning discipline**. Best experience installs
both:

```bash
npx skills add Waybox-AI/roadtrip-skill   # workflow knowledge → your agent
<host> mcp add roadtrip ...               # tools → your agent (see above)
```

Hosts without skill support still get the discipline on demand via
`get_planning_guide(topic="workflow")`.

## Development

```bash
pip install -e ".[dev]"       # installs the mcp SDK + pytest
python3 -m pytest tests/test_mcp_server.py
```

`mcp_server/server.py` is a thin adapter over [`tools/`](../tools) and
[`assets/generate.py`](../assets/generate.py) — planning logic and HTTP calls
live in the clients (each with its own tests and CLI), never here. When you
add a client, wrap it here, mirror its schema in a test, and mention it in
`_TOOLS_GUIDE`.
