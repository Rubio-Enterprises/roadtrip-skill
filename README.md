# RoadTrip Navigator MCP

Data tools and planning guidance for North American road trips, served over MCP.

This fork dropped the generated roadbook because we keep trips in TREK.
For the page and its agent skill, see [Waybox AI's upstream project](https://github.com/Waybox-AI/roadtrip-skill).

## Install

From this checkout, install the server with [uv](https://docs.astral.sh/uv/):

    uv tool install .

## Usage

Configure your MCP host to launch the following command over stdio:

    roadtrip-mcp

Start with `get_planning_guide` for a multi-day plan, or call a data tool directly.
For example, `route` measures a drive; `route_legs` checks which road Google takes.
See the [tool list](mcp_server/README.md) and [gateway setup](INSTALL.md).

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Thanks to Waybox AI and the
[upstream contributors](https://github.com/Waybox-AI/roadtrip-skill/graphs/contributors),
including ziminpan and cazermess.

## License

[MIT](LICENSE) © yang-hong.
