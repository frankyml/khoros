# Contributing to shop

Read this before changing code. CI and the audit team rely on these rules.

## 1. Every stock change is audited

Each method that changes an `Inventory` emits exactly one event per inventory it changes, through `shop.events.emit(kind, **fields)`:

- `kind` is `stock.<method name in the past tense>`: `restock` emits `stock.restocked`, `take` emits `stock.taken`.
- Fields: `sku`; every other argument of the method under its parameter name, except `Inventory` objects; and `on_hand`, that inventory's units after the change.
- Emit only after the change has succeeded. An operation that fails changes nothing and emits nothing.

## 2. Errors

Raise subclasses of `shop.errors.ShopError`, choosing the most specific one: `InvalidQuantity` for a bad quantity, `InvalidArgument` for any other bad argument value, `OutOfStock` when there are not enough units.

## 3. Quantities

Quantities are `int` and greater than zero unless the method documents otherwise. `bool` is not a quantity.

## 4. Money

Money is always `Decimal`; see `money.py`.
