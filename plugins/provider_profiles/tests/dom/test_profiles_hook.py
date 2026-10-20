"""Existing provider-memory hook (_10_provider_profiles.html) on both pinned hosts."""
from __future__ import annotations

import unittest

from .base import DomCase

HOOK = "_10_provider_profiles.html"
CHAT_SELECT = "#slot-chat select[x-model='model.provider']"

GET_CHAT = "Alpine.$data(document.querySelector('#editor')).selectedPreset.chat"


class HookMixin:
    def open_hooked(self, **kwargs):
        page = self.open_harness(ext=HOOK, **kwargs)
        page.wait_for_function(f"document.querySelector(\"{CHAT_SELECT}\")?.__providerProfilesWired === true", timeout=10000)
        return page

    def choose(self, page, selector, value):
        # A real user focuses/presses the select before changing it; the hook snapshots the previous provider then.
        page.focus(selector)
        page.select_option(selector, value)

    def chat(self, page, expr=""):
        return page.evaluate(f"() => {GET_CHAT}{expr}")

    def wait_saved(self, key):
        deadline_ms = 5000
        self.page.wait_for_function(
            "() => true", timeout=deadline_ms
        )
        for _ in range(50):
            profiles = self.server.state.configs.get("_provider_profiles", {}).get("profiles", {})
            if key in profiles:
                return profiles[key]
            self.page.wait_for_timeout(100)
        self.fail(f"profile {key} was not saved: {self.server.state.configs}")

    def test_restored_kwargs_survive_save(self):
        page = self.open_hooked()
        page.evaluate(f"""() => {{ const c = {GET_CHAT}; c.kwargs = {{a: 1}}; c._kwargs_text = 'a=1'; c.name = 'my-model'; }}""")
        self.choose(page, CHAT_SELECT, "lm_studio")
        page.wait_for_function(f"() => {GET_CHAT}.provider === 'lm_studio'")
        self.wait_saved("chat_model:openrouter")
        self.assertEqual(self.chat(page, ".api_base"), "http://host.docker.internal:1234/v1")
        self.assertEqual(self.chat(page, ".name"), "")
        self.choose(page, CHAT_SELECT, "openrouter")
        page.wait_for_function(f"() => {GET_CHAT}.provider === 'openrouter' && {GET_CHAT}.name === 'my-model'")
        self.assertEqual(self.chat(page, ".kwargs"), {"a": 1})
        self.assertEqual(self.chat(page, "._kwargs_text"), "a=1")
        page.click("#btn-save")
        self.assertEqual(page.evaluate("window.__saved[0].chat.kwargs"), {"a": 1})
        self.assertEqual(self.errors(), [])

    def test_unknown_fields_kept_and_secrets_dropped(self):
        page = self.open_hooked()
        page.evaluate(f"""() => {{ const c = {GET_CHAT}; c.timeout = 300; c.max_tokens = 2000; c.api_key = 'sk-secret'; c.name = 'm'; }}""")
        self.choose(page, CHAT_SELECT, "lm_studio")
        saved = self.wait_saved("chat_model:openrouter")
        self.assertEqual(saved["timeout"], 300)
        self.assertEqual(saved["max_tokens"], 2000)
        self.assertNotIn("api_key", saved)
        self.assertFalse([k for k in saved if k.startswith("_")])

    def test_switch_provider_api(self):
        page = self.open_hooked()
        result = page.evaluate(f"""async () => {{
          const select = document.querySelector("{CHAT_SELECT}");
          const scope = __providerProfiles.findModelScope(select);
          const ok = await __providerProfiles.switchProvider(select, scope, 'ollama');
          const missing = await __providerProfiles.switchProvider(select, scope, 'no_such_provider');
          const same = await __providerProfiles.switchProvider(select, scope, 'ollama');
          return {{ ok, missing, same, provider: scope.model.provider, api_base: scope.model.api_base, selectValue: select.value }};
        }}""")
        self.assertEqual(result["ok"], {"ok": True, "changed": True})
        self.assertEqual(result["missing"], {"ok": False, "reason": "provider-unavailable"})
        self.assertEqual(result["same"], {"ok": True, "changed": False})
        self.assertEqual(result["provider"], "ollama")
        self.assertEqual(result["api_base"], "http://host.docker.internal:11434")
        self.assertEqual(result["selectValue"], "ollama")
        self.wait_saved("chat_model:openrouter")  # previous provider captured exactly through the programmatic path

    def test_listener_does_not_run_twice_for_programmatic_switch(self):
        page = self.open_hooked()
        page.evaluate(f"""async () => {{
          const select = document.querySelector("{CHAT_SELECT}");
          await __providerProfiles.switchProvider(select, __providerProfiles.findModelScope(select), 'ollama');
        }}""")
        page.wait_for_timeout(300)
        saves = [r for r in self.server.state.calls("/api/plugins") if (r["body"] or {}).get("action") == "save_config"]
        self.assertEqual(len(saves), 1)

    def test_idempotent_reload_and_dispose(self):
        page = self.open_hooked()
        page.evaluate("""() => { window.__pp1 = __providerProfiles; }""")
        page.evaluate("""() => { const el = document.createElement('x-component'); el.setAttribute('path', '/plugins/provider_profiles/extensions/webui/page-head/_10_provider_profiles.html'); document.head.appendChild(el); }""")
        page.wait_for_timeout(400)
        self.assertTrue(page.evaluate("__providerProfiles === window.__pp1"))
        patched_before = page.evaluate("Alpine.store('modelConfig').__providerProfilesPatched")
        self.assertTrue(patched_before)
        page.evaluate("__providerProfiles.dispose()")
        self.assertEqual(page.evaluate("typeof globalThis.__providerProfiles"), "undefined")
        self.assertFalse(page.evaluate("Alpine.store('modelConfig').__providerProfilesPatched"))
        self.assertEqual(page.evaluate("typeof Alpine.store('modelConfig').onProviderProfileChanged"), "undefined")
        self.assertEqual(self.errors(), [])

    def test_store_before_extension_order(self):
        page = self.open_hooked(order="store-first")
        self.assertTrue(page.evaluate("Alpine.store('modelConfig').__providerProfilesPatched"))
        self.assertEqual(self.errors(), [])

    def test_vision_slot_gets_profiles(self):
        page = self.open_hooked()
        page.evaluate("""() => { Alpine.$data(document.querySelector('#editor')).selectedPreset.chat.vision = false; }""")
        page.wait_for_selector("#slot-vision select[x-model='model.provider']")
        page.wait_for_function("document.querySelector(\"#slot-vision select[x-model='model.provider']\")?.__providerProfilesWired === true")
        page.evaluate("""() => { const v = Alpine.$data(document.querySelector('#editor')).selectedPreset.vision; v.provider = 'openrouter'; v.name = 'vis-model'; }""")
        self.choose(page, "#slot-vision select[x-model='model.provider']", "ollama")
        self.wait_saved("vision_model:openrouter")


class HookV211(HookMixin, DomCase):
    host = "v2.11"


class HookV214(HookMixin, DomCase):
    host = "v2.14"


if __name__ == "__main__":
    unittest.main()
