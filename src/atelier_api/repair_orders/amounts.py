"""Calculate rounded line amounts before summing exact monetary totals."""

from collections.abc import Iterable
from decimal import ROUND_HALF_UP, Decimal, localcontext

CENT = Decimal("0.01")


def line_amount(quantity: Decimal, unit_price: Decimal) -> Decimal:
    """Round quantity times unit price to cents using commercial rounding."""
    with localcontext() as context:
        context.prec = 38
        context.rounding = ROUND_HALF_UP
        return (quantity * unit_price).quantize(CENT)


def sum_amounts(amounts: Iterable[Decimal]) -> Decimal:
    """Sum already rounded line amounts without binary floating point arithmetic."""
    with localcontext() as context:
        context.prec = 38
        context.rounding = ROUND_HALF_UP
        return sum(amounts, start=Decimal("0.00")).quantize(CENT)
