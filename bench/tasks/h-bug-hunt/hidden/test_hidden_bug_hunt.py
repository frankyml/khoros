import sys
import unittest
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from shop.cart import Cart
from shop.inventory import Inventory, OutOfStock
from shop.models import LineItem, Product
from shop.money import format_money, to_money

D = Decimal


class TestGbpFormatting(unittest.TestCase):
    def test_thousands_separator(self):
        self.assertEqual(format_money(D("1234.5"), "GBP"), "£1,234.50")
        self.assertEqual(format_money(D("1000000"), "GBP"), "£1,000,000.00")

    def test_unchanged(self):
        self.assertEqual(format_money(D("3"), "GBP"), "£3.00")
        self.assertEqual(format_money(D("1234.5")), "$1,234.50")
        with self.assertRaises(ValueError):
            format_money(1, "XYZ")


class TestSoldOutStock(unittest.TestCase):
    def test_zero_counts_load(self):
        inv = Inventory({"SOLD": 0, "TEA": 2})
        self.assertEqual(inv.available("SOLD"), 0)
        self.assertEqual(inv.available("TEA"), 2)
        with self.assertRaises(OutOfStock):
            inv.take("SOLD", 1)
        inv.restock("SOLD", 3)
        self.assertEqual(inv.available("SOLD"), 3)

    def test_still_rejects_bad_quantities(self):
        with self.assertRaises(ValueError):
            Inventory({"TEA": -1})
        with self.assertRaises(ValueError):
            Inventory().restock("TEA", 0)


class TestHalfUpRounding(unittest.TestCase):
    def test_to_money(self):
        self.assertEqual(to_money("0.125"), D("0.13"))
        self.assertEqual(to_money(D("2.665")), D("2.67"))
        self.assertEqual(to_money(D("2.675")), D("2.68"))

    def test_reported_cart(self):
        cart = Cart()
        cart.add(Product("STK", "Sticker", D("0.25")))
        self.assertEqual(cart.tax(), D("0.03"))
        self.assertEqual(cart.total(), D("0.28"))

    def test_line_total(self):
        self.assertEqual(LineItem(Product("X", "x", D("0.125")), 1).total, D("0.13"))


if __name__ == "__main__":
    unittest.main()
