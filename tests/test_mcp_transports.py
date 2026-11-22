"""The server's two transports, each exercised against a real server process:
stdio (the default) and Streamable HTTP (--http). Nothing is faked here: the
HTTP tests go over a real TCP socket, the stdio test over real pipes.
"""

import asyncio
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import pytest

pytest.importorskip(
    "mcp", reason="mcp SDK not installed — pip install -e '.[dev]' to run these")

from mcp import ClientSession, StdioServerParameters  # noqa: E402
from mcp.client.stdio import stdio_client  # noqa: E402
try:
    from mcp.client.streamable_http import streamable_http_client  # noqa: E402
except ImportError:  # mcp 1.23 has only the older name
    from mcp.client.streamable_http import (  # noqa: E402
        streamablehttp_client as streamable_http_client)

from tools import customs_client  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SERVER = [sys.executable, "-m", "mcp_server.server"]
TRIP = {"title": "Test trip", "disclaimer": "Check before you go.",
        "days": [{"date": "09/12", "title": "Day 1",
                  "stops": [{"name": "Zion", "lat": 37.2982, "lng": -113.0263}]}]}


def server_env():
    """The server imports the checkout, whatever directory it is started in."""
    env = {k: v for k, v in os.environ.items()
           if k not in ("TOMTOM_API_KEY", "NPS_API_KEY", "OCM_API_KEY")}
    env["PYTHONPATH"] = str(ROOT)
    return env


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def http(url, host=None, body=None):
    """One raw HTTP request. Returns (status, headers, text)."""
    headers = {"Accept": "application/json, text/event-stream"}
    if host:
        headers["Host"] = host
    data = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode()
    try:
        with urlopen(Request(url, data=data, headers=headers), timeout=10) as r:
            return r.status, r.headers, r.read().decode()
    except HTTPError as e:
        return e.code, e.headers, e.read().decode()


def rpc(method, params, id=1):
    return {"jsonrpc": "2.0", "id": id, "method": method, "params": params}


INITIALIZE = rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                "clientInfo": {"name": "test", "version": "0"}})


def rpc_result(text):
    """The JSON-RPC message in a response body, sent as JSON or as one SSE event."""
    for line in text.splitlines():
        if line.startswith("data:"):
            return json.loads(line[5:])
    return json.loads(text)


def tool_payload(result):
    return json.loads(result.content[0].text)


class HttpServer:
    def __init__(self, base, cwd):
        self.base, self.cwd = base, cwd
        self.mcp = base + "/mcp"

    def session(self, calls):
        """Open an MCP client session over HTTP and run `calls(session)`."""
        async def run():
            async with streamable_http_client(self.mcp) as (read, write, _):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    return await calls(session)
        return asyncio.run(run())


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    cwd = tmp_path_factory.mktemp("http-server-cwd")
    port = free_port()
    proc = subprocess.Popen(
        SERVER + ["--http", "--port", str(port),
                  "--allowed-host", "gateway.test",
                  "--allowed-host", "ported.test:9443"],
        cwd=cwd, env=server_env(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = "http://127.0.0.1:%d" % port
    try:
        deadline = time.time() + 30
        while True:
            try:
                if http(base + "/health")[0] == 200:
                    break
            except URLError:
                pass
            assert proc.poll() is None, "server exited with %s" % proc.returncode
            assert time.time() < deadline, "server did not answer /health within 30s"
            time.sleep(0.1)
        yield HttpServer(base, cwd)
    finally:
        proc.terminate()
        proc.wait(timeout=10)


class TestStreamableHttp:
    def test_tool_call_round_trip(self, server):
        async def calls(session):
            tools = await session.list_tools()
            result = await session.call_tool(
                "customs_exemption", {"residence": "US", "hours_abroad": 72})
            return [t.name for t in tools.tools], tool_payload(result)

        names, exemption = server.session(calls)
        assert len(names) == 15 and "route" in names
        assert exemption == json.loads(json.dumps(
            customs_client.personal_exemption("US", 72, False)))

    def test_serves_at_slash_mcp(self, server):
        status, _, text = http(server.mcp, body=INITIALIZE)
        assert status == 200
        assert rpc_result(text)["result"]["serverInfo"]["name"] == "roadtrip-navigator"

    def test_is_stateless(self, server):
        """No session is issued, and a call needs no initialize before it."""
        _, headers, _ = http(server.mcp, body=INITIALIZE)
        assert headers.get("mcp-session-id") is None
        status, _, text = http(server.mcp, body=rpc("tools/call", {
            "name": "customs_exemption",
            "arguments": {"residence": "CA", "hours_abroad": 12}}))
        assert status == 200
        payload = json.loads(rpc_result(text)["result"]["content"][0]["text"])
        assert payload == json.loads(json.dumps(
            customs_client.personal_exemption("CA", 12, False)))

    @pytest.mark.parametrize("host", [
        "gateway.test",          # behind a proxy on 80/443: no port in the header
        "gateway.test:8000",     # called directly by name and port
        "ported.test:9443",      # a name allowed with one port only
        "localhost:8000",
    ])
    def test_answers_an_allowed_host(self, server, host):
        assert http(server.mcp, host=host, body=INITIALIZE)[0] == 200

    @pytest.mark.parametrize("host", ["other.test", "ported.test:1", "gateway.test.evil.test"])
    def test_refuses_any_other_host(self, server, host):
        assert http(server.mcp, host=host, body=INITIALIZE)[0] == 421

    def test_render_trip_refuses_and_writes_nothing(self, server):
        async def calls(session):
            return tool_payload(await session.call_tool(
                "render_trip", {"trip_data": TRIP, "output_path": "trip.html"}))

        out = server.session(calls)
        assert out["source"] == "error"
        assert "python3 assets/generate.py tripData.json -o trip.html" in out["reason"]
        assert list(server.cwd.iterdir()) == []


class TestHealth:
    def test_answers_ok(self, server):
        status, _, text = http(server.base + "/health")
        assert (status, json.loads(text)) == (200, {"status": "ok"})

    def test_answers_whatever_the_host_header(self, server):
        """An orchestrator probes by address, not by a name on the allow-list."""
        assert http(server.base + "/health", host="10.42.0.17:8000")[0] == 200


class TestStdioIsStillTheDefault:
    def test_no_arguments_serves_stdio_and_renders_locally(self, tmp_path):
        async def run():
            params = StdioServerParameters(command=SERVER[0], args=SERVER[1:],
                                           env=server_env(), cwd=str(tmp_path))
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    return tool_payload(await session.call_tool(
                        "render_trip", {"trip_data": TRIP, "output_path": "trip.html"}))

        out = asyncio.run(run())
        assert out["days"] == 1
        assert Path(out["path"]) == (tmp_path / "trip.html").resolve()
        assert "Test trip" in (tmp_path / "trip.html").read_text(encoding="utf-8")

    @pytest.mark.parametrize("flags", [["--port", "9000"], ["--host", "0.0.0.0"],
                                       ["--allowed-host", "gateway.test"]])
    def test_http_flags_without_http_are_refused(self, flags):
        proc = subprocess.run(SERVER + flags, env=server_env(), capture_output=True,
                              encoding="utf-8", timeout=30, stdin=subprocess.DEVNULL)
        assert proc.returncode == 2
        assert "need --http" in proc.stderr
