from helpers.api import ApiHandler, Input, Output, Request, Response
from usr.plugins.multi_preset_manager.helpers import history
from usr.plugins.multi_preset_manager.helpers.errors import PresetError


class UndoBackup(ApiHandler):
    """Restore what an operation changed. Input: id, force (restore presets edited afterwards too)."""

    async def process(self, input: Input, request: Request) -> Output:
        force = input.get("force", False)
        if not isinstance(force, bool):
            return Response("force must be true or false", 400)
        try:
            outcome = history.undo(input.get("id"), force)
        except PresetError as error:
            return Response(str(error), 400)
        return {"ok": outcome["ok"], **outcome}
