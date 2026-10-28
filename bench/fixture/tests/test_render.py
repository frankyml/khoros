import sys
import unittest
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from shop.web.render import render_badge


class TestRender(unittest.TestCase):
    def test_known_badges(self):
        self.assertEqual(render_badge("new"), '<span class="badge badge--new">New</span>')
        self.assertEqual(render_badge("low-stock"), '<span class="badge badge--low-stock">Low stock</span>')

    def test_unknown_badge(self):
        with self.assertRaises(ValueError):
            render_badge("bogus")


if __name__ == "__main__":
    unittest.main()
