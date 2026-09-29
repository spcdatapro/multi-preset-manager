from helpers.api import ApiHandler, Input, Output, Request, Response
from usr.plugins.multi_preset_manager.helpers import copy_settings
from usr.plugins.multi_preset_manager.helpers.errors import PresetError


class CopySettings(ApiHandler):
    """Copy field groups of a source preset to target presets, after backing up what changes.

    Input: source, targets, groups, kwargs_mode, hash (from preview_copy: refused if the presets
    changed since). Output: changed, backup_id (null when nothing changed), changes, warnings.
    """

    async def process(self, input: Input, request: Request) -> Output:
        try:
            result = copy_settings.apply(
                input.get("source"),
                input.get("targets"),
                input.get("groups"),
                input.get("kwargs_mode", "merge"),
                input.get("hash"),
            )
        except PresetError as error:
            return Response(str(error), 400)
        return {"ok": True, **result}
