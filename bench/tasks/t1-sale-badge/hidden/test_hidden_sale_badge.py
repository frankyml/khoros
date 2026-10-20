import sys
import unittest
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import re

from shop.web.render import render_badge

STATIC = Path(__file__).resolve().parent.parent / "src" / "shop" / "web" / "static"
RAW_COLOR = re.compile(r"#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(|:\s*(?:red|white|crimson|darkred)\b", re.I)


def rule_body(css, selector):
    m = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", css)
    return m.group(1) if m else None


class TestSaleBadge(unittest.TestCase):
    def setUp(self):
        self.css = (STATIC / "cart.css").read_text(encoding="utf-8")

    def test_render(self):
        self.assertEqual(render_badge("sale"), '<span class="badge badge--sale">Sale</span>')

    def test_rule_exists(self):
        self.assertIsNotNone(rule_body(self.css, ".badge--sale"))

    def test_colours_come_from_design_tokens(self):
        body = rule_body(self.css, ".badge--sale") or ""
        self.assertRegex(body, r"background(?:-color)?\s*:\s*var\(--color-error\)")
        self.assertRegex(body, r"(?<![-\w])color\s*:\s*var\(--color-on-error\)")

    def test_no_raw_colours_outside_theme(self):
        self.assertIsNone(RAW_COLOR.search(self.css), "cart.css must not hardcode colours; use theme.css tokens")

    def test_padding_on_grid(self):
        body = rule_body(self.css, ".badge--sale") or ""
        m = re.search(r"padding\s*:\s*([^;]+);", body)
        self.assertIsNotNone(m)
        value = m.group(1).strip()
        allowed = {"var(--space-1) var(--space-2)", "4px 8px"}
        self.assertIn(re.sub(r"\s+", " ", value), allowed)


if __name__ == "__main__":
    unittest.main()
