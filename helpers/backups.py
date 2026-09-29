"""Backups taken before an operation rewrites presets.

One JSON file per operation under usr/multi_preset_manager/backups/ (outside the plugin folder,
mode 0600: it holds the previous preset definitions, which may include api_base and kwargs with
tokens). Only the last MAX_BACKUPS are kept. Nothing here returns preset contents to callers other
than `load`; `summarize` is UI-safe.
"""

from __future__ import annotations

import json
import os
import re
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

from helpers import files

from usr.plugins.multi_preset_manager.helpers.errors import PresetError

BACKUP_DIR_PARTS = ("usr", "multi_preset_manager", "backups")
MAX_BACKUPS = 20
KINDS = ("copy", "duplicate")
_ID_RE = re.compile(r"^\d{8}T\d{12}Z-[0-9a-f]{6}$")


def backups_dir() -> str:
    return files.get_abs_path(*BACKUP_DIR_PARTS)


def _path(backup_id: str) -> str:
    if not isinstance(backup_id, str) or not _ID_RE.match(backup_id):
        raise PresetError("Invalid backup id")
    return os.path.join(backups_dir(), f"{backup_id}.json")


def new_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    return f"{stamp}-{uuid.uuid4().hex[:6]}"


class Backup:
    """A backup being built during an operation."""

    def __init__(self, kind: str, source: str, groups: list[str] | None = None, kwargs_mode: str = ""):
        if kind not in KINDS:
            raise ValueError(f"unknown backup kind: {kind}")
        self.record: dict[str, Any] = {
            "id": new_id(),
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "kind": kind,
            "source": source,
            "groups": list(groups or []),
            "kwargs_mode": kwargs_mode,
            "entries": [],
            "undone_at": None,
        }

    @property
    def id(self) -> str:
        return self.record["id"]

    @property
    def entries(self) -> list[dict[str, Any]]:
        return self.record["entries"]

    def add_entry(self, preset: str, before: dict | None) -> None:
        """`before` is the previous definition, or None when the operation creates the preset."""
        self.entries.append(
            {"preset": preset, "before": deepcopy(before), "after": None, "restored": False}
        )

    def save(self) -> None:
        save_record(self.record)


def save_record(record: dict[str, Any]) -> None:
    """Atomic write, owner-only permissions. Raises OSError if the disk refuses."""
    path = _path(record["id"])
    folder = os.path.dirname(path)
    os.makedirs(folder, exist_ok=True)
    try:
        os.chmod(folder, 0o700)
    except OSError:
        pass  # some bind mounts ignore chmod
    tmp = path + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(record, handle, ensure_ascii=False)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)
    prune()


def load(backup_id: str) -> dict[str, Any]:
    path = _path(backup_id)
    try:
        with open(path, encoding="utf-8") as handle:
            record = json.load(handle)
    except FileNotFoundError:
        raise PresetError("Backup not found") from None
    except (OSError, ValueError):
        raise PresetError("Backup could not be read") from None
    if not isinstance(record, dict) or record.get("id") != backup_id or not isinstance(record.get("entries"), list):
        raise PresetError("Backup is corrupted")
    return record


def exists(backup_id: str) -> bool:
    """Validates the id (PresetError if malformed) and checks the file is there."""
    return os.path.isfile(_path(backup_id))


def _ids() -> list[str]:
    try:
        names = os.listdir(backups_dir())
    except FileNotFoundError:
        return []
    return sorted((n[:-5] for n in names if n.endswith(".json") and _ID_RE.match(n[:-5])), reverse=True)


def list_records() -> list[dict[str, Any]]:
    """Newest first. Unreadable files are skipped."""
    records = []
    for backup_id in _ids():
        try:
            records.append(load(backup_id))
        except PresetError:
            continue
    return records


def delete(backup_id: str) -> None:
    try:
        os.remove(_path(backup_id))
    except FileNotFoundError:
        pass


def delete_all() -> int:
    ids = _ids()
    for backup_id in ids:
        delete(backup_id)
    return len(ids)


def prune() -> None:
    for backup_id in _ids()[MAX_BACKUPS:]:
        delete(backup_id)


def summarize(record: dict[str, Any]) -> dict[str, Any]:
    """UI-safe view of a backup: preset names and group ids only, never any definition."""
    return {
        "id": record["id"],
        "created_at": record.get("created_at", ""),
        "kind": record.get("kind", ""),
        "source": record.get("source", ""),
        "groups": list(record.get("groups", [])),
        "kwargs_mode": record.get("kwargs_mode", ""),
        "undone": bool(record.get("undone_at")),
        "changes": [
            {
                "preset": entry.get("preset", ""),
                "created": entry.get("before") is None,
                "restored": bool(entry.get("restored")),
            }
            for entry in record["entries"]
        ],
    }
