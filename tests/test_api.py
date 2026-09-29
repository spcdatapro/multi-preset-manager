import asyncio
import json
from pathlib import Path

import pytest

from helpers.api import ApiHandler
from helpers.modules import load_classes_from_file
from usr.plugins.multi_preset_manager.api.copy_settings import CopySettings
from usr.plugins.multi_preset_manager.api.delete_backup import DeleteBackup
from usr.plugins.multi_preset_manager.api.duplicate_preset import DuplicatePreset
from usr.plugins.multi_preset_manager.api.list_backups import ListBackups
from usr.plugins.multi_preset_manager.api.presets_overview import PresetsOverview
from usr.plugins.multi_preset_manager.api.preview_copy import PreviewCopy
from usr.plugins.multi_preset_manager.api.undo_backup import UndoBackup

import mpr_samples as s

API_DIR = Path(__file__).resolve().parent.parent / "api"
HANDLERS = {
    "presets_overview": PresetsOverview,
    "preview_copy": PreviewCopy,
    "copy_settings": CopySettings,
    "duplicate_preset": DuplicatePreset,
    "list_backups": ListBackups,
    "undo_backup": UndoBackup,
    "delete_backup": DeleteBackup,
}


def call(handler_cls, payload):
    return asyncio.run(handler_cls(None, None).process(payload, None))


def status_and_text(response):
    return response.status_code, response.get_data(as_text=True)


def copy_payload(**extra):
    overview = call(PresetsOverview, {})
    return {"source": "Source", "targets": ["Target"], "groups": ["chat.context"], "kwargs_mode": "merge",
            "hash": overview["hash"], **extra}


@pytest.fixture
def seeded(tree):
    tree.write(s.standard())
    return tree


@pytest.mark.parametrize("file_name, handler_cls", HANDLERS.items())
def test_each_file_exposes_exactly_its_handler_with_secure_defaults(file_name, handler_cls):
    classes = load_classes_from_file(str(API_DIR / f"{file_name}.py"), ApiHandler)
    assert [cls.__name__ for cls in classes] == [handler_cls.__name__]
    assert handler_cls.requires_auth() is True
    assert handler_cls.requires_csrf() is True
    assert handler_cls.requires_api_key() is False
    assert handler_cls.requires_loopback() is False
    assert handler_cls.get_methods() == ["POST"]


def test_overview_lists_presets_groups_and_options(seeded):
    data = call(PresetsOverview, {})
    assert data["ok"] is True and data["hash"]
    assert [p["name"] for p in data["presets"]] == ["Default", "Source", "Target"]
    assert data["presets"][1]["main"] == "anthropic/big-2"
    assert {g["id"] for g in data["groups"]} >= {"chat.model", "utility.kwargs", "embedding.model", "vision.slot"}
    assert data["kwargs_modes"] == ["merge", "replace"] and data["max_backups"] == 20
    assert data["slots"]["chat"] == "Main model"


def test_preview_then_copy_then_history_then_undo(seeded):
    original = seeded.stored()
    preview = call(PreviewCopy, copy_payload())
    assert preview["ok"] is True and [c["preset"] for c in preview["changes"]] == ["Target"]
    assert seeded.stored() == original  # a preview writes nothing

    done = call(CopySettings, copy_payload(hash=preview["hash"]))
    assert done["ok"] is True and done["changed"] == ["Target"] and done["backup_id"]
    assert seeded.by_name("Target")["chat"]["ctx_length"] == 300000

    listing = call(ListBackups, {})
    assert [b["id"] for b in listing["backups"]] == [done["backup_id"]]
    assert listing["backups"][0]["changes"] == [{"preset": "Target", "created": False, "restored": False}]

    undone = call(UndoBackup, {"id": done["backup_id"]})
    assert undone["ok"] is True and undone["undone"] is True
    assert seeded.stored() == original


def test_kwargs_mode_defaults_to_merge(seeded):
    payload = copy_payload(groups=["chat.kwargs"])
    del payload["kwargs_mode"]
    call(CopySettings, payload)
    assert seeded.by_name("Target")["chat"]["kwargs"] == {"top_p": 0.5, **s.source_preset()["chat"]["kwargs"]}


@pytest.mark.parametrize(
    "change, message",
    [
        ({"source": "Nope"}, "Source preset not found"),
        ({"targets": []}, "at least one target"),
        ({"targets": ["Source"]}, "cannot be a target"),
        ({"groups": ["nope"]}, "Unknown group"),
        ({"groups": ["chat.kwargs"], "kwargs_mode": "sideways"}, "kwargs_mode"),
    ],
)
def test_invalid_copy_requests_are_400_for_preview_and_apply(seeded, change, message):
    before = seeded.raw()
    for handler in (PreviewCopy, CopySettings):
        status, text = status_and_text(call(handler, copy_payload(**change)))
        assert status == 400 and message in text
    assert seeded.raw() == before


def test_apply_needs_a_fresh_preview_hash(seeded):
    before = seeded.raw()
    for bad in ({"hash": None}, {"hash": ""}, {"hash": "0" * 64}):
        status, text = status_and_text(call(CopySettings, copy_payload(**bad)))
        assert status == 400 and ("hash" in text or "preview again" in text)
    assert seeded.raw() == before


def test_duplicate_success_and_errors(seeded):
    data = call(DuplicatePreset, {"source": "Source", "name": "Source 2"})
    assert data["ok"] is True and data["name"] == "Source 2" and data["backup_id"]
    assert [p["name"] for p in seeded.stored()] == ["Default", "Source", "Source 2", "Target"]
    for payload, message in (
        ({"source": "Source", "name": "source 2"}, "already exists"),
        ({"source": "Source", "name": ""}, "required"),
        ({"source": "Nope", "name": "X"}, "not found"),
    ):
        status, text = status_and_text(call(DuplicatePreset, payload))
        assert status == 400 and message in text


@pytest.mark.parametrize("payload", [{"id": "../x"}, {"id": None}, {"id": "20260101T000000000000Z-abcdef"}])
def test_undo_rejects_bad_or_unknown_ids(seeded, payload):
    status, _ = status_and_text(call(UndoBackup, payload))
    assert status == 400


def test_undo_requires_a_boolean_force(seeded):
    backup_id = call(CopySettings, copy_payload())["backup_id"]
    status, text = status_and_text(call(UndoBackup, {"id": backup_id, "force": "yes"}))
    assert status == 400 and "force" in text


def test_undo_reports_conflicts_and_force_resolves_them(seeded):
    backup_id = call(CopySettings, copy_payload())["backup_id"]
    edited = seeded.stored()
    edited[2]["chat"]["name"] = "changed-later"
    seeded.write(edited)
    first = call(UndoBackup, {"id": backup_id})
    assert first["ok"] is False and first["has_conflicts"] is True and first["undone"] is False
    second = call(UndoBackup, {"id": backup_id, "force": True})
    assert second["ok"] is True and second["undone"] is True


def test_delete_backup_one_all_and_unknown(seeded):
    first = call(CopySettings, copy_payload())["backup_id"]
    assert call(DeleteBackup, {"id": first}) == {"ok": True, "deleted": 1}
    assert call(ListBackups, {})["backups"] == []
    status, text = status_and_text(call(DeleteBackup, {"id": first}))
    assert status == 400 and "not found" in text
    status, _ = status_and_text(call(DeleteBackup, {"id": "../etc/passwd"}))
    assert status == 400
    call(DuplicatePreset, {"source": "Source", "name": "A"})
    call(DuplicatePreset, {"source": "Source", "name": "B"})
    assert call(DeleteBackup, {"all": True}) == {"ok": True, "deleted": 2}
    assert call(DeleteBackup, {"all": True}) == {"ok": True, "deleted": 0}


def test_no_endpoint_ever_returns_a_secret(tree):
    data = s.standard()
    data[1]["chat"]["kwargs"] = {"extra_headers": {"Authorization": f"Bearer {s.SECRET}"}, "api_key": s.SECRET}
    data[1]["chat"]["api_base"] = f"https://user:{s.SECRET}@host.example/v1?token={s.SECRET}"
    tree.write(data)
    outputs = [call(PresetsOverview, {})]
    payload = copy_payload(groups=["chat.kwargs", "chat.api_base"])
    outputs.append(call(PreviewCopy, payload))
    done = call(CopySettings, payload)
    outputs += [done, call(DuplicatePreset, {"source": "Source", "name": "Copy"}), call(ListBackups, {})]
    outputs.append(call(UndoBackup, {"id": done["backup_id"]}))
    assert s.SECRET not in json.dumps(outputs)
