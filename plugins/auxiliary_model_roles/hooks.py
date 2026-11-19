"""Validate specialist configuration while keeping unknown host keys intact."""


def save_plugin_config(result=None, settings=None, **kwargs):
    if not isinstance(settings, dict):
        return settings
    for role in ("tool", "coding"):
        section = settings.get(role, {})
        if not isinstance(section, dict):
            raise ValueError(f"{role} model settings must be an object")
        if section.get("enabled") and (
            not isinstance(section.get("provider"), str) or not section["provider"].strip()
            or not isinstance(section.get("name"), str) or not section["name"].strip()
        ):
            raise ValueError(f"{role} specialist requires provider and model name")
    return settings
