"""Money helpers.

Money is always Decimal in Python and NUMERIC in PostgreSQL, never float.

    >>> 0.1 + 0.2
    0.30000000000000004
    >>> Decimal("0.1") + Decimal("0.2")
    Decimal('0.3')
"""

from decimal import ROUND_HALF_UP, Decimal

PAISE = Decimal("0.01")


def rupees(value: Decimal | int | str) -> Decimal:
    """Round to 2 decimal places the way a bill is rounded (half up, not banker's rounding)."""
    return Decimal(value).quantize(PAISE, rounding=ROUND_HALF_UP)
