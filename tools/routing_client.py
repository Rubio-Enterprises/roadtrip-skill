#!/usr/bin/env python3
"""
routing_client.py — route distance & driving time between waypoints.

Preferred: TomTom Routing API, when TOMTOM_API_KEY is set in the environment.
Otherwise: OSRM public demo server (OSM-based, no key). Its times run about
           19-34% long: that server drives at 80% of every posted limit.
Fallback:  great-circle distance × a road-winding factor, with a web-search note.

Returns miles + an "Xh Ym" string, and "source" naming the engine that produced
them ("tomtom", "osrm" or "fallback"). Units default to miles (US road trips).
Neither engine knows road closures: a pass shut for the season routes as open.

CLI:
    python3 routing_client.py 36.1699,-115.1398 37.2982,-113.0263 ...
    TOMTOM_API_KEY=xxx python3 routing_client.py 36.1699,-115.1398 37.2982,-113.0263
"""

import json
import math
import os
import sys
from urllib.parse import quote_plus, urlencode
from urllib.request import urlopen

try:
    from web_search import fallback
except ImportError:  # when imported as tools.web_search
    from tools.web_search import fallback

TOMTOM = "https://api.tomtom.com/routing/1/calculateRoute/"
OSRM = "https://router.project-osrm.org/route/v1/driving/"
KM_PER_MILE = 1.60934
ROAD_FACTOR = 1.25  # straight-line → driving distance fudge factor for fallback
AVG_MPH = 55        # fallback average speed incl. stops


def _fmt_time(hours):
    h = int(hours)
    m = int(round((hours - h) * 60))
    if m == 60:
        h, m = h + 1, 0
    return "%dh%02dm" % (h, m)


def haversine_miles(a, b):
    lat1, lon1, lat2, lon2 = map(math.radians, [a[0], a[1], b[0], b[1]])
    dlat, dlon = lat2 - lat1, lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * 3958.8 * math.asin(math.sqrt(h))


def _routed(source, meters, seconds):
    hours = seconds / 3600.0
    return {
        "source": source,
        "miles": round(meters / 1000.0 / KM_PER_MILE, 1),
        "driveTime": _fmt_time(hours),
        "hours": round(hours, 2),
    }


def _tomtom(waypoints, key, timeout):
    locs = ":".join("%f,%f" % (lat, lng) for (lat, lng) in waypoints)  # TomTom=lat,lng
    # traffic=false: typical speeds for the road as if open. TomTom delivers
    # closures through the traffic feed and applies today's to any departure
    # date, so with traffic on a pass shut for winter is also avoided for a July
    # trip. The cost: like OSRM, this routes over a road that is closed today.
    url = TOMTOM + locs + "/json?" + urlencode({"traffic": "false", "key": key})
    with urlopen(url, timeout=timeout) as r:
        data = json.loads(r.read().decode())
    summary = data["routes"][0]["summary"]
    return _routed("tomtom", summary["lengthInMeters"], summary["travelTimeInSeconds"])


def _without_key(text, key):
    """The key travels in the request URL, and some urllib errors quote the URL."""
    return str(text).replace(key, "***").replace(quote_plus(key), "***")


def route(waypoints, timeout=8):
    """waypoints: list of (lat, lng). Returns a dict with miles + driveTime.

    "source" names the engine: "tomtom" when TOMTOM_API_KEY is set and TomTom
    answered, else "osrm", else "fallback" (the offline estimate)."""
    if len(waypoints) < 2:
        return {"source": "error", "reason": "need >= 2 waypoints"}

    tomtom_failure = None
    key = os.environ.get("TOMTOM_API_KEY")
    if key:
        try:
            return _tomtom(waypoints, key, timeout)
        except Exception as e:  # bad key / quota / network blocked / no route
            tomtom_failure = "TomTom unavailable: %s" % _without_key(e, key)

    coords = ";".join("%f,%f" % (lng, lat) for (lat, lng) in waypoints)  # OSRM=lng,lat
    url = OSRM + coords + "?overview=false"
    try:
        with urlopen(url, timeout=timeout) as r:
            data = json.loads(r.read().decode())
        if data.get("code") == "Ok" and data.get("routes"):
            rt = data["routes"][0]
            out = _routed("osrm", rt["distance"], rt["duration"])
            if tomtom_failure:
                out["note"] = tomtom_failure + "; OSRM times run about 19-34% long"
            return out
    except Exception as e:  # network blocked / OSRM down
        reason = "OSRM unavailable: %s" % e
    else:
        reason = "OSRM returned no route"
    if tomtom_failure:
        reason = tomtom_failure + "; " + reason

    # ---- fallback: straight-line × winding factor ----
    miles = sum(haversine_miles(waypoints[i], waypoints[i + 1])
                for i in range(len(waypoints) - 1)) * ROAD_FACTOR
    hours = miles / AVG_MPH
    out = fallback(reason, ["driving distance and time " + " to ".join(
        "%.3f,%.3f" % w for w in waypoints)])
    out.update({
        "miles": round(miles, 1),
        "driveTime": _fmt_time(hours),
        "hours": round(hours, 2),
        "note": "rough estimate (great-circle × %.2f); verify with a maps app" % ROAD_FACTOR,
    })
    return out


def _parse(s):
    lat, lng = s.split(",")
    return (float(lat), float(lng))


if __name__ == "__main__":
    pts = [_parse(a) for a in sys.argv[1:]]
    if len(pts) < 2:
        pts = [(36.1699, -115.1398), (37.2982, -113.0263)]  # Vegas -> Zion demo
    print(json.dumps(route(pts), indent=2))
