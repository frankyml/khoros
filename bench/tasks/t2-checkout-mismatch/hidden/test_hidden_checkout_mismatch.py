import sys
import unittest
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from shop.cart import Cart
from shop.checkout import checkout
from shop.inventory import Inventory
from shop.models import Product
from shop.pricing import FixedAmountOff

TEA = Product("TEA", "Green tea", Decimal("4.50"))
BOOK = Product("BOOK", "Book", Decimal("20.00"), taxable=False)
MUG = Product("MUG", "Mug", Decimal("9.99"))


def snapshot(cart):
    return cart.subtotal(), cart.discount_total(), cart.tax(), cart.total()


class TestCheckoutMatchesCart(unittest.TestCase):
    def assert_order_matches(self, cart):
        expected = snapshot(cart)
        order = checkout(cart, Inventory({"TEA": 50, "BOOK": 50, "MUG": 50}))
        self.assertEqual((order.subtotal, order.discount, order.tax, order.total), expected)

    def test_reported_example(self):
        cart = Cart()
        cart.add(TEA, 2)
        cart.add(BOOK)
        cart.apply_discount(FixedAmountOff("5"))
        self.assertEqual(cart.total(), Decimal("24.74"))
        self.assert_order_matches(cart)

    def test_all_taxable_with_coupon(self):
        cart = Cart(tax_rate=Decimal("0.21"))
        cart.add(TEA, 3)
        cart.add(MUG, 2)
        cart.apply_discount(FixedAmountOff("7.77"))
        self.assert_order_matches(cart)

    def test_coupon_larger_than_cart(self):
        cart = Cart()
        cart.add(MUG)
        cart.apply_discount(FixedAmountOff("100"))
        self.assert_order_matches(cart)

    def test_no_coupon(self):
        cart = Cart()
        cart.add(TEA)
        cart.add(BOOK, 2)
        self.assert_order_matches(cart)


if __name__ == "__main__":
    unittest.main()
