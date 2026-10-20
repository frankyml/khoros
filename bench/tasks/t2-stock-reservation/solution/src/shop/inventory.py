from typing import Dict, Optional


class OutOfStock(Exception):
    def __init__(self, sku: str, requested: int, available: int):
        super().__init__(f"{sku}: requested {requested}, only {available} available")
        self.sku = sku
        self.requested = requested
        self.available = available


def _require_positive(quantity: int) -> None:
    if quantity <= 0:
        raise ValueError("quantity must be positive")


class Inventory:
    def __init__(self, stock: Optional[Dict[str, int]] = None):
        self._on_hand: Dict[str, int] = {}
        self._reserved: Dict[str, int] = {}
        for sku, quantity in (stock or {}).items():
            self.restock(sku, quantity)

    def on_hand(self, sku: str) -> int:
        return self._on_hand.get(sku, 0)

    def reserved(self, sku: str) -> int:
        return self._reserved.get(sku, 0)

    def available(self, sku: str) -> int:
        return self.on_hand(sku) - self.reserved(sku)

    def restock(self, sku: str, quantity: int) -> None:
        _require_positive(quantity)
        self._on_hand[sku] = self.on_hand(sku) + quantity

    def reserve(self, sku: str, quantity: int) -> None:
        _require_positive(quantity)
        have = self.available(sku)
        if quantity > have:
            raise OutOfStock(sku, quantity, have)
        self._reserved[sku] = self.reserved(sku) + quantity

    def release(self, sku: str, quantity: int) -> None:
        _require_positive(quantity)
        if quantity > self.reserved(sku):
            raise ValueError(f"cannot release {quantity}, only {self.reserved(sku)} reserved")
        self._reserved[sku] = self.reserved(sku) - quantity

    def take(self, sku: str, quantity: int, reserved: bool = False) -> None:
        _require_positive(quantity)
        if reserved:
            if quantity > self.reserved(sku):
                raise ValueError(f"cannot take {quantity}, only {self.reserved(sku)} reserved")
            self._reserved[sku] = self.reserved(sku) - quantity
        else:
            have = self.available(sku)
            if quantity > have:
                raise OutOfStock(sku, quantity, have)
        self._on_hand[sku] = self.on_hand(sku) - quantity
