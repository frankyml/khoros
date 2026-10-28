import csv
import io
import re
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Dict, List, Tuple

from .models import Product
from .money import to_money

REQUIRED = ("sku", "name", "price", "taxable")
_SKU = re.compile(r"[A-Z0-9-]+")
_PRICE = re.compile(r"\d+(?:\.\d{1,2})?")
_TAXABLE = {"yes": True, "true": True, "y": True, "1": True, "": True, "no": False, "false": False, "n": False, "0": False}


@dataclass
class CatalogResult:
    products: Dict[str, Product] = field(default_factory=dict)
    errors: List[Tuple[int, str]] = field(default_factory=list)
    warnings: List[Tuple[int, str]] = field(default_factory=list)


def parse_price(text: str) -> Decimal:
    value = text.strip()
    if value[:1] in ("$", "£", "€"):
        value = value[1:].strip()
    if "," in value and "." in value:
        raise ValueError(f"thousands separators are not allowed: {text!r}")
    value = value.replace(",", ".")
    if not _PRICE.fullmatch(value):
        raise ValueError(f"invalid price: {text!r}")
    price = to_money(value)
    if price <= 0:
        raise ValueError(f"price must be positive: {text!r}")
    return price


def _parse_row(fields: Dict[str, str]) -> Product:
    missing = [name for name in REQUIRED if fields.get(name) is None]
    if missing:
        raise ValueError(f"missing {', '.join(missing)}")
    sku = fields["sku"].upper()
    if not _SKU.fullmatch(sku):
        raise ValueError(f"invalid sku: {fields['sku']!r}")
    if not fields["name"]:
        raise ValueError("name is empty")
    taxable = _TAXABLE.get(fields["taxable"].lower())
    if taxable is None:
        raise ValueError(f"invalid taxable flag: {fields['taxable']!r}")
    return Product(sku, fields["name"], parse_price(fields["price"]), taxable)


def load_catalog(path) -> CatalogResult:
    text = Path(path).read_text(encoding="utf-8-sig")
    reader = csv.reader(io.StringIO(text))
    result = CatalogResult()
    columns: Dict[str, int] = {}
    start = 1
    for row in reader:
        line, start = start, reader.line_num + 1
        if not any(cell.strip() for cell in row):
            continue
        if not columns:
            header = [cell.strip().lower() for cell in row]
            missing = [name for name in REQUIRED if name not in header]
            if missing:
                raise ValueError(f"missing required column(s): {', '.join(missing)}")
            columns = {name: header.index(name) for name in REQUIRED}
            continue
        fields = {name: row[i].strip() if i < len(row) else None for name, i in columns.items()}
        try:
            product = _parse_row(fields)
        except ValueError as exc:
            result.errors.append((line, str(exc)))
            continue
        if product.sku in result.products:
            result.warnings.append((line, f"duplicate sku {product.sku} replaces an earlier row"))
        result.products[product.sku] = product
    return result
