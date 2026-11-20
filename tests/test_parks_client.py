import datetime as dt
from urllib.parse import parse_qs, urlsplit

import pytest
from tests.fakenet import FakeNetwork
from tools import parks_client
from tools.parks_client import book_by, countdown, park_info, RELEASE_RULES


class TestBookBy:
    def test_future_campground_date(self):
        # arrival 2027-01-01, today well before the 180-day release window
        today = dt.date(2026, 1, 1)
        expected = (dt.date(2027, 1, 1) - dt.timedelta(days=180)).isoformat()
        assert book_by("2027-01-01", "campground", today=today) == expected

    def test_past_deadline_clamps_to_today(self):
        # release date already passed → clamp to today, not a date in the past
        today = dt.date(2026, 6, 20)
        result = book_by("2026-06-25", "campground", today=today)
        assert result == today.isoformat()

    def test_arrival_same_day_as_today_clamps_to_today(self):
        today = dt.date(2026, 6, 23)
        result = book_by("2026-06-23", "campground", today=today)
        assert result == today.isoformat()

    def test_timed_entry_future_date(self):
        # arrival 2026-06-20, timed-entry = 7 days → release 2026-06-13
        today = dt.date(2026, 6, 1)
        expected = (dt.date(2026, 6, 20) - dt.timedelta(days=7)).isoformat()
        assert book_by("2026-06-20", "timed-entry", today=today) == expected

    def test_in_park_lodge_future_date(self):
        # today 2025-01-01, arrival 2027-07-01; 395-day window opens 2026-06-01
        today = dt.date(2025, 1, 1)
        expected = (dt.date(2027, 7, 1) - dt.timedelta(days=395)).isoformat()
        assert book_by("2027-07-01", "in-park-lodge", today=today) == expected

    def test_unknown_rule_returns_none(self):
        assert book_by("2027-01-01", "nonexistent-rule") is None

    def test_result_never_before_today(self):
        today = dt.date(2026, 6, 23)
        for rule in RELEASE_RULES:
            result = book_by("2026-07-01", rule, today=today)
            if result is not None:
                assert result >= today.isoformat(), (
                    f"rule '{rule}' returned a past date: {result}"
                )


class TestCountdown:
    def test_returns_expected_keys(self):
        result = countdown("2027-06-01")
        assert result["source"] == "rules"
        assert "bookingCountdown" in result
        assert "disclaimer" in result

    def test_default_three_items(self):
        result = countdown("2027-06-01")
        assert len(result["bookingCountdown"]) == 3

    def test_each_item_has_required_fields(self):
        result = countdown("2027-06-01")
        for item in result["bookingCountdown"]:
            assert "item" in item
            assert "bookBy" in item
            assert "where" in item
            assert "priority" in item
            assert "note" in item

    def test_custom_items(self):
        items = [("My Campsite", "campground", "Recreation.gov")]
        result = countdown("2027-06-01", items=items)
        assert len(result["bookingCountdown"]) == 1
        assert result["bookingCountdown"][0]["item"] == "My Campsite"

    def test_past_arrival_book_by_equals_arrival(self):
        # When arrival is in the past, book_by clamps to min(today, arrival) = arrival.
        # The countdown should reflect that date, not a future date.
        arrival = "2020-01-01"
        result = countdown(arrival)
        for item in result["bookingCountdown"]:
            assert item["bookBy"] == arrival


def park(full_name, code, fees=(), name=None):
    """One park record, cut down to the fields the NPS API sends that we read."""
    return {
        "fullName": full_name, "name": name or full_name.split(" National")[0],
        "parkCode": code, "states": "NM", "url": "https://www.nps.gov/%s/index.htm" % code,
        "description": "A park.", "latitude": "32.14", "longitude": "-104.55",
        "entranceFees": [{"cost": cost, "title": title} for cost, title in fees],
    }


# Fee lists as the NPS API returned them in November 2026.
CARLSBAD = park("Carlsbad Caverns National Park", "cave", [
    ("1.00", "Timed Entry Reservation - Location"),
    ("15.00", "Entrance - Per Person")])
CEDAR_BREAKS = park("Cedar Breaks National Monument", "cebr", [
    ("25.00", "Commercial Entrance - Sedan"),
    ("25.00", "Entrance - Private Vehicle"),
    ("15.00", "Entrance - Per Person"),
    ("20.00", "Entrance - Motorcycle")])
PETRIFIED = park("Petrified Forest National Park", "pefo", [
    ("25.00", "Entrance - Private Vehicle"),
    ("15.00", "Entrance - Per Person")])
GATEWAY_ARCH = park("Gateway Arch National Park", "jeff", [
    ("19.00", "Timed Entry Reservation - Location")])
SANDBURG = park("Carl Sandburg Home National Historic Site", "carl")
ALASKA = park("Alaska Public Lands", "anch")
PETROGLYPH = park("Petroglyph National Monument", "petr")
ZION = park("Zion National Park", "zion", [("35.00", "Entrance - Private Vehicle")])
TUBMAN = park("Harriet Tubman National Historical Park", "hart")


def nps(monkeypatch, parks):
    net = FakeNetwork({"developer.nps.gov": {"total": str(len(parks)), "data": parks}})
    monkeypatch.setattr(parks_client, "urlopen", net)
    monkeypatch.setenv("NPS_API_KEY", "test-nps-key")
    return net


def names(result):
    return [p["name"] for p in result["parks"]]


class TestParkInfoRanking:
    def test_asks_nps_for_its_most_relevant_matches(self, monkeypatch):
        net = nps(monkeypatch, [CARLSBAD])
        park_info("Carlsbad Caverns National Park")
        asked = parse_qs(urlsplit(net.urls[0]).query)
        assert asked["q"] == ["Carlsbad Caverns National Park"]
        assert asked["sort"] == ["-relevanceScore"]
        assert int(asked["limit"][0]) > 3

    def test_exact_name_comes_first_whatever_order_nps_sends(self, monkeypatch):
        nps(monkeypatch, [ALASKA, SANDBURG, PETRIFIED, CARLSBAD])
        assert names(park_info("carlsbad caverns national park"))[0] == \
            "Carlsbad Caverns National Park"

    def test_name_starting_with_the_query_comes_first(self, monkeypatch):
        nps(monkeypatch, [ALASKA, PETROGLYPH, PETRIFIED])
        assert names(park_info("Petrified Forest"))[0] == "Petrified Forest National Park"

    def test_park_code_counts_as_an_exact_match(self, monkeypatch):
        nps(monkeypatch, [TUBMAN, ZION])
        assert names(park_info("zion"))[0] == "Zion National Park"

    def test_nps_order_is_kept_among_equal_matches(self, monkeypatch):
        nps(monkeypatch, [PETROGLYPH, ALASKA, SANDBURG])
        assert names(park_info("desert"))[:2] == [
            "Petroglyph National Monument", "Alaska Public Lands"]

    def test_returns_at_most_three_parks(self, monkeypatch):
        nps(monkeypatch, [ALASKA, SANDBURG, PETROGLYPH, TUBMAN, CARLSBAD])
        assert names(park_info("Carlsbad Caverns")) == [
            "Carlsbad Caverns National Park", "Alaska Public Lands",
            "Carl Sandburg Home National Historic Site"]


class TestParkInfoEntranceFee:
    def fee(self, monkeypatch, record):
        nps(monkeypatch, [record])
        p = park_info(record["fullName"])["parks"][0]
        return p["entranceFee"], p["entranceFeeTitle"]

    def test_timed_entry_reservation_is_not_the_entrance_fee(self, monkeypatch):
        assert self.fee(monkeypatch, CARLSBAD) == ("15.00", "Entrance - Per Person")

    def test_private_vehicle_fee_wins_over_commercial_and_per_person(self, monkeypatch):
        assert self.fee(monkeypatch, CEDAR_BREAKS) == ("25.00", "Entrance - Private Vehicle")

    def test_park_with_only_a_reservation_fee_has_no_entrance_fee(self, monkeypatch):
        assert self.fee(monkeypatch, GATEWAY_ARCH) == (None, None)

    def test_park_with_no_fees_has_no_entrance_fee(self, monkeypatch):
        assert self.fee(monkeypatch, SANDBURG) == (None, None)


class TestParkInfoFallback:
    def test_no_key_asks_nobody_and_falls_back(self, monkeypatch):
        net = nps(monkeypatch, [CARLSBAD])
        monkeypatch.delenv("NPS_API_KEY")
        assert park_info("Carlsbad Caverns")["source"] == "fallback"
        assert net.urls == []

    def test_nps_down_falls_back(self, monkeypatch):
        monkeypatch.setattr(parks_client, "urlopen", FakeNetwork({}))
        monkeypatch.setenv("NPS_API_KEY", "test-nps-key")
        assert park_info("Carlsbad Caverns")["source"] == "fallback"

    def test_no_match_falls_back(self, monkeypatch):
        nps(monkeypatch, [])
        assert park_info("Atlantis")["source"] == "fallback"
