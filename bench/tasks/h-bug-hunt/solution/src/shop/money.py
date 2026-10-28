"""Money helpers. Amounts are Decimals quantized to cents, rounded half-up."""

from decimal import ROUND_HALF_UP, Decimal

CENT = Decimal("0.01")
_FORMATS = {"USD": "${:,.2f}", "GBP": "£{:,.2f}"}


def to_money(value) -> Decimal:
    """Convert an int, str or Decimal to a cent-quantized Decimal."""
    if isinstance(value, float):
        raise TypeError("use Decimal or str for money, not float")
    return Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


def format_money(amount, currency: str = "USD") -> str:
    template = _FORMATS.get(currency)
    if template is None:
        raise ValueError(f"unsupported currency: {currency}")
    return template.format(to_money(amount))
