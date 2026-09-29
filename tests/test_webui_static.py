"""Cheap checks that catch the usual UI slips without a browser (the real check is the browser run)."""

import re
from pathlib import Path

import pytest

from plugins._model_config.helpers import model_config

PLUGIN_DIR = Path(__file__).resolve().parent.parent
HTML = (PLUGIN_DIR / "webui" / "main.html").read_text(encoding="utf-8")
STORE = (PLUGIN_DIR / "webui" / "mpr-store.js").read_text(encoding="utf-8")
ENTRY = next((PLUGIN_DIR / "extensions" / "webui" / "sidebar-quick-actions-dropdown-start").glob("*.html"))


def store_members() -> set[str]:
    """Top-level members of the store model: methods and properties."""
    model = STORE[STORE.index("const model = {"): STORE.index("export const store")]
    return set(re.findall(r"^  (?:async )?(\w+)\s*(?:\(|:)", model, re.MULTILINE))


def test_every_store_member_used_by_the_html_exists():
    used = set(re.findall(r"\bm\.(\w+)", HTML))
    assert used, "the template should use the store"
    assert used <= store_members(), sorted(used - store_members())


def test_the_html_binds_the_store_it_imports():
    assert 'createStore("multiPresetManager"' in STORE
    assert "$store.multiPresetManager" in HTML
    assert '/plugins/multi_preset_manager/webui/mpr-store.js' in HTML


def test_every_api_call_names_an_existing_handler():
    called = set(re.findall(r'api\("(\w+)"', STORE))
    assert called == {p.stem for p in (PLUGIN_DIR / "api").glob("*.py")}


def test_no_raw_html_rendering_in_the_template():
    assert "x-html" not in HTML and "innerHTML" not in HTML


def test_strings_built_as_html_escape_everything_dynamic():
    """Toasts and confirm dialogs render HTML: dynamic pieces must go through esc()."""
    for name in ("confirmHtml", "undoHtml"):
        body = STORE[STORE.index(f"  {name}("):]
        body = body[: body.index("\n  },")]
        for placeholder in re.findall(r"\$\{([^}]+)\}", body):
            safe = (
                placeholder.startswith("esc(") or placeholder in {"groups", "listed", "more", "rows", "kwargs"}
                or placeholder.startswith("extra.join") or placeholder.startswith("plural(")
                or placeholder.startswith("targets.length") or placeholder.startswith("preview.changes.length")
                or placeholder.startswith('c.created ? " <em>')  # picks between two fixed texts
            )
            assert safe, f"{name}: unescaped ${{{placeholder}}}"


def test_the_menu_entry_opens_this_plugins_modal():
    text = ENTRY.read_text(encoding="utf-8")
    assert "/plugins/multi_preset_manager/webui/main.html" in text
    assert (PLUGIN_DIR / "webui" / "main.html").is_file()


def test_the_native_editor_entry_point_still_exists():
    """Canary: the plugin opens the native editor through this method of the _model_config store."""
    native = Path(model_config.__file__).parents[1] / "webui" / "model-config-store.js"
    text = native.read_text(encoding="utf-8")
    assert "async openPresetEditor(" in text and 'createStore("modelConfig"' in text
    assert "export const store" in text
