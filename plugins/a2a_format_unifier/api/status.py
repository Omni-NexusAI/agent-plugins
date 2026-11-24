"""Authenticated, read-only binding diagnostics; never installs or sends."""
from helpers.api import ApiHandler, Request, Response


class Status(ApiHandler):
    async def process(self, input: dict, request: Request) -> dict | Response:
        from helpers.plugins import get_enabled_plugins
        from usr.plugins.a2a_format_unifier.helpers import native_client

        resolver = getattr(native_client, "_native_connection_class", None)
        connection = None
        try:
            if callable(resolver):
                connection = resolver()
        except (ImportError, AttributeError):
            pass
        try:
            from helpers.fasta2a_server import DynamicA2AProxy
            server_bound = bool(getattr(DynamicA2AProxy.__call__, "_a2a_unifier", False))
        except (ImportError, AttributeError):
            server_bound = False
        return {
            "enabled": "a2a_format_unifier" in get_enabled_plugins(None),
            "client_interface_available": connection is not None,
            "client_module": getattr(connection, "__module__", None),
            "client_bound": bool(connection and getattr(connection.__init__, "_a2a_format_fallback", False)),
            "server_bound": server_bound,
        }
