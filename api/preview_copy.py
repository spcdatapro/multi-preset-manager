from helpers.api import ApiHandler, Input, Output, Request, Response
from usr.plugins.multi_preset_manager.helpers import copy_settings
from usr.plugins.multi_preset_manager.helpers.errors import PresetError


class PreviewCopy(ApiHandler):
    """Show what copying would change, without writing anything.

    Input: source, targets, groups, kwargs_mode (merge|replace, default merge).
    Output: hash, changes (effective, redacted), unchanged, warnings.
    """

    async def process(self, input: Input, request: Request) -> Output:
        try:
            result = copy_settings.preview(
                input.get("source"), input.get("targets"), input.get("groups"), input.get("kwargs_mode", "merge")
            )
        except PresetError as error:
            return Response(str(error), 400)
        return {"ok": True, **result}
