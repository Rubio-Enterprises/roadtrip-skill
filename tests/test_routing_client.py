import json
from urllib.error import HTTPError

import pytest
from tests.fakenet import FakeNetwork
from tools import routing_client
from tools.routing_client import haversine_miles, route

# Great-circle (straight-line) distances between well-known city pairs.
# Expected values are the true haversine distances (not driving distances).
# Tolerance is ±5% as specified.
CITY_PAIRS = [
    # (point_a, point_b, expected_miles, label)
    (
        (36.1699, -115.1398),  # Las Vegas, NV
        (37.2982, -113.0263),  # Zion NP entrance, UT
        141,
        "Las Vegas to Zion NP",
    ),
    (
        (34.0522, -118.2437),  # Los Angeles, CA
        (37.7749, -122.4194),  # San Francisco, CA
        348,
        "LA to San Francisco",
    ),
    (
        (47.6062, -122.3321),  # Seattle, WA
        (45.5051, -122.6750),  # Portland, OR
        146,
        "Seattle to Portland",
    ),
    (
        (40.7128, -74.0060),   # New York City, NY
        (42.3601, -71.0589),   # Boston, MA
        190,
        "NYC to Boston",
    ),
]


class TestHaversineMiles:
    @pytest.mark.parametrize("a,b,expected,label", CITY_PAIRS)
    def test_known_city_pair(self, a, b, expected, label):
        result = haversine_miles(a, b)
        assert abs(result - expected) / expected <= 0.05, (
            f"{label}: got {result:.1f} mi, expected ~{expected} mi (±5%)"
        )

    def test_same_point_is_zero(self):
        assert haversine_miles((36.0, -115.0), (36.0, -115.0)) == pytest.approx(0.0)

    def test_symmetric(self):
        a = (36.1699, -115.1398)
        b = (37.2982, -113.0263)
        assert haversine_miles(a, b) == pytest.approx(haversine_miles(b, a))

    def test_result_is_positive(self):
        a = (34.0522, -118.2437)
        b = (37.7749, -122.4194)
        assert haversine_miles(a, b) > 0


ABQ = (35.0841, -106.65099)       # Albuquerque, NM
VEGAS = (36.16743, -115.14841)    # Las Vegas, NV

# Albuquerque -> Las Vegas as each engine really answered it in November 2026.
TOMTOM_ANSWER = {"formatVersion": "0.0.12", "routes": [{"summary": {
    "lengthInMeters": 929314, "travelTimeInSeconds": 29046,
    "trafficDelayInSeconds": 0, "trafficLengthInMeters": 0}}]}
OSRM_ANSWER = {"code": "Ok", "routes": [{"distance": 919759.8, "duration": 36255}]}

KEY = "test-key-0123456789"


def http_error(code, msg):
    return HTTPError("https://example.invalid/", code, msg, None, None)


@pytest.fixture
def network(monkeypatch):
    """Both engines up. A test overrides an entry to take one down."""
    net = FakeNetwork({"api.tomtom.com": TOMTOM_ANSWER,
                       "router.project-osrm.org": OSRM_ANSWER})
    monkeypatch.setattr(routing_client, "urlopen", net)
    monkeypatch.delenv("TOMTOM_API_KEY", raising=False)
    return net


class TestRouteWithTomTomKey:
    def test_tomtom_answers_and_is_named_as_the_source(self, network, monkeypatch):
        monkeypatch.setenv("TOMTOM_API_KEY", KEY)
        assert route([ABQ, VEGAS]) == {
            "source": "tomtom", "miles": 577.5, "driveTime": "8h04m", "hours": 8.07}
        assert network.hosts() == ["api.tomtom.com"]

    def test_tomtom_gets_lat_lng_joined_by_colons(self, network, monkeypatch):
        monkeypatch.setenv("TOMTOM_API_KEY", KEY)
        route([ABQ, (35.1983, -111.6513), VEGAS])
        assert ("/calculateRoute/35.084100,-106.650990:35.198300,-111.651300"
                ":36.167430,-115.148410/json?") in network.urls[0]

    def test_tomtom_is_asked_for_typical_not_live_traffic(self, network, monkeypatch):
        monkeypatch.setenv("TOMTOM_API_KEY", KEY)
        route([ABQ, VEGAS])
        assert "traffic=false" in network.urls[0]

    def test_tomtom_down_falls_back_to_osrm_and_says_why(self, network, monkeypatch):
        monkeypatch.setenv("TOMTOM_API_KEY", KEY)
        network.answers["api.tomtom.com"] = http_error(403, "Forbidden")
        out = route([ABQ, VEGAS])
        assert out["source"] == "osrm"
        assert out["driveTime"] == "10h04m"
        assert "TomTom unavailable: HTTP Error 403: Forbidden" in out["note"]
        assert network.hosts() == ["api.tomtom.com", "router.project-osrm.org"]

    def test_tomtom_answer_without_a_route_falls_back_to_osrm(self, network, monkeypatch):
        monkeypatch.setenv("TOMTOM_API_KEY", KEY)
        network.answers["api.tomtom.com"] = {"formatVersion": "0.0.12", "routes": []}
        assert route([ABQ, VEGAS])["source"] == "osrm"

    def test_both_engines_down_gives_the_offline_estimate(self, network, monkeypatch):
        monkeypatch.setenv("TOMTOM_API_KEY", KEY)
        network.answers["api.tomtom.com"] = http_error(429, "Too Many Requests")
        network.answers["router.project-osrm.org"] = OSError("network unreachable")
        out = route([ABQ, VEGAS])
        assert out["source"] == "fallback"
        assert out["miles"] == pytest.approx(haversine_miles(ABQ, VEGAS) * 1.25, abs=0.1)
        assert "TomTom unavailable" in out["reason"]
        assert "OSRM unavailable" in out["reason"]

    @pytest.mark.parametrize("osrm", [OSRM_ANSWER, OSError("network unreachable")])
    def test_key_never_appears_in_the_result(self, network, monkeypatch, osrm):
        # http.client.InvalidURL and friends quote the request URL, key included.
        key = "s3cret key+with/odd chars"
        monkeypatch.setenv("TOMTOM_API_KEY", key)
        network.answers["api.tomtom.com"] = lambda url: ValueError("bad URL: " + url)
        network.answers["router.project-osrm.org"] = osrm
        text = json.dumps(route([ABQ, VEGAS]))
        assert "TomTom unavailable: bad URL" in text
        assert key not in text
        assert "s3cret" not in text


class TestRouteWithoutKey:
    def test_osrm_answers_exactly_as_before(self, network):
        assert route([ABQ, VEGAS]) == {
            "source": "osrm", "miles": 571.5, "driveTime": "10h04m", "hours": 10.07}
        assert network.hosts() == ["router.project-osrm.org"]

    def test_osrm_gets_lng_lat_joined_by_semicolons(self, network):
        route([ABQ, VEGAS])
        assert network.urls[0].endswith(
            "/driving/-106.650990,35.084100;-115.148410,36.167430?overview=false")

    def test_empty_key_counts_as_no_key(self, network, monkeypatch):
        monkeypatch.setenv("TOMTOM_API_KEY", "")
        assert route([ABQ, VEGAS])["source"] == "osrm"
        assert network.hosts() == ["router.project-osrm.org"]

    def test_osrm_down_gives_the_offline_estimate(self, network):
        network.answers["router.project-osrm.org"] = OSError("network unreachable")
        out = route([ABQ, VEGAS])
        assert out["source"] == "fallback"
        assert out["reason"] == "OSRM unavailable: network unreachable"

    def test_fewer_than_two_waypoints_asks_nobody(self, network):
        assert route([ABQ])["source"] == "error"
        assert network.urls == []
