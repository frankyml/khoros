from typing import Dict, Optional


class OutOfStock(Exception):
    def __init__(self, sku: str, requested: int, available: int):
        super().__init__(f"{sku}: requested {requested}, only {available} available")
        self.sku = sku
        self.requested = requested
        self.available = available


class Inventory:
    def __init__(self, stock: Optional[Dict[str, int]] = None):
        self._on_hand: Dict[str, int] = {}
        for sku, quantity in (stock or {}).items():
            self.restock(sku, quantity)

    def available(self, sku: str) -> int:
        return self._on_hand.get(sku, 0)

    def restock(self, sku: str, quantity: int) -> None:
        if quantity <= 0:
            raise ValueError("quantity must be positive")
        self._on_hand[sku] = self.available(sku) + quantity

    def take(self, sku: str, quantity: int) -> None:
        if quantity <= 0:
            raise ValueError("quantity must be positive")
        have = self.available(sku)
        if quantity > have:
            raise OutOfStock(sku, quantity, have)
        self._on_hand[sku] = have - quantity
