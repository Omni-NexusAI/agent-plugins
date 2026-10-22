"""The host-compat probe's checks, run offline against the pinned fixtures."""
from __future__ import annotations

import json
import unittest

from .compat import check_upstream as probe
from .loader import PLUGIN_DIR

FIXTURES = PLUGIN_DIR / "tests" / "fixtures"
PATHS = probe.FILES


def load(version: str) -> dict[str, str]:
    return {path: (FIXTURES / f"a0-{version}" / path).read_text(encoding="utf-8") for path in PATHS}


class ProbeOnPinnedHosts(unittest.TestCase):
    def test_pinned_hosts_have_every_dependency(self):
        for version in ("v2.11", "v2.14"):
            with self.subTest(version=version):
                rows = probe.evaluate(load(version))
                self.assertGreaterEqual(len(rows), 15)
                bad = [row for row in rows if row[0] != "PASS"]
                self.assertEqual(bad, [])

    def test_missing_dependency_is_reported_as_fail(self):
        files = load("v2.14")
        files[probe.FIELD] = files[probe.FIELD].replace("model-search-item", "renamed-row")
        statuses = {name: status for status, name, _ in probe.evaluate(files)}
        self.assertEqual(statuses["result rows"], "FAIL")
        files = load("v2.14")
        files[probe.STORE] = files[probe.STORE].replace("async searchModelsDetailed(", "async searchModelsRenamed(")
        statuses = {name: status for status, name, _ in probe.evaluate(files)}
        self.assertEqual(statuses["searchModelsDetailed"], "FAIL")

    def test_discovery_dependencies_are_checked(self):
        rows = {name: (status, detail) for status, name, detail in probe.evaluate(load("v2.14"))}
        self.assertEqual(rows["get_api_key_raw"][0], "PASS")
        self.assertIn("present", rows["get_api_key_raw"][1])
        self.assertIn("absent", {name: detail for _s, name, detail in probe.evaluate(load("v2.11"))}["get_api_key_raw"], "v2.11 has no raw reader: the fallback is used")
        files = load("v2.14")
        files[probe.MODELS] = files[probe.MODELS].replace("def get_api_key(", "def get_key(")
        files[probe.PROVIDERS] = files[probe.PROVIDERS].replace("def get_provider_config(", "def provider_config(")
        files[probe.STORE] = files[probe.STORE].replace("models: data.models || [],", "list: data.models || [],")
        statuses = {name: status for status, name, _ in probe.evaluate(files)}
        self.assertEqual(statuses["get_api_key"], "FAIL")
        self.assertEqual(statuses["get_provider_config"], "FAIL")
        self.assertEqual(statuses["search result carries models"], "FAIL")
        files = load("v2.14")
        files[probe.MODELS] = files[probe.MODELS].replace('f"{service.upper()}_API_TOKEN"', 'f"{service.upper()}_TOKEN"')
        self.assertEqual({name: status for status, name, _ in probe.evaluate(files)}["stored key lookups"], "WARN")

    def test_native_favorites_in_the_host_warn(self):
        files = load("v2.14")
        files[probe.STORE] = files[probe.STORE].replace("  groupResults(models, query) {", "  toggleFavorite(model) {},\n  groupResults(models, query) {", 1)
        statuses = {name: status for status, name, _ in probe.evaluate(files)}
        self.assertEqual(statuses["no native favorites store members"], "WARN")

    def test_missing_files_fail_cleanly(self):
        rows = probe.evaluate({})
        self.assertTrue(any(status == "FAIL" for status, _, _ in rows))

    def test_fixture_manifests_match_the_files(self):
        for version in ("v2.11", "v2.14"):
            manifest = json.loads((FIXTURES / f"a0-{version}" / "MANIFEST.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["commit"], probe.upstream.PINNED[version])
            for path, meta in manifest["files"].items():
                data = (FIXTURES / f"a0-{version}" / path).read_bytes()
                self.assertEqual(probe.upstream.sha256(data), meta["sha256"], f"{version} {path}")
                self.assertEqual(len(data), meta["bytes"])

    def test_fixtures_are_marked_byte_exact(self):
        self.assertIn("-text", (FIXTURES / ".gitattributes").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
