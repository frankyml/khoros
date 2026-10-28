# shop

A tiny shopping-cart library used as a benchmark fixture.

- Source: `src/shop/`
- Tests: `python3 -m unittest discover -s tests`
- Demo: `PYTHONPATH=src python3 -m shop demo`

Money is always `decimal.Decimal`, rounded half-up to the cent (see `src/shop/money.py`).
