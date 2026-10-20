import sys
import unittest
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from shop.money import format_money, to_money


class TestMoney(unittest.TestCase):
    def test_to_money_rounds_half_up(self):
        self.assertEqual(to_money(Decimal("2.675")), Decimal("2.68"))
        self.assertEqual(to_money("1.004"), Decimal("1.00"))

    def test_to_money_rejects_float(self):
        with self.assertRaises(TypeError):
            to_money(1.5)

    def test_format_usd_and_gbp(self):
        self.assertEqual(format_money(Decimal("1234.5")), "$1,234.50")
        self.assertEqual(format_money(Decimal("3"), "GBP"), "£3.00")

    def test_format_unknown_currency(self):
        with self.assertRaises(ValueError):
            format_money(1, "XYZ")


if __name__ == "__main__":
    unittest.main()
