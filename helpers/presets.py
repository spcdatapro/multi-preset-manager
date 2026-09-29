"""Access to the global model presets, through the framework's own helpers.

Presets live in one file and saving replaces the whole list, so every operation of this plugin runs
under LOCK as read -> change in memory -> validate -> one save. The save repeats what the native
editor does (plugins/_model_config/api/model_presets.py, action "save"): repair references to
removed presets and announce embedding changes. Nothing here writes presets.yaml directly.
"""

from __future__ import annotations

import hashlib
import json
import threading
from typing import Any

from plugins._model_config.helpers import model_config

from usr.plugins.multi_preset_manager.helpers.errors import PresetError

LOCK = threading.RLock()


def _framework():
    # Lazy: the API module pulls in the whole agent runtime.
    from plugins._model_config.api import model_presets

    return model_presets


def _notify_embedding_changed() -> None:
    _framework()._notify_embedding_changed()


def load() -> list[dict]:
    """Fresh deep copy of the global presets, Default first."""
    return model_config.get_presets()


def validate(presets: list[dict]) -> list[dict]:
    try:
        return model_config.validate_presets(presets)
    except ValueError as error:
        raise PresetError(str(error)) from None


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")).hexdigest()


def presets_hash(presets: list[dict]) -> str:
    return digest(presets)


def preset_hash(preset: dict) -> str:
    return digest(preset)


def effective_config(preset: dict, default: dict) -> dict:
    """The runtime model config a preset resolves to (same inheritance as the framework)."""
    config = model_config.preset_to_config(default)
    if str(preset.get("name") or "") != model_config.DEFAULT_PRESET_NAME:
        config = model_config.build_config_from_preset(preset, config, strip_api_key=False)
    return config


def effective_configs(presets: list[dict]) -> dict[str, dict]:
    default = next((p for p in presets if p.get("name") == model_config.DEFAULT_PRESET_NAME), {})
    return {str(p.get("name") or ""): effective_config(p, default) for p in presets}


def save(new_presets: list[dict]) -> list[dict]:
    """Save the whole collection with the native editor's side effects. Caller holds LOCK.

    Returns the presets as stored (re-read from disk).
    """
    api = _framework()
    previous = model_config.get_presets()
    previous_names = {str(p.get("name") or "") for p in previous}
    previous_embeddings = api._embedding_signatures(previous)
    try:
        model_config.save_presets(new_presets)
    except ValueError as error:
        raise PresetError(str(error)) from None
    saved = model_config.get_presets()
    saved_names = {str(p.get("name") or "") for p in saved}
    api._rename_preset_references(api._retired_preset_references(previous_names, saved_names))
    if previous_embeddings != api._embedding_signatures(saved):
        _notify_embedding_changed()
    return saved


def model_label(section: dict) -> str:
    provider, name = str(section.get("provider") or ""), str(section.get("name") or "")
    return f"{provider}/{name}" if provider and name else provider or name


def overview() -> dict:
    """What the UI needs to list presets. Model names only: no kwargs, api_base or keys."""
    presets = load()
    configs = effective_configs(presets)
    return {
        "hash": presets_hash(presets),
        "presets": [
            {
                "name": str(p.get("name") or ""),
                "is_default": p.get("name") == model_config.DEFAULT_PRESET_NAME,
                "main": model_label(configs[str(p.get("name") or "")].get("chat_model") or {}),
                "utility": model_label(configs[str(p.get("name") or "")].get("utility_model") or {}),
                "embedding": model_label(configs[str(p.get("name") or "")].get("embedding_model") or {}),
                "vision": model_label(configs[str(p.get("name") or "")].get("vision_model") or {}),
            }
            for p in presets
        ],
    }
