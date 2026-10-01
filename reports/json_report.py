"""
JSON report: the machine-readable form of an ``Investigation``.

The payload is ``inv.model_dump(mode="json")`` (ISO-8601 datetimes, enum
values as strings) with a top-level ``schema_version`` key added so
consumers can detect layout changes.  Round-trip::

    data = json.loads(render_json(inv))
    data.pop("schema_version")
    Investigation.model_validate(data)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from core.models import Investigation

SCHEMA_VERSION = "1.0"


def to_dict(inv: Investigation) -> dict[str, Any]:
    """Serialisable dict with ``schema_version`` first, then every model field."""
    return {"schema_version": SCHEMA_VERSION, **inv.model_dump(mode="json")}


def render_json(inv: Investigation, indent: int = 2) -> str:
    """Render the investigation as a JSON string."""
    return json.dumps(to_dict(inv), indent=indent, ensure_ascii=False)


def write_json(inv: Investigation, path: Path | str) -> Path:
    """Write ``report.json`` (parents created) and return the path."""
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_json(inv), encoding="utf-8")
    return out


__all__ = ["SCHEMA_VERSION", "to_dict", "render_json", "write_json"]
