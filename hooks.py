"""Lifecycle hooks (run in the Agent Zero framework runtime).

The plugin needs no setup or dependencies, so there is no install(). It does own data outside its
folder: the backups taken before each operation (usr/multi_preset_manager/backups), which hold the
previous preset definitions, api_base and kwargs included. They are removed on uninstall so nothing
sensitive is left behind. The presets themselves are never touched.
"""

import os


def uninstall():
    from usr.plugins.multi_preset_manager.helpers import backups

    backups.delete_all()
    folder = backups.backups_dir()
    for path in (folder, os.path.dirname(folder)):
        try:
            os.rmdir(path)  # only if empty: never removes anything we do not own
        except OSError:
            pass
