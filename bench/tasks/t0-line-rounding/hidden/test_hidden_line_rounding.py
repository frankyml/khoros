import sys
import unittest
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from shop.cart import Cart
from shop.models import LineItem, Product


class TestLineRounding(unittest.TestCase):
    def test_half_up_on_line_total(self):
        item = LineItem(Product("X", "x", Decimal("1.005")), 3)
        self.assertEqual(item.total, Decimal("3.02"))
        self.assertIsInstance(item.total, Decimal)

    def test_classic_float_trap(self):
        self.assertEqual(LineItem(Product("Y", "y", Decimal("2.675")), 1).total, Decimal("2.68"))

    def test_subtotal_uses_exact_lines(self):
        cart = Cart()
        cart.add(Product("X", "x", Decimal("1.005")), 3)
        cart.add(Product("Y", "y", Decimal("0.125")), 1)
        self.assertEqual(cart.subtotal(), Decimal("3.15"))


if __name__ == "__main__":
    unittest.main()
