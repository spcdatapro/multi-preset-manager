import json
import os
import stat
from pathlib import Path

import pytest

from helpers import files
from usr.plugins.multi_preset_manager.helpers import backups
from usr.plugins.multi_preset_manager.helpers.errors import PresetError

import mpr_samples as s


@pytest.fixture
def base(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(files, "_base_dir", str(tmp_path))
    return tmp_path


def make_backup(secret=s.SECRET):
    backup = backups.Backup("copy", "Source", ["chat.kwargs"], "merge")
    before = s.target_preset()
    before["chat"]["kwargs"] = {"api_key": secret}
    backup.add_entry("Target", before)
    backup.add_entry("Created", None)
    backup.save()
    return backup


def test_save_and_load_roundtrip_lives_outside_the_plugin_folder(base):
    backup = make_backup()
    path = Path(backups.backups_dir()) / f"{backup.id}.json"
    assert path.is_file()
    assert "plugins" not in path.relative_to(base).parts
    record = backups.load(backup.id)
    assert record["entries"][0]["before"]["chat"]["kwargs"] == {"api_key": s.SECRET}
    assert record["entries"][1]["before"] is None and record["kind"] == "copy"


def test_backup_file_is_private_and_no_temp_file_is_left(base):
    backup = make_backup()
    path = Path(backups.backups_dir()) / f"{backup.id}.json"
    mode = stat.S_IMODE(os.stat(path).st_mode)
    if os.name != "nt":  # Windows has no POSIX modes; the target runtime is Linux
        assert mode & 0o077 == 0, oct(mode)
    assert [p.name for p in path.parent.iterdir()] == [path.name]


@pytest.mark.parametrize("bad", ["../etc/passwd", "x", "", None, 5, "20260101T000000000000Z-zzzzzz", "a/b"])
def test_invalid_ids_are_rejected_before_touching_the_disk(base, bad):
    for call in (backups.load, backups.exists):
        with pytest.raises(PresetError, match="Invalid backup id"):
            call(bad)


def test_missing_and_corrupted_backups_raise_clear_errors(base):
    with pytest.raises(PresetError, match="not found"):
        backups.load("20260101T000000000000Z-abcdef")
    backup = make_backup()
    path = Path(backups.backups_dir()) / f"{backup.id}.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(PresetError, match="could not be read"):
        backups.load(backup.id)
    assert backups.list_records() == []  # unreadable files are skipped, not fatal
    assert backups.exists(backup.id) is True  # ...but can still be deleted
    backups.delete(backup.id)
    assert backups.exists(backup.id) is False


def test_only_the_newest_backups_are_kept(base, monkeypatch):
    monkeypatch.setattr(backups, "MAX_BACKUPS", 3)
    ids = [make_backup().id for _ in range(5)]
    assert [r["id"] for r in backups.list_records()] == sorted(ids, reverse=True)[:3]


def test_summary_never_contains_preset_definitions(base):
    backup = make_backup()
    summary = backups.summarize(backups.load(backup.id))
    assert s.SECRET not in json.dumps(summary)
    assert summary["changes"] == [
        {"preset": "Target", "created": False, "restored": False},
        {"preset": "Created", "created": True, "restored": False},
    ]
    assert summary["groups"] == ["chat.kwargs"] and summary["kind"] == "copy" and summary["undone"] is False


def test_unknown_kind_is_a_programming_error(base):
    with pytest.raises(ValueError):
        backups.Backup("nope", "Source")


def test_delete_and_delete_all(base):
    a, b = make_backup(), make_backup()
    backups.delete(a.id)
    backups.delete(a.id)  # deleting twice is harmless
    assert [r["id"] for r in backups.list_records()] == [b.id]
    assert backups.delete_all() == 1
    assert backups.delete_all() == 0
