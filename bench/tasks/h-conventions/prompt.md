Add two operations to `Inventory`:

- `adjust(sku, delta, reason)`: a manual correction after a stock count. `delta` is a non-zero int and may be negative, but stock can't go below zero. `reason` says why.
- `transfer(sku, quantity, destination)`: moves units to another `Inventory`. Either both inventories change or neither does.
