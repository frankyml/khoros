"""In-memory audit log of stock changes. See CONTRIBUTING.md, section 1."""

from typing import Any, Dict, List

_LOG: List[Dict[str, Any]] = []


def emit(kind: str, **fields: Any) -> None:
    _LOG.append({"kind": kind, **fields})


def events() -> List[Dict[str, Any]]:
    return list(_LOG)


def clear() -> None:
    _LOG.clear()
