"""The "Open this day in Google Maps" link on each day card."""

import json
import re
import shutil
import subprocess
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = (ROOT / "assets" / "template.html").read_text(encoding="utf-8")


def stop(lat, lng):
    return {"name": "stop", "lat": lat, "lng": lng}


def link_for(day):
    """Run the template's own gmapsDayUrl in Node and return what it built."""
    source = re.search(r"  function gmapsDayUrl\(d\) \{\n.*?\n  \}\n", TEMPLATE, re.S).group(0)
    script = source + "process.stdout.write(JSON.stringify(gmapsDayUrl(%s)));" % json.dumps(day)
    out = subprocess.run(["node", "-e", script], capture_output=True, check=True,
                         encoding="utf-8")
    return json.loads(out.stdout)


def params(url):
    return parse_qs(urlsplit(url).query)


def test_day_card_carries_the_link():
    card = TEMPLATE[TEMPLATE.index("function dayCard(d, idx) {"):
                    TEMPLATE.index("function stopRow(s) {")]
    assert "var gUrl = gmapsDayUrl(d);" in card
    assert "Open this day in Google Maps" in card
    assert 'href="\' + esc(gUrl)' in card


@pytest.mark.skipif(shutil.which("node") is None, reason="needs Node.js to run the template's JS")
class TestGmapsDayUrl:
    DAY = {"from": "Carlsbad, NM", "to": "Socorro, NM",
           "stops": [stop(32.1479, -104.5567), stop(33.3943, -104.523),
                     stop(33.8039, -106.8911)]}

    def test_is_a_google_maps_driving_directions_link(self):
        url = link_for(self.DAY)
        assert url.startswith("https://www.google.com/maps/dir/?api=1&")
        assert params(url)["travelmode"] == ["driving"]

    def test_origin_and_destination_are_the_days_from_and_to(self):
        asked = params(link_for(self.DAY))
        assert asked["origin"] == ["Carlsbad, NM"]
        assert asked["destination"] == ["Socorro, NM"]

    def test_waypoints_are_the_stop_coordinates_in_order_joined_by_pipes(self):
        url = link_for(self.DAY)
        assert params(url)["waypoints"] == [
            "32.1479,-104.5567|33.3943,-104.523|33.8039,-106.8911"]
        assert "%7C" in url          # the pipe itself must be encoded

    def test_place_names_are_url_encoded(self):
        url = link_for({"from": "Coeur d'Alene & Co, ID", "to": "Banff #1, AB", "stops": []})
        assert "&origin=Coeur%20d'Alene%20%26%20Co%2C%20ID&" in url
        assert params(url)["destination"] == ["Banff #1, AB"]

    def test_at_most_nine_waypoints(self):
        day = dict(self.DAY, stops=[stop(30 + i, -100 - i) for i in range(12)])
        waypoints = params(link_for(day))["waypoints"][0].split("|")
        assert waypoints == ["%d,%d" % (30 + i, -100 - i) for i in range(9)]

    def test_stops_without_coordinates_are_left_out(self):
        day = dict(self.DAY, stops=[{"name": "no pin"}, stop(None, None), stop(0, 0),
                                    stop(33.3943, -104.523)])
        assert params(link_for(day))["waypoints"] == ["33.3943,-104.523"]

    def test_no_waypoints_parameter_when_no_stop_has_coordinates(self):
        url = link_for({"from": "Carlsbad, NM", "to": "Socorro, NM"})
        assert "waypoints" not in url

    @pytest.mark.parametrize("day", [
        {"to": "Socorro, NM", "stops": [stop(33.3943, -104.523)]},
        {"from": "Carlsbad, NM", "stops": [stop(33.3943, -104.523)]},
    ])
    def test_no_link_without_both_from_and_to(self, day):
        assert link_for(day) == ""
