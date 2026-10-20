"""Errors the shop raises on purpose. See CONTRIBUTING.md, section 2."""


class ShopError(Exception):
    """Base class for every error the shop raises deliberately."""


class InvalidArgument(ShopError, ValueError):
    """An argument has an invalid value."""


class InvalidQuantity(InvalidArgument):
    """A quantity is not a valid int for this operation."""


class OutOfStock(ShopError):
    def __init__(self, sku: str, requested: int, available: int):
        super().__init__(f"{sku}: requested {requested}, only {available} available")
        self.sku = sku
        self.requested = requested
        self.available = available
