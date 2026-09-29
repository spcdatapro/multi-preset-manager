import json
from pathlib import Path

import pytest

from usr.plugins.multi_preset_manager.helpers import backups, copy_settings, presets
from usr.plugins.multi_preset_manager.helpers.errors import PresetError

import mpr_samples as s


def seed(tree, extra=()):
    tree.write([*s.standard(), *extra])
    return presets.presets_hash(presets.load())


def do_preview(groups=("chat.context",), targets=("Target",), mode="merge"):
    return copy_settings.preview("Source", list(targets), list(groups), mode)


def do_apply(expected, groups=("chat.context",), targets=("Target",), mode="merge"):
    return copy_settings.apply("Source", list(targets), list(groups), mode, expected)


def backup_files(tree):
    folder = Path(backups.backups_dir())
    return sorted(folder.glob("*.json")) if folder.exists() else []


def test_preview_reports_effective_changes_and_writes_nothing(tree):
    digest = seed(tree)
    before = tree.raw()
    result = do_preview(["chat.context", "utility.kwargs"], mode="replace")
    assert result["hash"] == digest
    assert [c["preset"] for c in result["changes"]] == ["Target"] and result["changes"][0]["is_target"]
    fields = {(c["slot"], c["field"]): (c["before"], c["after"]) for c in result["changes"][0]["changes"]}
    assert fields[("chat", "ctx_length")] == (111000, 300000)
    assert fields[("utility", "kwargs.temperature")] == (0.1, 0.9)
    assert result["unchanged"] == [] and result["warnings"]["reindex_embedding"] == []
    assert tree.raw() == before and backup_files(tree) == []


def test_apply_changes_only_the_chosen_groups_of_the_targets_and_takes_a_backup(tree):
    digest = seed(tree)
    original = tree.stored()
    result = do_apply(digest)
    assert result["changed"] == ["Target"] and result["backup_id"]
    stored = {p["name"]: p for p in tree.stored()}
    assert stored["Target"]["chat"]["ctx_length"] == 300000 and stored["Target"]["chat"]["ctx_history"] == 0.5
    assert stored["Target"]["chat"]["api_base"] == "https://old.example"
    assert stored["Source"] == original[1] and stored["Default"] == original[0]
    record = backups.load(result["backup_id"])
    entry = record["entries"][0]
    assert entry["preset"] == "Target" and entry["before"] == original[2]
    assert entry["after"] == presets.preset_hash(stored["Target"])
    assert record["kind"] == "copy" and record["groups"] == ["chat.context"] and record["source"] == "Source"


def test_apply_refuses_when_the_presets_changed_since_the_preview(tree):
    digest = seed(tree)
    other = presets.load()
    other[2]["chat"]["name"] = "edited-in-the-native-editor"
    tree.write(other)
    before = tree.raw()
    with pytest.raises(PresetError, match="preview again"):
        do_apply(digest)
    assert tree.raw() == before and backup_files(tree) == []


@pytest.mark.parametrize("bad", [None, "", 5])
def test_apply_requires_the_preview_hash(tree, bad):
    seed(tree)
    with pytest.raises(PresetError, match="preview hash"):
        do_apply(bad)


def test_apply_with_nothing_to_change_makes_no_backup_and_no_write(tree):
    digest = seed(tree)
    do_apply(digest)
    digest = presets.presets_hash(presets.load())
    before = tree.raw()
    result = do_apply(digest)
    assert result["changed"] == [] and result["backup_id"] is None and result["unchanged"] == ["Target"]
    assert tree.raw() == before and len(backup_files(tree)) == 1


def test_secrets_never_reach_previews_results_or_summaries(tree):
    data = s.standard()
    data[1]["chat"]["kwargs"] = {"extra_headers": {"Authorization": f"Bearer {s.SECRET}"}, "api_key": s.SECRET}
    data[1]["chat"]["api_base"] = f"https://user:{s.SECRET}@host.example/v1?token={s.SECRET}"
    tree.write(data)
    digest = presets.presets_hash(presets.load())
    groups = ["chat.kwargs", "chat.api_base"]
    preview = do_preview(groups)
    assert preview["changes"] and s.SECRET not in json.dumps(preview)
    result = do_apply(digest, groups)
    assert s.SECRET not in json.dumps(result)
    assert s.SECRET not in json.dumps(backups.summarize(backups.load(result["backup_id"])))
    assert s.SECRET in tree.raw().decode()  # the real value was copied, on the server


def test_embedding_change_warns_and_is_announced(tree):
    digest = seed(tree)
    preview = do_preview(["embedding.model"])
    assert preview["warnings"]["reindex_embedding"] == ["Target"]
    do_apply(digest, ["embedding.model"])
    assert tree.notified == [1]


def test_chat_only_change_does_not_touch_the_embedding(tree):
    digest = seed(tree)
    assert do_preview()["warnings"]["reindex_embedding"] == []
    do_apply(digest)
    assert tree.notified == []


def test_rate_limit_change_of_an_embedding_is_announced_but_needs_no_reindex_warning(tree):
    digest = seed(tree)
    assert do_preview(["embedding.rate_limits"])["warnings"]["reindex_embedding"] == []
    do_apply(digest, ["embedding.rate_limits"])
    assert tree.notified == [1]  # the framework compares the whole embedding config


def test_targeting_default_lists_the_presets_that_inherit_the_change(tree):
    digest = seed(tree, [s.lean_preset()])
    preview = do_preview(["utility.context"], targets=["Default"])
    assert preview["warnings"]["default_target"] is True
    assert preview["warnings"]["inherited"] == ["Lean"]
    assert {c["preset"] for c in preview["changes"]} == {"Default", "Lean"}
    result = do_apply(digest, ["utility.context"], targets=["Default"])
    assert result["changed"] == ["Default"]


def test_provider_change_is_reported(tree):
    data = s.standard()
    data[1]["chat"]["provider"], data[1]["chat"]["name"] = "openai", "gpt-x"
    tree.write(data)
    result = do_preview(["chat.model"])
    assert result["warnings"]["provider_changed"] == ["Target"]
    fields = {c["field"]: c["after"] for c in result["changes"][0]["changes"]}
    assert fields["provider"] == "openai" and fields["kwargs.top_p"] is None


def test_framework_drops_values_equal_to_its_implicit_defaults(tree):
    """Canary: a copied utility ctx_length of 128000 is stored as "inherit", so a Default with
    another value wins. If the framework changes this, the CLAUDE.md rule needs revisiting."""
    data = s.standard()
    data[1]["utility"]["ctx_length"] = 128000
    tree.write(data)
    digest = presets.presets_hash(presets.load())
    result = do_apply(digest, ["utility.context"])
    assert result["changed"] == ["Target"]
    assert "ctx_length" not in tree.by_name("Target")["utility"]
    effective = presets.effective_configs(presets.load())["Target"]
    assert effective["utility_model"]["ctx_length"] == 150000  # Default's, not 128000


def test_cosmetic_normalization_of_other_presets_is_neither_reported_nor_backed_up(tree):
    """Any save rewrites the whole file through validate_presets, dropping implicit-default values
    (here a utility ctx_length of 128000) from presets that are not Default. The framework already
    ignores them when resolving, so nothing effective changes for that preset."""
    legacy = s.target_preset("Legacy")
    legacy["utility"]["ctx_length"] = 128000
    digest = seed(tree, [legacy])
    effective_before = presets.effective_configs(presets.load())["Legacy"]
    preview = do_preview()
    assert [c["preset"] for c in preview["changes"]] == ["Target"] and preview["warnings"]["inherited"] == []
    result = do_apply(digest)
    assert result["changed"] == ["Target"]
    assert [e["preset"] for e in backups.load(result["backup_id"])["entries"]] == ["Target"]
    assert "ctx_length" not in tree.by_name("Legacy")["utility"]  # normalized by the save...
    assert presets.effective_configs(presets.load())["Legacy"] == effective_before  # ...harmlessly


def test_a_copy_with_no_effective_change_writes_nothing_and_takes_no_backup(tree):
    data = s.standard()
    data[2]["utility"]["ctx_length"] = 128000  # ignored by the framework: Target inherits 150000
    del data[1]["utility"]["ctx_length"]  # Source inherits it too
    data[1]["utility"]["ctx_input"] = data[2]["utility"]["ctx_input"]
    tree.write(data)
    digest = presets.presets_hash(presets.load())
    before = tree.raw()
    assert do_preview(["utility.context"])["changes"] == []
    result = do_apply(digest, ["utility.context"])
    assert result["changed"] == [] and result["backup_id"] is None and result["unchanged"] == ["Target"]
    assert tree.raw() == before and backup_files(tree) == []


def test_a_backup_that_cannot_be_stored_blocks_the_write(tree, monkeypatch):
    digest = seed(tree)
    before = tree.raw()

    def refuse(self):
        raise OSError("disk full")

    monkeypatch.setattr(backups.Backup, "save", refuse)
    with pytest.raises(OSError):
        do_apply(digest)
    assert tree.raw() == before


def test_a_failed_save_removes_its_backup_and_leaves_the_file_alone(tree, monkeypatch):
    digest = seed(tree)
    before = tree.raw()

    def boom(new):
        raise RuntimeError("write failed")

    monkeypatch.setattr(presets, "save", boom)
    with pytest.raises(RuntimeError):
        do_apply(digest)
    assert tree.raw() == before and backup_files(tree) == []


def test_invalid_input_writes_nothing(tree):
    digest = seed(tree)
    before = tree.raw()
    for args in (("Nope", ["Target"], ["chat.context"]), ("Source", ["Source"], ["chat.context"]),
                 ("Source", ["Target"], ["nope"])):
        with pytest.raises(PresetError):
            copy_settings.apply(*args, "merge", digest)
    assert tree.raw() == before and backup_files(tree) == []
