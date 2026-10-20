import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional, Tuple

from .cart import Cart
from .inventory import Inventory, OutOfStock
from .money import to_money


@dataclass(frozen=True)
class OrderLine:
    sku: str
    quantity: int
    unit_price: Decimal
    total: Decimal


@dataclass(frozen=True)
class Order:
    order_id: str
    lines: Tuple[OrderLine, ...]
    subtotal: Decimal
    discount: Decimal
    tax: Decimal
    total: Decimal


def checkout(cart: Cart, inventory: Inventory, order_id: Optional[str] = None) -> Order:
    """Turn the cart into an order, taking stock all-or-nothing, then empty the cart."""
    items = cart.items
    if not items:
        raise ValueError("cannot check out an empty cart")
    # Check everything first so a shortage leaves stock untouched.
    for item in items:
        available = inventory.available(item.product.sku)
        if item.quantity > available:
            raise OutOfStock(item.product.sku, item.quantity, available)
    for item in items:
        inventory.take(item.product.sku, item.quantity)

    subtotal = cart.subtotal()
    discount = cart.discount_total()
    taxable = sum((item.total for item in items if item.product.taxable), Decimal("0"))
    tax = to_money(taxable * cart.tax_rate)
    order = Order(
        order_id=order_id or uuid.uuid4().hex[:12],
        lines=tuple(
            OrderLine(item.product.sku, item.quantity, item.product.price, item.total) for item in items
        ),
        subtotal=subtotal,
        discount=discount,
        tax=tax,
        total=subtotal - discount + tax,
    )
    cart.clear()
    return order
