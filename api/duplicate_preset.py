from helpers.api import ApiHandler, Input, Output, Request, Response
from usr.plugins.multi_preset_manager.helpers import duplicate
from usr.plugins.multi_preset_manager.helpers.errors import PresetError


class DuplicatePreset(ApiHandler):
    """Duplicate a preset under a new name. Input: source, name. Output: name, source, backup_id."""

    async def process(self, input: Input, request: Request) -> Output:
        try:
            result = duplicate.duplicate_preset(input.get("source"), input.get("name"))
        except PresetError as error:
            return Response(str(error), 400)
        return {"ok": True, **result}
