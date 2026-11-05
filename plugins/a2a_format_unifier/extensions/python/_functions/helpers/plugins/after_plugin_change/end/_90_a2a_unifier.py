from helpers.extension import Extension


class ActivateA2AUnifier(Extension):
    def execute(self, data, **kwargs):
        from usr.plugins.a2a_format_unifier.helpers.bindings import after_plugin_change
        after_plugin_change(data)
