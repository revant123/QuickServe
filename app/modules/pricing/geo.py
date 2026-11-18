"""Distance between a restaurant and a delivery address.

Real platforms ask a routing engine (Google Maps, OSRM) for the actual road
distance. That costs money per request and a network call per quote, so many
systems estimate first: the straight-line ("as the crow flies") distance,
times a detour index. Road distance is usually 20-30% longer than the straight
line (transport research calls the ratio "circuity"); QuickServe uses 1.25.
"""

import math
from dataclasses import dataclass
from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP, Decimal

EARTH_RADIUS_KM = 6371.0088  # mean Earth radius


def straight_line_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance with the haversine formula."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def road_km(lat1, lon1, lat2, lon2, detour_factor: Decimal) -> Decimal:
    """Estimated road distance, to 0.1 km."""
    km = Decimal(str(straight_line_km(float(lat1), float(lon1), float(lat2), float(lon2)))) * detour_factor
    return km.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class Box:
    min_lat: Decimal
    max_lat: Decimal
    min_lng: Decimal
    max_lng: Decimal


def _deg(x: float, rounding) -> Decimal:
    # Round OUTWARD to the column's 6 decimals: a box a hair too big is harmless
    # (the exact distance check runs next), a box a hair too small loses a restaurant.
    return Decimal(str(math.degrees(x))).quantize(Decimal("0.000001"), rounding=rounding)


def bounding_box(lat: float, lng: float, km: float) -> Box:
    """The smallest latitude/longitude rectangle that contains every point within
    `km` (straight line) of (lat, lng). Method from Jan Philip Matuschek,
    "Finding Points Within a Distance of a Latitude/Longitude Using Bounding Coordinates".

    Why a rectangle? "distance < 6 km" is a formula over every row: the database
    must compute it for the whole table. "latitude BETWEEN a AND b" is a range
    an ordinary B-tree index can answer. So: cut the rectangle with the index,
    then compute the exact distance only for the few rows inside it.
    """
    angular = km / EARTH_RADIUS_KM  # the radius as an angle, in radians
    lat_r, lng_r = math.radians(lat), math.radians(lng)
    min_lat, max_lat = lat_r - angular, lat_r + angular
    if min_lat > -math.pi / 2 and max_lat < math.pi / 2:
        # Lines of longitude get closer together away from the equator, so the
        # box is wider (in degrees) than it is tall: 1 / cos(latitude) wider.
        d_lng = math.asin(math.sin(angular) / math.cos(lat_r))
        min_lng, max_lng = lng_r - d_lng, lng_r + d_lng
        if min_lng < -math.pi or max_lng > math.pi:
            # The circle crosses the 180th meridian (Fiji, not India). Matuschek
            # splits the box in two there; we simply search every longitude.
            min_lng, max_lng = -math.pi, math.pi
    else:
        # A pole is inside the circle: every longitude is in range.
        min_lat, max_lat = max(min_lat, -math.pi / 2), min(max_lat, math.pi / 2)
        min_lng, max_lng = -math.pi, math.pi
    return Box(
        min_lat=_deg(min_lat, ROUND_FLOOR),
        max_lat=_deg(max_lat, ROUND_CEILING),
        min_lng=_deg(min_lng, ROUND_FLOOR),
        max_lng=_deg(max_lng, ROUND_CEILING),
    )
