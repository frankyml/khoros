Add a percentage discount to `shop/pricing.py`: `PercentOff(percent)`.

- `percent` may be an int, str or Decimal; it must satisfy `0 < percent <= 100`, otherwise raise `ValueError`.
- `amount_off(subtotal)` returns `percent`% of the subtotal, rounded half-up to the cent.
- It must work with `Cart.apply_discount` and stack with `FixedAmountOff` (the cart already caps the total discount at the subtotal).
