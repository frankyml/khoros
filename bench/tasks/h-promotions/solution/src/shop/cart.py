from decimal import Decimal
from typing import Dict, List, Optional

from .models import LineItem, Product
from .money import to_money
from .pricing import Discount
from .promotions import Promotion, PromotionResult, apply_promotions

DEFAULT_TAX_RATE = Decimal("0.10")
ZERO = Decimal("0")


class Cart:
    def __init__(self, tax_rate: Decimal = DEFAULT_TAX_RATE):
        self.tax_rate = Decimal(tax_rate)
        self._items: Dict[str, LineItem] = {}
        self._discounts: List[Discount] = []
        self._promotions: List[Promotion] = []

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

    def set_promotions(self, promotions: List[Promotion]) -> None:
        self._promotions = list(promotions)

    def promotion_result(self) -> PromotionResult:
        return apply_promotions(self.items, self._promotions)

    def clear(self) -> None:
        self._items.clear()
        self._discounts.clear()
        self._promotions.clear()

    def subtotal(self) -> Decimal:
        return to_money(sum((item.total for item in self._items.values()), ZERO))

    def _coupon_total(self, promotion_total: Decimal) -> Decimal:
        remaining = self.subtotal() - promotion_total
        off = sum((d.amount_off(remaining) for d in self._discounts), ZERO)
        return to_money(min(off, remaining))

    def discount_total(self) -> Decimal:
        promotion_total = self.promotion_result().total_discount
        return to_money(promotion_total + self._coupon_total(promotion_total))

    def tax(self) -> Decimal:
        """Tax on taxable lines after their promotion discounts, then coupons spread proportionally."""
        result = self.promotion_result()
        remaining = self.subtotal() - result.total_discount
        if remaining == 0:
            return to_money(0)
        taxable = sum(
            (item.total - result.line_discounts[item.product.sku] for item in self._items.values() if item.product.taxable),
            ZERO,
        )
        coupons = self._coupon_total(result.total_discount)
        return to_money((taxable - coupons * taxable / remaining) * self.tax_rate)

    def total(self) -> Decimal:
        return self.subtotal() - self.discount_total() + self.tax()
