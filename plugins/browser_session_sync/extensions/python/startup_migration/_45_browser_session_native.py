from helpers.extension import Extension


class BrowserSessionNativeStartup(Extension):
    def execute(self, **kwargs):
        from usr.plugins.browser_session_sync.helpers.native_adapter import patch_runtime
        patch_runtime()
