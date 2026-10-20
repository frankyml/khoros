import sys
import unittest
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from shop.cart import Cart
from shop.models import Product
from shop.pricing import FixedAmountOff, PercentOff


class TestPercentOff(unittest.TestCase):
    def test_amounts(self):
        self.assertEqual(PercentOff(15).amount_off(Decimal("40.00")), Decimal("6.00"))
        self.assertEqual(PercentOff("12.5").amount_off(Decimal("9.99")), Decimal("1.25"))
        self.assertEqual(PercentOff(Decimal("100")).amount_off(Decimal("7.30")), Decimal("7.30"))

    def test_validation(self):
        for bad in (0, -5, 101, "100.01"):
            with self.assertRaises(ValueError, msg=bad):
                PercentOff(bad)

    def test_in_cart_and_stacking(self):
        cart = Cart()
        cart.add(Product("BOOK", "Book", Decimal("20.00"), taxable=False), 2)
        cart.apply_discount(PercentOff(10))
        self.assertEqual(cart.discount_total(), Decimal("4.00"))
        cart.apply_discount(FixedAmountOff("50"))
        self.assertEqual(cart.discount_total(), Decimal("40.00"))
        self.assertEqual(cart.total(), Decimal("0.00"))


if __name__ == "__main__":
    unittest.main()
