from dataclasses import dataclass
from decimal import ROUND_DOWN, Decimal
from typing import Dict, Tuple

from .checkout import Order
from .inventory import Inventory
from .money import CENT, to_money

ZERO = Decimal("0")


def _allocate(amount: Decimal, weights: Dict[str, Decimal]) -> Dict[str, Decimal]:
    """Split `amount` in cents proportionally to `weights` (largest remainder, ties to the smaller key)."""
    total = sum(weights.values(), ZERO)
    if amount == 0 or total <= 0:
        return {key: Decimal("0.00") for key in weights}
    raw = {key: amount * w / total for key, w in weights.items()}
    parts = {key: value.quantize(CENT, rounding=ROUND_DOWN) for key, value in raw.items()}
    leftover = int((amount - sum(parts.values(), ZERO)) / CENT)
    for key in sorted(weights, key=lambda k: (-(raw[k] - parts[k]), k))[:leftover]:
        parts[key] += CENT
    return parts


@dataclass(frozen=True)
class Refund:
    return_id: str
    lines: Dict[str, Decimal]
    total: Decimal


class ReturnLedger:
    def __init__(self, order: Order):
        self.order = order
        self._lines = {line.sku: line for line in order.lines}
        discount = _allocate(order.discount, {sku: line.total for sku, line in self._lines.items()})
        taxable = {sku: line.total - discount[sku] for sku, line in self._lines.items() if line.taxable}
        tax = _allocate(order.tax, taxable)
        self._values = {sku: line.total - discount[sku] + tax.get(sku, ZERO) for sku, line in self._lines.items()}
        self._returned = {sku: 0 for sku in self._lines}
        self._processed: Dict[str, Tuple[Dict[str, int], Refund]] = {}

    def line_value(self, sku: str) -> Decimal:
        return self._values[sku]

    def returned(self, sku: str) -> int:
        if sku not in self._lines:
            raise KeyError(sku)
        return self._returned[sku]

    def _amount(self, sku: str, units: int) -> Decimal:
        return to_money(self._values[sku] * units / self._lines[sku].quantity)

    def refund_for(self, sku: str, quantity: int) -> Decimal:
        if sku not in self._lines:
            raise KeyError(sku)
        already = self._returned[sku]
        if quantity <= 0 or quantity > self._lines[sku].quantity - already:
            raise ValueError(f"cannot return {quantity} of {sku}")
        return self._amount(sku, already + quantity) - self._amount(sku, already)

    def process(self, return_id: str, items: Dict[str, int], inventory: Inventory) -> Refund:
        if return_id in self._processed:
            seen_items, refund = self._processed[return_id]
            if seen_items != dict(items):
                raise ValueError(f"return {return_id} was already processed with different items")
            return refund
        lines = {sku: self.refund_for(sku, quantity) for sku, quantity in items.items()}
        for sku, quantity in items.items():
            self._returned[sku] += quantity
            inventory.restock(sku, quantity)
        refund = Refund(return_id, lines, sum(lines.values(), Decimal("0.00")))
        self._processed[return_id] = (dict(items), refund)
        return refund

    @property
    def refunded_total(self) -> Decimal:
        return sum((refund.total for _, refund in self._processed.values()), Decimal("0.00"))
