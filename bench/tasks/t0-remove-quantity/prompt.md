Bug report: `Cart.remove(sku, quantity)` misbehaves.

- `cart.remove("TEA", 2)` on a line with 5 units leaves 4 units instead of 3.
- An item whose quantity drops to zero stays in the cart with quantity 0.

Expected: it removes exactly `quantity` units, deletes the line when it reaches zero, and raises `ValueError` when `quantity` is zero, negative, or more than the units in the cart. `remove(sku)` with no quantity still removes the whole line. Please fix it.
