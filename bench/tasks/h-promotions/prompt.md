Add a promotions engine in a new module `shop/promotions.py`, and wire it into `Cart`.

## Promotion types

- `BuyXGetY(sku, buy, get)`: for every complete group of `buy + get` units of `sku`, `get` units are free. Example: buy 2 get 1 with 7 units gives 2 free units. `buy` and `get` must both be >= 1, otherwise `ValueError`.
- `Bundle(skus, price)`: each complete set of one unit of every sku in `skus` costs `price` instead of the sum of their unit prices. The number of sets is the smallest available quantity among the skus. `skus` must contain at least 2 distinct skus and `price` must be > 0, otherwise `ValueError`. If the set would not be cheaper (`price` >= sum of unit prices) the bundle does nothing.
- `Threshold(min_subtotal, percent)`: `percent`% off the amount left after item promotions, if that amount is >= `min_subtotal`. Rounded half-up to the cent. `percent` must satisfy `0 < percent <= 100` and `min_subtotal >= 0`, otherwise `ValueError`.

## `apply_promotions(items, promotions) -> PromotionResult`

`items` is a list of `LineItem`. `PromotionResult` has `total_discount` (Decimal) and `line_discounts` (dict sku -> Decimal with an entry, `0.00` when none, for every sku in `items`).

1. Item promotions (`BuyXGetY`, `Bundle`) run in list order. Each unit can be used by at most one item promotion: units a promotion uses (all `buy + get` units of each group, every unit in each bundle set) are no longer available to later promotions. A bundle that does nothing uses no units.
2. Then at most one `Threshold` applies: of those whose `min_subtotal` is met, the one giving the largest discount (first in the list on a tie).
3. Allocation to lines:
   - A `BuyXGetY` discount (free units × unit price, rounded half-up to the cent) belongs to its sku.
   - A bundle's total discount (sets × saving per set, rounded half-up to the cent) is split across its skus in proportion to their unit prices.
   - The threshold discount is split across all lines in proportion to each line's remaining amount (line total minus its item-promotion discounts).
   - Every split uses the largest-remainder method in whole cents: give each line its share rounded down to the cent, then hand out the leftover cents one at a time to the lines with the largest discarded fractions (ties go to the alphabetically smaller sku). The parts always sum exactly to the amount split.

`sum(line_discounts.values()) == total_discount` must always hold.

## Cart integration

- `cart.set_promotions(promotions)` replaces the cart's promotions (none by default). `cart.clear()` also removes them.
- `cart.promotion_result()` returns `apply_promotions(cart.items, <the cart's promotions>)`.
- `cart.discount_total()` = promotion discount + coupon discount, where coupons (existing `Discount` objects) are applied to `subtotal - promotion discount` and capped at that amount.
- `cart.tax()`: start from the taxable lines' totals minus their promotion line discounts, then spread the coupon discount proportionally over the amount left after promotions (as the cart already does with coupons today), rounded half-up. With no promotions, every cart total must stay exactly as it is today.
