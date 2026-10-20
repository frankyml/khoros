import sys
import unittest
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import json
import os
import subprocess
import tempfile

from shop.cart import Cart
from shop.checkout import checkout
from shop.inventory import Inventory
from shop.models import Product
from shop.orders import OrderRepository, order_from_dict, order_to_dict
from shop.pricing import FixedAmountOff

SRC = Path(__file__).resolve().parent.parent / "src"
TEA = Product("TEA", "Green tea", Decimal("4.50"))
BOOK = Product("BOOK", "Book", Decimal("20.00"), taxable=False)


def make_order(order_id, repo=None):
    cart = Cart()
    cart.add(TEA, 2)
    cart.add(BOOK)
    cart.apply_discount(FixedAmountOff("5"))
    return checkout(cart, Inventory({"TEA": 9, "BOOK": 9}), order_id=order_id, repository=repo)


class TestSerialisation(unittest.TestCase):
    def test_round_trip(self):
        order = make_order("o1")
        data = order_to_dict(order)
        json.dumps(data)
        self.assertEqual(data["total"], "24.74")
        self.assertEqual(data["lines"][0]["unit_price"], "4.50")
        self.assertEqual(order_from_dict(json.loads(json.dumps(data))), order)


class TestRepository(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "orders.json"

    def tearDown(self):
        self.tmp.cleanup()

    def test_empty_when_missing(self):
        self.assertEqual(OrderRepository(self.db).list(), [])

    def test_checkout_saves_and_persists(self):
        repo = OrderRepository(self.db)
        a = make_order("a", repo)
        b = make_order("b", repo)
        fresh = OrderRepository(self.db)
        self.assertEqual(fresh.list(), [a, b])
        self.assertEqual(fresh.get("b"), b)

    def test_duplicate_and_missing(self):
        repo = OrderRepository(self.db)
        make_order("a", repo)
        with self.assertRaises(ValueError):
            repo.save(make_order("a"))
        with self.assertRaises(KeyError):
            repo.get("zzz")
        self.assertEqual(len(repo.list()), 1)

    def test_checkout_without_repository_still_works(self):
        self.assertEqual(make_order("x").total, Decimal("24.74"))


class TestCli(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "orders.json"

    def tearDown(self):
        self.tmp.cleanup()

    def run_cli(self, *args):
        env = dict(os.environ, PYTHONPATH=str(SRC))
        return subprocess.run(
            [sys.executable, "-m", "shop", "orders", "--db", str(self.db), *args],
            capture_output=True, text=True, env=env, timeout=30,
        )

    def test_list(self):
        repo = OrderRepository(self.db)
        make_order("o1", repo)
        make_order("o2", repo)
        res = self.run_cli()
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(res.stdout.strip().splitlines(), ["o1 $24.74", "o2 $24.74"])

    def test_list_empty(self):
        res = self.run_cli()
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(res.stdout.strip(), "")

    def test_show(self):
        make_order("o1", OrderRepository(self.db))
        res = self.run_cli("--show", "o1")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(
            res.stdout.strip().splitlines(),
            ["2 x TEA @ $4.50 = $9.00", "1 x BOOK @ $20.00 = $20.00", "TOTAL $24.74"],
        )

    def test_show_unknown(self):
        res = self.run_cli("--show", "nope")
        self.assertEqual(res.returncode, 1)
        self.assertTrue(res.stderr.strip())


if __name__ == "__main__":
    unittest.main()
