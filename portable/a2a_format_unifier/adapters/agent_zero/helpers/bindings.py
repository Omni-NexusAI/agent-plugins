"""Install only plugin-owned bindings through supported host lifecycle hooks."""


def install_enabled():
    from helpers.plugins import get_enabled_plugins

    result = {"enabled": False, "server": False, "client": False}
    if "a2a_format_unifier" not in get_enabled_plugins(None):
        return result
    result["enabled"] = True
    for name in ("server", "client"):
        try:
            if name == "server":
                from .server import install
            else:
                from .native_client import install
            result[name] = bool(install())
        except (ImportError, RuntimeError):
            print("A2A Format Unifier: " + name +
                  " adapter unavailable on this host; native behavior retained", flush=True)
    return result


def after_plugin_change(data):
    """A toggle clears discovery caches before this supported end hook runs."""
    if data.get("exception"):
        return None
    args = data.get("args") or ()
    changed = (data.get("kwargs") or {}).get("plugin_names", args[0] if args else None)
    if changed is not None and "a2a_format_unifier" not in changed:
        return None
    return install_enabled()
