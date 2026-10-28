from decimal import ROUND_HALF_UP, Decimal
from typing import Dict, List, Tuple

from .checkout import Order
from .money import format_money, to_money


def sales_report(orders: List[Order], top: int = 5) -> str:
    """Plain-text nightly sales report: order totals, then the top SKUs by gross line revenue."""
    lines = ["SALES REPORT"]
    revenue = sum((order.total for order in orders), Decimal("0"))
    lines.append(f"Orders: {len(orders)}")
    lines.append(f"Revenue: {format_money(revenue)}")
    if orders:
        lines.append(f"Average order: {format_money(to_money(revenue / len(orders)))}")

    totals: Dict[str, Tuple[int, Decimal]] = {}
    for order in orders:
        for line in order.lines:
            units, gross = totals.get(line.sku, (0, Decimal("0")))
            totals[line.sku] = (units + line.quantity, gross + line.total)
    rows = [(sku, units, gross) for sku, (units, gross) in totals.items()]

    gross_total = sum((row[2] for row in rows), Decimal("0"))
    rows.sort(key=lambda row: (-row[2], -row[1], row[0]))

    lines.append("")
    lines.append(f"{'SKU':<10}{'UNITS':>8}{'GROSS':>14}{'SHARE':>8}")
    shown = Decimal("0")
    for sku, units, gross in rows[:top]:
        if gross_total:
            share = (gross / gross_total * 100).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
        else:
            share = Decimal("0.0")
        shown += share
        lines.append(f"{sku:<10}{units:>8}{format_money(gross):>14}{share:>7}%")
    rest = rows[top:]
    if rest:
        units = sum(row[1] for row in rest)
        gross = sum((row[2] for row in rest), Decimal("0"))
        lines.append(f"{'OTHER':<10}{units:>8}{format_money(gross):>14}{Decimal(100) - shown:>7}%")
    return "\n".join(lines) + "\n"
