"""Agent Zero adapter for the framework-independent A2A Format Unifier."""
import asyncio
from pathlib import Path

from helpers.plugins import get_plugin_config
from helpers.tool import Tool, Response
from usr.plugins.a2a_format_unifier.helpers.client import Client, A2AError, converse_persisted
from usr.plugins.a2a_format_unifier.helpers.credentials import resolve_credential


class A2AUnifiedChat(Tool):
    async def execute(self, message="", peer="hermes", reset=False, **kwargs):
        if not isinstance(message, str) or not message.strip():
            return Response(message="A2A requires a nonempty message", break_loop=False)
        if not isinstance(reset, bool):
            return Response(message="A2A reset must be a boolean", break_loop=False)
        config = get_plugin_config("a2a_format_unifier", agent=self.agent) or {}
        peers = config.get("peers", {})
        routes = config.get("routes", {})
        if peer in routes:
            route = routes[peer]
            peer = route.get("via")
            message = f"Delegate the following task to your configured A2A peer '{route.get('peer')}' and return its result. Task: {message}"
        if peer not in peers:
            return Response(message="Unknown configured A2A peer alias", break_loop=False)
        entry = peers[peer]
        try:
            plugin_root = Path(__file__).resolve().parents[1]
            credential = resolve_credential(entry, plugin_root)
            client = Client(entry.get("url", ""), credential,
                            config.get("timeout", 180))
            root = plugin_root / ".runtime"
            result = await asyncio.to_thread(converse_persisted, client, message, root, reset)
            return Response(message=result["text"], break_loop=False)
        except A2AError as exc:
            return Response(message="A2A unifier error: " + str(exc), break_loop=False)
        except Exception as exc:
            return Response(message=f"A2A unifier local error ({type(exc).__name__})", break_loop=False)
