from pathlib import Path

import pytest

from usr.plugins.multi_preset_manager.helpers import backups, duplicate, presets
from usr.plugins.multi_preset_manager.helpers.errors import PresetError

import mpr_samples as s


def backup_files():
    folder = Path(backups.backups_dir())
    return sorted(folder.glob("*.json")) if folder.exists() else []


def test_duplicate_is_inserted_right_after_the_source_and_is_identical(tree):
    tree.write(s.standard())
    result = duplicate.duplicate_preset("Source", "Source 2")
    assert [p["name"] for p in tree.stored()] == ["Default", "Source", "Source 2", "Target"]
    assert {**tree.by_name("Source 2"), "name": "Source"} == tree.by_name("Source")
    assert result["name"] == "Source 2" and result["source"] == "Source"


def test_duplicate_records_a_backup_whose_undo_information_removes_it(tree):
    tree.write(s.standard())
    result = duplicate.duplicate_preset("Source", "  Copy  ")
    record = backups.load(result["backup_id"])
    entry = record["entries"][0]
    assert record["kind"] == "duplicate" and record["source"] == "Source"
    assert entry["preset"] == "Copy" and entry["before"] is None
    assert entry["after"] == presets.preset_hash(tree.by_name("Copy"))


def test_duplicating_default_creates_a_regular_preset_that_can_be_renamed_or_deleted(tree):
    tree.write(s.standard())
    duplicate.duplicate_preset("default", "Default copy")
    assert [p["name"] for p in tree.stored()] == ["Default", "Default copy", "Source", "Target"]
    assert tree.by_name("Default copy")["chat"] == tree.by_name("Default")["chat"]


@pytest.mark.parametrize("name", ["Target", "target", " TARGET ", "Default", "default"])
def test_existing_names_are_rejected_without_renaming_silently(tree, name):
    tree.write(s.standard())
    before = tree.raw()
    with pytest.raises(PresetError, match="already exists"):
        duplicate.duplicate_preset("Source", name)
    assert tree.raw() == before and backup_files() == []


@pytest.mark.parametrize("name, message", [
    ("", "required"), ("   ", "required"), (None, "required"), (7, "required"),
    ("x" * 101, "too long"), ("bad\nname", "invalid characters"), ("tab\there", "invalid characters"),
])
def test_invalid_names_are_rejected(tree, name, message):
    tree.write(s.standard())
    before = tree.raw()
    with pytest.raises(PresetError, match=message):
        duplicate.duplicate_preset("Source", name)
    assert tree.raw() == before


def test_unknown_source_is_rejected(tree):
    tree.write(s.standard())
    with pytest.raises(PresetError, match="Source preset not found"):
        duplicate.duplicate_preset("Nope", "New")
    with pytest.raises(PresetError, match="Source preset not found"):
        duplicate.duplicate_preset(None, "New")


def test_source_lookup_ignores_case(tree):
    tree.write(s.standard())
    assert duplicate.duplicate_preset("source", "New")["source"] == "Source"


def test_selections_by_scope_are_not_copied(tree):
    tree.write(s.standard())
    config = tree.select("p1", "Source")
    duplicate.duplicate_preset("Source", "Copy")
    assert config.read_text(encoding="utf-8") == '{"model_preset": "Source"}'


def test_a_backup_that_cannot_be_stored_blocks_the_duplicate(tree, monkeypatch):
    tree.write(s.standard())
    before = tree.raw()

    def refuse(self):
        raise OSError("disk full")

    monkeypatch.setattr(backups.Backup, "save", refuse)
    with pytest.raises(OSError):
        duplicate.duplicate_preset("Source", "New")
    assert tree.raw() == before


def test_a_failed_save_removes_its_backup(tree, monkeypatch):
    tree.write(s.standard())
    before = tree.raw()

    def boom(new):
        raise RuntimeError("write failed")

    monkeypatch.setattr(presets, "save", boom)
    with pytest.raises(RuntimeError):
        duplicate.duplicate_preset("Source", "New")
    assert tree.raw() == before and backup_files() == []
