import random
import sys
import time
import unittest
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import List

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from shop.checkout import Order, OrderLine
from shop.money import format_money, to_money
from shop.reports import sales_report

D = Decimal


# The implementation as it was before the task: the output contract.
def reference_report(orders: List[Order], top: int = 5) -> str:
    """Plain-text nightly sales report: order totals, then the top SKUs by gross line revenue."""
    lines = ["SALES REPORT"]
    revenue = sum((order.total for order in orders), Decimal("0"))
    lines.append(f"Orders: {len(orders)}")
    lines.append(f"Revenue: {format_money(revenue)}")
    if orders:
        lines.append(f"Average order: {format_money(to_money(revenue / len(orders)))}")

    skus = []
    for order in orders:
        for line in order.lines:
            if line.sku not in skus:
                skus.append(line.sku)

    rows = []
    for sku in skus:
        units = 0
        gross = Decimal("0")
        for order in orders:
            for line in order.lines:
                if line.sku == sku:
                    units += line.quantity
                    gross += line.total
        rows.append((sku, units, gross))

    gross_total = sum((row[2] for row in rows), Decimal("0"))
    rows.sort(key=lambda row: (-row[2], -row[1], row[0]))

    lines.append("")
    lines.append(f"{'SKU':<10}{'UNITS':>8}{'GROSS':>14}{'SHARE':>8}")
    shown = Decimal("0")
    for sku, units, gross in rows[:top]:
        if gross_total:
            share = (gross / gross_total * 100).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
        else:
            share = Decimal("0.0")
        shown += share
        lines.append(f"{sku:<10}{units:>8}{format_money(gross):>14}{share:>7}%")
    rest = rows[top:]
    if rest:
        units = sum(row[1] for row in rest)
        gross = sum((row[2] for row in rest), Decimal("0"))
        lines.append(f"{'OTHER':<10}{units:>8}{format_money(gross):>14}{Decimal(100) - shown:>7}%")
    return "\n".join(lines) + "\n"


def make_orders(seed, n_orders, n_skus, max_lines=3, prices=("0.99", "1.50", "4.50", "9.99", "20.00")):
    rng = random.Random(seed)
    orders = []
    for i in range(n_orders):
        lines = []
        for _ in range(rng.randint(1, max_lines)):
            sku = f"S{rng.randrange(n_skus):03d}"
            qty = rng.randint(1, 4)
            price = D(rng.choice(prices))
            lines.append(OrderLine(sku, qty, price, to_money(price * qty)))
        subtotal = sum((l.total for l in lines), D("0"))
        discount = to_money(subtotal * D(rng.choice(["0", "0.05", "0.1"])))
        tax = to_money((subtotal - discount) * D("0.1"))
        orders.append(Order(f"o{i}", tuple(lines), subtotal, discount, tax, subtotal - discount + tax))
    return orders


class TestIdenticalOutput(unittest.TestCase):
    def assert_same(self, orders, top=5):
        self.assertEqual(sales_report(orders, top), reference_report(orders, top))

    def test_random_inputs(self):
        for seed in range(6):
            orders = make_orders(seed, 400, 40)
            for top in (0, 1, 5, 39, 40, 41, 100):
                with self.subTest(seed=seed, top=top):
                    self.assert_same(orders, top)

    def test_heavy_ties(self):
        orders = make_orders(99, 300, 12, prices=("2.00",))
        for top in (3, 12):
            self.assert_same(orders, top)

    def test_empty(self):
        self.assert_same([])
        self.assert_same([], top=0)

    def test_zero_priced_lines(self):
        line = OrderLine("FREE", 2, D("0"), D("0.00"))
        orders = [Order("z", (line,), D("0"), D("0"), D("0"), D("0"))]
        for top in (0, 1):
            self.assert_same(orders, top)

    def test_default_top(self):
        orders = make_orders(7, 200, 30)
        self.assertEqual(sales_report(orders), reference_report(orders))


class TestSpeed(unittest.TestCase):
    def test_large_input_is_fast(self):
        orders = make_orders(2026, 50000, 1000)
        start = time.perf_counter()
        sales_report(orders, 10)
        elapsed = time.perf_counter() - start
        self.assertLess(elapsed, 1.0, f"report took {elapsed:.2f}s for 50,000 orders")


if __name__ == "__main__":
    unittest.main()
