Extend `format_money` in `shop/money.py`:

1. Support `"EUR"` using continental formatting: `format_money(Decimal("1234.56"), "EUR") == "1.234,56 €"` (dot for thousands, comma for decimals, a space then the euro sign after the number).
2. Negative amounts put the minus sign first: `format_money(Decimal("-5"), "USD") == "-$5.00"` and `format_money(Decimal("-1234.5"), "EUR") == "-1.234,50 €"`. Today they render as `$-5.00`.

USD and GBP output for positive amounts must not change.
