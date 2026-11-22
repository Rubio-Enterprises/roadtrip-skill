"""Google's Routes API, leg by leg. The network is the one fake: answers are
what Google returned for two short legs in November 2026."""

import json
from urllib.error import HTTPError

import pytest

from tests.fakenet import FakeNetwork
from tools import google_routes
from tools.google_routes import decode_polyline, route_legs, simplify

KEY = "test-key-0123456789"

# Santa Fe, two blocks: 260 m in 79 s.
SANTA_FE = [(35.68619, -105.93866), (35.68510, -105.93989)]
SANTA_FE_LEG = {"distanceMeters": 260, "duration": "79s", "staticDuration": "79s",
                "polyline": {"encodedPolyline": "u}xxEtcreS@CTw@zBf@`@Hv@PARKtBG`B"}}
# Albuquerque, down 4th Street: 467 m in 85 s.
FOURTH_ST_LEG = {"distanceMeters": 467, "duration": "85s", "staticDuration": "85s",
                 "polyline": {"encodedPolyline": "iceuEfa}iSTB`Ed@h@F|BVXDt@HxBTNBxANjBTBc@"}}


def answer_for(request_legs):
    return {"routes": [{"legs": request_legs}]}


@pytest.fixture
def google(monkeypatch):
    """Google up and keyed. Each request is answered with one recorded leg per
    leg it asks for."""
    net = FakeNetwork({})
    net.sent = []

    def answer(url):
        body = json.loads(net.requests[-1].data.decode())
        net.sent.append(body)
        return answer_for([SANTA_FE_LEG] * (len(body["intermediates"]) + 1))

    net.answers["routes.googleapis.com"] = answer
    monkeypatch.setattr(google_routes, "urlopen", net)
    monkeypatch.setenv("GOOGLE_ROUTES_API_KEY", KEY)
    return net


class TestPolyline:
    def test_decodes_googles_own_documented_example(self):
        assert decode_polyline("_p~iF~ps|U_ulLnnqC_mqNvxq`@") == [
            [38.5, -120.2], [40.7, -120.95], [43.252, -126.453]]

    def test_recorded_leg_starts_and_ends_at_its_stops(self):
        path = decode_polyline(SANTA_FE_LEG["polyline"]["encodedPolyline"])
        assert path[0] == pytest.approx(SANTA_FE[0], abs=2e-4)
        assert path[-1] == pytest.approx(SANTA_FE[1], abs=2e-4)

    def test_simplify_drops_points_on_a_straight_run_and_keeps_a_corner(self):
        straight = [[35.0, -106.0], [35.0, -105.9995], [35.0, -105.999]]
        assert simplify(straight, 10) == [straight[0], straight[-1]]
        corner = [[35.0, -106.0], [35.0, -105.999], [35.001, -105.999]]
        assert simplify(corner, 10) == corner

    def test_simplify_at_zero_keeps_every_point(self):
        path = decode_polyline(FOURTH_ST_LEG["polyline"]["encodedPolyline"])
        assert simplify(path, 0) == path
        assert len(simplify(path, 10)) < len(path)


class TestRouteLegs:
    def test_one_leg_per_pair_of_stops_with_metres_seconds_and_path(self, google):
        google.answers["routes.googleapis.com"] = answer_for([SANTA_FE_LEG, FOURTH_ST_LEG])
        out = route_legs([SANTA_FE[0], SANTA_FE[1], (35.08915, -106.65055)])
        assert out["source"] == "google"
        assert [(leg["meters"], leg["seconds"]) for leg in out["legs"]] == [(260, 79), (467, 85)]
        assert (out["meters"], out["seconds"]) == (727, 164)
        assert out["legs"][0]["path"][0] == pytest.approx(SANTA_FE[0], abs=2e-4)

    def test_asks_for_stops_in_order_with_the_key_in_a_header(self, google):
        route_legs([SANTA_FE[0], (35.5, -106.0), SANTA_FE[1]])
        body, request = google.sent[0], google.requests[0]
        assert body["origin"]["location"]["latLng"] == {
            "latitude": SANTA_FE[0][0], "longitude": SANTA_FE[0][1]}
        assert [w["location"]["latLng"]["latitude"] for w in body["intermediates"]] == [35.5]
        assert body["travelMode"] == "DRIVE"
        assert request.get_header("X-goog-api-key") == KEY
        assert KEY not in request.full_url
        assert "routes.legs.polyline.encodedPolyline" in request.get_header("X-goog-fieldmask")

    def test_checks_roads_without_live_traffic_by_default(self, google):
        out = route_legs(SANTA_FE)
        assert google.sent[0]["routingPreference"] == "TRAFFIC_UNAWARE"
        assert "departureTime" not in google.sent[0]
        assert (out["traffic"], out["tier"]) == ("none", "essentials")

    def test_live_traffic_is_the_apps_mode_and_the_pro_tier(self, google):
        out = route_legs(SANTA_FE, traffic="live", depart_at="2026-11-26T15:00:00Z")
        assert google.sent[0]["routingPreference"] == "TRAFFIC_AWARE_OPTIMAL"
        assert google.sent[0]["departureTime"] == "2026-11-26T15:00:00Z"
        assert out["tier"] == "pro"

    def test_long_list_is_split_into_requests_that_share_an_end(self, google):
        stops = [(35.0 + i / 100.0, -106.0) for i in range(26)]  # 25 legs
        out = route_legs(stops)
        assert out["requests"] == 3 and len(out["legs"]) == 25
        assert [len(b["intermediates"]) for b in google.sent] == [10, 10, 2]
        assert google.sent[1]["origin"] == google.sent[0]["destination"]
        assert out["tier"] == "essentials"

    def test_more_than_ten_stops_between_the_ends_is_the_pro_tier(self, google):
        stops = [(35.0 + i / 100.0, -106.0) for i in range(27)]  # 26 legs
        out = route_legs(stops, max_intermediates=25)
        assert out["requests"] == 1 and out["tier"] == "pro"
        assert len(google.sent[0]["intermediates"]) == 25

    def test_never_asks_for_more_than_googles_limit(self, google):
        stops = [(35.0 + i / 100.0, -106.0) for i in range(60)]
        route_legs(stops, max_intermediates=99)
        assert max(len(b["intermediates"]) for b in google.sent) == 25

    def test_path_tolerance_thins_the_path(self, google):
        google.answers["routes.googleapis.com"] = answer_for([FOURTH_ST_LEG])
        full = route_legs(SANTA_FE, path_tolerance_m=0)["legs"][0]["path"]
        thin = route_legs(SANTA_FE, path_tolerance_m=10)["legs"][0]["path"]
        assert full[0] == thin[0] and full[-1] == thin[-1]
        assert len(thin) < len(full)


class TestRouteLegsRefusals:
    def test_no_key_is_an_error_and_google_is_not_asked(self, google, monkeypatch):
        monkeypatch.delenv("GOOGLE_ROUTES_API_KEY")
        out = route_legs(SANTA_FE)
        assert out == {"source": "error", "reason": "the server has no GOOGLE_ROUTES_API_KEY"}
        assert google.urls == []

    @pytest.mark.parametrize("kwargs,reason", [
        ({"traffic": "heavy"}, "traffic must be 'none' or 'live'"),
        ({"depart_at": "2026-11-26T15:00:00Z"}, "depart_at needs traffic='live'"),
    ])
    def test_bad_options_are_refused_before_asking(self, google, kwargs, reason):
        assert route_legs(SANTA_FE, **kwargs) == {"source": "error", "reason": reason}
        assert google.urls == []

    def test_fewer_than_two_stops_is_an_error(self, google):
        assert route_legs([SANTA_FE[0]])["source"] == "error"

    def test_google_refusal_is_reported_with_its_message(self, google):
        import io
        detail = {"error": {"code": 403, "message": "Routes API has not been used in project 1",
                            "status": "PERMISSION_DENIED"}}
        google.answers["routes.googleapis.com"] = HTTPError(
            "https://routes.googleapis.com/", 403, "Forbidden", None,
            io.BytesIO(json.dumps(detail).encode()))
        out = route_legs(SANTA_FE)
        assert out["source"] == "error" and out["requests"] == 0
        assert "HTTP Error 403: Forbidden" in out["reason"]
        assert "Routes API has not been used in project 1" in out["reason"]

    def test_no_route_is_an_error(self, google):
        google.answers["routes.googleapis.com"] = {}
        assert "Google returned no route" in route_legs(SANTA_FE)["reason"]

    def test_key_never_appears_in_a_failure(self, google, monkeypatch):
        key = "s3cret-key-with-odd/chars"
        monkeypatch.setenv("GOOGLE_ROUTES_API_KEY", key)
        google.answers["routes.googleapis.com"] = lambda url: ValueError("refused key " + key)
        text = json.dumps(route_legs(SANTA_FE))
        assert "refused key ***" in text and key not in text

    def test_a_failure_part_way_reports_the_requests_already_made(self, google):
        calls = []

        def second_fails(url):
            calls.append(url)
            if len(calls) == 2:
                return OSError("network unreachable")
            return answer_for([SANTA_FE_LEG] * 11)

        google.answers["routes.googleapis.com"] = second_fails
        out = route_legs([(35.0 + i / 100.0, -106.0) for i in range(26)])
        assert out["source"] == "error" and out["requests"] == 1
