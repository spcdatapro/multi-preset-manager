"""Field groups that "Copy settings" can transfer, and the pure logic that applies them.

Works on plain preset dicts (the shape of presets.yaml) and never touches the disk: presets.py
owns that. Inheritance rules it relies on (from plugins/_model_config): a non-Default preset
inherits omitted fields from Default, a slot without provider/name is ignored as a whole, and
`kwargs` and `vision` are never inherited.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from usr.plugins.multi_preset_manager.helpers.errors import PresetError

DEFAULT_NAME = "Default"
KWARGS_MODES = ("merge", "replace")
SLOT_LABELS = {
    "chat": "Main model",
    "utility": "Utility model",
    "embedding": "Embedding model",
    "vision": "Vision sidecar",
}


@dataclass(frozen=True)
class Group:
    id: str
    slot: str
    label: str
    kind: str  # "model" | "fields" | "kwargs" | "slot"
    fields: tuple[str, ...] = ()


_RATE_LIMITS = ("rl_requests", "rl_input", "rl_output")

# Order matters: within a slot, "model" is applied first so the provider change can be detected.
GROUP_LIST = (
    Group("chat.model", "chat", "Model", "model", ("provider", "name")),
    Group("chat.api_base", "chat", "API base", "fields", ("api_base",)),
    Group("chat.context", "chat", "Context", "fields", ("ctx_length", "ctx_history")),
    Group("chat.vision", "chat", "Vision input", "fields", ("vision", "max_embeds")),
    Group("chat.rate_limits", "chat", "Rate limits", "fields", _RATE_LIMITS),
    Group("chat.kwargs", "chat", "Additional parameters", "kwargs", ("kwargs",)),
    Group("utility.model", "utility", "Model", "model", ("provider", "name")),
    Group("utility.api_base", "utility", "API base", "fields", ("api_base",)),
    Group("utility.context", "utility", "Context", "fields", ("ctx_length", "ctx_input")),
    Group("utility.rate_limits", "utility", "Rate limits", "fields", _RATE_LIMITS),
    Group("utility.kwargs", "utility", "Additional parameters", "kwargs", ("kwargs",)),
    Group("embedding.model", "embedding", "Model", "model", ("provider", "name")),
    Group("embedding.api_base", "embedding", "API base", "fields", ("api_base",)),
    Group("embedding.rate_limits", "embedding", "Rate limits", "fields", ("rl_requests", "rl_input")),
    Group("embedding.kwargs", "embedding", "Additional parameters", "kwargs", ("kwargs",)),
    Group("vision.slot", "vision", "Whole slot", "slot"),
)
GROUPS = {group.id: group for group in GROUP_LIST}


def catalog() -> list[dict[str, str]]:
    """What the UI renders: every group with its slot."""
    return [
        {"id": g.id, "slot": g.slot, "slot_label": SLOT_LABELS[g.slot], "label": g.label, "kind": g.kind}
        for g in GROUP_LIST
    ]


def known_fields(slot: str) -> set[str]:
    """Slot fields covered by some group (used by the drift test against the framework)."""
    return {field for g in GROUP_LIST if g.slot == slot for field in g.fields}


def has_identity(slot: Any) -> bool:
    return isinstance(slot, dict) and bool(slot.get("provider") or slot.get("name"))


def find_index(presets: list[dict], name: Any) -> int | None:
    if not isinstance(name, str):
        return None
    wanted = name.strip().casefold()
    for index, preset in enumerate(presets):
        if str(preset.get("name") or "").strip().casefold() == wanted:
            return index
    return None


def _resolve_groups(group_ids: Any) -> list[Group]:
    if not isinstance(group_ids, list) or not group_ids:
        raise PresetError("Choose at least one group to copy")
    selected: set[str] = set()
    for group_id in group_ids:
        if not isinstance(group_id, str) or group_id not in GROUPS:
            raise PresetError("Unknown group")
        selected.add(group_id)
    return [group for group in GROUP_LIST if group.id in selected]


def _resolve_targets(presets: list[dict], targets: Any, source_index: int) -> list[int]:
    if not isinstance(targets, list) or not targets:
        raise PresetError("Choose at least one target preset")
    indexes: list[int] = []
    for name in targets:
        index = find_index(presets, name)
        if index is None:
            raise PresetError("Target preset not found")
        if index == source_index:
            raise PresetError("The source preset cannot be a target")
        if index not in indexes:
            indexes.append(index)
    return indexes


def _identity(slot: dict, default_slot: dict) -> tuple[str, str]:
    """Effective provider and name of a slot with identity (omitted parts come from Default)."""
    return (
        str(slot.get("provider") or default_slot.get("provider") or ""),
        str(slot.get("name") or default_slot.get("name") or ""),
    )


def _materialized(default_slot: dict) -> dict:
    """What a slot effectively is when it is missing or ignored: Default's identity and kwargs."""
    base = {key: deepcopy(default_slot[key]) for key in ("provider", "name") if default_slot.get(key)}
    kwargs = default_slot.get("kwargs")
    if isinstance(kwargs, dict) and kwargs:
        base["kwargs"] = deepcopy(kwargs)
    return base


def _apply_kwargs(new: dict, source_slot: dict, mode: str, start_empty: bool) -> None:
    source_kwargs = source_slot.get("kwargs") if isinstance(source_slot.get("kwargs"), dict) else {}
    if mode == "replace":
        merged = deepcopy(source_kwargs)
    else:
        current = new.get("kwargs") if isinstance(new.get("kwargs"), dict) else {}
        merged = {**({} if start_empty else deepcopy(current)), **deepcopy(source_kwargs)}
    if merged:
        new["kwargs"] = merged
    else:
        new.pop("kwargs", None)


def _apply_slot(
    target: dict, slot: str, groups: list[Group], source: dict, default: dict, mode: str, is_default: bool
) -> None:
    default_slot = default.get(slot) if isinstance(default.get(slot), dict) else {}
    original = target.get(slot)
    source_slot = source[slot] if has_identity(source.get(slot)) else _materialized(default_slot)
    # A missing or identity-less slot is ignored by the framework, so it effectively equals
    # Default's: materialize that first or the copied fields would have no effect (or kwargs
    # inherited from Default would be lost).
    new = deepcopy(original) if has_identity(original) else _materialized(default_slot)
    baseline = deepcopy(new)
    provider_before = _identity(new, default_slot)[0]

    model_selected = any(g.kind == "model" for g in groups)
    if model_selected:
        provider, name = _identity(source_slot, default_slot)
        if provider:
            new["provider"] = provider
        if name:
            new["name"] = name
    provider_changed = model_selected and _identity(new, default_slot)[0].casefold() != provider_before.casefold()

    api_base_copied = False
    kwargs_copied = False
    for group in groups:
        if group.kind == "fields":
            for field in group.fields:
                if field in source_slot:
                    new[field] = deepcopy(source_slot[field])
                elif not is_default:  # Default cannot fall back to itself: keep what it has
                    new.pop(field, None)
            api_base_copied = api_base_copied or "api_base" in group.fields
        elif group.kind == "kwargs":
            _apply_kwargs(new, source_slot, mode, start_empty=provider_changed)
            kwargs_copied = True

    if provider_changed:  # both are provider-specific and must not leak across providers
        if not (api_base_copied and "api_base" in source_slot):
            new["api_base"] = ""
        if not kwargs_copied:
            new.pop("kwargs", None)

    if new != baseline:
        target[slot] = new


def _apply_vision(target: dict, source: dict) -> None:
    if has_identity(source.get("vision")):
        target["vision"] = deepcopy(source["vision"])
    else:
        target.pop("vision", None)


def plan_copy(
    presets: list[dict], source: str, targets: list[str], group_ids: list[str], kwargs_mode: str = "merge"
) -> list[dict]:
    """Return a copy of `presets` with the chosen groups of `source` applied to every target.

    Not validated or cleaned: pass the result through presets.validate. The input is not mutated.
    """
    if not isinstance(presets, list):
        raise PresetError("Presets must be a list")
    groups = _resolve_groups(group_ids)
    if any(g.kind == "kwargs" for g in groups) and kwargs_mode not in KWARGS_MODES:
        raise PresetError("kwargs_mode must be 'merge' or 'replace'")
    source_index = find_index(presets, source)
    if source_index is None:
        raise PresetError("Source preset not found")
    target_indexes = _resolve_targets(presets, targets, source_index)
    default_index = find_index(presets, DEFAULT_NAME)
    if default_index is None:
        raise PresetError("The Default preset is missing")

    result = deepcopy(presets)
    source_preset = deepcopy(presets[source_index])
    default_before = deepcopy(presets[default_index])  # snapshot: Default may be a target too
    for index in target_indexes:
        target = result[index]
        is_default = index == default_index
        for slot in ("chat", "utility", "embedding"):
            slot_groups = [g for g in groups if g.slot == slot]
            if slot_groups:
                _apply_slot(target, slot, slot_groups, source_preset, default_before, kwargs_mode, is_default)
        if any(g.kind == "slot" for g in groups):
            _apply_vision(target, source_preset)
    return result
