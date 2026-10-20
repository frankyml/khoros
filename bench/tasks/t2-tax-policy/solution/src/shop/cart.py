from decimal import Decimal
from typing import Dict, List, Optional

from .models import LineItem, Product
from .money import to_money
from .pricing import Discount
from .tax import FlatRateTax, TaxPolicy

DEFAULT_TAX_RATE = Decimal("0.10")
ZERO = Decimal("0")


class Cart:
    def __init__(self, tax_rate: Optional[Decimal] = None, tax_policy: Optional[TaxPolicy] = None):
        if tax_rate is not None and tax_policy is not None:
            raise TypeError("pass tax_rate or tax_policy, not both")
        if tax_policy is None:
            tax_policy = FlatRateTax(DEFAULT_TAX_RATE if tax_rate is None else tax_rate)
        self.tax_policy = tax_policy
        self._items: Dict[str, LineItem] = {}
        self._discounts: List[Discount] = []

    @property
    def items(self) -> List[LineItem]:
        return list(self._items.values())

    def add(self, product: Product, quantity: int = 1) -> None:
        if quantity <= 0:
            raise ValueError("quantity must be positive")
        item = self._items.get(product.sku)
        if item is None:
            self._items[product.sku] = LineItem(product, quantity)
        else:
            item.quantity += quantity

    def remove(self, sku: str, quantity: Optional[int] = None) -> None:
        """Remove `quantity` units of `sku`, or every unit when quantity is None."""
        item = self._items.get(sku)
        if item is None:
            raise KeyError(sku)
        if quantity is not None and (quantity <= 0 or quantity > item.quantity):
            raise ValueError(f"cannot remove {quantity} of {item.quantity} units")
        if quantity is None or quantity == item.quantity:
            del self._items[sku]
        else:
            item.quantity -= quantity

    def apply_discount(self, discount: Discount) -> None:
        self._discounts.append(discount)

    def clear(self) -> None:
        self._items.clear()
        self._discounts.clear()

    def subtotal(self) -> Decimal:
        return to_money(sum((item.total for item in self._items.values()), ZERO))

    def discount_total(self) -> Decimal:
        subtotal = self.subtotal()
        off = sum((d.amount_off(subtotal) for d in self._discounts), ZERO)
        return to_money(min(off, subtotal))

    def tax(self) -> Decimal:
        return self.tax_policy.tax_for(self.items, self.discount_total())

    def total(self) -> Decimal:
        return self.subtotal() - self.discount_total() + self.tax()
