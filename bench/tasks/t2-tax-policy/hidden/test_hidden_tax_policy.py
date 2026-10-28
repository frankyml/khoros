import sys
import unittest
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import inspect

from shop import cart as cart_module
from shop.cart import Cart
from shop.models import Product
from shop.pricing import FixedAmountOff
from shop.tax import ExemptTax, FlatRateTax, TaxPolicy

TEA = Product("TEA", "Green tea", Decimal("4.50"))
BOOK = Product("BOOK", "Book", Decimal("20.00"), taxable=False)


def fill(cart):
    cart.add(TEA, 2)
    cart.add(BOOK)
    cart.apply_discount(FixedAmountOff("5"))
    return cart


class Fixed123(TaxPolicy):
    def __init__(self):
        self.calls = []

    def tax_for(self, items, discount_total):
        self.calls.append(([i.product.sku for i in items], discount_total))
        return Decimal("1.23")


class TestTaxPolicy(unittest.TestCase):
    def test_default_behaviour_unchanged(self):
        cart = fill(Cart())
        self.assertIsInstance(cart.tax_policy, FlatRateTax)
        self.assertEqual(cart.tax(), Decimal("0.74"))
        self.assertEqual(cart.total(), Decimal("24.74"))

    def test_tax_rate_kwarg_still_works(self):
        a = fill(Cart(tax_rate=Decimal("0.21")))
        b = fill(Cart(tax_policy=FlatRateTax(Decimal("0.21"))))
        self.assertEqual(a.tax(), b.tax())
        self.assertEqual(a.tax(), Decimal("1.56"))

    def test_positional_tax_rate_still_works(self):
        self.assertEqual(fill(Cart(Decimal("0.21"))).tax(), Decimal("1.56"))

    def test_both_args_rejected(self):
        with self.assertRaises(TypeError):
            Cart(tax_rate=Decimal("0.1"), tax_policy=ExemptTax())

    def test_exempt(self):
        cart = fill(Cart(tax_policy=ExemptTax()))
        self.assertEqual(cart.tax(), Decimal("0.00"))
        self.assertEqual(cart.total(), Decimal("24.00"))

    def test_cart_delegates_to_policy(self):
        policy = Fixed123()
        cart = fill(Cart(tax_policy=policy))
        self.assertEqual(cart.total(), Decimal("25.23"))
        self.assertEqual(policy.calls[-1], (["TEA", "BOOK"], Decimal("5.00")))

    def test_flat_rate_direct(self):
        cart = fill(Cart())
        self.assertEqual(FlatRateTax(Decimal("0.10")).tax_for(cart.items, Decimal("5.00")), Decimal("0.74"))
        self.assertEqual(FlatRateTax(Decimal("0.10")).tax_for([], Decimal("0")), Decimal("0.00"))

    def test_cart_has_no_tax_arithmetic(self):
        source = inspect.getsource(cart_module.Cart.tax)
        self.assertNotIn("taxable", source)


if __name__ == "__main__":
    unittest.main()
