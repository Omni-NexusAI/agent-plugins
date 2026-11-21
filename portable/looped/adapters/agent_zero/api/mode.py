"""Read or change looped mode for one chat."""

from agent import AgentContext
from helpers.api import ApiHandler, Request, Response


def _helpers():
    try:
        from usr.plugins.looped.helpers import command, runtime
    except ImportError:
        from plugins.looped.helpers import command, runtime
    return command, runtime


class Mode(ApiHandler):
    async def process(self, input: dict, request: Request) -> dict | Response:
        command, runtime = _helpers()
        context = AgentContext.get(str(input.get("context_id") or ""))
        if not context:
            return Response(status=404, response="Context not found")
        chat = context.data
        default_mode = runtime.config(context.agent0)["mode"]
        action = input.get("action", "get")
        note = ""
        rest = None

        if action == "set":
            mode = input.get("mode")
            if mode in runtime.MODES:
                chat[command.MODE_KEY] = mode
            elif mode in (None, "", "default"):
                chat.pop(command.MODE_KEY, None)
            else:
                return Response(status=400, response="Unknown mode")
        elif action == "arm":
            if input.get("armed", True):
                chat[command.ARM_KEY] = True
            else:
                chat.pop(command.ARM_KEY, None)
        elif action == "command":
            handled = command.handle(chat, input.get("text"), default_mode)
            if handled is None:
                return Response(status=400, response="Not a /looped command")
            rest, note = handled
        elif action != "get":
            return Response(status=400, response="Unknown action")

        if action != "get":
            try:
                from helpers.persist_chat import save_tmp_chat
                save_tmp_chat(context)
            except Exception:
                pass

        mode = chat.get(command.MODE_KEY)
        return {"ok": True, "mode": mode if mode in runtime.MODES else None,
                "default_mode": default_mode,
                "armed": bool(chat.get(command.ARM_KEY)),
                "note": note, "rest": rest}
