from dataclasses import dataclass
from decimal import Decimal

from .money import to_money


@dataclass(frozen=True)
class Product:
    sku: str
    name: str
    price: Decimal
    taxable: bool = True


@dataclass
class LineItem:
    product: Product
    quantity: int

    @property
    def total(self) -> Decimal:
        return to_money(self.product.price * self.quantity)
