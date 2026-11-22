# Develop and verify the server

Use uv from the repository root. The package needs Python 3.10+ and the MCP SDK;
pytest is the dev extra. No credentials are needed for these checks.

    uv run --no-project --with-editable ".[dev]" python -m pytest tests/ -q
    uv run --no-project --with-editable . roadtrip-mcp --help
    uv build

Data clients live in `tools/`; Hatch copies them into `mcp_server/_vendor/tools/`
in the wheel. The two guide documents live in the package itself. When changing
packaging, run `uvx --from /absolute/path/to/candidate.whl roadtrip-mcp` from outside
the checkout through a stdio MCP client. Initialize, list tools, read each guide and
call a keyless tool. Checkout-only tests cannot detect missing wheel contents.

`tests/test_mcp_server.py` checks tool schemas and delegation. The transport tests
start real stdio and HTTP subprocesses, including the gateway Host allowlist and
health endpoint. For networked client tests, use fixtures at the HTTP boundary
(see `tests/fakenet.py`).
