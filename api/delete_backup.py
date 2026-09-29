from helpers.api import ApiHandler, Input, Output, Request, Response
from usr.plugins.multi_preset_manager.helpers import history
from usr.plugins.multi_preset_manager.helpers.errors import PresetError


class DeleteBackup(ApiHandler):
    """Delete one backup (input: id) or all of them (input: all=true). Deleting is permanent."""

    async def process(self, input: Input, request: Request) -> Output:
        if input.get("all") is True:
            return {"ok": True, "deleted": history.delete_all()}
        try:
            history.delete_backup(input.get("id"))
        except PresetError as error:
            return Response(str(error), 400)
        return {"ok": True, "deleted": 1}
