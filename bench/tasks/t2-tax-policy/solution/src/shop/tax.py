from decimal import Decimal
from typing import List

from .models import LineItem
from .money import to_money

ZERO = Decimal("0")


class TaxPolicy:
    def tax_for(self, items: List[LineItem], discount_total: Decimal) -> Decimal:
        raise NotImplementedError


class FlatRateTax(TaxPolicy):
    """Taxes taxable lines at a flat rate, after spreading discounts proportionally over all lines."""

    def __init__(self, rate):
        self.rate = Decimal(rate)

    def tax_for(self, items: List[LineItem], discount_total: Decimal) -> Decimal:
        subtotal = sum((item.total for item in items), ZERO)
        if subtotal == 0:
            return to_money(0)
        taxable = sum((item.total for item in items if item.product.taxable), ZERO)
        taxable_after_discount = taxable - discount_total * taxable / subtotal
        return to_money(taxable_after_discount * self.rate)


class ExemptTax(TaxPolicy):
    def tax_for(self, items: List[LineItem], discount_total: Decimal) -> Decimal:
        return to_money(0)
