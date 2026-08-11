from helpers.extension import Extension
from plugins._agentspine_identity.helpers.identity import apply_identity_text, is_identity_enabled


class AgentspineIdentityBanners(Extension):
    async def execute(self, banners: list = [], frontend_context: dict = {}, **kwargs):
        if not is_identity_enabled():
            return
        for banner in banners:
            if isinstance(banner, dict):
                for key in ("title", "html", "message"):
                    if key in banner and isinstance(banner[key], str):
                        banner[key] = apply_identity_text(banner[key])
