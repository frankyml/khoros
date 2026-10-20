Add returns and refunds in a new module `shop/returns.py`.

## Order lines need to know whether they were taxable

Add a `taxable: bool = True` field to `OrderLine` (keep it the last field so existing code keeps working), filled from the product at checkout.

## `ReturnLedger(order)`

Tracks returns against one `Order`.

**What each line is worth.** Spread the order's `discount` across all its lines in proportion to their line totals, then spread the order's `tax` across the taxable lines in proportion to (line total − that line's discount share). Non-taxable lines get no tax. Each spread uses the largest-remainder method in whole cents: round every share down to the cent, then give the leftover cents one at a time to the lines with the largest discarded fractions (ties go to the alphabetically smaller sku). A line's **value** is `line total − discount share + tax share`. The values of all lines add up exactly to `order.total`.

- `ledger.line_value(sku) -> Decimal`: that value.
- `ledger.returned(sku) -> int`: units of that sku returned so far.
- `ledger.refund_for(sku, quantity) -> Decimal`: what returning `quantity` more units would refund, without changing anything. With `Q` units bought and `r` already returned, define `amount(k) = line_value × k / Q` rounded half-up to the cent; the refund is `amount(r + quantity) − amount(r)`. This way partial returns always add up exactly to the line's value.
- `ledger.process(return_id, items, inventory) -> Refund`: `items` maps sku → quantity. Refunds each sku as `refund_for` would, records the return, and restocks the units in `inventory`. It validates everything before changing anything.
  - Calling it again with the same `return_id` and the same `items` returns the original `Refund` and changes nothing. The same `return_id` with different `items` raises `ValueError`.
- `ledger.refunded_total -> Decimal`: total refunded so far (`0.00` initially).

`Refund` is a dataclass with `return_id`, `lines` (dict sku → refunded Decimal, only the skus in this return) and `total` (sum of `lines`).

Errors (from `refund_for` and `process`): a sku not in the order raises `KeyError`; a quantity <= 0 or more than the units still returnable raises `ValueError`.
