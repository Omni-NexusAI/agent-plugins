def install(**kwargs):
    pass


def get_plugin_config(default=None, **kwargs):
    from usr.plugins.browser_session_sync.helpers.session_sync import normalize_config

    return normalize_config(default or {}, preserve_unknown=True)


def save_plugin_config(settings=None, default=None, **kwargs):
    from usr.plugins.browser_session_sync.helpers.session_sync import enforce_retention, normalize_config

    config = normalize_config(settings or default or {}, preserve_unknown=True)
    enforce_retention(config)
    return config
