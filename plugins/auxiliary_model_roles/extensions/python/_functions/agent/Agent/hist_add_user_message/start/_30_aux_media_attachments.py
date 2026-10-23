from helpers.extension import Extension

from usr.plugins.auxiliary_model_roles.helpers import media_embedding as me


PENDING = "_aux_media_attachments"


class AuxMediaAttachments(Extension):
    """Remember this message's media attachments for one media recall pass."""

    def execute(self, data: dict = {}, **kwargs):
        if not self.agent or not isinstance(data, dict):
            return
        args = data.get("args") or ()
        message = data.get("kwargs", {}).get("message") or (args[1] if len(args) > 1 else None)
        paths = [path for path in getattr(message, "attachments", None) or [] if isinstance(path, str) and me.kind_of(path)]
        self.agent.set_data(PENDING, paths[:3] if paths else None)
