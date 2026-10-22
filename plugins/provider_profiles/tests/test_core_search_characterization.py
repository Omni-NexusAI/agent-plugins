"""Phase 0: what Agent Zero's OWN model search does today, measured against fake endpoints.

Runs the pinned upstream `model_search.py` (v2.11 and v2.14) with real httpx against real sockets. Every test
documents one measured behavior (a "baseline" the plugin must not regress, or a "gap" PR 2 closes). If a
future Agent Zero release changes one of these, the matching test fails and the discovery layer must be
re-checked (see tests/compat/check_upstream.py).
"""
from __future__ import annotations

import unittest

from . import endpoint_payloads as payloads
from .core_search_host import CoreSearch, yaml
from .fake_endpoints import FakeEndpoint, Route, TempCert, redirect

CHAT_DROPPED_SUBSTRINGS = ("embed", "image", "audio", "tts", "whisper", "speech", "transcri", "realtime", "moderation", "vision-preview")

STRATA_PROVIDER = {"chat": {"strata_router": {
    "name": "Strata Router", "litellm_provider": "openai",
    "kwargs": {"api_base": "https://host.docker.internal:8096/v1"},
    "models_list": {"endpoint_url": "/models"},
}}}


@unittest.skipIf(yaml is None, "PyYAML is required to read the pinned provider config")
class CoreSearchMixin:
    version = ""

    def core(self, **kw):
        return CoreSearch(self.version, **kw)

    # ------------------------------------------------------------ baseline: what already works
    def test_result_shape_is_ids_only(self):
        with FakeEndpoint("lmstudio") as ep:
            result = self.core().run("lm_studio", ep.url)
        self.assertEqual(set(result), {"models", "provider", "source", "error"})
        self.assertTrue(all(isinstance(m, str) for m in result["models"]), "bare id strings: no state, context or type")
        self.assertEqual(result["source"], "provider_endpoint")

    def test_results_are_sorted_and_unique(self):
        routes = {"/v1/models": {"data": [{"id": "b"}, {"id": "A"}, {"id": "b"}, {"id": "c"}]}}
        with FakeEndpoint(routes) as ep:
            result = self.core().run("llama_cpp", ep.url)
        self.assertEqual(result["models"], ["A", "b", "c"])

    def test_lm_studio_lists_openai_ids_at_slash_v1_models(self):
        with FakeEndpoint("lmstudio") as ep:
            result = self.core().run("lm_studio", ep.url)
            self.assertEqual(ep.paths(), ["/v1/models"])
        self.assertEqual(result["models"], ["google/gemma-3-12b", "qwen/qwen3-30b-a3b"])

    def test_ollama_native_merges_tags_and_ps_without_keeping_the_loaded_state(self):
        with FakeEndpoint("ollama") as ep:
            result = self.core().run("ollama", ep.url)
            self.assertEqual(ep.paths(), ["/api/tags", "/api/ps"])
        self.assertEqual(result["models"], ["llama3.1:8b", "llama3.1:8b-instruct-q8_0"])

    def test_ollama_base_with_v1_switches_to_the_openai_list(self):
        with FakeEndpoint("ollama") as ep:
            self.core().run("ollama", ep.url + "/v1")
            self.assertIn("/v1/models", ep.paths())
            self.assertNotIn("/api/tags", ep.paths())

    def test_generic_other_provider_needs_a_base_that_ends_in_v1(self):
        with FakeEndpoint("openai_generic") as ep:
            without = self.core().run("other", ep.url)
            with_v1 = self.core().run("other", ep.url + "/v1")
        self.assertEqual(without["models"], [])
        self.assertIn("HTTP 404", without["error"])
        self.assertEqual(with_v1["models"], ["another-model", "my-served-model"])

    def test_custom_provider_with_models_list_behaves_like_other(self):
        with FakeEndpoint("strata_router") as ep:
            result = self.core(extra_providers=STRATA_PROVIDER).run("strata_router", ep.url + "/v1")
            self.assertEqual(ep.paths(), ["/v1/models"])
        self.assertEqual(len(result["models"]), 3)

    def test_embedding_type_is_not_name_filtered(self):
        with FakeEndpoint("llamacpp_router") as ep:
            result = self.core().run("llama_cpp", ep.url, model_type="embedding")
        self.assertEqual(len(result["models"]), len(payloads.llamacpp_router_rows()))

    # ------------------------------------------------------------ gaps PR 2 closes
    def test_gap_router_rows_are_reduced_to_ids_losing_state_aliases_and_failures(self):
        with FakeEndpoint("llamacpp_router") as ep:
            result = self.core().run("llama_cpp", ep.url)
        listed = set(result["models"])
        # loaded, unloaded, sleeping, downloading, incomplete and crashing configurations are indistinguishable
        self.assertTrue({"qwen38-27b-apex-mini", "qwen38-27b-apex-mini-vision", "ornith-1.5-35b-gpukv-128k-vision",
                         "gemma-4-12b-qat", "half-downloaded-model", "crashing-config"} <= listed)
        self.assertNotIn("qwen38-mini", listed, "router aliases are not listed")
        self.assertEqual(set(result), {"models", "provider", "source", "error"})

    def test_gap_name_filter_drops_chat_ids_that_merely_contain_embed_or_image(self):
        with FakeEndpoint("llamacpp_router") as ep:
            chat = set(self.core().run("llama_cpp", ep.url)["models"])
        self.assertNotIn("qwen3-embedding-0.6b", chat)
        self.assertNotIn("qwen-image-edit-2509-q4", chat)
        ids = ["plain-chat", "text-embedding-x", "qwen-image-edit", "whisper-large", "gemma-vision-preview", "tts-1",
               payloads.STRATA_VISION_160K, "omni-moderation", "realtime-x", "my-audio-assistant"]
        with FakeEndpoint({"/v1/models": {"data": [{"id": i} for i in ids]}}) as ep:
            kept = set(self.core().run("llama_cpp", ep.url)["models"])
        self.assertEqual(kept, {"plain-chat", payloads.STRATA_VISION_160K})
        for dropped in set(ids) - kept:
            self.assertTrue(any(s in dropped for s in CHAT_DROPPED_SUBSTRINGS), dropped)

    def test_gap_server_side_text_filter_hides_the_other_router_configurations(self):
        with FakeEndpoint("strata_router") as ep:
            core = self.core(extra_providers=STRATA_PROVIDER)
            filled = core.run("strata_router", ep.url + "/v1", query=payloads.STRATA_VISION_160K)
            empty = core.run("strata_router", ep.url + "/v1", query="")
        self.assertEqual(filled["models"], [payloads.STRATA_VISION_160K], "a filled field lists only near-matches")
        self.assertEqual(len(empty["models"]), 3)

    def test_gap_failures_are_raw_strings_without_a_category_or_a_hint(self):
        with FakeEndpoint("lmstudio", token="k1") as ep:
            unauthorized = self.core().run("lm_studio", ep.url)
        self.assertEqual(unauthorized["models"], [])
        self.assertTrue(unauthorized["error"].endswith("/v1/models: HTTP 401"), unauthorized["error"])
        refused = self.core().run("lm_studio", "http://127.0.0.1:9")
        self.assertEqual(refused["error"], "All connection attempts failed", "no host, no hint, same text for every connect failure")
        with FakeEndpoint({"/v1/models": Route(raw=b"<html>login</html>")}) as ep:
            html = self.core().run("llama_cpp", ep.url)
        self.assertEqual(html["models"], [])
        self.assertIn("Expecting value", html["error"], "a non-JSON answer surfaces the parser's message")

    def test_gap_untrusted_tls_is_a_raw_ssl_error(self):
        with TempCert() as cert:
            if not cert:
                self.skipTest("no TLS tooling (cryptography or openssl)")
            with FakeEndpoint("openai_generic", tls=cert) as ep:
                result = self.core().run("other", ep.url + "/v1")
                self.assertEqual(ep.requests, [], "the handshake fails before any request")
        self.assertEqual(result["models"], [])
        self.assertIn("CERTIFICATE_VERIFY_FAILED", result["error"])

    def test_gap_redirects_are_not_followed(self):
        with FakeEndpoint("openai_generic") as target:
            with FakeEndpoint({"/v1/models": redirect(f"{target.url}/v1/models")}) as ep:
                result = self.core().run("llama_cpp", ep.url)
            self.assertEqual(target.requests, [])
        self.assertIn("HTTP 302", result["error"])

    # ------------------------------------------------------------ authentication
    def test_auth_unsaved_ui_keys_are_never_sent_and_env_keys_are_bearer(self):
        with FakeEndpoint("lmstudio", token="k1") as ep:
            none = self.core(keys={}).run("lm_studio", ep.url)
            saved = self.core(keys={"lm_studio": "k1"}).run("lm_studio", ep.url)
            seen = [r["headers"].get("authorization") for r in ep.requests]
        self.assertEqual(none["models"], [])
        self.assertEqual(seen, [None, "Bearer k1"])
        self.assertEqual(saved["models"], ["google/gemma-3-12b", "qwen/qwen3-30b-a3b"])

    def test_auth_placeholder_keys_are_skipped_for_local_providers(self):
        with FakeEndpoint("lmstudio") as ep:
            self.core(keys={"lm_studio": "lm-studio"}).run("lm_studio", ep.url)
            self.assertIsNone(ep.requests[0]["headers"].get("authorization"))

    def test_auth_ollama_is_never_authenticated(self):
        with FakeEndpoint("ollama", token="k1") as ep:
            result = self.core(keys={"ollama": "k1"}).run("ollama", ep.url)
            self.assertTrue(all(r["headers"].get("authorization") is None for r in ep.requests))
        self.assertEqual(result["models"], [])

    # ------------------------------------------------------------ fallbacks and static facts
    def test_litellm_registry_fallback_lists_openai_catalog_names_for_a_failing_local_endpoint(self):
        registry = {"openai": {"openai/gpt-4o", "openai/gpt-image-1", "openai/text-embedding-3-small", "openai/whisper-1"}}
        result = self.core(litellm_models=registry).run("other", "http://127.0.0.1:9/v1")
        self.assertEqual(result["source"], "litellm_registry")
        self.assertEqual(result["models"], ["gpt-4o"], "unrelated cloud catalog names appear for a local `other` endpoint")

    def test_static_facts_that_the_discovery_design_relies_on(self):
        source = self.core().source()
        self.assertIn("timeout=10.0", source, "10 s per request, requests run sequentially")
        self.assertNotIn("follow_redirects", source, "redirects are not followed")
        self.assertNotIn("max_bytes", source.lower(), "no response size cap")
        self.assertIn("models.get_api_key", source, "API keys come from the host key store only")


class CoreSearchV211(CoreSearchMixin, unittest.TestCase):
    version = "v2.11"


class CoreSearchV214(CoreSearchMixin, unittest.TestCase):
    version = "v2.14"


if __name__ == "__main__":
    unittest.main()
