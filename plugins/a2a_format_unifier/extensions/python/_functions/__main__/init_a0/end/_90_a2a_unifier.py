from helpers.extension import Extension


class InstallA2AUnifier(Extension):
    def execute(self, **kwargs):
        from usr.plugins.a2a_format_unifier.helpers.bindings import install_enabled
        install_enabled()
