from __future__ import annotations

from pathlib import Path
from typing import Any

from helpers.extension import Extension


def _add_svg_thumbnail_urls(items: Any) -> Any:
    """Advertise plugin-local SVG thumbnails on hosts that scan rasters only."""
    if not isinstance(items, list):
        return items

    for item in items:
        if getattr(item, "thumbnail_url", ""):
            continue
        plugin_path = getattr(item, "path", "")
        plugin_name = getattr(item, "name", "")
        if not plugin_path or not plugin_name:
            continue
        if (Path(plugin_path) / "webui" / "thumbnail.svg").is_file():
            item.thumbnail_url = f"/plugins/{plugin_name}/webui/thumbnail.svg"
    return items


class EnhancedSpeechSvgPluginThumbnails(Extension):
    """Extend the plugin catalog without changing the host's raster allow-list."""

    def execute(self, **kwargs):
        try:
            from helpers import plugins

            if getattr(plugins, "_agentspine_svg_thumbnail_patch", False):
                return

            original = plugins.get_enhanced_plugins_list

            def get_enhanced_plugins_list_with_svg(*args, **inner_kwargs):
                return _add_svg_thumbnail_urls(original(*args, **inner_kwargs))

            plugins.get_enhanced_plugins_list = get_enhanced_plugins_list_with_svg
            plugins._agentspine_svg_thumbnail_patch = True
        except Exception:
            # Plugin discovery must stay available if an older host has a
            # different inventory module or lifecycle ordering.
            return
