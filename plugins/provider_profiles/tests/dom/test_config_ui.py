"""webui/config.html inside Alpine: opening never mutates the config; edits write the new keys."""
from __future__ import annotations

import unittest

from .base import DomCase

MOUNT = """async (initial) => {
  const html = await (await fetch('/plugins/provider_profiles/webui/config.html')).text();
  const host = document.createElement('div');
  host.id = 'cfg';
  host.setAttribute('x-data', '{ config: ' + JSON.stringify(initial) + ' }');
  host.innerHTML = html;
  document.body.appendChild(host);
}"""


class ConfigUi(DomCase):
    host = "v2.14"

    def mount(self, initial, wait=True):
        page = self.open_harness()
        page.evaluate(MOUNT, initial)
        if wait:
            page.wait_for_selector("#cfg select")
        return page

    def config(self):
        return self.page.evaluate("JSON.parse(JSON.stringify(Alpine.$data(document.querySelector('#cfg')).config))")

    def test_old_config_is_not_modified_by_opening_the_page(self):
        old = {"history_storage_key": "modelConfig_providerHistory",
               "local_provider_defaults": {"lm_studio": "http://a/v1", "ollama": "http://b"},
               "clear_stale_model_on_new_provider": True}
        page = self.mount(old)
        page.wait_for_timeout(300)
        self.assertEqual(self.config(), old)
        self.assertEqual(page.eval_on_selector("#cfg select >> nth=0", "e => e.value"), "auto")
        self.assertEqual(page.eval_on_selector("#cfg input[type=number]", "e => e.value"), "5")
        self.assertEqual(page.eval_on_selector("#cfg select >> nth=1", "e => e.value"), "narrow")
        self.assertTrue(page.is_checked("#cfg input[type=checkbox]"))

    def test_edits_write_the_new_keys(self):
        page = self.mount({"local_provider_defaults": {"lm_studio": "http://a/v1", "ollama": "http://b"}})
        page.select_option("#cfg select >> nth=0", "off")
        page.fill("#cfg input[type=number]", "7")
        page.select_option("#cfg select >> nth=1", "core")
        page.fill("#cfg input[type=url] >> nth=0", "http://changed:1234/v1")
        page.uncheck("#cfg input[type=checkbox]")
        cfg = self.config()
        self.assertEqual(cfg["favorites_ui"], "off")
        self.assertEqual(cfg["favorites_shown"], 7)
        self.assertEqual(cfg["normal_results_mode"], "core")
        self.assertEqual(cfg["local_provider_defaults"]["lm_studio"], "http://changed:1234/v1")
        self.assertFalse(cfg["clear_stale_model_on_new_provider"])

    def test_renders_nothing_without_a_config(self):
        page = self.mount({}, wait=False)
        page.wait_for_timeout(300)
        self.assertEqual(page.locator("#cfg select").count(), 0)


if __name__ == "__main__":
    unittest.main()
