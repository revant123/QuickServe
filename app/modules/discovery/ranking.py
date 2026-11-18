"""Pure functions for the restaurant list: delivery time and rating score.

No database here, like pricing/calculator.py: easy to test, easy to read.
"""

import math
from decimal import Decimal

from app.core.config import Settings


def eta_minutes(prep_minutes: int, distance_km: Decimal, settings: Settings) -> int:
    """Estimated minutes from "Place order" to the doorbell.

    Swiggy's engineering blog breaks delivery time into:
        max(assignment delay + first mile, prep time) + last mile
    The rider is found and rides to the restaurant WHILE the kitchen cooks, so
    only the slower of the two counts. Then the ride to the customer, and a few
    minutes to park and hand over.

    Real platforms predict each part with machine learning (traffic, the
    restaurant's current load, rain). This is the same shape with averages.
    """
    first_part = max(settings.rider_first_mile_minutes, prep_minutes)
    last_mile = math.ceil(float(distance_km) / float(settings.rider_speed_kmph) * 60)
    return first_part + last_mile + settings.handoff_minutes


def eta_text(minutes: int) -> str:
    """Apps show a range, not a promise to the minute: 27 -> "25-30 min"."""
    low = minutes // 5 * 5
    return f"{low}-{low + 5} min"


def bayesian_rating(rating_sum: int, rating_count: int, prior_mean: Decimal, prior_weight: int) -> Decimal:
    """Average rating as if every restaurant started with `prior_weight` reviews
    at `prior_mean`.

    Sorting by the plain average puts a new place with one 5-star review above a
    favourite with 400 reviews averaging 4.6. Evan Miller ("Bayesian Average
    Ratings") and IMDb's Top 250 formula both fix it the same way:

        score = (C x m + sum of ratings) / (C + number of ratings)

    With few reviews the score stays near m, the platform average. As reviews
    pile up, they outweigh the C imaginary ones and the score moves to the
    restaurant's own average.
    """
    return (prior_weight * prior_mean + rating_sum) / (prior_weight + rating_count)
