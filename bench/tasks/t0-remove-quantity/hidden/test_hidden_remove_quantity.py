import sys
import unittest
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from shop.cart import Cart
from shop.models import Product

TEA = Product("TEA", "Green tea", Decimal("4.50"))


class TestRemoveQuantity(unittest.TestCase):
    def make(self, qty):
        cart = Cart()
        cart.add(TEA, qty)
        return cart

    def test_removes_exact_quantity(self):
        cart = self.make(5)
        cart.remove("TEA", 2)
        self.assertEqual(cart.items[0].quantity, 3)

    def test_removing_all_units_deletes_line(self):
        cart = self.make(3)
        cart.remove("TEA", 3)
        self.assertEqual(cart.items, [])

    def test_step_down_to_zero(self):
        cart = self.make(2)
        cart.remove("TEA", 1)
        cart.remove("TEA", 1)
        self.assertEqual(cart.items, [])

    def test_invalid_quantities(self):
        for bad in (0, -1, 4):
            cart = self.make(3)
            with self.assertRaises(ValueError, msg=bad):
                cart.remove("TEA", bad)
            self.assertEqual(cart.items[0].quantity, 3)

    def test_remove_without_quantity(self):
        cart = self.make(4)
        cart.remove("TEA")
        self.assertEqual(cart.items, [])


if __name__ == "__main__":
    unittest.main()
