"""Copy settings: preview and apply the transfer of field groups from one preset to others.

Preview and apply share `_compute`. Apply only proceeds if the presets are exactly as the preview
saw them (hash), takes a backup first and then does a single save: all or nothing.
"""

from __future__ import annotations

from typing import Any

from usr.plugins.multi_preset_manager.helpers import backups, diff, groups, presets
from usr.plugins.multi_preset_manager.helpers.errors import PresetError


def _compute(current: list[dict], source: Any, targets: Any, group_ids: Any, kwargs_mode: Any) -> dict:
    planned = groups.plan_copy(current, source, targets, group_ids, kwargs_mode)
    validated = presets.validate(planned)
    before = {p["name"]: p for p in current}
    after = {p["name"]: p for p in validated}
    before_cfg, after_cfg = presets.effective_configs(current), presets.effective_configs(validated)
    effective = {
        name: changes
        for name in after
        if name in before_cfg and (changes := diff.effective_changes(before_cfg[name], after_cfg[name]))
    }
    return {
        "validated": validated,
        "before": before,
        "effective": effective,
        # What is backed up and reported: stored definitions that really change behavior. Saving
        # also normalizes other presets (implicit defaults are dropped), but the framework already
        # ignores those values when resolving, so that is cosmetic and not worth an Undo entry.
        "changed": [name for name, preset in after.items() if name in effective and preset != before.get(name)],
    }


def _summary(computed: dict, targets: list[str]) -> dict:
    target_keys = {str(t).strip().casefold() for t in targets}
    effective = computed["effective"]
    return {
        "changes": [
            {"preset": name, "is_target": name.casefold() in target_keys, "changes": changes}
            for name, changes in effective.items()
        ],
        "unchanged": [t for t in targets if t not in effective],
        "warnings": {
            "default_target": groups.DEFAULT_NAME.casefold() in target_keys,
            "inherited": [name for name in effective if name.casefold() not in target_keys],
            "provider_changed": [n for n, cs in effective.items() if any(c["field"] == "provider" for c in cs)],
            "reindex_embedding": [
                n
                for n, cs in effective.items()
                if any(c["slot"] == "embedding" and c["field"] in ("provider", "name") for c in cs)
            ],
        },
    }


def preview(source: Any, targets: Any, group_ids: Any, kwargs_mode: Any = "merge") -> dict:
    """What applying would change (effective values, redacted). Writes nothing."""
    with presets.LOCK:
        current = presets.load()
        computed = _compute(current, source, targets, group_ids, kwargs_mode)
    return {"hash": presets.presets_hash(current), **_summary(computed, targets)}


def apply(source: Any, targets: Any, group_ids: Any, kwargs_mode: Any, expected_hash: Any) -> dict:
    if not isinstance(expected_hash, str) or not expected_hash:
        raise PresetError("Missing preview hash")
    with presets.LOCK:
        current = presets.load()
        if presets.presets_hash(current) != expected_hash:
            raise PresetError("The presets changed since the preview; preview again")
        computed = _compute(current, source, targets, group_ids, kwargs_mode)
        summary = _summary(computed, targets)
        changed = computed["changed"]
        if not changed:
            return {"changed": [], "backup_id": None, **summary}

        backup = backups.Backup("copy", str(source).strip(), list(group_ids), str(kwargs_mode))
        for name in changed:
            backup.add_entry(name, computed["before"][name])
        backup.save()  # if the backup cannot be stored, nothing is written
        try:
            saved = presets.save(computed["validated"])
        except BaseException:
            backups.delete(backup.id)
            raise
        stored = {p["name"]: p for p in saved}
        for entry in backup.entries:
            preset = stored.get(entry["preset"])
            entry["after"] = presets.preset_hash(preset) if preset is not None else None
        try:
            backup.save()
        except OSError:
            pass  # without "after" hashes Undo needs force, but the backup itself is intact
    return {"changed": changed, "backup_id": backup.id, **summary}
