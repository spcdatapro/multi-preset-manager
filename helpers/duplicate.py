"""Duplicate a preset under a new name."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from usr.plugins.multi_preset_manager.helpers import backups, groups, presets
from usr.plugins.multi_preset_manager.helpers.errors import PresetError

MAX_NAME_LENGTH = 100


def clean_name(value: Any) -> str:
    if not isinstance(value, str):
        raise PresetError("The new name is required")
    name = value.strip()
    if not name:
        raise PresetError("The new name is required")
    if len(name) > MAX_NAME_LENGTH:
        raise PresetError(f"The name is too long (max {MAX_NAME_LENGTH} characters)")
    if not name.isprintable():
        raise PresetError("The name contains invalid characters")
    return name


def duplicate_preset(source: Any, new_name: Any) -> dict:
    """Copy `source` verbatim under `new_name`, inserted right after it. Never renames silently."""
    name = clean_name(new_name)
    with presets.LOCK:
        current = presets.load()
        index = groups.find_index(current, source)
        if index is None:
            raise PresetError("Source preset not found")
        if groups.find_index(current, name) is not None:
            raise PresetError("A preset with that name already exists")
        clone = deepcopy(current[index])
        clone["name"] = name
        validated = presets.validate([*current[: index + 1], clone, *current[index + 1 :]])

        backup = backups.Backup("duplicate", str(current[index]["name"]))
        backup.add_entry(name, None)
        backup.save()  # if the backup cannot be stored, nothing is written
        try:
            saved = presets.save(validated)
        except BaseException:
            backups.delete(backup.id)
            raise
        stored = groups.find_index(saved, name)
        backup.entries[0]["after"] = presets.preset_hash(saved[stored]) if stored is not None else None
        try:
            backup.save()
        except OSError:
            pass  # without the "after" hash Undo needs force, but the backup itself is intact
    return {"name": name, "source": current[index]["name"], "backup_id": backup.id}
