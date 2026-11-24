"""Plugin-owned credentials; never alter Agent Zero's environment defaults."""
import os
from pathlib import Path, PurePosixPath

from .client import A2AError


def resolve_credential(entry, plugin_root):
    token_file, token_env = entry.get("token_file"), entry.get("token_env")
    if token_file and token_env:
        raise A2AError("Configure exactly one credential source for this peer")
    if token_file:
        if not isinstance(token_file, str):
            raise A2AError("Peer credential file must be plugin-local")
        relative = PurePosixPath(token_file)
        if (relative.is_absolute() or ".." in relative.parts or "\\" in token_file
                or len(relative.parts) != 2 or relative.parts[0] != ".private"):
            raise A2AError("Peer credential file must be inside the plugin's .private directory")
        root = Path(plugin_root).resolve()
        private = root / ".private"
        path = root / Path(*relative.parts)
        if private.is_symlink() or path.is_symlink() or not path.resolve().is_relative_to(root):
            raise A2AError("Peer credential file must not redirect outside this plugin")
        try:
            with path.open("rb") as stream:
                raw = stream.read(4097)
            if len(raw) > 4096:
                raise ValueError()
            credential = raw.decode("utf-8").strip()
        except (OSError, UnicodeError, ValueError):
            raise A2AError("Peer credential file is missing or invalid") from None
        if not credential or any(ord(c) < 32 for c in credential):
            raise A2AError("Peer credential file is empty or invalid")
        return credential
    if token_env:
        if token_env == "A2A_TOKEN":
            raise A2AError("A2A_TOKEN is reserved for native Agent Zero; use a plugin-local credential")
        if not isinstance(token_env, str):
            raise A2AError("Peer credential environment name is invalid")
        return os.getenv(token_env, "")
    return None
