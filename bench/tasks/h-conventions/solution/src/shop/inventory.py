from typing import Dict, Optional

from . import events
from .errors import InvalidArgument, InvalidQuantity, OutOfStock

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

    def adjust(self, sku: str, delta: int, reason: str) -> None:
        """Manual correction after a stock count; `delta` is a non-zero int and may be negative."""
        if isinstance(delta, bool) or not isinstance(delta, int) or delta == 0:
            raise InvalidQuantity(f"delta must be a non-zero int, got {delta!r}")
        if not isinstance(reason, str) or not reason.strip():
            raise InvalidArgument("an adjustment needs a reason")
        have = self.available(sku)
        if have + delta < 0:
            raise OutOfStock(sku, -delta, have)
        self._on_hand[sku] = have + delta
        events.emit("stock.adjusted", sku=sku, delta=delta, reason=reason, on_hand=self._on_hand[sku])

    def transfer(self, sku: str, quantity: int, destination: "Inventory") -> None:
        """Move units to another inventory; both change or neither does."""
        _check_quantity(quantity)
        if not isinstance(destination, Inventory) or destination is self:
            raise InvalidArgument("destination must be another Inventory")
        have = self.available(sku)
        if quantity > have:
            raise OutOfStock(sku, quantity, have)
        self._on_hand[sku] = have - quantity
        destination._on_hand[sku] = destination.available(sku) + quantity
        events.emit("stock.transferred", sku=sku, quantity=quantity, on_hand=self._on_hand[sku])
        events.emit("stock.transferred", sku=sku, quantity=quantity, on_hand=destination._on_hand[sku])
