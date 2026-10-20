import json
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List

from .checkout import Order, OrderLine

_MONEY_FIELDS = ("subtotal", "discount", "tax", "total")


def order_to_dict(order: Order) -> Dict[str, Any]:
    data: Dict[str, Any] = {"order_id": order.order_id}
    data["lines"] = [
        {
            "sku": line.sku,
            "quantity": line.quantity,
            "unit_price": f"{line.unit_price:.2f}",
            "total": f"{line.total:.2f}",
        }
        for line in order.lines
    ]
    for field in _MONEY_FIELDS:
        data[field] = f"{getattr(order, field):.2f}"
    return data


def order_from_dict(data: Dict[str, Any]) -> Order:
    lines = tuple(
        OrderLine(line["sku"], int(line["quantity"]), Decimal(line["unit_price"]), Decimal(line["total"]))
        for line in data["lines"]
    )
    return Order(order_id=data["order_id"], lines=lines, **{f: Decimal(data[f]) for f in _MONEY_FIELDS})


class OrderRepository:
    def __init__(self, path):
        self.path = Path(path)

    def _load(self) -> List[Dict[str, Any]]:
        if not self.path.exists():
            return []
        return json.loads(self.path.read_text(encoding="utf-8"))

    def save(self, order: Order) -> None:
        records = self._load()
        if any(r["order_id"] == order.order_id for r in records):
            raise ValueError(f"order {order.order_id} already exists")
        records.append(order_to_dict(order))
        self.path.write_text(json.dumps(records, indent=2), encoding="utf-8")

    def get(self, order_id: str) -> Order:
        for record in self._load():
            if record["order_id"] == order_id:
                return order_from_dict(record)
        raise KeyError(order_id)

    def list(self) -> List[Order]:
        return [order_from_dict(r) for r in self._load()]
