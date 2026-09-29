import json

import pytest

from usr.plugins.multi_preset_manager.helpers import presets
from usr.plugins.multi_preset_manager.helpers.errors import PresetError

import mpr_samples as s


def test_hash_is_stable_and_sensitive_to_any_change(tree):
    tree.write(s.standard())
    first = presets.presets_hash(presets.load())
    assert first == presets.presets_hash(presets.load())
    changed = presets.load()
    changed[2]["chat"]["kwargs"]["top_p"] = 0.6
    assert presets.presets_hash(changed) != first
    assert presets.preset_hash(changed[2]) != presets.preset_hash(presets.load()[2])


def test_effective_config_resolves_inheritance_like_the_framework(tree):
    tree.write([*s.standard(), s.lean_preset()])
    loaded = presets.load()
    configs = presets.effective_configs(loaded)
    lean = configs["Lean"]
    assert lean["chat_model"]["name"] == "lean-1"
    assert lean["chat_model"]["ctx_length"] == 200000  # inherited from Default
    assert lean["chat_model"]["kwargs"] == {}  # kwargs are never inherited
    assert lean["utility_model"]["name"] == "small-1" and lean["utility_model"]["kwargs"] == {"temperature": 0.2}
    assert configs["Default"]["chat_model"]["kwargs"] == {"max_tokens": 4000}


def test_save_writes_through_the_framework_and_strips_api_keys(tree):
    tree.write(s.standard())
    new = presets.load()
    new[2]["chat"]["api_key"] = s.SECRET
    presets.save(presets.validate(new))
    assert s.SECRET not in tree.raw().decode()


def test_save_repairs_references_to_a_preset_that_disappears(tree):
    tree.write(s.standard())
    config = tree.select("p1", "Target")
    new = [p for p in presets.load() if p["name"] != "Target"]
    presets.save(presets.validate(new))
    assert json.loads(config.read_text(encoding="utf-8")) == {"model_preset": "Default"}


def test_save_keeps_references_to_presets_that_survive(tree):
    tree.write(s.standard())
    config = tree.select("p1", "Source")
    presets.save(presets.validate(presets.load()))
    assert json.loads(config.read_text(encoding="utf-8")) == {"model_preset": "Source"}


def test_save_announces_embedding_changes_only(tree):
    tree.write(s.standard())
    new = presets.load()
    new[2]["chat"]["ctx_length"] = 99999
    presets.save(presets.validate(new))
    assert tree.notified == []
    new = presets.load()
    new[2]["embedding"]["name"] = "another-embedding"
    presets.save(presets.validate(new))
    assert tree.notified == [1]


def test_invalid_collections_raise_a_user_error_and_write_nothing(tree):
    tree.write(s.standard())
    before = tree.raw()
    duplicated = presets.load() + [s.target_preset("target")]
    with pytest.raises(PresetError, match="unique"):
        presets.validate(duplicated)
    with pytest.raises(PresetError, match="Default"):
        presets.save([p for p in presets.load() if p["name"] != "Default"])
    assert tree.raw() == before


def test_overview_lists_effective_models_and_hides_everything_else(tree):
    data = s.standard()
    data[2]["chat"]["kwargs"] = {"api_key": s.SECRET}
    data[2]["chat"]["api_base"] = f"https://u:{s.SECRET}@host.example"
    tree.write([*data, s.lean_preset()])
    view = presets.overview()
    assert [p["name"] for p in view["presets"]] == ["Default", "Source", "Target", "Lean"]
    assert view["presets"][0]["is_default"] and not view["presets"][1]["is_default"]
    lean = view["presets"][3]
    assert lean["main"] == "anthropic/lean-1" and lean["utility"] == "anthropic/small-1"
    assert view["presets"][1]["vision"] == "anthropic/vis-1" and lean["vision"] == ""
    assert view["hash"] == presets.presets_hash(presets.load())
    assert s.SECRET not in json.dumps(view)
