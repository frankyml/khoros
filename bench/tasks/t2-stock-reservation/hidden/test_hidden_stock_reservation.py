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


class TestInventoryReservations(unittest.TestCase):
    def test_reserve_and_release(self):
        inv = Inventory({"TEA": 5})
        inv.reserve("TEA", 3)
        self.assertEqual((inv.on_hand("TEA"), inv.reserved("TEA"), inv.available("TEA")), (5, 3, 2))
        inv.release("TEA", 1)
        self.assertEqual((inv.reserved("TEA"), inv.available("TEA")), (2, 3))

    def test_reserve_errors(self):
        inv = Inventory({"TEA": 2})
        with self.assertRaises(OutOfStock):
            inv.reserve("TEA", 3)
        with self.assertRaises(ValueError):
            inv.reserve("TEA", 0)
        inv.reserve("TEA", 1)
        with self.assertRaises(ValueError):
            inv.release("TEA", 2)
        self.assertEqual(inv.reserved("TEA"), 1)

    def test_take_reserved(self):
        inv = Inventory({"TEA": 5})
        inv.reserve("TEA", 2)
        inv.take("TEA", 2, reserved=True)
        self.assertEqual((inv.on_hand("TEA"), inv.reserved("TEA"), inv.available("TEA")), (3, 0, 3))
        with self.assertRaises(ValueError):
            inv.take("TEA", 1, reserved=True)

    def test_unreserved_take_respects_reservations(self):
        inv = Inventory({"TEA": 5})
        inv.reserve("TEA", 4)
        with self.assertRaises(OutOfStock):
            inv.take("TEA", 2)
        inv.take("TEA", 1)
        self.assertEqual(inv.on_hand("TEA"), 4)


class TestCartReservations(unittest.TestCase):
    def test_add_reserves(self):
        inv = Inventory({"TEA": 5})
        cart = Cart(inventory=inv)
        self.assertIs(cart.inventory, inv)
        cart.add(TEA, 2)
        cart.add(TEA)
        self.assertEqual(inv.reserved("TEA"), 3)

    def test_add_out_of_stock_leaves_cart_unchanged(self):
        inv = Inventory({"TEA": 2})
        cart = Cart(inventory=inv)
        cart.add(TEA, 1)
        with self.assertRaises(OutOfStock):
            cart.add(TEA, 2)
        self.assertEqual(cart.items[0].quantity, 1)
        self.assertEqual(inv.reserved("TEA"), 1)

    def test_two_carts_cannot_oversell(self):
        inv = Inventory({"MUG": 4})
        a, b = Cart(inventory=inv), Cart(inventory=inv)
        a.add(MUG, 3)
        with self.assertRaises(OutOfStock):
            b.add(MUG, 2)
        b.add(MUG, 1)
        self.assertEqual(inv.available("MUG"), 0)

    def test_remove_and_clear_release(self):
        inv = Inventory({"TEA": 5, "MUG": 5})
        cart = Cart(inventory=inv)
        cart.add(TEA, 4)
        cart.add(MUG, 2)
        cart.remove("TEA", 1)
        self.assertEqual(inv.reserved("TEA"), 3)
        cart.remove("MUG")
        self.assertEqual(inv.reserved("MUG"), 0)
        cart.clear()
        self.assertEqual(inv.reserved("TEA"), 0)
        self.assertEqual(cart.items, [])


class TestCheckoutReservations(unittest.TestCase):
    def test_checkout_consumes_reservations(self):
        inv = Inventory({"TEA": 5, "MUG": 2})
        cart = Cart(inventory=inv)
        cart.add(TEA, 2)
        cart.add(MUG, 2)
        order = checkout(cart, inv)
        self.assertEqual(order.subtotal, Decimal("28.98"))
        self.assertEqual((inv.on_hand("TEA"), inv.reserved("TEA")), (3, 0))
        self.assertEqual((inv.on_hand("MUG"), inv.reserved("MUG")), (0, 0))
        self.assertEqual(cart.items, [])

    def test_checkout_with_other_inventory(self):
        cart = Cart(inventory=Inventory({"TEA": 5}))
        cart.add(TEA)
        with self.assertRaises(ValueError):
            checkout(cart, Inventory({"TEA": 5}))

    def test_cart_without_inventory_unchanged(self):
        inv = Inventory({"TEA": 5})
        cart = Cart()
        cart.add(TEA, 9)
        with self.assertRaises(OutOfStock):
            checkout(cart, inv)
        cart.remove("TEA", 5)
        checkout(cart, inv)
        self.assertEqual(inv.on_hand("TEA"), 1)


if __name__ == "__main__":
    unittest.main()
