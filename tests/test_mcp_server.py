"""Tests for mcp_server/server.py — the MCP adapter layer.

The client functions themselves are covered by their own test files; here we
test what the adapter adds: tool registration/schemas, input conversion,
delegation, and the planning guides.
Every network-touching client function is monkeypatched — no test hits the
network.
"""

import asyncio
import json

import pytest

pytest.importorskip(
    "mcp", reason="mcp SDK not installed; run the dev suite described in DEVELOPMENT.md")

from mcp_server import server as srv  # noqa: E402

EXPECTED_TOOLS = {
    "validate_place", "route", "route_legs", "weather_forecast", "weather_climatology",
    "park_info", "reservation_countdown", "chargers_near", "ev_corridor",
    "border_crossing", "customs_exemption", "fuel_cost", "lodging_quote",
    "get_planning_guide",
}


def call(name, args):
    """Invoke a tool through the MCP layer and decode the result payload."""
    res = asyncio.run(srv.mcp.call_tool(name, args))
    content = res[0] if isinstance(res, tuple) else res  # (content, structured) on newer SDKs
    text = content[0].text
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return text


def list_tools():
    return asyncio.run(srv.mcp.list_tools())


class TestRegistry:
    def test_exactly_the_expected_tools(self):
        assert {t.name for t in list_tools()} == EXPECTED_TOOLS

    def test_every_tool_has_a_description(self):
        for t in list_tools():
            assert t.description and len(t.description) > 40, t.name

    @pytest.mark.parametrize("tool,required", [
        ("route", "waypoints"),
        ("route_legs", "waypoints"),
        ("ev_corridor", "legs"),
        ("ev_corridor", "usable_range_miles"),
        ("border_crossing", "crossings"),
        ("reservation_countdown", "arrival_date"),
    ])
    def test_required_params_in_schema(self, tool, required):
        t = next(t for t in list_tools() if t.name == tool)
        assert required in t.inputSchema.get("properties", {})
        assert required in t.inputSchema.get("required", [])

    def test_no_nullable_or_union_schemas(self):
        """Cross-host hardening: some MCP hosts mishandle anyOf/null schemas
        (Optional[...] params), so every input schema must stay plain-typed."""
        for t in list_tools():
            s = json.dumps(t.inputSchema)
            assert '"anyOf"' not in s, t.name
            assert '"null"' not in s, t.name

    def test_lodging_tier_is_schema_enforced(self):
        t = next(t for t in list_tools() if t.name == "lodging_quote")
        tier = t.inputSchema["properties"]["tier"]
        assert set(tier.get("enum", [])) == {"budget", "midrange", "upscale",
                                             "campground", "rv-site", "in-park-lodge"}

    def test_prompt_and_resources_registered(self):
        assert {str(r.uri) for r in asyncio.run(srv.mcp.list_resources())} == \
            {"roadtrip://skill.md", "roadtrip://reference.md"}
        assert [p.name for p in asyncio.run(srv.mcp.list_prompts())] == ["plan_road_trip"]


class TestDelegation:
    """Wrappers convert JSON-shaped input to what the clients expect."""

    def test_route_converts_pairs_to_tuples(self, monkeypatch):
        seen = {}

        def fake_route(pts, timeout=8):
            seen["pts"] = pts
            return {"source": "osrm", "miles": 158.7, "driveTime": "2h39m", "hours": 2.65}

        monkeypatch.setattr(srv.routing_client, "route", fake_route)
        out = call("route", {"waypoints": [[36.1699, -115.1398], [37.2982, -113.0263]]})
        assert out["miles"] == 158.7
        assert seen["pts"] == [(36.1699, -115.1398), (37.2982, -113.0263)]

    def test_route_reports_tomtom_and_never_the_key(self, monkeypatch):
        from tests.fakenet import FakeNetwork
        net = FakeNetwork({"api.tomtom.com": {"routes": [{"summary": {
            "lengthInMeters": 929314, "travelTimeInSeconds": 29046}}]}})
        monkeypatch.setattr(srv.routing_client, "urlopen", net)
        monkeypatch.setenv("TOMTOM_API_KEY", "test-key-0123456789")
        out = call("route", {"waypoints": [[35.0841, -106.65099], [36.16743, -115.14841]]})
        assert out == {"source": "tomtom", "miles": 577.5, "driveTime": "8h04m", "hours": 8.07}
        assert net.hosts() == ["api.tomtom.com"]

    def test_route_legs_passes_options_and_tuples_through(self, monkeypatch):
        seen = {}

        def fake_legs(pts, **options):
            seen.update(pts=pts, **options)
            return {"source": "google", "legs": []}

        monkeypatch.setattr(srv.google_routes, "route_legs", fake_legs)
        out = call("route_legs", {"waypoints": [[35.19, -111.65], [35.25, -112.19]],
                                  "traffic": "live", "max_intermediates": 25})
        assert out["source"] == "google"
        assert seen == {"pts": [(35.19, -111.65), (35.25, -112.19)], "traffic": "live",
                        "depart_at": None, "path_tolerance_m": 10.0, "max_intermediates": 25}

    def test_route_legs_without_a_server_key_says_so(self, monkeypatch):
        monkeypatch.delenv("GOOGLE_ROUTES_API_KEY", raising=False)
        out = call("route_legs", {"waypoints": [[35.19, -111.65], [35.25, -112.19]]})
        assert out == {"source": "error", "reason": "the server has no GOOGLE_ROUTES_API_KEY"}

    def test_route_legs_rejects_malformed_waypoint(self):
        assert call("route_legs", {"waypoints": [[35.19]]})["source"] == "error"

    def test_route_rejects_malformed_waypoint(self):
        out = call("route", {"waypoints": [[36.17]]})
        assert out["source"] == "error"

    def test_validate_place_passes_options_through(self, monkeypatch):
        seen = {}

        def fake_validate(name, na_bias=True, limit=8):
            seen.update(name=name, na_bias=na_bias, limit=limit)
            return {"source": "photon", "verdict": "match", "query": name}

        monkeypatch.setattr(srv.places_client, "validate_place", fake_validate)
        out = call("validate_place", {"name": "Zzyzx, CA", "na_bias": False, "limit": 3})
        assert out["verdict"] == "match"
        assert seen == {"name": "Zzyzx, CA", "na_bias": False, "limit": 3}

    def test_weather_forecast_delegates(self, monkeypatch):
        monkeypatch.setattr(srv.weather_client, "forecast",
                            lambda lat, lng: {"source": "nws", "units": "F", "days": []})
        assert call("weather_forecast", {"lat": 37.3, "lng": -113.0})["source"] == "nws"

    def test_climatology_none_becomes_standard_fallback(self, monkeypatch):
        monkeypatch.setattr(srv.weather_client, "climatology",
                            lambda *a, **k: None)
        out = call("weather_climatology",
                   {"lat": 37.3, "lng": -113.0, "month": 9, "day": 15})
        assert out["source"] == "fallback"
        assert out["searchQueries"] and out["suggestedSources"]

    def test_chargers_near_passes_filters(self, monkeypatch):
        seen = {}

        def fake_chargers(lat, lng, distance_mi=25, min_kw=50, limit=8):
            seen.update(distance_mi=distance_mi, min_kw=min_kw, limit=limit)
            return {"source": "openchargemap", "chargers": []}

        monkeypatch.setattr(srv.charging_client, "chargers_near", fake_chargers)
        call("chargers_near", {"lat": 37.1, "lng": -113.6,
                               "distance_mi": 10, "min_kw": 150, "limit": 2})
        assert seen == {"distance_mi": 10, "min_kw": 150, "limit": 2}


class TestRulesTools:
    """Deterministic clients run for real — no network involved."""

    def test_customs_us_standard_tier(self):
        out = call("customs_exemption", {"residence": "US", "hours_abroad": 72})
        assert (out["amount"], out["currency"], out["tier"]) == (800, "USD", "standard")

    def test_customs_us_reduced_when_used_recently(self):
        out = call("customs_exemption",
                   {"residence": "US", "hours_abroad": 72, "used_within_30_days": True})
        assert (out["amount"], out["tier"]) == (200, "reduced")

    def test_customs_ca_under_24h_has_no_exemption(self):
        out = call("customs_exemption", {"residence": "CA", "hours_abroad": 20})
        assert (out["amount"], out["tier"]) == (0, "none")

    def test_border_crossing_builds_trip_section(self):
        out = call("border_crossing",
                   {"crossings": [{"from": "US", "to": "CA", "rental": True}]})
        c = out["crossings"][0]
        assert (c["from"], c["to"]) == ("US", "CA")
        assert any("rental" in d.lower() for d in c["vehicleDocs"])
        assert out["summary"] == "US→CA"

    def test_ev_corridor_flags_impossible_leg(self):
        out = call("ev_corridor", {
            "legs": [
                {"to": "Stop A", "miles": 35, "charger": True, "chargerKW": 150},
                {"to": "Stop B", "miles": 250, "charger": False, "chargerKW": None},
            ],
            "usable_range_miles": 280,
        })
        assert out["legs"][1]["ok"] is False
        assert out["warnings"]

    def test_reservation_countdown_default_items(self):
        out = call("reservation_countdown", {"arrival_date": "2030-09-12"})
        items = out["bookingCountdown"]
        assert len(items) == 3
        assert all(it["bookBy"] and it["priority"] for it in items)

    def test_reservation_countdown_rejects_bad_date(self):
        out = call("reservation_countdown", {"arrival_date": "2030-9-1"})
        assert out["source"] == "error"
        assert "YYYY-MM-DD" in out["reason"]

    def test_reservation_countdown_rejects_unknown_rule(self):
        out = call("reservation_countdown", {
            "arrival_date": "2030-09-12",
            "items": [{"item": "Ferry", "rule": "ferry", "where": "BC Ferries"}],
        })
        assert out["source"] == "error"
        assert "campground" in out["reason"]

    def test_fuel_cost_gas_and_ev_modes(self):
        gas = call("fuel_cost", {"miles": 1180, "mpg": 26, "region": "southwest"})
        assert gas["type"] == "gas" and gas["cost"] > 0
        assert gas["pricePerGal"] == 4.10  # -1 sentinel → regional prior
        ev = call("fuel_cost", {"miles": 500, "vehicle": "ev", "place": "Kanab, UT"})
        assert ev["type"] == "charge" and "gasbuddySearch" in ev

    def test_fuel_cost_explicit_price_wins_over_prior(self):
        out = call("fuel_cost", {"miles": 100, "mpg": 25, "price_per_gal": 5.0})
        assert out["pricePerGal"] == 5.0 and out["cost"] == 20.0

    def test_lodging_quote_tier_and_dated_link(self):
        out = call("lodging_quote", {"place": "Springdale, UT", "tier": "campground",
                                     "checkin": "2030-09-12", "checkout": "2030-09-14"})
        assert out["pricePerNight"] == 35
        assert "checkin=2030-09-12" in out["links"]["booking"]

    def test_park_info_fallback_contract_without_key(self, monkeypatch):
        monkeypatch.delenv("NPS_API_KEY", raising=False)
        out = call("park_info", {"query": "zion"})
        assert out["source"] == "fallback"
        assert out["searchQueries"] and isinstance(out["suggestedSources"], list)


class TestPlanningGuide:
    def test_workflow_hands_the_plan_to_the_caller(self):
        workflow = call("get_planning_guide", {})
        assert workflow == call("get_planning_guide", {"topic": "workflow"})
        assert "Plan by daylight" in workflow
        assert workflow.rstrip().endswith("Hand the plan to the caller.")

    def test_tools_guide_names_every_data_tool(self):
        guide = call("get_planning_guide", {"topic": "tools"})
        for name in EXPECTED_TOOLS - {"get_planning_guide"}:
            assert f"`{name}`" in guide
        assert "searchQueries" in guide

    def test_guide_topics(self):
        tool = next(t for t in list_tools() if t.name == "get_planning_guide")
        assert set(tool.inputSchema["properties"]["topic"]["enum"]) == {"workflow", "tools"}
