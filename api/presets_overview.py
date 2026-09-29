from helpers.api import ApiHandler, Input, Output, Request
from usr.plugins.multi_preset_manager.helpers import backups, groups, presets


class PresetsOverview(ApiHandler):
    """List the presets (effective model names only) plus the groups and options the UI needs.

    Output: hash (send it back with copy_settings), presets, groups, kwargs_modes, max_backups.
    """

    async def process(self, input: Input, request: Request) -> Output:
        return {
            "ok": True,
            **presets.overview(),
            "groups": groups.catalog(),
            "slots": groups.SLOT_LABELS,
            "kwargs_modes": list(groups.KWARGS_MODES),
            "max_backups": backups.MAX_BACKUPS,
        }
