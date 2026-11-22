"""Weather codes, forecast source order, and seasonal archive parsing."""

from tools import weather_client as wc


# --------------------------------------------------------------------------- #
# weather_client: parsing + source ladder
# --------------------------------------------------------------------------- #

def _fake_http(mapping):
    """Return a _get_json stand-in: substring in URL -> canned dict."""
    def _get(url, timeout):
        for needle, payload in mapping.items():
            if needle in url:
                return payload
        raise AssertionError("unexpected URL: " + url)
    return _get


class TestWmoMapping:
    def test_codes_map_to_weather_icons(self):
        assert wc._wmo_icon(0) == "sunny"
        assert wc._wmo_icon(3) == "cloudy"
        assert wc._wmo_icon(65) == "rain"
        assert wc._wmo_icon(75) == "snow"
        assert wc._wmo_icon(95) == "storm"
        assert wc._wmo_icon(45) == "fog"
        assert wc._wmo_icon(None) == "partly-cloudy"
        assert wc._wmo_icon(9999) == "partly-cloudy"     # unknown code


class TestForecastLadder:
    _OM = {"daily": {
        "time": ["2026-07-13", "2026-07-14"],
        "weather_code": [3, 95],
        "temperature_2m_max": [91.7, 88.0],
        "temperature_2m_min": [70.2, 68.0],
        "precipitation_probability_max": [9, 60],
        "wind_speed_10m_max": [15.9, 22.0],
    }}

    def test_nws_used_first(self, monkeypatch):
        monkeypatch.setattr(wc, "_nws", lambda lat, lng, t=8: [
            {"date": "2026-07-13", "icon": "storm", "high": 91, "low": 56}])
        out = wc.forecast(37.3, -113.0)
        assert out["source"] == "nws" and out["days"][0]["icon"] == "storm"

    def test_falls_back_to_open_meteo(self, monkeypatch):
        monkeypatch.setattr(wc, "_nws",
                            lambda *a, **k: (_ for _ in ()).throw(Exception("US-only")))
        monkeypatch.setattr(wc, "_get_json", _fake_http({"open-meteo": self._OM}))
        out = wc.forecast(51.18, -115.57)                 # Banff — NWS can't
        assert out["source"] == "open-meteo"
        assert len(out["days"]) == 2
        d1 = out["days"][1]
        assert d1["icon"] == "storm" and d1["high"] == 88      # WMO 95 -> storm
        assert d1["precipProb"] == 60 and d1["windMph"] == 22  # extra signals

    def test_total_failure_returns_fallback_shape(self, monkeypatch):
        monkeypatch.setattr(wc, "_nws",
                            lambda *a, **k: (_ for _ in ()).throw(Exception("down")))
        monkeypatch.setattr(wc, "_get_json",
                            lambda *a, **k: (_ for _ in ()).throw(Exception("down")))
        out = wc.forecast(0.0, 0.0)
        assert out["source"] == "fallback"                # never raises


class TestClimatology:
    _ARCHIVE = {"daily": {
        "time": ["2025-09-12", "2025-09-13", "2025-09-14", "2025-09-15"],
        "weather_code": [3, 3, 95, 61],
        "temperature_2m_max": [88.0, 90.0, 78.0, 80.0],
        "temperature_2m_min": [60.0, 62.0, 55.0, 57.0],
        "precipitation_sum": [0.0, 0.0, 0.3, 0.1],
    }}

    def test_averages_and_flags_wet_share(self, monkeypatch):
        monkeypatch.setattr(wc, "_get_json", _fake_http({"archive": self._ARCHIVE}))
        c = wc.climatology(37.3, -113.0, 9, 13, span_days=4)
        assert c["source"] == "climatology" and c["year"] == 2025
        assert c["high"] == 84                            # mean of the 4 highs
        assert c["icon"] == "storm"                       # most notable = WMO 95
        assert 0.4 < c["wetShare"] <= 0.5                 # 2 of 4 days wet

    def test_feb_29_reference_year_does_not_crash(self, monkeypatch):
        monkeypatch.setattr(wc, "_get_json", _fake_http({"archive": self._ARCHIVE}))
        assert wc.climatology(37.3, -113.0, 2, 29) is not None

    def test_empty_archive_returns_none(self, monkeypatch):
        monkeypatch.setattr(wc, "_get_json", _fake_http({"archive": {"daily": {}}}))
        assert wc.climatology(37.3, -113.0, 9, 13) is None
