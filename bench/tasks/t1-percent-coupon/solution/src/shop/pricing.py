from decimal import Decimal

from .money import to_money


class Discount:
    """A discount computes the amount it takes off a cart subtotal."""

    def amount_off(self, subtotal: Decimal) -> Decimal:
        raise NotImplementedError


class FixedAmountOff(Discount):
    def __init__(self, amount):
        amount = to_money(amount)
        if amount <= 0:
            raise ValueError("amount must be positive")
        self.amount = amount

    def amount_off(self, subtotal: Decimal) -> Decimal:
        return min(self.amount, subtotal)


class PercentOff(Discount):
    def __init__(self, percent):
        percent = Decimal(str(percent))
        if not 0 < percent <= 100:
            raise ValueError("percent must be in (0, 100]")
        self.percent = percent

    def amount_off(self, subtotal: Decimal) -> Decimal:
        return to_money(subtotal * self.percent / 100)
