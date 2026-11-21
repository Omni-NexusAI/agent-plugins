"""Handle ``/looped`` for messages from any source (queue, API, chat apps).

Runs before the host's own slash-command resolver, so the token never reaches
the model. A command with no remaining message ends the chain with a note.
"""

import logging

from helpers.extension import Extension


def _helpers():
    try:
        from usr.plugins.looped.helpers import command, runtime
    except ImportError:
        from plugins.looped.helpers import command, runtime
    return command, runtime


class LoopedCommand(Extension):
    async def execute(self, data=None, **kwargs):
        try:
            if not isinstance(data, dict):
                return
            args = data.get("args")
            call_kwargs = data.get("kwargs") if isinstance(data.get("kwargs"), dict) else {}
            if not isinstance(args, tuple) or len(args) < 3:
                return
            context, agent, message = args[0], args[1], args[2]
            is_user = call_kwargs.get("user", args[3] if len(args) > 3 else True)
            if not is_user or getattr(agent, "number", 0) != 0:
                return
            text = getattr(message, "message", None)
            chat = getattr(context, "data", None)
            if not isinstance(text, str) or not isinstance(chat, dict):
                return
            command, runtime = _helpers()
            handled = command.handle(chat, text, runtime.config(agent)["mode"])
            if handled is None:
                return
            rest, note = handled
            if rest.strip() or getattr(message, "attachments", None):
                message.message = rest
            else:
                data["result"] = note
        except Exception:
            logging.getLogger("looped").exception("looped: command hook failed")
