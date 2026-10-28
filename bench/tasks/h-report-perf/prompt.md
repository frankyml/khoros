The nightly sales report (`sales_report` in `shop/reports.py`) takes several minutes on production data: tens of thousands of orders, a few hundred SKUs. Make it fast.

Downstream tooling parses this report, so the output must stay byte-for-byte identical to the current implementation for every possible input, including edge cases.
