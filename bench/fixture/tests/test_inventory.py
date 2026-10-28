import sys
import unittest
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from shop.inventory import Inventory, OutOfStock


class TestInventory(unittest.TestCase):
    def test_restock_and_take(self):
        inv = Inventory({"TEA": 5})
        inv.restock("TEA", 2)
        inv.take("TEA", 4)
        self.assertEqual(inv.available("TEA"), 3)

    def test_take_too_many(self):
        inv = Inventory({"TEA": 1})
        with self.assertRaises(OutOfStock) as ctx:
            inv.take("TEA", 2)
        self.assertEqual(ctx.exception.available, 1)
        self.assertEqual(inv.available("TEA"), 1)

    def test_unknown_sku_has_no_stock(self):
        self.assertEqual(Inventory().available("NOPE"), 0)


if __name__ == "__main__":
    unittest.main()
