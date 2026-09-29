import pytest

from usr.plugins.multi_preset_manager import hooks
from usr.plugins.multi_preset_manager.helpers import backups, duplicate

import mpr_samples as s


def make_backup():
    backup = backups.Backup("duplicate", "Source")
    backup.add_entry("Copy", None)
    backup.save()


def test_uninstall_removes_backups_and_the_empty_data_folders(tree):
    make_backup()
    make_backup()
    hooks.uninstall()
    assert not (tree.root / "usr" / "multi_preset_manager").exists()


def test_uninstall_never_removes_files_it_does_not_own(tree):
    make_backup()
    stray = tree.root / "usr" / "multi_preset_manager" / "notes.txt"
    stray.write_text("keep", encoding="utf-8")
    hooks.uninstall()
    assert backups.list_records() == []
    assert stray.read_text(encoding="utf-8") == "keep"


def test_uninstall_never_touches_the_presets(tree):
    tree.write(s.standard())
    duplicate.duplicate_preset("Source", "Copy")
    before = tree.raw()
    hooks.uninstall()
    assert tree.raw() == before and backups.list_records() == []


def test_uninstall_with_nothing_to_clean_is_harmless(tree):
    hooks.uninstall()
    hooks.uninstall()
