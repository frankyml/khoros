import sys
import unittest
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from shop.cart import Cart
from shop.models import Product
from shop.pricing import FixedAmountOff

TEA = Product("TEA", "Green tea", Decimal("4.50"))
BOOK = Product("BOOK", "Book", Decimal("20.00"), taxable=False)


class TestCart(unittest.TestCase):
    def test_add_merges_lines(self):
        cart = Cart()
        cart.add(TEA)
        cart.add(TEA, 2)
        self.assertEqual(len(cart.items), 1)
        self.assertEqual(cart.items[0].quantity, 3)

    def test_add_rejects_non_positive(self):
        with self.assertRaises(ValueError):
            Cart().add(TEA, 0)

    def test_remove_all_units(self):
        cart = Cart()
        cart.add(TEA, 3)
        cart.remove("TEA")
        self.assertEqual(cart.items, [])

    def test_remove_unknown_sku(self):
        with self.assertRaises(KeyError):
            Cart().remove("NOPE")

    def test_totals_without_discount(self):
        cart = Cart()
        cart.add(TEA, 2)
        cart.add(BOOK)
        self.assertEqual(cart.subtotal(), Decimal("29.00"))
        self.assertEqual(cart.tax(), Decimal("0.90"))
        self.assertEqual(cart.total(), Decimal("29.90"))

    def test_discount_reduces_taxable_base_proportionally(self):
        cart = Cart()
        cart.add(TEA, 2)
        cart.add(BOOK)
        cart.apply_discount(FixedAmountOff("5"))
        self.assertEqual(cart.discount_total(), Decimal("5.00"))
        # 9.00 taxable of 29.00; discount share 5 * 9/29 = 1.5517...
        self.assertEqual(cart.tax(), Decimal("0.74"))
        self.assertEqual(cart.total(), Decimal("24.74"))

    def test_discount_capped_at_subtotal(self):
        cart = Cart()
        cart.add(TEA)
        cart.apply_discount(FixedAmountOff("100"))
        self.assertEqual(cart.discount_total(), Decimal("4.50"))
        self.assertEqual(cart.total(), Decimal("0.00"))


if __name__ == "__main__":
    unittest.main()
