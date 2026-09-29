"""History: list, undo and delete the backups taken before each operation.

Undo restores the previous definition of every preset the operation changed (or removes the ones it
created). A preset that changed since the operation is a conflict: it is skipped and reported, and
`force` restores it anyway. A second call only processes what is still pending.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

from usr.plugins.multi_preset_manager.helpers import backups, groups, presets
from usr.plugins.multi_preset_manager.helpers.errors import PresetError


def list_history() -> list[dict]:
    return [backups.summarize(record) for record in backups.list_records()]


def delete_backup(backup_id: Any) -> None:
    with presets.LOCK:
        if not backups.exists(backup_id):
            raise PresetError("Backup not found")
        backups.delete(backup_id)


def delete_all() -> int:
    with presets.LOCK:
        return backups.delete_all()


def _conflict(entry: dict, current: dict | None) -> str | None:
    """Why this entry cannot be restored blindly, or None if the preset is as the operation left it."""
    if entry.get("before") is None:  # created by the operation: nothing to lose if it is gone
        if current is None:
            return None
    elif current is None:
        return "missing"
    after = entry.get("after")
    return None if after is not None and presets.preset_hash(current) == after else "changed"


def undo(backup_id: Any, force: bool = False) -> dict:
    with presets.LOCK:
        record = backups.load(backup_id)
        if record.get("undone_at"):
            raise PresetError("This operation was already undone")
        working = presets.load()
        results: list[dict[str, Any]] = []
        pending_write = False
        for entry in record["entries"]:
            if entry.get("restored"):
                continue
            name = entry["preset"]
            index = groups.find_index(working, name)
            current = working[index] if index is not None else None
            conflict = _conflict(entry, current)
            if conflict and not force:
                results.append({"preset": name, "ok": False, "action": "skipped", "conflict": conflict})
                continue
            before = entry.get("before")
            if before is None:
                action = "removed" if current is not None else "already removed"
                if current is not None:
                    working.pop(index)
                    pending_write = True
            else:
                action = "restored"
                if index is None:
                    working.append(deepcopy(before))
                else:
                    working[index] = deepcopy(before)
                pending_write = True
            entry["restored"] = True
            results.append({"preset": name, "ok": True, "action": action, "conflict": conflict})

        if pending_write:
            presets.save(presets.validate(working))
        if all(entry.get("restored") for entry in record["entries"]):
            record["undone_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        backups.save_record(record)
    return {
        "ok": all(r["ok"] for r in results),
        "results": results,
        "undone": bool(record.get("undone_at")),
        "has_conflicts": any(r["conflict"] and not r["ok"] for r in results),
    }
