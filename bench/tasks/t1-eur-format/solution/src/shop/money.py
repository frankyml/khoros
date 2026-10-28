"""Money helpers. Amounts are Decimals quantized to cents, rounded half-up."""

from decimal import ROUND_HALF_UP, Decimal

CENT = Decimal("0.01")
_SYMBOLS = {"USD": "$", "GBP": "£", "EUR": "€"}


def to_money(value) -> Decimal:
    """Convert an int, str or Decimal to a cent-quantized Decimal."""
    if isinstance(value, float):
        raise TypeError("use Decimal or str for money, not float")
    return Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


def format_money(amount, currency: str = "USD") -> str:
    symbol = _SYMBOLS.get(currency)
    if symbol is None:
        raise ValueError(f"unsupported currency: {currency}")
    amount = to_money(amount)
    sign = "-" if amount < 0 else ""
    digits = f"{abs(amount):,.2f}"
    if currency == "EUR":
        digits = digits.replace(",", "_").replace(".", ",").replace("_", ".")
        return f"{sign}{digits} {symbol}"
    return f"{sign}{symbol}{digits}"
