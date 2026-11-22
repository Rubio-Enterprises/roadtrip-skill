import json
import os
import re
import shutil
import subprocess

import pytest
from assets.generate import validate, build_html

TEMPLATE_PATH = os.path.join(os.path.dirname(__file__), "..", "assets", "template.html")

MINIMAL_VALID = {
    "title": "My Trip",
    "days": [
        {
            "date": "2026-07-01",
            "title": "Day 1",
            "stops": [{"lat": 36.1, "lng": -112.1}],
        }
    ],
    "disclaimer": "Check all info before travelling.",
}

TEMPLATE = "<html><script>var x = __TRIP_DATA__;</script></html>"


class TestValidate:
    def test_valid_trip_no_critical_warnings(self):
        warnings = validate(MINIMAL_VALID)
        assert not any("missing top-level" in w for w in warnings)

    def test_missing_title(self):
        trip = {k: v for k, v in MINIMAL_VALID.items() if k != "title"}
        assert any("title" in w for w in validate(trip))

    def test_missing_days_key(self):
        trip = {k: v for k, v in MINIMAL_VALID.items() if k != "days"}
        assert any("days" in w for w in validate(trip))

    def test_empty_days_list(self):
        trip = {**MINIMAL_VALID, "days": []}
        assert any("days" in w for w in validate(trip))

    def test_day_missing_date(self):
        trip = {**MINIMAL_VALID, "days": [{"title": "Day 1"}]}
        assert any("date" in w for w in validate(trip))

    def test_day_missing_title(self):
        trip = {**MINIMAL_VALID, "days": [{"date": "2026-07-01"}]}
        assert any("title" in w for w in validate(trip))

    def test_no_coords_warning(self):
        trip = {
            **MINIMAL_VALID,
            "days": [{"date": "2026-07-01", "title": "D1",
                      "stops": [{"name": "somewhere"}]}],
        }
        assert any("lat/lng" in w for w in validate(trip))

    def test_budget_mismatch_warning(self):
        trip = {
            **MINIMAL_VALID,
            "budget": {"total": 1000, "items": [{"amount": 400}, {"amount": 400}]},
        }
        assert any("budget" in w for w in validate(trip))

    def test_budget_balanced_no_warning(self):
        trip = {
            **MINIMAL_VALID,
            "budget": {"total": 800, "items": [{"amount": 400}, {"amount": 400}]},
        }
        assert not any("budget" in w for w in validate(trip))

    def test_no_disclaimer_warning(self):
        trip = {k: v for k, v in MINIMAL_VALID.items() if k != "disclaimer"}
        assert any("disclaimer" in w for w in validate(trip))


class TestBuildHtml:
    def test_token_replaced(self):
        trip = {"title": "T", "days": []}
        html = build_html(trip, TEMPLATE)
        assert "__TRIP_DATA__" not in html
        assert '"title"' in html

    def test_script_closing_tag_escaped(self):
        trip = {"note": "</script>", "days": []}
        html = build_html(trip, TEMPLATE)
        assert "<\\/script>" in html
        # The raw </script> must not appear inside the payload section
        payload_section = html.split("<script>")[1]
        assert "</script>" not in payload_section.split("</script>")[0]

    def test_html_comment_escaped(self):
        trip = {"note": "<!-- inject -->", "days": []}
        html = build_html(trip, TEMPLATE)
        assert "<\\!--" in html

    def test_missing_token_raises_value_error(self):
        with pytest.raises(ValueError, match="missing"):
            build_html({"days": []}, "<html>no token here</html>")


def rendered_sections(trip):
    """Run the generated page's inline scripts offline; collect their DOM writes."""
    if not shutil.which("node"):
        pytest.skip("needs Node.js to run the template's JS")
    with open(TEMPLATE_PATH, encoding="utf-8") as f:
        html = build_html(trip, f.read())
    dom = """
        const nodes = {};
        function element() {
            return {style: {}, setAttribute() {}, getAttribute() {},
                    addEventListener() {}, querySelectorAll() { return []; }};
        }
        const document = {documentElement: element(), getElementById(id) {
            return nodes[id] || (nodes[id] = element());
        }};
    """
    scripts = re.findall(r"<script>(.*?)</script>", html, re.S)
    output = """
        const sections = Object.fromEntries(Object.entries(nodes).map(([id, el]) => [id, el.innerHTML]));
        console.log(JSON.stringify(sections));
    """
    result = subprocess.run(["node"], input="\n".join([dom] + scripts + [output]),
                            capture_output=True, encoding="utf-8", check=True)
    return json.loads(result.stdout)


@pytest.mark.parametrize("currency,printed", [
    ("GBP", "£1,234.5"), ("EUR", "€1,234.5"), ("ZZZ", "ZZZ 1,234.5"),
    ("USD", "$1,234.5"), ("CAD", "C$1,234.5"), ("MXN", "MX$1,234.5"),
    ("CNY", "¥1,234.5"), ("RMB", "¥1,234.5"),
])
def test_budget_prints_trip_currency(currency, printed):
    sections = rendered_sections({"days": [], "budget": {
        "currency": currency, "items": [{"amount": 1234.5}], "total": 1234.5}})
    assert printed in sections["budget"].replace("\xa0", " ")


def test_booking_prints_item_currency_or_trip_currency():
    sections = rendered_sections({"units": {"currency": "GBP"}, "bookingCountdown": [
        {"item": "Guided walk", "price": {"amount": 18, "unit": "person"}},
        {"item": "Hotel", "price": {"amount": 90, "currency": "EUR", "unit": "night"}},
    ]})
    assert "£18/person" in sections["bookingTabs"]
    assert "€90/night" in sections["bookingTabs"]


@pytest.mark.parametrize("date,lang,label", [
    ("11/28", "en", "28 Nov"), ("1/2", "en", "2 Jan"),
    ("11/28", "zh", "11月28日"), ("2026-11-28", "en", "2026-11-28"),
    ("TBD & flexible", "en", "TBD &amp; flexible"),
])
def test_day_and_booking_show_the_same_trip_date(date, lang, label):
    trip = {"lang": lang, "days": [{"date": date, "meal": {"name": "Cafe"}}]}
    sections = rendered_sections(trip)
    assert "Day 1 · " + label in sections["days"]
    assert ("行程日期 " if lang == "zh" else "Trip date ") + label in sections["bookingTabs"]


