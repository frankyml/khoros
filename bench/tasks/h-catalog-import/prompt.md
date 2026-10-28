Add `load_catalog(path) -> CatalogResult` in a new module `shop/catalog.py`. It imports products from the CSV files the suppliers send us. `CatalogResult` has `products` (dict sku → `Product`), `errors` and `warnings` (lists of `(line_number, message)`).

File format:
- UTF-8, possibly starting with a byte-order mark. Standard CSV quoting (a quoted field may contain commas).
- The first non-blank line is the header. It must contain the columns `sku`, `name`, `price` and `taxable` in any order, matched case-insensitively and ignoring surrounding whitespace; extra columns are ignored. A missing required column raises `ValueError`.
- Blank lines are skipped anywhere.
- Every field is trimmed of surrounding whitespace.

Each data row:
- `sku`: uppercased; must be non-empty and contain only `A-Z`, `0-9` and `-`.
- `name`: non-empty.
- `price`: optionally prefixed by `$`, `£` or `€` (spaces after the symbol are allowed), then one or more digits, optionally followed by a decimal separator and one or two digits. The decimal separator is `.` or `,` (`4,50` means 4.50). Thousands separators are not allowed, so a value containing both `,` and `.` is invalid. Must be greater than zero. Stored as a Decimal quantized to cents.
- `taxable`: `yes`/`no`, `true`/`false`, `y`/`n`, `1`/`0`, case-insensitive. Empty means taxable.

A row with any invalid or missing field is skipped and adds one entry to `errors`. If a sku appears again, the later row replaces the earlier one and adds an entry to `warnings`. Line numbers are 1-based physical line numbers in the file (the header is usually line 1).
