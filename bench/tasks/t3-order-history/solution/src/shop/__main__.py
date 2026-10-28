import argparse
import sys
from decimal import Decimal

from .cart import Cart
from .checkout import checkout
from .inventory import Inventory
from .models import Product
from .money import format_money
from .orders import OrderRepository


def cmd_demo(args) -> int:
    cart = Cart()
    cart.add(Product("TEA", "Green tea", Decimal("4.50")), 2)
    cart.add(Product("MUG", "Mug", Decimal("9.99")))
    print_receipt(checkout(cart, Inventory({"TEA": 10, "MUG": 3}), order_id="demo"))
    return 0


def print_receipt(order) -> None:
    for line in order.lines:
        print(f"{line.quantity} x {line.sku} @ {format_money(line.unit_price)} = {format_money(line.total)}")
    print(f"TOTAL {format_money(order.total)}")


def cmd_orders(args) -> int:
    repo = OrderRepository(args.db)
    if args.show:
        try:
            order = repo.get(args.show)
        except KeyError:
            print(f"unknown order: {args.show}", file=sys.stderr)
            return 1
        print_receipt(order)
        return 0
    for order in repo.list():
        print(f"{order.order_id} {format_money(order.total)}")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="shop")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("demo", help="Check out a sample cart and print the receipt").set_defaults(func=cmd_demo)
    orders = sub.add_parser("orders", help="List saved orders or show one receipt")
    orders.add_argument("--db", required=True, help="Path to the orders JSON file")
    orders.add_argument("--show", metavar="ORDER_ID", help="Print the receipt for one order")
    orders.set_defaults(func=cmd_orders)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
