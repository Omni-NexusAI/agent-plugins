from helpers.extension import Extension


class InstallA2AUnifier(Extension):
    def execute(self, **kwargs):
        try:
            from usr.plugins.a2a_format_unifier.helpers.server import install
            install()
        except (ImportError, RuntimeError):
            print("A2A Format Unifier: inbound adapter unavailable on this host; native server retained", flush=True)
