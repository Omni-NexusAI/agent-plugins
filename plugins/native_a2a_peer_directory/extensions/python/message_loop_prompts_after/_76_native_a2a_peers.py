from helpers.extension import Extension


class NativeA2APeers(Extension):
    def execute(self, loop_data, **kwargs):
        if self.agent is None:
            return
        from helpers.plugins import get_plugin_config
        from usr.plugins.native_a2a_peer_directory.helpers.directory import render
        try:
            text = render(get_plugin_config("native_a2a_peer_directory", self.agent) or {})
        except (ValueError, TypeError):
            # Configuration may contain private values. Never print it.
            text = ""
        if text:
            loop_data.extras_temporary["native_a2a_peer_directory"] = text
