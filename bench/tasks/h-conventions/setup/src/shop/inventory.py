from typing import Dict, Optional

from . import events
from .errors import InvalidQuantity, OutOfStock

__all__ = ["Inventory", "OutOfStock"]


def _check_quantity(quantity) -> None:
    if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity <= 0:
        raise InvalidQuantity(f"quantity must be a positive int, got {quantity!r}")


class Inventory:
    def __init__(self, stock: Optional[Dict[str, int]] = None):
        self._on_hand: Dict[str, int] = {}
        for sku, quantity in (stock or {}).items():
            self.restock(sku, quantity)

    def available(self, sku: str) -> int:
        return self._on_hand.get(sku, 0)

    def restock(self, sku: str, quantity: int) -> None:
        _check_quantity(quantity)
        self._on_hand[sku] = self.available(sku) + quantity
        events.emit("stock.restocked", sku=sku, quantity=quantity, on_hand=self._on_hand[sku])

    def take(self, sku: str, quantity: int) -> None:
        _check_quantity(quantity)
        have = self.available(sku)
        if quantity > have:
            raise OutOfStock(sku, quantity, have)
        self._on_hand[sku] = have - quantity
        events.emit("stock.taken", sku=sku, quantity=quantity, on_hand=self._on_hand[sku])
