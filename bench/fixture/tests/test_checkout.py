import sys
import unittest
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from shop.cart import Cart
from shop.checkout import checkout
from shop.inventory import Inventory, OutOfStock
from shop.models import Product

TEA = Product("TEA", "Green tea", Decimal("4.50"))
MUG = Product("MUG", "Mug", Decimal("9.99"))


class TestCheckout(unittest.TestCase):
    def test_checkout_builds_order_and_takes_stock(self):
        cart = Cart()
        cart.add(TEA, 2)
        cart.add(MUG)
        inv = Inventory({"TEA": 5, "MUG": 1})
        expected_total = cart.total()
        order = checkout(cart, inv, order_id="o1")
        self.assertEqual(order.order_id, "o1")
        self.assertEqual(order.total, expected_total)
        self.assertEqual([(l.sku, l.quantity) for l in order.lines], [("TEA", 2), ("MUG", 1)])
        self.assertEqual(inv.available("TEA"), 3)
        self.assertEqual(inv.available("MUG"), 0)
        self.assertEqual(cart.items, [])

    def test_shortage_is_all_or_nothing(self):
        cart = Cart()
        cart.add(TEA, 2)
        cart.add(MUG, 2)
        inv = Inventory({"TEA": 5, "MUG": 1})
        with self.assertRaises(OutOfStock):
            checkout(cart, inv)
        self.assertEqual(inv.available("TEA"), 5)
        self.assertEqual(len(cart.items), 2)

    def test_empty_cart(self):
        with self.assertRaises(ValueError):
            checkout(Cart(), Inventory())


if __name__ == "__main__":
    unittest.main()
