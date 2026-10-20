"""Repository hygiene: docs, config, manifest and code must agree."""
from __future__ import annotations

import py_compile
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from .loader import PLUGIN_DIR, load_helper

settings_mod = load_helper("settings")

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None


def plugin_files(*patterns):
    for pattern in patterns:
        yield from PLUGIN_DIR.glob(pattern)


class Hygiene(unittest.TestCase):
    def test_python_files_compile(self):
        with tempfile.TemporaryDirectory() as tmp:
            for path in PLUGIN_DIR.rglob("*.py"):
                if "fixtures" in path.parts or "__pycache__" in path.parts:
                    continue
                py_compile.compile(str(path), cfile=str(Path(tmp) / (path.stem + ".pyc")), doraise=True)

    def test_no_bytecode_is_tracked(self):
        if shutil.which("git") is None:
            self.skipTest("git not available")
        result = subprocess.run(["git", "ls-files", "--", str(PLUGIN_DIR)], capture_output=True, text=True, cwd=PLUGIN_DIR)
        if result.returncode != 0:
            self.skipTest("not a git checkout")
        tracked = [line for line in result.stdout.splitlines() if "__pycache__" in line or line.endswith((".pyc", ".pyo"))]
        self.assertEqual(tracked, [])

    def test_versions_agree(self):
        manifest = (PLUGIN_DIR / "plugin.yaml").read_text(encoding="utf-8")
        version = re.search(r"(?m)^version:\s*(\S+)", manifest).group(1)
        for relative in ("extensions/webui/page-head/_10_provider_profiles.html", "extensions/webui/page-head/_20_model_favorites.html", "webui/favorites-ui.js"):
            text = (PLUGIN_DIR / relative).read_text(encoding="utf-8")
            self.assertIn(f'const VERSION = "{version}"', text, relative)

    def test_default_config_matches_code_and_docs(self):
        if yaml is None:
            self.skipTest("PyYAML not available")
        config = yaml.safe_load((PLUGIN_DIR / "default_config.yaml").read_text(encoding="utf-8"))
        self.assertEqual(config, settings_mod.DEFAULTS, "default_config.yaml must equal helpers/settings.py DEFAULTS")
        ui = (PLUGIN_DIR / "webui" / "config.html").read_text(encoding="utf-8")
        readme = (PLUGIN_DIR / "README.md").read_text(encoding="utf-8")
        agents = (PLUGIN_DIR / "AGENTS.md").read_text(encoding="utf-8")
        for key, value in config.items():
            keys = [f"{key}.{sub}" for sub in value] if isinstance(value, dict) else [key]
            for dotted in keys:
                self.assertIn(f"config.{dotted}", ui, f"config.html does not bind {dotted}")
                self.assertIn(f"`{dotted}`", readme, f"README does not document {dotted}")
            self.assertIn(key, agents, f"AGENTS.md does not mention {key}")
        self.assertNotIn("history_storage_key", ui + readme)

    def test_plugin_manifest_identity(self):
        manifest = (PLUGIN_DIR / "plugin.yaml").read_text(encoding="utf-8")
        self.assertRegex(manifest, r"(?m)^name:\s*provider_profiles\s*$")
        self.assertEqual(PLUGIN_DIR.name, "provider_profiles", "directory name must equal the manifest name")

    def test_ui_code_avoids_risky_patterns(self):
        files = list(plugin_files("webui/*.js", "extensions/webui/page-head/*.html"))
        self.assertTrue(files)
        for path in files:
            text = path.read_text(encoding="utf-8")
            code = "\n".join(line for line in text.splitlines() if not line.strip().startswith("//"))
            for pattern in (r"\.innerHTML\s*=", r"\beval\s*\(", r"window\.fetch\s*=", r"globalThis\.fetch\s*=", r"new Function\s*\("):
                self.assertIsNone(re.search(pattern, code), f"{path.name} uses {pattern}")

    def test_css_and_dom_names_are_namespaced(self):
        css = (PLUGIN_DIR / "webui" / "favorites.css").read_text(encoding="utf-8")
        own = re.findall(r"\.(pp-[\w-]+)", css)
        self.assertTrue(own)
        for selector in re.findall(r"(?m)^([^\s@{}/][^{}]*)\{", css):
            for cls in re.findall(r"\.([A-Za-z][\w-]*)", selector):
                self.assertTrue(cls.startswith("pp-") or cls in {"field-control", "model-search-results", "model-search-item", "model-search-btn"},
                                f"unexpected class .{cls} in favorites.css")

    def test_every_api_file_has_one_handler(self):
        for path in plugin_files("api/*.py"):
            self.assertEqual(len(re.findall(r"(?m)^class \w+\(ApiHandler\)", path.read_text(encoding="utf-8"))), 1, path.name)


if __name__ == "__main__":
    unittest.main()
