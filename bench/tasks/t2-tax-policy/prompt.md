Refactor tax calculation out of `Cart` into pluggable policies, in a new module `shop/tax.py`:

- `TaxPolicy`: base class with `tax_for(self, items, discount_total) -> Decimal`, where `items` is the cart's list of `LineItem`s and `discount_total` is the cart's total discount.
- `FlatRateTax(rate)`: reproduces today's behaviour exactly (taxable lines only, discount spread proportionally over all lines, rounded half-up to the cent).
- `ExemptTax()`: always returns `Decimal("0.00")`.

`Cart` changes:
- New keyword argument `tax_policy`, stored as `cart.tax_policy`. `Cart.tax()` must delegate to it.
- With neither argument, the default is `FlatRateTax(Decimal("0.10"))`.
- `Cart(tax_rate=...)` must keep working (equivalent to `FlatRateTax(tax_rate)`). Passing both `tax_rate` and `tax_policy` raises `TypeError`.

Behaviour must not change for existing callers, and `Cart` should no longer contain tax arithmetic.
