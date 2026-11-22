# Working on RoadTrip Navigator MCP

- Keep `mcp_server/server.py` a thin adapter: convert inputs and delegate; put data
  access and calculations in `tools/`. Clients use the Python 3.8+ standard library,
  not the MCP SDK, and remain importable and runnable as standalone scripts.
- Tool names, schemas, units, source markers, fallback payloads and error responses are
  public contracts. Never substitute an engine for Google in `route_legs`. Read keys
  only from the environment; offline tests must not require them.
- For a client change, test success and degradation at the network boundary. For a
  registration change, check the registry and both transports. Include new client files
  in the wheel's force-include table; see [DEVELOPMENT.md](DEVELOPMENT.md) for verification.
- Keep the packaged [workflow](mcp_server/workflow.md), [tool guide](mcp_server/tool-guide.md)
  and [tool list](mcp_server/README.md) in sync with runtime behavior. The caller owns the trip.
- Create task branches from the fork's main unless another base is specified. Target the
  same base in pull requests and use Conventional Commits.
