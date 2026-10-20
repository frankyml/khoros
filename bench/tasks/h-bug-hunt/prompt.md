Support escalated three customer reports from this week. They may or may not be related.

1. "My UK receipt says £1234.50. The US site shows a comma, like $1,234.50."
2. Ops: "The nightly job crashed this morning while loading the stock file." It builds the inventory with `Inventory(stock_counts)` from that file, and it started failing right after a product sold out.
3. Accounting: "Some amounts are a cent lower than our spreadsheet. A cart with one $0.25 sticker shows $0.02 tax, but we always round half-up, so it should be $0.03."

Find the root causes and fix them without changing behaviour that isn't broken.
