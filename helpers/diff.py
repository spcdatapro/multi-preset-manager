"""Effective differences between two resolved preset configs, safe to show in the UI.

Values are redacted: kwargs and api_base can carry tokens (keys never live in presets, but headers,
URLs with credentials or `api_key`-like kwargs can). A changed sensitive value shows as "***".
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlsplit, urlunsplit

MASK = "***"
_SECTIONS = {"chat_model": "chat", "utility_model": "utility", "embedding_model": "embedding", "vision_model": "vision"}
_SENSITIVE = re.compile(
    r"api[_-]?key|secret|passw(or)?d|authorization|bearer|credential|cookie|private[_-]?key|(^|[_.-])(token|key)$",
    re.IGNORECASE,
)


def _clean_url(value: str) -> str:
    """Drop credentials and query string from anything that looks like a URL."""
    if "://" not in value:
        return value
    try:
        parts = urlsplit(value)
    except ValueError:
        return MASK
    if not (parts.username or parts.password or parts.query):
        return value
    host = parts.hostname or ""
    if parts.port:
        host = f"{host}:{parts.port}"
    return urlunsplit((parts.scheme, host, parts.path, "", ""))


def redact(key: str, value: Any) -> Any:
    if value is None:
        return None
    if _SENSITIVE.search(key):
        return MASK
    if isinstance(value, dict):
        return {k: redact(str(k), v) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(key, item) for item in value]
    if isinstance(value, str):
        return _clean_url(value)
    return value


def _norm(value: Any) -> Any:
    return None if value in (None, "") else value


def _flatten(section: dict) -> dict[str, Any]:
    flat = {k: v for k, v in section.items() if k not in ("api_key", "kwargs") and not k.startswith("_")}
    kwargs = section.get("kwargs")
    if isinstance(kwargs, dict):
        flat.update({f"kwargs.{k}": v for k, v in kwargs.items()})
    return flat


def effective_changes(before: dict, after: dict) -> list[dict[str, Any]]:
    """Field-level changes between two configs from presets.effective_config."""
    changes = []
    for section, slot in _SECTIONS.items():
        old, new = _flatten(before.get(section) or {}), _flatten(after.get(section) or {})
        for field in sorted(set(old) | set(new)):
            if _norm(old.get(field)) != _norm(new.get(field)):
                changes.append(
                    {"slot": slot, "field": field, "before": redact(field, old.get(field)), "after": redact(field, new.get(field))}
                )
    return changes
