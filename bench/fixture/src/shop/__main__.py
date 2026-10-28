import argparse
import sys
from decimal import Decimal

from .cart import Cart
from .checkout import checkout
from .inventory import Inventory
from .models import Product
from .money import format_money


def cmd_demo(args) -> int:
    cart = Cart()
    cart.add(Product("TEA", "Green tea", Decimal("4.50")), 2)
    cart.add(Product("MUG", "Mug", Decimal("9.99")))
    order = checkout(cart, Inventory({"TEA": 10, "MUG": 3}), order_id="demo")
    for line in order.lines:
        print(f"{line.quantity} x {line.sku} @ {format_money(line.unit_price)} = {format_money(line.total)}")
    print(f"TOTAL {format_money(order.total)}")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="shop")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("demo", help="Check out a sample cart and print the receipt").set_defaults(func=cmd_demo)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
