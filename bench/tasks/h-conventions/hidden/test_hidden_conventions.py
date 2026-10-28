import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from shop import events
from shop.errors import InvalidArgument, InvalidQuantity, OutOfStock, ShopError
from shop.inventory import Inventory


class Base(unittest.TestCase):
    def setUp(self):
        self.inv = Inventory({"TEA": 5})
        self.other = Inventory({"TEA": 1})
        events.clear()


class TestAdjust(Base):
    def test_increase_emits_event(self):
        self.inv.adjust("TEA", 3, "recount")
        self.assertEqual(self.inv.available("TEA"), 8)
        self.assertEqual(events.events(), [{"kind": "stock.adjusted", "sku": "TEA", "delta": 3, "reason": "recount", "on_hand": 8}])

    def test_decrease(self):
        self.inv.adjust("TEA", -5, "damaged")
        self.assertEqual(self.inv.available("TEA"), 0)
        self.assertEqual(events.events()[-1]["on_hand"], 0)

    def test_below_zero(self):
        with self.assertRaises(OutOfStock):
            self.inv.adjust("TEA", -6, "recount")
        self.assertEqual(self.inv.available("TEA"), 5)
        self.assertEqual(events.events(), [])

    def test_invalid_delta(self):
        for bad in (0, True, 1.5, "2"):
            with self.subTest(delta=bad):
                with self.assertRaises(InvalidArgument):
                    self.inv.adjust("TEA", bad, "recount")
        self.assertEqual(events.events(), [])

    def test_reason_required(self):
        for bad in ("", "   ", None):
            with self.subTest(reason=bad):
                with self.assertRaises(InvalidArgument):
                    self.inv.adjust("TEA", 1, bad)
        self.assertEqual(self.inv.available("TEA"), 5)
        self.assertEqual(events.events(), [])


class TestTransfer(Base):
    def test_moves_units_and_audits_both_sides(self):
        self.inv.transfer("TEA", 2, self.other)
        self.assertEqual((self.inv.available("TEA"), self.other.available("TEA")), (3, 3))
        log = events.events()
        self.assertEqual(len(log), 2)
        for event in log:
            self.assertEqual(set(event), {"kind", "sku", "quantity", "on_hand"})
            self.assertEqual((event["kind"], event["sku"], event["quantity"]), ("stock.transferred", "TEA", 2))
        self.assertEqual(sorted(e["on_hand"] for e in log), [3, 3])

    def test_on_hand_per_inventory(self):
        self.inv.transfer("TEA", 4, self.other)
        self.assertEqual(sorted(e["on_hand"] for e in events.events()), [1, 5])

    def test_not_enough_changes_nothing(self):
        with self.assertRaises(OutOfStock):
            self.inv.transfer("TEA", 6, self.other)
        self.assertEqual((self.inv.available("TEA"), self.other.available("TEA")), (5, 1))
        self.assertEqual(events.events(), [])

    def test_bad_quantity(self):
        for bad in (0, -1, True, 2.0):
            with self.subTest(quantity=bad):
                with self.assertRaises(InvalidQuantity):
                    self.inv.transfer("TEA", bad, self.other)
        self.assertEqual(events.events(), [])


class TestExistingBehaviour(Base):
    def test_errors_are_shop_errors(self):
        self.assertTrue(issubclass(OutOfStock, ShopError))
        with self.assertRaises(ValueError):
            self.inv.take("TEA", 0)

    def test_restock_and_take_still_audited(self):
        self.inv.restock("TEA", 1)
        self.inv.take("TEA", 2)
        self.assertEqual([e["kind"] for e in events.events()], ["stock.restocked", "stock.taken"])


if __name__ == "__main__":
    unittest.main()
