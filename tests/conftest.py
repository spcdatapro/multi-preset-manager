import json
from pathlib import Path

import pytest
import yaml

from helpers import cache, files, plugins
from usr.plugins.multi_preset_manager.helpers import presets


class Tree:
    """A throwaway Agent Zero tree with the real _model_config code reading from it."""

    def __init__(self, root: Path):
        self.root = root
        self.notified: list[int] = []

    @property
    def presets_file(self) -> Path:
        return self.root / "usr" / "plugins" / "_model_config" / "presets.yaml"

    def write(self, preset_list: list[dict]) -> None:
        self.presets_file.parent.mkdir(parents=True, exist_ok=True)
        self.presets_file.write_text(yaml.safe_dump(preset_list, sort_keys=False), encoding="utf-8")
        cache.clear("*(plugins)*")

    def raw(self) -> bytes:
        return self.presets_file.read_bytes()

    def stored(self) -> list[dict]:
        return yaml.safe_load(self.presets_file.read_text(encoding="utf-8"))

    def by_name(self, name: str) -> dict:
        return next(p for p in self.stored() if p["name"] == name)

    def select(self, project: str, preset: str) -> Path:
        path = self.root / "usr" / "projects" / project / ".a0proj" / "plugins" / "_model_config" / "config.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"model_preset": preset}), encoding="utf-8")
        return path


@pytest.fixture
def tree(monkeypatch, tmp_path: Path) -> Tree:
    monkeypatch.setattr(files, "_base_dir", str(tmp_path))
    monkeypatch.setattr(plugins, "call_plugin_hook", lambda plugin_name, hook_name, default=None, **kwargs: default)
    plugin_dir = tmp_path / "plugins" / "_model_config"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "plugin.yaml").write_text(
        "name: _model_config\nper_project_config: true\nper_agent_config: true\n", encoding="utf-8"
    )
    (plugin_dir / "mode_presets_fallback.yaml").write_text(
        "- name: Default\n"
        "  chat: {provider: fallback, name: chat}\n"
        "  utility: {provider: fallback, name: utility}\n"
        "  embedding: {provider: fallback, name: embedding}\n",
        encoding="utf-8",
    )
    (tmp_path / "usr" / "plugins" / "_model_config").mkdir(parents=True)
    (tmp_path / "usr" / "projects").mkdir(parents=True)
    cache.clear("*(plugins)*")
    made = Tree(tmp_path)
    # The real notification starts a deferred task that reloads the memory index.
    monkeypatch.setattr(presets, "_notify_embedding_changed", lambda: made.notified.append(1))
    yield made
    cache.clear("*(plugins)*")
