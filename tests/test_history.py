import json

import pytest

from usr.plugins.multi_preset_manager.helpers import backups, copy_settings, duplicate, history, presets
from usr.plugins.multi_preset_manager.helpers.errors import PresetError

import mpr_samples as s


def copy(groups=("chat.context",), targets=("Target",), mode="merge"):
    digest = presets.presets_hash(presets.load())
    return copy_settings.apply("Source", list(targets), list(groups), mode, digest)


def edit_after(tree, name, field, value):
    """Simulates a later change made elsewhere (the native editor, another operation)."""
    current = presets.load()
    next(p for p in current if p["name"] == name)["chat"][field] = value
    tree.write(current)


def test_undo_restores_exactly_what_the_operation_overwrote(tree):
    tree.write(s.standard())
    original = presets.load()
    result = copy(["chat.context", "utility.kwargs"], mode="replace")
    assert presets.load() != original
    outcome = history.undo(result["backup_id"])
    assert outcome["ok"] and outcome["undone"] and not outcome["has_conflicts"]
    assert outcome["results"] == [{"preset": "Target", "ok": True, "action": "restored", "conflict": None}]
    assert presets.load() == original
    assert backups.load(result["backup_id"])["undone_at"]


def test_undoing_twice_is_rejected(tree):
    tree.write(s.standard())
    backup_id = copy()["backup_id"]
    history.undo(backup_id)
    with pytest.raises(PresetError, match="already undone"):
        history.undo(backup_id)


def test_a_preset_edited_after_the_operation_is_a_conflict_that_is_not_overwritten(tree):
    tree.write(s.standard())
    backup_id = copy()["backup_id"]
    edit_after(tree, "Target", "name", "changed-later")
    before = tree.raw()
    outcome = history.undo(backup_id)
    assert outcome["has_conflicts"] and not outcome["ok"] and not outcome["undone"]
    assert outcome["results"][0]["conflict"] == "changed" and outcome["results"][0]["action"] == "skipped"
    assert tree.raw() == before
    assert not backups.load(backup_id)["entries"][0]["restored"]


def test_force_restores_a_conflicting_preset_anyway(tree):
    tree.write(s.standard())
    original = presets.load()
    backup_id = copy()["backup_id"]
    edit_after(tree, "Target", "name", "changed-later")
    outcome = history.undo(backup_id, force=True)
    assert outcome["ok"] and outcome["undone"] and not outcome["has_conflicts"]
    assert presets.load() == original


def test_a_second_call_only_processes_what_is_still_pending(tree):
    tree.write([*s.standard(), s.target_preset("Other")])
    original = presets.load()
    backup_id = copy(targets=["Target", "Other"])["backup_id"]
    edit_after(tree, "Other", "name", "changed-later")
    first = history.undo(backup_id)
    assert [(r["preset"], r["action"]) for r in first["results"]] == [("Target", "restored"), ("Other", "skipped")]
    assert not first["undone"]
    assert tree.by_name("Target") == next(p for p in original if p["name"] == "Target")
    second = history.undo(backup_id, force=True)
    assert [r["preset"] for r in second["results"]] == ["Other"] and second["undone"]
    assert tree.by_name("Other")["chat"]["name"] == "big-3"


def test_a_missing_preset_is_a_conflict_and_force_brings_it_back(tree):
    tree.write(s.standard())
    backup_id = copy()["backup_id"]
    tree.write([p for p in presets.load() if p["name"] != "Target"])
    assert history.undo(backup_id)["results"][0]["conflict"] == "missing"
    outcome = history.undo(backup_id, force=True)
    assert outcome["ok"] and "Target" in [p["name"] for p in tree.stored()]


def test_undoing_a_duplicate_removes_it_and_repairs_references_to_default(tree):
    tree.write(s.standard())
    backup_id = duplicate.duplicate_preset("Source", "Copy")["backup_id"]
    config = tree.select("p1", "Copy")
    outcome = history.undo(backup_id)
    assert outcome["results"] == [{"preset": "Copy", "ok": True, "action": "removed", "conflict": None}]
    assert [p["name"] for p in tree.stored()] == ["Default", "Source", "Target"]
    assert json.loads(config.read_text(encoding="utf-8")) == {"model_preset": "Default"}


def test_undoing_a_duplicate_that_was_edited_needs_force(tree):
    tree.write(s.standard())
    backup_id = duplicate.duplicate_preset("Source", "Copy")["backup_id"]
    edit_after(tree, "Copy", "name", "changed-later")
    assert history.undo(backup_id)["results"][0]["conflict"] == "changed"
    assert "Copy" in [p["name"] for p in tree.stored()]
    assert history.undo(backup_id, force=True)["ok"]
    assert "Copy" not in [p["name"] for p in tree.stored()]


def test_undoing_a_duplicate_that_is_already_gone_is_harmless(tree):
    tree.write(s.standard())
    backup_id = duplicate.duplicate_preset("Source", "Copy")["backup_id"]
    tree.write([p for p in presets.load() if p["name"] != "Copy"])
    before = tree.raw()
    outcome = history.undo(backup_id)
    assert outcome["ok"] and outcome["undone"] and outcome["results"][0]["action"] == "already removed"
    assert tree.raw() == before


def test_without_an_after_hash_undo_needs_force(tree):
    tree.write(s.standard())
    backup_id = copy()["backup_id"]
    record = backups.load(backup_id)
    record["entries"][0]["after"] = None
    backups.save_record(record)
    assert history.undo(backup_id)["results"][0]["conflict"] == "changed"
    assert history.undo(backup_id, force=True)["ok"]


def test_undoing_an_embedding_change_announces_it_again(tree):
    tree.write(s.standard())
    backup_id = copy(["embedding.model"])["backup_id"]
    assert tree.notified == [1]
    history.undo(backup_id)
    assert tree.notified == [1, 1]


def test_list_history_is_newest_first_and_has_no_definitions(tree):
    data = s.standard()
    data[1]["chat"]["kwargs"] = {"api_key": s.SECRET}
    tree.write(data)
    first = copy(["chat.kwargs"])["backup_id"]
    second = duplicate.duplicate_preset("Source", "Copy")["backup_id"]
    listing = history.list_history()
    assert [item["id"] for item in listing] == sorted([first, second], reverse=True)
    assert s.SECRET not in json.dumps(listing)


def test_delete_backup(tree):
    tree.write(s.standard())
    backup_id = copy()["backup_id"]
    history.delete_backup(backup_id)
    assert history.list_history() == []
    with pytest.raises(PresetError, match="not found"):
        history.delete_backup(backup_id)
    with pytest.raises(PresetError, match="Invalid backup id"):
        history.delete_backup("../x")
