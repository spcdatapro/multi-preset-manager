from copy import deepcopy
from pathlib import Path

import pytest
import yaml

from plugins._model_config.helpers import model_config
from usr.plugins.multi_preset_manager.helpers import presets
from usr.plugins.multi_preset_manager.helpers.errors import PresetError
from usr.plugins.multi_preset_manager.helpers.groups import GROUP_LIST, GROUPS, catalog, known_fields, plan_copy

import mpr_samples as s

FIELD_GROUPS = [g for g in GROUP_LIST if g.kind != "slot"]


def run(presets_list, groups, targets=("Target",), mode="merge", source="Source"):
    return plan_copy(presets_list, source, list(targets), list(groups), mode)


def by_name(result, name):
    return next(p for p in result if p["name"] == name)


@pytest.mark.parametrize("group", FIELD_GROUPS, ids=lambda g: g.id)
def test_each_group_copies_only_its_own_fields(group):
    data = s.standard()
    target_before = deepcopy(data[2])
    out = run(data, [group.id], mode="replace")
    target = by_name(out, "Target")
    for slot in ("chat", "utility", "embedding"):
        if slot != group.slot:
            assert target[slot] == target_before[slot]
            continue
        for field in set(target_before[slot]) | set(target[slot]):
            expected = data[1][slot].get(field) if field in group.fields else target_before[slot].get(field)
            assert target[slot].get(field) == expected, field
    assert by_name(out, "Source") == data[1] and by_name(out, "Default") == data[0]


def test_input_is_not_mutated():
    data = s.standard()
    snapshot = deepcopy(data)
    run(data, [g.id for g in GROUP_LIST], mode="replace")
    assert data == snapshot


def test_a_field_missing_in_the_source_is_removed_from_the_target_so_it_inherits_like_the_source():
    data = s.standard()
    del data[1]["chat"]["ctx_history"]
    out = run(data, ["chat.context"])
    assert "ctx_history" not in by_name(out, "Target")["chat"]
    assert by_name(out, "Target")["chat"]["ctx_length"] == 300000


def test_default_as_target_keeps_fields_the_source_lacks():
    data = s.standard()
    del data[1]["chat"]["ctx_history"]
    out = run(data, ["chat.context"], targets=["Default"])
    assert by_name(out, "Default")["chat"]["ctx_history"] == 0.75
    assert by_name(out, "Default")["chat"]["ctx_length"] == 300000


def test_kwargs_merge_keeps_target_only_keys_and_source_wins():
    out = run(s.standard(), ["chat.kwargs"], mode="merge")
    assert by_name(out, "Target")["chat"]["kwargs"] == {
        "top_p": 0.5, "thinking": {"type": "enabled"}, "max_tokens": 9000,
    }


def test_kwargs_replace_makes_the_target_identical_to_the_source():
    out = run(s.standard(), ["chat.kwargs"], mode="replace")
    assert by_name(out, "Target")["chat"]["kwargs"] == s.source_preset()["chat"]["kwargs"]


def test_kwargs_replace_with_an_empty_source_clears_the_target():
    data = s.standard()
    del data[1]["chat"]["kwargs"]
    assert "kwargs" not in by_name(run(data, ["chat.kwargs"], mode="replace"), "Target")["chat"]


def test_kwargs_mode_is_only_validated_when_a_kwargs_group_is_selected():
    run(s.standard(), ["chat.context"], mode="bogus")
    with pytest.raises(PresetError, match="kwargs_mode"):
        run(s.standard(), ["chat.kwargs"], mode="bogus")


def test_missing_target_slot_is_materialized_from_default_so_the_copy_takes_effect():
    data = s.standard()
    del data[2]["utility"]
    out = run(data, ["utility.context"])
    assert by_name(out, "Target")["utility"] == {
        "provider": "anthropic", "name": "small-1", "kwargs": {"temperature": 0.2},
        "ctx_length": 64000, "ctx_input": 0.4,
    }
    effective = presets.effective_config(by_name(presets.validate(out), "Target"), by_name(out, "Default"))
    assert effective["utility_model"]["kwargs"] == {"temperature": 0.2}  # inherited behavior preserved
    assert effective["utility_model"]["ctx_length"] == 64000


def test_identityless_target_slot_is_materialized_and_its_ignored_fields_dropped():
    data = s.standard()
    data[2]["utility"] = {"ctx_length": 5}  # ignored by the framework: no provider/name
    out = run(data, ["utility.rate_limits"])
    utility = by_name(out, "Target")["utility"]
    assert utility["provider"] == "anthropic" and "ctx_length" not in utility


def test_nothing_effective_to_change_leaves_the_target_untouched():
    data = s.standard()
    data[2]["utility"] = {"ctx_length": 5}
    del data[1]["utility"]  # source inherits everything; target inherits too: nothing to do
    assert run(data, ["utility.model"]) == data


def test_source_slot_without_identity_copies_what_it_effectively_is():
    data = s.standard()
    del data[1]["utility"]
    out = run(data, ["utility.model", "utility.kwargs"], mode="replace")
    assert by_name(out, "Target")["utility"]["name"] == "small-1"
    assert by_name(out, "Target")["utility"]["kwargs"] == {"temperature": 0.2}


def test_name_only_identity_takes_the_provider_from_default():
    data = s.standard()
    data[1]["utility"] = {"name": "just-a-name"}
    data[2]["utility"]["provider"] = "openai"
    out = run(data, ["utility.model"])
    assert (by_name(out, "Target")["utility"]["provider"], by_name(out, "Target")["utility"]["name"]) == (
        "anthropic", "just-a-name",
    )


def make_other_provider_source():
    data = s.standard()
    data[1]["chat"]["provider"], data[1]["chat"]["name"] = "openai", "gpt-x"
    return data


def test_provider_change_clears_api_base_and_kwargs_which_are_provider_specific():
    out = run(make_other_provider_source(), ["chat.model"])
    chat = by_name(out, "Target")["chat"]
    assert (chat["provider"], chat["name"], chat["api_base"]) == ("openai", "gpt-x", "")
    assert "kwargs" not in chat
    assert chat["ctx_length"] == 111000  # unrelated fields stay


def test_provider_change_with_kwargs_merge_does_not_keep_the_old_providers_keys():
    out = run(make_other_provider_source(), ["chat.model", "chat.kwargs"], mode="merge")
    kwargs = by_name(out, "Target")["chat"]["kwargs"]
    assert kwargs == s.source_preset()["chat"]["kwargs"] and "top_p" not in kwargs


def test_provider_change_with_api_base_selected_copies_it():
    out = run(make_other_provider_source(), ["chat.model", "chat.api_base"])
    assert by_name(out, "Target")["chat"]["api_base"] == "https://proxy.example/v1"


def test_same_provider_leaves_api_base_and_kwargs_alone():
    out = run(s.standard(), ["chat.model"])
    chat = by_name(out, "Target")["chat"]
    assert chat["name"] == "big-2" and chat["api_base"] == "https://old.example" and chat["kwargs"] == {"top_p": 0.5}


def test_vision_sidecar_is_copied_whole_and_removed_when_the_source_has_none():
    data = s.standard()
    assert by_name(run(data, ["vision.slot"]), "Target")["vision"] == s.source_preset()["vision"]
    data[2]["vision"] = {"provider": "anthropic", "name": "old-vision"}
    del data[1]["vision"]
    assert "vision" not in by_name(run(data, ["vision.slot"]), "Target")
    assert "vision" not in by_name(run(data, ["vision.slot"], targets=["Default"]), "Default")


def test_several_targets_and_duplicated_targets_are_handled_once():
    data = [*s.standard(), s.target_preset("Other")]
    out = run(data, ["chat.context"], targets=["Target", "other", "Target"])
    assert by_name(out, "Target")["chat"]["ctx_length"] == 300000 == by_name(out, "Other")["chat"]["ctx_length"]


def test_default_snapshot_is_used_even_if_default_is_also_a_target():
    data = s.standard()
    del data[2]["utility"]
    out = run(data, ["utility.model", "utility.kwargs"], targets=["Default", "Target"], mode="replace")
    assert by_name(out, "Target")["utility"]["name"] == "small-2"


@pytest.mark.parametrize(
    "kwargs, message",
    [
        ({"source": "Nope"}, "Source preset not found"),
        ({"source": 5}, "Source preset not found"),
        ({"targets": []}, "at least one target"),
        ({"targets": "Target"}, "at least one target"),
        ({"targets": ["Nope"]}, "Target preset not found"),
        ({"targets": ["source"]}, "cannot be a target"),
        ({"groups": []}, "at least one group"),
        ({"groups": ["chat.nope"]}, "Unknown group"),
        ({"groups": [3]}, "Unknown group"),
    ],
)
def test_invalid_input_is_rejected(kwargs, message):
    args = {"source": "Source", "targets": ["Target"], "groups": ["chat.context"], **kwargs}
    with pytest.raises(PresetError, match=message):
        plan_copy(s.standard(), args["source"], args["targets"], args["groups"], "merge")


def test_missing_default_is_rejected():
    with pytest.raises(PresetError, match="Default"):
        plan_copy(s.standard()[1:], "Source", ["Target"], ["chat.context"], "merge")


def test_catalog_lists_every_group_once():
    ids = [entry["id"] for entry in catalog()]
    assert ids == [g.id for g in GROUP_LIST] and len(set(ids)) == len(ids) == len(GROUPS)


def test_no_framework_field_is_left_without_a_group():
    """Drift guard: when _model_config adds a slot field, decide which group it belongs to."""
    fallback = Path(model_config.__file__).parents[1] / "mode_presets_fallback.yaml"
    seen = {slot: set() for slot in ("chat", "utility", "embedding")}
    for preset in yaml.safe_load(fallback.read_text(encoding="utf-8")):
        for slot in seen:
            seen[slot] |= set(preset.get(slot) or {})
    for slot, defaults in model_config.IMPLICIT_PRESET_SLOT_DEFAULTS.items():
        if slot in seen:
            seen[slot] |= set(defaults)
    for slot, fields in seen.items():
        assert fields <= known_fields(slot), f"{slot}: {sorted(fields - known_fields(slot))}"
