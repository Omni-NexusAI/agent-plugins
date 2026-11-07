"""Activate guarded bindings for legacy and v2.15 native client layouts."""
from helpers.extension import Extension


class ActivateA2AUnifier(Extension):
    def execute(self, data, **kwargs):
        if data.get("exception"):
            return
        args = data.get("args") or ()
        changed = (data.get("kwargs") or {}).get("plugin_names", args[0] if args else None)
        if changed is not None and "a2a_format_unifier" not in changed:
            return
        # Windows bind mounts may not deliver host writes to the native watcher.
        # A supported own-plugin change must refresh this namespace explicitly.
        from helpers.modules import purge_namespace
        purge_namespace("usr.plugins.a2a_format_unifier")
        from usr.plugins.a2a_format_unifier.helpers.bindings import after_plugin_change
        after_plugin_change(data)
