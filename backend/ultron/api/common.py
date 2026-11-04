"""Utilidades de serialização para a API."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.inspection import inspect


def iso(dt: datetime | None) -> str | None:
    return dt.isoformat() + "Z" if dt else None


def row(obj: Any, exclude: tuple[str, ...] = ()) -> dict:
    out = {}
    for attr in inspect(obj).mapper.column_attrs:
        k = attr.key
        if k in exclude:
            continue
        v = getattr(obj, k)
        out[k] = iso(v) if isinstance(v, datetime) else v
    return out
