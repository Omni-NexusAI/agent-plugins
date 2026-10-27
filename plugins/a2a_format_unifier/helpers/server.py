"""Guarded Agent Zero binding. No shipped source files are edited."""
import inspect
from datetime import datetime


def install():
    from helpers.fasta2a_server import DynamicA2AProxy
    from .middleware import LegacyServerUnifier
    original = DynamicA2AProxy.__call__
    if getattr(original, "_a2a_unifier", False):
        return False
    if not inspect.iscoroutinefunction(original):
        raise RuntimeError("Unsupported Agent Zero A2A server interface")

    async def unified(self, scope, receive, send):
        if not LegacyServerUnifier.supports_scope(scope):
            return await original(self, scope, receive, send)
        from helpers.plugins import get_enabled_plugins, get_plugin_config
        if "a2a_format_unifier" not in get_enabled_plugins(None):
            return await original(self, scope, receive, send)
        if not (get_plugin_config("a2a_format_unifier") or {}).get("inbound_compatibility", True):
            return await original(self, scope, receive, send)

        async def native(s, r, w):
            return await original(self, s, r, w)

        config = get_plugin_config("a2a_format_unifier") or {}
        timeout = min(max(int(config.get("timeout", 180)), 5), 90)
        return await LegacyServerUnifier(native, poll_timeout=timeout,
                                         legacy_timezone=datetime.now().astimezone().tzinfo)(scope, receive, send)

    unified._a2a_unifier = True
    unified._a2a_original = original
    DynamicA2AProxy.__call__ = unified
    return True
