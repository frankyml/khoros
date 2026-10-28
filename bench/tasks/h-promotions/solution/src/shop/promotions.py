from dataclasses import dataclass
from decimal import ROUND_DOWN, Decimal
from typing import Dict, List, Sequence

from .models import LineItem
from .money import CENT, to_money

ZERO = Decimal("0")


def allocate(amount: Decimal, weights: Dict[str, Decimal]) -> Dict[str, Decimal]:
    """Split `amount` in cents proportionally to `weights` (largest remainder, ties to the smaller key)."""
    total = sum(weights.values(), ZERO)
    if amount == 0 or total <= 0:
        return {key: Decimal("0.00") for key in weights}
    raw = {key: amount * w / total for key, w in weights.items()}
    parts = {key: value.quantize(CENT, rounding=ROUND_DOWN) for key, value in raw.items()}
    leftover = int((amount - sum(parts.values(), ZERO)) / CENT)
    for key in sorted(weights, key=lambda k: (-(raw[k] - parts[k]), k))[:leftover]:
        parts[key] += CENT
    return parts


class Promotion:
    pass


class BuyXGetY(Promotion):
    def __init__(self, sku: str, buy: int, get: int):
        if buy < 1 or get < 1:
            raise ValueError("buy and get must be at least 1")
        self.sku, self.buy, self.get = sku, buy, get


class Bundle(Promotion):
    def __init__(self, skus: Sequence[str], price):
        skus = list(skus)
        if len(skus) < 2 or len(set(skus)) != len(skus):
            raise ValueError("a bundle needs at least two distinct skus")
        price = to_money(price)
        if price <= 0:
            raise ValueError("bundle price must be positive")
        self.skus, self.price = skus, price


class Threshold(Promotion):
    def __init__(self, min_subtotal, percent):
        min_subtotal = to_money(min_subtotal)
        percent = Decimal(str(percent))
        if min_subtotal < 0 or not 0 < percent <= 100:
            raise ValueError("invalid threshold")
        self.min_subtotal, self.percent = min_subtotal, percent


@dataclass
class PromotionResult:
    total_discount: Decimal
    line_discounts: Dict[str, Decimal]


def apply_promotions(items: List[LineItem], promotions: Sequence[Promotion]) -> PromotionResult:
    lines = {item.product.sku: item for item in items}
    unused = {sku: item.quantity for sku, item in lines.items()}
    discounts = {sku: Decimal("0.00") for sku in lines}

    for promo in promotions:
        if isinstance(promo, BuyXGetY):
            item = lines.get(promo.sku)
            if item is None:
                continue
            groups = unused[promo.sku] // (promo.buy + promo.get)
            if groups == 0:
                continue
            unused[promo.sku] -= groups * (promo.buy + promo.get)
            discounts[promo.sku] += to_money(item.product.price * groups * promo.get)
        elif isinstance(promo, Bundle):
            if any(sku not in lines for sku in promo.skus):
                continue
            sets = min(unused[sku] for sku in promo.skus)
            saving = sum((lines[sku].product.price for sku in promo.skus), ZERO) - promo.price
            if sets == 0 or saving <= 0:
                continue
            for sku in promo.skus:
                unused[sku] -= sets
            split = allocate(to_money(saving * sets), {sku: lines[sku].product.price for sku in promo.skus})
            for sku, part in split.items():
                discounts[sku] += part

    subtotal = sum((item.total for item in items), ZERO)
    remaining = subtotal - sum(discounts.values(), ZERO)
    best = None
    for promo in promotions:
        if isinstance(promo, Threshold) and remaining >= promo.min_subtotal:
            amount = to_money(remaining * promo.percent / 100)
            if best is None or amount > best:
                best = amount
    if best:
        split = allocate(best, {sku: lines[sku].total - discounts[sku] for sku in lines})
        for sku, part in split.items():
            discounts[sku] += part
    return PromotionResult(sum(discounts.values(), Decimal("0.00")), discounts)
