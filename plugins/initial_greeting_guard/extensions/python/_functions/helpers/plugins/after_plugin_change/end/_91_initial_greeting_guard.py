"""Refresh only this plugin's pure provenance helpers on supported changes."""
from helpers.extension import Extension


class RefreshGreetingProvenance(Extension):
    def execute(self, data, **kwargs):
        if data.get("exception"):
            return
        args = data.get("args") or ()
        changed = (data.get("kwargs") or {}).get("plugin_names", args[0] if args else None)
        if changed is not None and "initial_greeting_guard" not in changed:
            return
        from helpers.modules import purge_namespace
        purge_namespace("usr.plugins.initial_greeting_guard")
