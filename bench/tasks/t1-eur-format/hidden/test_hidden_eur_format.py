import sys
import unittest
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from shop.money import format_money


class TestEurFormat(unittest.TestCase):
    def test_eur(self):
        self.assertEqual(format_money(Decimal("1234.56"), "EUR"), "1.234,56 €")
        self.assertEqual(format_money(Decimal("0.5"), "EUR"), "0,50 €")
        self.assertEqual(format_money(Decimal("1234567.891"), "EUR"), "1.234.567,89 €")

    def test_negative(self):
        self.assertEqual(format_money(Decimal("-5"), "USD"), "-$5.00")
        self.assertEqual(format_money(Decimal("-1234.5"), "EUR"), "-1.234,50 €")
        self.assertEqual(format_money(Decimal("-0.01"), "GBP"), "-£0.01")

    def test_positive_unchanged(self):
        self.assertEqual(format_money(Decimal("1234.5")), "$1,234.50")
        self.assertEqual(format_money(3, "GBP"), "£3.00")


if __name__ == "__main__":
    unittest.main()
