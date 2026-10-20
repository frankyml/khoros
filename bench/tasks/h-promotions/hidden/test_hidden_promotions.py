import sys
import unittest
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from shop.cart import Cart
from shop.checkout import checkout
from shop.inventory import Inventory
from shop.models import LineItem, Product
from shop.pricing import FixedAmountOff
from shop.promotions import Bundle, BuyXGetY, Threshold, apply_promotions

D = Decimal
TEA = Product("TEA", "Green tea", D("4.50"))
MUG = Product("MUG", "Mug", D("9.99"))
BOOK = Product("BOOK", "Book", D("20.00"), taxable=False)
PEN = Product("PEN", "Pen", D("1.25"))


def items(*pairs):
    return [LineItem(p, q) for p, q in pairs]


class TestItemPromotions(unittest.TestCase):
    def test_buy_x_get_y(self):
        r = apply_promotions(items((TEA, 7)), [BuyXGetY("TEA", 2, 1)])
        self.assertEqual(r.total_discount, D("9.00"))
        self.assertEqual(r.line_discounts, {"TEA": D("9.00")})

    def test_buy_x_get_y_incomplete_group(self):
        r = apply_promotions(items((TEA, 2), (MUG, 1)), [BuyXGetY("TEA", 2, 1)])
        self.assertEqual(r.total_discount, D("0"))
        self.assertEqual(r.line_discounts, {"TEA": D("0"), "MUG": D("0")})

    def test_bundle_split_by_unit_price(self):
        r = apply_promotions(items((MUG, 2), (TEA, 3)), [Bundle(["MUG", "TEA"], "12.00")])
        self.assertEqual(r.total_discount, D("4.98"))
        self.assertEqual(r.line_discounts, {"MUG": D("3.43"), "TEA": D("1.55")})

    def test_units_are_claimed_in_list_order(self):
        cart = items((TEA, 4), (MUG, 2))
        r = apply_promotions(cart, [BuyXGetY("TEA", 2, 1), Bundle(["MUG", "TEA"], "12.00")])
        self.assertEqual(r.line_discounts, {"TEA": D("5.27"), "MUG": D("1.72")})
        self.assertEqual(r.total_discount, D("6.99"))
        r = apply_promotions(cart, [Bundle(["MUG", "TEA"], "12.00"), BuyXGetY("TEA", 2, 1)])
        self.assertEqual(r.line_discounts, {"TEA": D("1.55"), "MUG": D("3.43")})
        self.assertEqual(r.total_discount, D("4.98"))

    def test_useless_bundle_claims_nothing(self):
        r = apply_promotions(items((TEA, 2), (PEN, 1)), [Bundle(["PEN", "TEA"], "6.00"), BuyXGetY("TEA", 1, 1)])
        self.assertEqual(r.line_discounts, {"TEA": D("4.50"), "PEN": D("0")})

    def test_bundle_with_missing_sku(self):
        r = apply_promotions(items((TEA, 3)), [Bundle(["MUG", "TEA"], "12.00")])
        self.assertEqual(r.total_discount, D("0"))

    def test_remainder_tie_goes_to_smaller_sku(self):
        a = Product("AAA", "a", D("1.00"))
        b = Product("BBB", "b", D("1.00"))
        r = apply_promotions(items((b, 1), (a, 1)), [Bundle(["BBB", "AAA"], "1.99")])
        self.assertEqual(r.line_discounts, {"AAA": D("0.01"), "BBB": D("0.00")})


class TestThreshold(unittest.TestCase):
    def test_best_eligible_threshold(self):
        r = apply_promotions(items((BOOK, 3)), [Threshold("50", 10), Threshold("20", 5), Threshold("100", 30)])
        self.assertEqual(r.total_discount, D("6.00"))

    def test_threshold_uses_amount_after_item_promotions(self):
        cart = items((TEA, 6), (BOOK, 1))
        r = apply_promotions(cart, [BuyXGetY("TEA", 2, 1), Threshold("40", 10)])
        self.assertEqual(r.total_discount, D("9.00"))
        r = apply_promotions(cart, [BuyXGetY("TEA", 2, 1), Threshold("35", 10)])
        self.assertEqual(r.line_discounts, {"TEA": D("10.80"), "BOOK": D("2.00")})
        self.assertEqual(r.total_discount, D("12.80"))

    def test_largest_remainder_allocation(self):
        r = apply_promotions(items((PEN, 1), (TEA, 1), (MUG, 1)), [Threshold("0", 10)])
        self.assertEqual(r.total_discount, D("1.57"))
        self.assertEqual(r.line_discounts, {"PEN": D("0.12"), "TEA": D("0.45"), "MUG": D("1.00")})

    def test_parts_always_sum_to_total(self):
        promos = [BuyXGetY("TEA", 2, 1), Bundle(["MUG", "PEN"], "10.00"), Threshold("5", "12.5"), Threshold("1", 3)]
        for qt in range(0, 7):
            for qm in range(1, 4):
                for qp in range(1, 4):
                    cart = items((TEA, qt), (MUG, qm), (PEN, qp)) if qt else items((MUG, qm), (PEN, qp))
                    r = apply_promotions(cart, promos)
                    self.assertEqual(sum(r.line_discounts.values()), r.total_discount, (qt, qm, qp))


class TestValidation(unittest.TestCase):
    def test_invalid_arguments(self):
        for make in (
            lambda: BuyXGetY("TEA", 0, 1),
            lambda: BuyXGetY("TEA", 2, 0),
            lambda: Bundle(["TEA"], "1"),
            lambda: Bundle(["TEA", "TEA"], "1"),
            lambda: Bundle(["TEA", "MUG"], "0"),
            lambda: Threshold("10", 0),
            lambda: Threshold("10", 101),
            lambda: Threshold("-1", 10),
        ):
            with self.assertRaises(ValueError):
                make()


class TestCartIntegration(unittest.TestCase):
    def test_promotions_and_coupon(self):
        cart = Cart()
        cart.add(TEA, 3)
        cart.add(BOOK)
        cart.set_promotions([BuyXGetY("TEA", 2, 1)])
        cart.apply_discount(FixedAmountOff("5"))
        self.assertEqual(cart.subtotal(), D("33.50"))
        self.assertEqual(cart.promotion_result().total_discount, D("4.50"))
        self.assertEqual(cart.discount_total(), D("9.50"))
        self.assertEqual(cart.tax(), D("0.74"))
        self.assertEqual(cart.total(), D("24.74"))

    def test_coupon_capped_at_amount_after_promotions(self):
        cart = Cart()
        cart.add(TEA, 3)
        cart.set_promotions([BuyXGetY("TEA", 2, 1)])
        cart.apply_discount(FixedAmountOff("100"))
        self.assertEqual(cart.discount_total(), D("13.50"))
        self.assertEqual(cart.tax(), D("0.00"))
        self.assertEqual(cart.total(), D("0.00"))

    def test_no_promotions_unchanged(self):
        cart = Cart()
        cart.add(TEA, 2)
        cart.add(BOOK)
        cart.apply_discount(FixedAmountOff("5"))
        self.assertEqual((cart.discount_total(), cart.tax(), cart.total()), (D("5.00"), D("0.74"), D("24.74")))

    def test_order_matches_cart(self):
        cart = Cart()
        cart.add(TEA, 4)
        cart.add(MUG, 2)
        cart.set_promotions([Bundle(["MUG", "TEA"], "12.00"), Threshold("10", 5)])
        expected = cart.total()
        order = checkout(cart, Inventory({"TEA": 9, "MUG": 9}))
        self.assertEqual(order.total, expected)

    def test_clear_removes_promotions(self):
        cart = Cart()
        cart.add(TEA, 3)
        cart.set_promotions([BuyXGetY("TEA", 2, 1)])
        cart.clear()
        cart.add(TEA, 3)
        self.assertEqual(cart.discount_total(), D("0.00"))


if __name__ == "__main__":
    unittest.main()
