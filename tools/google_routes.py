#!/usr/bin/env python3
"""
google_routes.py — what Google routes between a list of stops, leg by leg.

Asks Google's Routes API (computeRoutes) for the driving route through the
waypoints as stops and returns each leg's metres, seconds and path. The path
is what `route` cannot give: it shows which road each leg takes, so a caller
can check that a route stays on a chosen road.

Needs GOOGLE_ROUTES_API_KEY in the environment. Without it, or when Google
refuses, the answer is {"source": "error", "reason": ...}: there is no other
engine to fall back to, because the point is Google's own choice of road.

Google bills per request, and a request with more than 10 stops between its
ends, or with live traffic, is billed at the Pro rate instead of Essentials.
The answer names the tier and the number of requests it took.

CLI:
    GOOGLE_ROUTES_API_KEY=xxx python3 google_routes.py 35.1983,-111.6513 35.2495,-112.1910
"""

import json
import math
import os
import sys
from urllib.request import Request, urlopen

URL = "https://routes.googleapis.com/directions/v2:computeRoutes"
FIELDS = ",".join("routes.legs." + f for f in (
    "distanceMeters", "duration", "staticDuration", "polyline.encodedPolyline"))
MAX_INTERMEDIATES = 25      # Google's limit per request
ESSENTIALS_INTERMEDIATES = 10
TRAFFIC = {"none": "TRAFFIC_UNAWARE", "live": "TRAFFIC_AWARE_OPTIMAL"}
EARTH_M = 6371008.8


def decode_polyline(text):
    """Google's encoded polyline -> [[lat, lng], ...] at five decimal places."""
    points, index, lat, lng = [], 0, 0, 0
    while index < len(text):
        for axis in (0, 1):
            shift = result = 0
            while True:
                byte = ord(text[index]) - 63
                index += 1
                result |= (byte & 0x1F) << shift
                shift += 5
                if byte < 0x20:
                    break
            delta = ~(result >> 1) if result & 1 else result >> 1
            if axis == 0:
                lat += delta
            else:
                lng += delta
        points.append([lat / 1e5, lng / 1e5])
    return points


def simplify(points, tolerance_m):
    """Drop path points that lie within tolerance_m of the line through their
    kept neighbours (Douglas-Peucker). Both ends are always kept."""
    if tolerance_m <= 0 or len(points) < 3:
        return points
    lat0 = math.radians(points[0][0])
    kx = EARTH_M * math.cos(lat0) * math.pi / 180.0
    ky = EARTH_M * math.pi / 180.0
    xy = [(lng * kx, lat * ky) for lat, lng in points]
    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    while stack:
        first, last = stack.pop()
        if last - first < 2:
            continue
        ax, ay = xy[first]
        bx, by = xy[last]
        dx, dy = bx - ax, by - ay
        length_sq = dx * dx + dy * dy
        worst, worst_at = -1.0, None
        for i in range(first + 1, last):
            px, py = xy[i]
            if length_sq == 0:
                d = math.hypot(px - ax, py - ay)
            else:
                t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length_sq))
                d = math.hypot(px - (ax + t * dx), py - (ay + t * dy))
            if d > worst:
                worst, worst_at = d, i
        if worst > tolerance_m:
            keep[worst_at] = True
            stack.append((first, worst_at))
            stack.append((worst_at, last))
    return [p for p, kept in zip(points, keep) if kept]


def _waypoint(point):
    return {"location": {"latLng": {"latitude": point[0], "longitude": point[1]}}}


def _seconds(text):
    return round(float(str(text or "0s").rstrip("s")))


def _ask(points, key, preference, depart_at, timeout):
    body = {
        "origin": _waypoint(points[0]),
        "destination": _waypoint(points[-1]),
        "intermediates": [_waypoint(p) for p in points[1:-1]],
        "travelMode": "DRIVE",
        "routingPreference": preference,
        "polylineQuality": "HIGH_QUALITY",
    }
    if depart_at:
        body["departureTime"] = depart_at
    request = Request(URL, data=json.dumps(body).encode(), headers={
        "Content-Type": "application/json",
        "X-Goog-Api-Key": key,
        "X-Goog-FieldMask": FIELDS,
    })
    with urlopen(request, timeout=timeout) as response:
        data = json.loads(response.read().decode())
    routes = data.get("routes") or []
    if not routes:
        raise ValueError("Google returned no route")
    legs = routes[0].get("legs") or []
    if len(legs) != len(points) - 1:
        raise ValueError("Google returned %d legs for %d stops" % (len(legs), len(points)))
    return legs


def _failure(error, key):
    """What went wrong, with Google's own message when it sent one and never
    the key."""
    text = str(error)
    read = getattr(error, "read", None)
    if read:
        try:
            detail = json.loads(read().decode()).get("error", {})
            text = "%s: %s" % (text, detail.get("message") or detail.get("status") or "")
        except Exception:  # not JSON, already read, or no body
            pass
    return text.replace(key, "***")


def route_legs(waypoints, traffic="none", depart_at=None, path_tolerance_m=10.0,
               max_intermediates=ESSENTIALS_INTERMEDIATES, timeout=30):
    """waypoints: list of (lat, lng), driven in order with a stop at each.

    Returns {"source": "google", "traffic", "requests", "tier", "meters",
    "seconds", "legs": [{"meters", "seconds", "path": [[lat, lng], ...]}]},
    one leg per pair of neighbouring waypoints. "seconds" follows `traffic`:
    "none" is Google's typical time with no live traffic, "live" is the app's
    own mode (today's traffic, or the forecast for depart_at, an RFC 3339 time
    in the future). path_tolerance_m thins each path; 0 keeps every point.
    """
    if len(waypoints) < 2:
        return {"source": "error", "reason": "need >= 2 waypoints"}
    if traffic not in TRAFFIC:
        return {"source": "error", "reason": "traffic must be 'none' or 'live'"}
    if depart_at and traffic != "live":
        return {"source": "error", "reason": "depart_at needs traffic='live'"}
    key = os.environ.get("GOOGLE_ROUTES_API_KEY", "").strip()
    if not key:
        return {"source": "error", "reason": "the server has no GOOGLE_ROUTES_API_KEY"}

    per_request = max(0, min(int(max_intermediates), MAX_INTERMEDIATES)) + 1
    legs, requests = [], 0
    for start in range(0, len(waypoints) - 1, per_request):
        points = waypoints[start:start + per_request + 1]
        try:
            answer = _ask(points, key, TRAFFIC[traffic], depart_at, timeout)
        except Exception as error:  # bad key / quota / network blocked / no route
            return {"source": "error", "requests": requests,
                    "reason": "Google unavailable: %s" % _failure(error, key)}
        requests += 1
        for leg in answer:
            encoded = (leg.get("polyline") or {}).get("encodedPolyline") or ""
            legs.append({
                "meters": int(leg.get("distanceMeters") or 0),
                "seconds": _seconds(leg.get("duration")),
                "path": simplify(decode_polyline(encoded), path_tolerance_m),
            })
    pro = traffic == "live" or per_request - 1 > ESSENTIALS_INTERMEDIATES
    return {
        "source": "google",
        "traffic": traffic,
        "requests": requests,
        "tier": "pro" if pro else "essentials",
        "meters": sum(leg["meters"] for leg in legs),
        "seconds": sum(leg["seconds"] for leg in legs),
        "legs": legs,
    }


def _parse(text):
    lat, lng = text.split(",")
    return (float(lat), float(lng))


if __name__ == "__main__":
    stops = [_parse(a) for a in sys.argv[1:]]
    if len(stops) < 2:
        stops = [(35.1983, -111.6513), (35.2495, -112.1910)]  # Flagstaff -> Williams
    print(json.dumps(route_legs(stops), indent=2))
