"""Integer-cent rounding. ASSIGNMENT requires round-half-up, not banker's rounding."""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP


def mul_round_half_up(rate: float, cents: int) -> int:
    """``round_half_up(rate * cents)`` without binary-float drift (e.g. 0.145 * 100)."""
    product = Decimal(str(rate)) * Decimal(cents)
    return int(product.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
