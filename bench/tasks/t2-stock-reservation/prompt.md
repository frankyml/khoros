We oversell because stock is only checked at checkout. Add stock reservations.

`Inventory` (shop/inventory.py):
- `on_hand(sku) -> int`: physical units.
- `reserved(sku) -> int`: units reserved by carts.
- `available(sku)` now means `on_hand - reserved`.
- `reserve(sku, quantity)`: raises `ValueError` if quantity <= 0, `OutOfStock` if quantity > available.
- `release(sku, quantity)`: raises `ValueError` if quantity <= 0 or more than is reserved.
- `take(sku, quantity, reserved=False)`: with `reserved=True`, consumes previously reserved units (reduces both on_hand and reserved) and raises `ValueError` if quantity > reserved. Without it, it behaves as today, against `available`.

`Cart` (shop/cart.py):
- New optional keyword argument `inventory`, stored as `cart.inventory`.
- When set: `add` reserves the units first (if that raises `OutOfStock`, the cart is unchanged); `remove` releases the removed units; `clear()` releases everything still in the cart.
- When not set, the cart behaves exactly as today.

`checkout(cart, inventory)` (shop/checkout.py):
- If `cart.inventory` is the same inventory, consume the reservations (`take(..., reserved=True)`) and empty the cart without releasing anything.
- If `cart.inventory` is a different inventory, raise `ValueError`.
- Carts without an inventory keep today's behaviour.
