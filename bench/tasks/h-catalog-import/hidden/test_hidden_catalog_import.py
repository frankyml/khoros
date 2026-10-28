import sys
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from shop.catalog import load_catalog

D = Decimal


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def load(self, text, bom=False):
        path = Path(self.tmp.name) / "catalog.csv"
        data = text.encode("utf-8")
        path.write_bytes((b"\xef\xbb\xbf" if bom else b"") + data)
        return load_catalog(path)

    def error_lines(self, result):
        return sorted(line for line, _ in result.errors)


class TestHappyPath(Base):
    def test_basic(self):
        r = self.load("sku,name,price,taxable\nTEA,Green tea,4.50,yes\nBOOK,Book,20,no\n")
        self.assertEqual(sorted(r.products), ["BOOK", "TEA"])
        tea = r.products["TEA"]
        self.assertEqual((tea.name, tea.price, tea.taxable), ("Green tea", D("4.50"), True))
        self.assertEqual(r.products["BOOK"].price, D("20.00"))
        self.assertFalse(r.products["BOOK"].taxable)
        self.assertEqual((r.errors, r.warnings), ([], []))

    def test_bom_header_case_order_and_extra_columns(self):
        r = self.load(" Price ,SKU,Notes,Taxable,Name\n4.50,tea,ignore me,Y,  Green tea  \n", bom=True)
        tea = r.products["TEA"]
        self.assertEqual((tea.sku, tea.name, tea.price, tea.taxable), ("TEA", "Green tea", D("4.50"), True))

    def test_quoted_field_with_comma(self):
        r = self.load('sku,name,price,taxable\nTEA,"Tea, green",4.50,1\n')
        self.assertEqual(r.products["TEA"].name, "Tea, green")

    def test_taxable_values(self):
        rows = ["sku,name,price,taxable"]
        values = {"A": "YES", "B": "No", "C": "TRUE", "E": "false", "F": "y", "G": "N", "H": "1", "I": "0", "J": ""}
        rows += [f"{sku},x,1,{v}" for sku, v in values.items()]
        r = self.load("\n".join(rows) + "\n")
        got = {sku: p.taxable for sku, p in r.products.items()}
        self.assertEqual(got, {"A": True, "B": False, "C": True, "E": False, "F": True, "G": False, "H": True, "I": False, "J": True})


class TestPrices(Base):
    def test_accepted_formats(self):
        r = self.load("sku,name,price,taxable\nA,a,\"4,50\",y\nB,b,€3,y\nC,c,$ 12.5,y\nD,d,£0.99,y\nE,e,7,y\n")
        self.assertEqual({s: p.price for s, p in r.products.items()},
                         {"A": D("4.50"), "B": D("3.00"), "C": D("12.50"), "D": D("0.99"), "E": D("7.00")})
        self.assertEqual(r.errors, [])

    def test_rejected_formats(self):
        bad = ['"1,234.50"', "4.505", "-1", "0", "0.00", "abc", "", "4.", ".50", "4 50", "$$4"]
        text = "sku,name,price,taxable\n" + "".join(f"S{i},x,{p},y\n" for i, p in enumerate(bad))
        r = self.load(text)
        self.assertEqual(r.products, {})
        self.assertEqual(self.error_lines(r), list(range(2, 2 + len(bad))))


class TestRowErrors(Base):
    def test_invalid_rows_skipped_with_physical_line_numbers(self):
        text = (
            "\n"                          # 1 blank before header
            "sku,name,price,taxable\n"    # 2 header
            "TEA,Tea,4.50,yes\n"          # 3 ok
            "\n"                          # 4 blank
            "te a,Bad sku,1,yes\n"        # 5 bad sku
            "MUG,,9.99,yes\n"             # 6 empty name
            "PEN,Pen,1.25,maybe\n"        # 7 bad taxable
            "CUP,Cup\n"                   # 8 short row
            "\n"                          # 9 blank
            "BOWL,Bowl,3,no\n"            # 10 ok
        )
        r = self.load(text)
        self.assertEqual(sorted(r.products), ["BOWL", "TEA"])
        self.assertEqual(self.error_lines(r), [5, 6, 7, 8])

    def test_duplicates_last_wins_with_warning(self):
        r = self.load("sku,name,price,taxable\nTEA,Old tea,4.00,y\nMUG,Mug,9.99,y\ntea,New tea,4.75,n\n")
        self.assertEqual(r.products["TEA"].name, "New tea")
        self.assertEqual(r.products["TEA"].price, D("4.75"))
        self.assertEqual([line for line, _ in r.warnings], [4])
        self.assertEqual(r.errors, [])

    def test_invalid_duplicate_does_not_replace(self):
        r = self.load("sku,name,price,taxable\nTEA,Tea,4.00,y\nTEA,Tea,free,y\n")
        self.assertEqual(r.products["TEA"].price, D("4.00"))
        self.assertEqual(r.warnings, [])
        self.assertEqual(self.error_lines(r), [3])


class TestHeader(Base):
    def test_missing_required_column(self):
        with self.assertRaises(ValueError):
            self.load("sku,name,price\nTEA,Tea,4.50\n")

    def test_lowercase_sku_with_hyphen(self):
        r = self.load("sku,name,price,taxable\ngreen-tea-01,Tea,4.50,\n")
        self.assertIn("GREEN-TEA-01", r.products)


if __name__ == "__main__":
    unittest.main()
