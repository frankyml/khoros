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
from shop.returns import Refund, ReturnLedger

D = Decimal
TEA = Product("TEA", "Green tea", D("4.50"))
BOOK = Product("BOOK", "Book", D("20.00"), taxable=False)
MUG = Product("MUG", "Mug", D("9.99"))


def make_order(coupon="7"):
    cart = Cart()
    cart.add(TEA, 3)
    cart.add(BOOK, 1)
    cart.add(MUG, 2)
    if coupon:
        cart.apply_discount(FixedAmountOff(coupon))
    inv = Inventory({"TEA": 10, "BOOK": 10, "MUG": 10})
    return checkout(cart, inv, order_id="o1"), inv


class TestOrderLines(unittest.TestCase):
    def test_taxable_flag(self):
        order, _ = make_order()
        self.assertEqual({l.sku: l.taxable for l in order.lines}, {"TEA": True, "BOOK": False, "MUG": True})


class TestLineValues(unittest.TestCase):
    def test_values(self):
        order, _ = make_order()
        self.assertEqual(order.total, D("49.39"))
        ledger = ReturnLedger(order)
        self.assertEqual(ledger.line_value("TEA"), D("12.90"))
        self.assertEqual(ledger.line_value("BOOK"), D("17.38"))
        self.assertEqual(ledger.line_value("MUG"), D("19.11"))

    def test_values_sum_to_total_without_coupon(self):
        order, _ = make_order(coupon=None)
        ledger = ReturnLedger(order)
        self.assertEqual(sum(ledger.line_value(s) for s in ("TEA", "BOOK", "MUG")), order.total)


class TestRefunds(unittest.TestCase):
    def setUp(self):
        self.order, self.inv = make_order()
        self.ledger = ReturnLedger(self.order)

    def test_partial_returns_add_up(self):
        self.assertEqual(self.ledger.refund_for("MUG", 1), D("9.56"))
        r1 = self.ledger.process("r1", {"MUG": 1}, self.inv)
        self.assertEqual(r1, Refund("r1", {"MUG": D("9.56")}, D("9.56")))
        self.assertEqual(self.ledger.refund_for("MUG", 1), D("9.55"))
        self.assertEqual(self.ledger.returned("MUG"), 1)

    def test_refund_for_does_not_change_state(self):
        self.ledger.refund_for("TEA", 2)
        self.assertEqual(self.ledger.returned("TEA"), 0)
        self.assertEqual(self.ledger.refunded_total, D("0.00"))
        self.assertEqual(self.inv.available("TEA"), 7)

    def test_full_return_refunds_order_total(self):
        self.ledger.process("a", {"TEA": 1, "MUG": 1}, self.inv)
        self.ledger.process("b", {"TEA": 2}, self.inv)
        self.ledger.process("c", {"BOOK": 1, "MUG": 1}, self.inv)
        self.assertEqual(self.ledger.refunded_total, self.order.total)
        self.assertEqual((self.inv.available("TEA"), self.inv.available("BOOK"), self.inv.available("MUG")), (10, 10, 10))

    def test_one_unit_at_a_time_adds_up(self):
        total = sum(self.ledger.process(f"t{i}", {"TEA": 1}, self.inv).total for i in range(3))
        self.assertEqual(total, self.ledger.line_value("TEA"))

    def test_idempotent_return_id(self):
        first = self.ledger.process("r1", {"TEA": 2}, self.inv)
        again = self.ledger.process("r1", {"TEA": 2}, self.inv)
        self.assertEqual(first, again)
        self.assertEqual(self.ledger.returned("TEA"), 2)
        self.assertEqual(self.inv.available("TEA"), 9)
        self.assertEqual(self.ledger.refunded_total, first.total)
        with self.assertRaises(ValueError):
            self.ledger.process("r1", {"TEA": 1}, self.inv)

    def test_validation(self):
        with self.assertRaises(KeyError):
            self.ledger.refund_for("NOPE", 1)
        with self.assertRaises(ValueError):
            self.ledger.refund_for("TEA", 0)
        with self.assertRaises(ValueError):
            self.ledger.refund_for("TEA", 4)
        self.ledger.process("r1", {"TEA": 3}, self.inv)
        with self.assertRaises(ValueError):
            self.ledger.refund_for("TEA", 1)

    def test_invalid_return_changes_nothing(self):
        with self.assertRaises(ValueError):
            self.ledger.process("bad", {"TEA": 1, "MUG": 5}, self.inv)
        self.assertEqual(self.ledger.returned("TEA"), 0)
        self.assertEqual(self.inv.available("TEA"), 7)
        self.assertEqual(self.ledger.refunded_total, D("0.00"))
        self.ledger.process("bad", {"TEA": 1}, self.inv)
        self.assertEqual(self.ledger.returned("TEA"), 1)


if __name__ == "__main__":
    unittest.main()
