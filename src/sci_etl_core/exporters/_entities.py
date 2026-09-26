from __future__ import annotations

import dataclasses
from typing import Any


def entity_to_dict(entity: Any) -> dict[str, Any]:
    """Return ``entity`` as a ``dict``.

    A ``dict`` is copied, a Pydantic model is dumped in JSON mode, a dataclass
    instance is converted with :func:`dataclasses.asdict`, and an object with a
    ``to_row`` method, such as a claim, returns that method's mapping.

    Raises:
        TypeError: ``entity`` is none of these.
    """
    if isinstance(entity, dict):
        return dict(entity)
    model_dump = getattr(entity, "model_dump", None)
    if callable(model_dump):
        dumped: dict[str, Any] = model_dump(mode="json")
        return dumped
    to_row = getattr(entity, "to_row", None)
    if callable(to_row):
        return dict(to_row())
    if dataclasses.is_dataclass(entity) and not isinstance(entity, type):
        return dataclasses.asdict(entity)
    raise TypeError(f"Cannot export an entity of type {type(entity).__name__}")
