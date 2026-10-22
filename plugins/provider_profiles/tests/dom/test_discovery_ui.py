"""Local endpoint discovery on the real upstream model field + store (pinned v2.11 and v2.14).

The discover_models API is the real endpoint_discovery.handle talking to stdlib fake endpoint servers over sockets;
the host search is either a canned list or the pinned upstream model_search.py (tests/core_search_host.py).
"""
from __future__ import annotations

import unittest

from ..core_search_host import yaml
from ..fake_endpoints import FakeEndpoint
from .base import DomCase

EDITOR = "Alpine.$data(document.querySelector('#editor'))"
CHAT_INPUT = "#slot-chat input[x-model='model.name']"
CHAT_ROWS = "#slot-chat .model-search-results .model-search-item:not(.disabled)"

# What the host's own search lists for the llama.cpp router fixture (its chat filter drops the embedding and image rows).
HOST_ROUTER = ["crashing-config", "gemma-4-12b-qat", "half-downloaded-model", "ornith-1.5-35b-gpukv-128k-vision",
               "qwen38-27b-apex-mini", "qwen38-27b-apex-mini-vision"]
ROUTER_UNION = sorted(HOST_ROUTER + ["qwen38-mini", "qwen-image-edit-2509-q4"], key=str.lower)


class DiscoveryUiMixin:
    def endpoint(self, kind="llamacpp_router", **kw):
        ep = FakeEndpoint(kind, **kw).start()
        self.addCleanup(ep.stop)
        return ep

    def open_disc(self, ep=None, *, provider="llama_cpp", suffix="/v1", settings=None, host_models=None, setup=None, name="",
                  slot="chat", provider_configs=None, keys=None, favorites_on=True, expect_installed=True, **kw):
        settings = dict(settings or {})
        if not favorites_on:
            settings["favorites_ui"] = "off"

        def prepare(state):
            if host_models is not None:
                state.models[provider] = list(host_models)
            if setup:
                setup(state)

        page = self.open_harness(ext=self.FAVORITES_EXT, favorites=settings, setup=prepare,
                                 discovery={"settings": settings, "provider_configs": provider_configs, "keys": keys}, **kw)
        if expect_installed:
            page.wait_for_function("window.__providerProfilesFavorites && window.__providerProfilesFavorites.fieldCount() >= 3", timeout=15000)
        if ep is not None:
            self.point(slot, provider, ep.url + suffix, name)
        return page

    def point(self, slot, provider, api_base, name=""):
        self.page.evaluate(
            "([slot, provider, apiBase, name]) => { const m = (" + EDITOR + ").selectedPreset[slot]; m.provider = provider; m.api_base = apiBase; m.name = name; }",
            [slot, provider, api_base, name])

    def model(self, slot="chat"):
        return self.page.evaluate(f"() => ({EDITOR}).selectedPreset.{slot}")

    def rows(self, slot="chat"):
        return self.page.evaluate(
            "(slot) => [...document.querySelectorAll(`#slot-${slot} .model-search-results .model-search-item:not(.disabled)`)].map(r => Alpine.$data(r).m)", slot)

    def tags(self, row_id, slot="chat"):
        return self.page.evaluate(
            """([slot, id]) => { const row = [...document.querySelectorAll(`#slot-${slot} .model-search-results .model-search-item`)].find(r => Alpine.$data(r)?.m === id);
                 return row ? [...row.querySelectorAll('.pp-tag')].map(t => t.textContent) : null; }""", [slot, row_id])

    def wait_tags(self, row_id, slot="chat", timeout=8000):
        self.page.wait_for_function(
            """([slot, id]) => [...document.querySelectorAll(`#slot-${slot} .model-search-results .model-search-item`)].some(r => Alpine.$data(r)?.m === id && r.querySelector('.pp-tag'))""",
            arg=[slot, row_id], timeout=timeout)

    def discover_calls(self):
        return self.server.state.calls("/discover_models")

    def open_dropdown(self, slot="chat"):
        self.page.click(f"#slot-{slot} input[x-model='model.name']")

    # ---------------------------------------------------------------- the union and the chips
    def test_union_adds_aliases_and_rows_the_host_filtered_out(self):
        ep = self.endpoint()
        page = self.open_disc(ep, host_models=HOST_ROUTER)
        self.open_dropdown()
        page.wait_for_selector(CHAT_ROWS)
        self.wait_tags("qwen38-mini")
        self.assertEqual(self.rows(), ROUTER_UNION)
        self.assertEqual(self.errors(), [])

    def test_chips_show_state_context_vision_alias_and_failure(self):
        ep = self.endpoint()
        page = self.open_disc(ep, host_models=HOST_ROUTER)
        self.open_dropdown()
        page.wait_for_selector(CHAT_ROWS)
        self.wait_tags("qwen38-27b-apex-mini")
        self.assertEqual(self.tags("qwen38-27b-apex-mini"), ["loaded", "128k ctx"])
        self.assertEqual(self.tags("qwen38-27b-apex-mini-vision"), ["unloaded", "80k ctx", "vision"])
        self.assertEqual(self.tags("qwen38-mini"), ["alias of qwen38-27b-apex-mini", "loaded", "128k ctx"])
        self.assertEqual(self.tags("crashing-config"), ["failed"])
        self.assertEqual(self.tags("gemma-4-12b-qat"), ["downloading"])
        self.assertEqual(self.tags("ornith-1.5-35b-gpukv-128k-vision"), ["sleeping", "32k ctx"])
        self.assertEqual(page.locator("#slot-chat .pp-meta [title], #slot-chat .pp-tag[title], #slot-chat .pp-reason[title], #slot-chat .pp-endpoint[title]").count(), 0,
                         "no title attributes on injected nodes: the host turns them into tooltips")

    def test_the_endpoint_line_names_the_detected_server(self):
        ep = self.endpoint()
        page = self.open_disc(ep, host_models=HOST_ROUTER)
        self.open_dropdown()
        page.wait_for_selector("#slot-chat .pp-endpoint")
        text = page.inner_text("#slot-chat .pp-endpoint")
        self.assertIn("llama.cpp router", text)
        self.assertIn(f"127.0.0.1:{ep.port}", text)
        self.assertIn("7 models", text, "the chat view: the tagged embedding configuration belongs to the embedding field")

    def test_request_body_and_a_single_request_per_open(self):
        ep = self.endpoint()
        page = self.open_disc(ep, host_models=HOST_ROUTER)
        self.open_dropdown()
        page.wait_for_selector(CHAT_ROWS)
        self.wait_tags("qwen38-mini")
        page.mouse.click(5, 5)
        self.open_dropdown()
        page.wait_for_timeout(300)
        calls = self.discover_calls()
        self.assertEqual(len(calls), 1, "the second open reuses the snapshot")
        self.assertEqual(calls[0]["body"], {"provider": "llama_cpp", "api_base": ep.url + "/v1", "model_type": "chat"})
        self.assertEqual(len(ep.requests), 1, "one probe request reached the server")

    def test_stars_work_on_discovered_aliases(self):
        ep = self.endpoint()
        page = self.open_disc(ep, host_models=HOST_ROUTER)
        self.open_dropdown()
        page.wait_for_selector(CHAT_ROWS)
        self.wait_tags("qwen38-mini")
        page.click("#slot-chat .model-search-item:has(.pp-meta):has-text('alias of') .pp-star")
        page.wait_for_function("document.querySelector('#slot-chat .pp-star-on') !== null")
        waited = 0
        stored = []
        while waited < 5000 and not stored:
            stored = [(e["provider"], e["api_base"], e["name"]) for e in self.server.state.favorites_store.snapshot()["types"]["chat"]]
            page.wait_for_timeout(50)
            waited += 50
        self.assertEqual(stored, [("llama_cpp", ep.url + "/v1", "qwen38-mini")])
        self.assertEqual(self.tags("qwen38-mini")[0], "alias of qwen38-27b-apex-mini", "chips survive the star toggle")

    def test_selecting_a_discovered_row_leaves_the_numbers_alone_by_default(self):
        ep = self.endpoint()
        page = self.open_disc(ep, host_models=HOST_ROUTER)
        page.evaluate(f"() => {{ const m = ({EDITOR}).selectedPreset.chat; m.vision = false; m.ctx_length = 4242; }}")
        self.open_dropdown()
        page.wait_for_selector(CHAT_ROWS)
        self.wait_tags("qwen38-27b-apex-mini-vision")
        page.click("#slot-chat .model-search-item:has-text('qwen38-27b-apex-mini-vision')")
        page.wait_for_timeout(300)
        model = self.model()
        self.assertEqual((model["name"], model["ctx_length"], model["vision"]), ("qwen38-27b-apex-mini-vision", 4242, False))

    def test_fill_on_select_sets_context_and_vision_from_the_server(self):
        ep = self.endpoint()
        page = self.open_disc(ep, host_models=HOST_ROUTER, settings={"discovery_fill_on_select": True})
        page.evaluate(f"() => {{ const m = ({EDITOR}).selectedPreset.chat; m.vision = false; m.ctx_length = 4242; }}")
        self.open_dropdown()
        page.wait_for_selector(CHAT_ROWS)
        self.wait_tags("qwen38-27b-apex-mini-vision")
        page.click("#slot-chat .model-search-item:has-text('qwen38-27b-apex-mini-vision')")
        page.wait_for_function(f"() => ({EDITOR}).selectedPreset.chat.ctx_length === 81920")
        model = self.model()
        self.assertEqual((model["name"], model["ctx_length"], model["vision"]), ("qwen38-27b-apex-mini-vision", 81920, True))
        self.open_dropdown()
        page.wait_for_selector(CHAT_ROWS)
        self.wait_tags("qwen38-mini")
        page.click("#slot-chat .model-search-item:has(.pp-meta):has-text('alias of')")
        page.wait_for_function(f"() => ({EDITOR}).selectedPreset.chat.ctx_length === 131072")
        self.assertEqual(self.model()["name"], "qwen38-mini")
        self.assertEqual(self.errors(), [])

    def test_fill_on_select_never_touches_embedding_or_unknown_numbers(self):
        ep = self.endpoint("lmstudio")
        page = self.open_disc(ep, provider="lm_studio", host_models=["google/gemma-3-12b", "qwen/qwen3-30b-a3b"], settings={"discovery_fill_on_select": True})
        page.evaluate(f"() => {{ const m = ({EDITOR}).selectedPreset.chat; m.vision = false; m.ctx_length = 4242; }}")
        self.open_dropdown()
        page.wait_for_selector(CHAT_ROWS)
        self.wait_tags("google/gemma-3-12b")
        page.click("#slot-chat .model-search-item:has-text('google/gemma-3-12b')")
        page.wait_for_function(f"() => ({EDITOR}).selectedPreset.chat.vision === true")
        self.assertEqual(self.model()["ctx_length"], 4242, "an unloaded model's 128k maximum is not an operating context")

    # ---------------------------------------------------------------- reasons instead of "No models found"
    def test_unauthorized_endpoint_explains_itself(self):
        ep = self.endpoint(token="k1")
        page = self.open_disc(ep, host_models=[])
        self.open_dropdown()
        page.wait_for_selector("#slot-chat .pp-reason")
        text = page.inner_text("#slot-chat .pp-reason")
        self.assertIn("requires an API key", text)
        self.assertIn('"llama_cpp"', text)
        self.assertEqual(self.rows(), [])
        self.assertTrue(page.is_visible("#slot-chat .pp-reason"), "the reason sits in the visible no-results box")
        self.assertEqual(self.errors(), [])

    def test_unreachable_endpoint_explains_itself(self):
        ep = self.endpoint()
        port = ep.port
        ep.stop()
        page = self.open_disc(None, host_models=[])
        self.point("chat", "llama_cpp", f"http://127.0.0.1:{port}/v1")
        self.open_dropdown()
        page.wait_for_selector("#slot-chat .pp-reason", timeout=10000)
        self.assertIn("Could not connect", page.inner_text("#slot-chat .pp-reason"))
        self.assertIn("host.docker.internal", page.inner_text("#slot-chat .pp-reason"))

    def test_catalog_suggestions_are_dropped_when_the_endpoint_answers(self):
        ep = self.endpoint("openai_generic")
        junk = ["gpt-4o", "gpt-4o-mini", "o3"]
        page = self.open_disc(ep, provider="other", host_models=junk, setup=lambda s: setattr(s, "search_source", "litellm_registry"))
        self.open_dropdown()
        page.wait_for_selector(CHAT_ROWS)
        self.wait_tags("my-served-model")
        self.assertEqual(self.rows(), ["another-model", "my-served-model"])
        if self.host == "v2.14":
            self.assertFalse(page.locator("#slot-chat .model-search-item.disabled:has-text('Catalog suggestions')").is_visible())

    def test_failed_discovery_adds_its_reason_above_catalog_suggestions(self):
        ep = self.endpoint("openai_generic", token="k1")
        page = self.open_disc(ep, provider="other", host_models=["gpt-4o"], setup=lambda s: setattr(s, "search_source", "litellm_registry"))
        self.open_dropdown()
        page.wait_for_selector(CHAT_ROWS)
        page.wait_for_selector("#slot-chat .model-search-results > .pp-reason", state="attached")
        first = page.evaluate("document.querySelector('#slot-chat .model-search-results').firstElementChild.className")
        self.assertIn("pp-reason", first)
        self.assertEqual(self.rows(), ["gpt-4o"], "the host's list is untouched")

    def test_discovery_service_down_is_silent(self):
        ep = self.endpoint()
        page = self.open_disc(ep, host_models=HOST_ROUTER, setup=lambda s: setattr(s, "discovery_status", 500))
        self.open_dropdown()
        page.wait_for_selector(CHAT_ROWS)
        page.wait_for_timeout(300)
        self.assertEqual(self.rows(), HOST_ROUTER)
        self.assertEqual(page.locator(".pp-meta, .pp-reason, .pp-endpoint").count(), 0)
        self.assertEqual(self.errors(), [])
        self.assertEqual(self.server.state.toasts if hasattr(self.server.state, "toasts") else [], [])

    def test_missing_discovery_api_is_silent(self):
        ep = self.endpoint()
        page = self.open_harness(ext=self.FAVORITES_EXT, favorites={}, setup=lambda s: s.models.update({"llama_cpp": list(HOST_ROUTER)}))
        page.wait_for_selector("#slot-chat .pp-star-input")
        self.point("chat", "llama_cpp", ep.url + "/v1")
        self.open_dropdown()
        page.wait_for_selector(CHAT_ROWS)
        page.wait_for_timeout(300)
        self.assertEqual(self.rows(), HOST_ROUTER)
        self.assertEqual(page.locator(".pp-meta, .pp-reason, .pp-endpoint").count(), 0)
        self.assertEqual(self.errors(), [])

    def test_cloud_providers_are_skipped_without_noise(self):
        page = self.open_disc(None)
        self.open_dropdown()
        page.wait_for_selector(CHAT_ROWS)
        page.wait_for_timeout(300)
        self.assertEqual(page.locator(".pp-meta, .pp-reason, .pp-endpoint").count(), 0)
        calls = self.discover_calls()
        self.assertEqual([c["body"]["provider"] for c in calls], ["openrouter"])
        page.mouse.click(5, 5)
        self.open_dropdown()
        page.wait_for_timeout(300)
        self.assertEqual(len(self.discover_calls()), 1, "a skipped answer is remembered for a while")

    # ---------------------------------------------------------------- deadline
    def test_a_hung_discovery_never_holds_the_dropdown_and_decorates_late(self):
        ep = self.endpoint()
        page = self.open_disc(ep, host_models=HOST_ROUTER, setup=lambda s: setattr(s, "discovery_mode", "hang"))
        self.open_dropdown()
        page.wait_for_selector(CHAT_ROWS, timeout=6000)
        self.assertEqual(self.rows(), sorted(HOST_ROUTER, key=str.lower), "only the host's rows after the 3 s deadline")
        self.assertEqual(self.tags("qwen38-27b-apex-mini"), [])
        self.server.state.release.set()
        self.wait_tags("qwen38-27b-apex-mini")
        self.assertEqual(self.tags("qwen38-27b-apex-mini"), ["loaded", "128k ctx"], "the late answer still decorates the open dropdown")
        self.assertEqual(self.errors(), [])

    # ---------------------------------------------------------------- modes and switches
    def test_core_mode_adds_only_what_the_hosts_query_rule_would_show(self):
        ep = self.endpoint()
        page = self.open_disc(ep, host_models=HOST_ROUTER, settings={"normal_results_mode": "core"}, name="qwen38-mini")
        self.open_dropdown()
        page.wait_for_selector(CHAT_ROWS)
        self.wait_tags("qwen38-mini")
        self.assertEqual(self.rows(), ["qwen38-mini", "qwen38-27b-apex-mini"], "the host's own match-first order: the alias, then the configuration it belongs to")
        self.assertEqual(self.server.state.calls("/model_search")[-1]["body"]["query"], "qwen38-mini", "official request preserved")

    def test_discovery_works_with_favorites_off(self):
        ep = self.endpoint()
        page = self.open_disc(ep, host_models=HOST_ROUTER, favorites_on=False, settings={"normal_results_mode": "narrow"})
        self.open_dropdown()
        page.wait_for_selector(CHAT_ROWS)
        self.wait_tags("qwen38-mini")
        self.assertEqual(self.rows(), ROUTER_UNION, "empty field: everything")
        self.assertEqual(page.locator(".pp-star, .pp-card, .pp-has-star").count(), 0, "no favorites UI")
        self.assertEqual(self.server.state.calls("/model_search")[-1]["body"]["query"], "", "the field was empty")
        self.point("chat", "llama_cpp", ep.url + "/v1", "qwen38-mini")
        page.mouse.click(5, 5)
        self.open_dropdown()
        page.wait_for_function("document.querySelectorAll('#slot-chat .model-search-results .model-search-item:not(.disabled)').length === 2", timeout=6000)
        self.assertEqual(self.server.state.calls("/model_search")[-1]["body"]["query"], "qwen38-mini", "favorites off means official request bodies")
        self.assertEqual(self.errors(), [])

    def test_flags_off_make_no_extra_request_and_change_nothing(self):
        ep = self.endpoint()
        page = self.open_disc(ep, host_models=HOST_ROUTER, favorites_on=False, expect_installed=False,
                              settings={"normal_results_mode": "core", "discovery_enabled": False})
        page.wait_for_timeout(700)
        self.point("chat", "llama_cpp", ep.url + "/v1")
        self.assertEqual(page.evaluate("typeof window.__providerProfilesFavorites"), "undefined", "nothing installed")
        self.open_dropdown()
        page.wait_for_selector(CHAT_ROWS)
        page.wait_for_timeout(300)
        self.assertEqual(self.discover_calls(), [])
        self.assertEqual(ep.requests, [])
        self.assertEqual(self.rows(), HOST_ROUTER)
        self.assertEqual(page.locator("[class*='pp-']").count(), 0)

    def test_discovery_off_with_favorites_on_is_a_pure_passthrough(self):
        ep = self.endpoint()
        page = self.open_disc(ep, host_models=HOST_ROUTER, settings={"discovery_enabled": False})
        self.assertFalse(page.evaluate("window.__providerProfilesFavorites.hasDiscovery"))
        self.open_dropdown()
        page.wait_for_selector(CHAT_ROWS)
        page.wait_for_timeout(300)
        self.assertEqual(self.discover_calls(), [])
        self.assertEqual(self.rows(), HOST_ROUTER)
        self.assertEqual(page.locator(".pp-meta, .pp-reason, .pp-endpoint").count(), 0)

    def test_discovery_modules_that_fail_to_load_leave_favorites_working(self):
        ep = self.endpoint()
        page = self.open_disc(ep, host_models=HOST_ROUTER, setup=lambda s: s.blocked_static.add("discovery-ui.js"))
        self.assertFalse(page.evaluate("window.__providerProfilesFavorites.hasDiscovery"))
        page.wait_for_selector("#slot-chat .pp-star-input")
        self.open_dropdown()
        page.wait_for_selector(CHAT_ROWS)
        page.wait_for_timeout(300)
        self.assertEqual(self.discover_calls(), [])
        self.assertEqual(self.rows(), HOST_ROUTER)

    def test_dispose_removes_the_decoration_and_restores_the_store(self):
        ep = self.endpoint()
        page = self.open_disc(ep, host_models=HOST_ROUTER)
        self.open_dropdown()
        page.wait_for_selector(CHAT_ROWS)
        self.wait_tags("qwen38-mini")
        page.evaluate("() => window.__providerProfilesFavorites.dispose()")
        self.assertEqual(page.locator("[class*='pp-']").count(), 0)
        calls = len(self.discover_calls())
        page.mouse.click(5, 5)
        self.open_dropdown()
        page.wait_for_selector(CHAT_ROWS)
        page.wait_for_timeout(300)
        self.assertEqual(len(self.discover_calls()), calls, "the host search no longer asks discovery")
        self.assertEqual(self.rows(), HOST_ROUTER)

    # ---------------------------------------------------------------- other slots
    def test_utility_slot_asks_for_the_effective_provider_and_base(self):
        ep = self.endpoint()
        page = self.open_disc(ep, host_models=HOST_ROUTER)
        page.click("#slot-utility input[x-model='model.name']")
        page.wait_for_selector("#slot-utility .model-search-results .model-search-item:not(.disabled)")
        self.wait_tags("qwen38-27b-apex-mini", slot="utility")
        self.assertEqual(self.discover_calls()[-1]["body"], {"provider": "llama_cpp", "api_base": ep.url + "/v1", "model_type": "chat"})

    def test_embedding_slot_gets_the_embedding_view(self):
        ep = self.endpoint("lmstudio")
        page = self.open_disc(ep, provider="lm_studio", slot="embedding", host_models=["text-embedding-nomic-embed-text-v1.5"])
        self.open_dropdown("embedding")
        page.wait_for_selector("#slot-embedding .model-search-results .model-search-item:not(.disabled)")
        self.wait_tags("text-embedding-nomic-embed-text-v1.5", slot="embedding")
        self.assertEqual(self.discover_calls()[-1]["body"]["model_type"], "embedding")
        self.assertEqual(self.rows("embedding"), ["text-embedding-nomic-embed-text-v1.5"])
        self.assertIn("embedding", self.tags("text-embedding-nomic-embed-text-v1.5", slot="embedding"))

    # ---------------------------------------------------------------- against the pinned upstream search
    @unittest.skipIf(yaml is None, "PyYAML is required to run the pinned upstream search")
    def test_with_the_pinned_upstream_search_the_union_closes_its_gaps(self):
        ep = self.endpoint()
        page = self.open_disc(ep, setup=lambda s: s.enable_core_search())
        self.point("chat", "llama_cpp", ep.url + "/v1")
        self.open_dropdown()
        page.wait_for_selector(CHAT_ROWS)
        self.wait_tags("qwen38-mini")
        self.assertEqual(self.rows(), ROUTER_UNION)
        self.assertEqual(self.tags("qwen-image-edit-2509-q4"), ["unloaded"], "the host's name filter would have hidden this configuration")

    @unittest.skipIf(yaml is None, "PyYAML is required to run the pinned upstream search")
    def test_with_the_pinned_upstream_search_a_401_is_explained(self):
        ep = self.endpoint(token="k1")
        page = self.open_disc(ep, setup=lambda s: s.enable_core_search())
        self.point("chat", "llama_cpp", ep.url + "/v1")
        self.open_dropdown()
        page.wait_for_selector("#slot-chat .pp-reason", timeout=10000)
        self.assertIn("requires an API key", page.inner_text("#slot-chat .pp-reason"))


class DiscoveryUiV211(DiscoveryUiMixin, DomCase):
    host = "v2.11"


class DiscoveryUiV214(DiscoveryUiMixin, DomCase):
    host = "v2.14"


if __name__ == "__main__":
    unittest.main()
