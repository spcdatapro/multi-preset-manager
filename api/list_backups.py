from helpers.api import ApiHandler, Input, Output, Request
from usr.plugins.multi_preset_manager.helpers import backups, history


class ListBackups(ApiHandler):
    """List the backups taken before each operation, newest first. Names only, never any preset."""

    async def process(self, input: Input, request: Request) -> Output:
        return {"ok": True, "backups": history.list_history(), "max_backups": backups.MAX_BACKUPS}
