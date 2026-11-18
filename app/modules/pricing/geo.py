"""Distance between a restaurant and a delivery address.

Real platforms ask a routing engine (Google Maps, OSRM) for the actual road
distance. That costs money per request and a network call per quote, so many
systems estimate first: the straight-line ("as the crow flies") distance,
times a detour index. Road distance is usually 20-30% longer than the straight
line (transport research calls the ratio "circuity"); QuickServe uses 1.25.
"""

import math
from decimal import ROUND_HALF_UP, Decimal

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
