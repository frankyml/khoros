Add order history: orders should be persisted to a JSON file and browsable from the CLI.

1. New module `shop/orders.py`:
   - `order_to_dict(order) -> dict`: JSON-serialisable; every Decimal is stored as a string with two decimals (e.g. `"24.74"`). Keys mirror the `Order`/`OrderLine` field names.
   - `order_from_dict(data) -> Order`: the exact inverse, so `order_from_dict(order_to_dict(o)) == o`.
   - `OrderRepository(path)`: stores orders in a JSON file at `path` (a missing file means no orders yet).
     - `save(order)`: persists immediately; raises `ValueError` if an order with that id is already stored.
     - `get(order_id) -> Order`: raises `KeyError` if unknown.
     - `list() -> list of Order`, in the order they were saved.
     - A new `OrderRepository` on the same path sees previously saved orders.
2. `checkout(cart, inventory, order_id=None, repository=None)`: when a repository is given, save the new order to it.
3. CLI: `python -m shop orders --db PATH`
   - Prints one line per order: `<order_id> <total>` with the total rendered by `format_money`, e.g. `o1 $24.74`. No orders: no output, exit code 0.
   - `--show ORDER_ID` instead prints the receipt in the same format as `python -m shop demo` (one `<qty> x <sku> @ <unit price> = <line total>` line per item, then `TOTAL <total>`). An unknown id prints an error to stderr and exits with code 1.
