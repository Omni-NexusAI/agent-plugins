from __future__ import annotations

import os
import re

from helpers.extension import Extension
from plugins._agentspine_identity.helpers.identity import (
    apply_identity_text,
    format_display_version,
    is_identity_enabled,
    release_tag_for_variant,
)


def _current_release_tag() -> str:
    return release_tag_for_variant(os.getenv("BUILD_VARIANT"))


class AgentspineIndexIdentity(Extension):
    def execute(self, data: dict | None = None, **kwargs):
        if not is_identity_enabled():
            return
        if not isinstance(data, dict):
            return
        result = data.get("result")
        if not isinstance(result, str):
            return

        def replace_gitinfo(match: re.Match[str]) -> str:
            current_version = match.group("version")
            commit_time = match.group("time")
            display = format_display_version(
                _current_release_tag(),
                commit_time,
                None,
            )
            return f'globalThis.gitinfo = {{ version: "{display}", commit_time: "{commit_time}" }};'

        result = re.sub(
            r'globalThis\.gitinfo\s*=\s*\{\s*version:\s*"(?P<version>[^"]*)",\s*commit_time:\s*"(?P<time>[^"]*)"\s*\};',
            replace_gitinfo,
            result,
            count=1,
        )
        result = result.replace("<title>Agent Zero</title>", "<title>Agentspine</title>")
        data["result"] = apply_identity_text(result).replace(
            "</head>",
            "<script>globalThis.agentspineIdentityEnabled = true;</script></head>",
            1,
        )
