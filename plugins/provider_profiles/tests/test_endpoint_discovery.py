"""Network layer of local endpoint discovery: address gate, pinned connection, auth, budget, cache, TLS.

Real sockets (stdlib FakeEndpoint on 127.0.0.1) wherever the production code path matters; httpx.MockTransport
only where a failure would be slow or impossible to stage (unreachable hosts, specific resolved addresses).
"""
from __future__ import annotations

import ast
import asyncio
import json
import os
import unittest
from pathlib import Path
from unittest import mock

import httpx

from . import endpoint_payloads as payloads
from .fake_endpoints import FakeEndpoint, Route, TempCert, redirect
from .loader import PLUGIN_DIR, load_helper

discovery = load_helper("endpoint_discovery")

CONFIGS = {
    "lm_studio": {"kwargs": {"api_base": "http://host.docker.internal:1234/v1"},
                  "models_list": {"endpoint_url": "/v1/models", "default_base": "http://host.docker.internal:1234"}},
    "ollama": {"kwargs": {"api_base": "http://host.docker.internal:11434"}, "models_list": {"endpoint_url": "/api/tags", "format": "ollama"}},
    "other": {},
}
KIND_PROVIDERS = {"llamacpp_router": "llama_cpp", "llamacpp_single": "llama_cpp", "lmstudio": "lm_studio", "lmstudio_legacy": "lm_studio",
                  "ollama": "ollama", "llama_swap": "other", "unsloth": "other", "strata_router": "strata_router", "openai_generic": "other"}
ALLOWED_PATHS = {"/v1/models", "/models", "/api/v1/models", "/api/v0/models", "/api/tags", "/api/ps", "/props", "/status"}
KEY = "sk-local-secret-123"


def resolver_for(table):
    async def resolve(host, port):
        value = table.get(host)
        if value is None:
            raise OSError("no such host")
        if isinstance(value, Exception):
            raise value
        return list(value)

    return resolve


def mock_factory(handler, log=None, made=None):
    def factory(scheme):
        if made is not None:
            made.append(scheme)

        def wrapped(request):
            if log is not None:
                log.append(request)
            return handler(request)

        return httpx.AsyncClient(transport=httpx.MockTransport(wrapped), follow_redirects=False)

    return factory


def models_response(request):
    if request.url.path == "/v1/models":
        return httpx.Response(200, json={"data": [{"id": "m1"}, {"id": "m2"}]})
    return httpx.Response(404, json={"error": "nope"})


def call(payload, *, module=None, key=None, settings=None, resolver=None, factory=None, clock=None, configs=None):
    module = module or discovery
    configs = CONFIGS if configs is None else configs
    extra = {}
    if resolver is not None:
        extra["resolver"] = resolver
    if factory is not None:
        extra["client_factory"] = factory
    if clock is not None:
        extra["clock"] = clock
    return asyncio.run(module.handle(payload, settings={"discovery_enabled": True} if settings is None else settings,
                                     provider_config=lambda model_type, provider: configs.get(provider),
                                     stored_key=lambda provider: key, **extra))


def ids(result):
    return [e["id"] for e in result["entries"]]


class Base(unittest.TestCase):
    def setUp(self):
        discovery.clear_cache()


# ------------------------------------------------------------------ address policy
class AddressPolicy(Base):
    def test_classification_table(self):
        table = {
            "127.0.0.1": "loopback", "127.8.8.8": "loopback", "::1": "loopback", "::ffff:127.0.0.1": "loopback",
            "10.1.2.3": "private", "172.16.0.1": "private", "172.31.255.255": "private", "192.168.1.5": "private", "fd12:3456::1": "private",
            "100.64.0.1": "cgnat", "100.127.255.254": "cgnat",
            "169.254.169.254": "blocked", "169.254.1.1": "blocked", "169.254.170.2": "blocked", "100.100.100.200": "blocked",
            "fd00:ec2::254": "blocked", "fe80::1": "blocked", "fe80::1%eth0": "blocked", "::ffff:169.254.169.254": "blocked",
            "0.0.0.0": "blocked", "::": "blocked", "224.0.0.1": "blocked", "ff02::1": "blocked", "240.0.0.1": "blocked",
            "not-an-ip": "blocked", "": "blocked",
            "8.8.8.8": "public", "172.32.0.1": "public", "100.128.0.1": "public", "2606:4700::1111": "public", "192.0.2.1": "public",
        }
        for address, expected in table.items():
            with self.subTest(address=address):
                self.assertEqual(discovery.classify_address(address), expected)

    def test_hosts_are_classified_by_every_resolved_address(self):
        resolver = resolver_for({"llm.lan": ["10.0.0.5"], "mixed.lan": ["10.0.0.5", "8.8.8.8"], "rebind.lan": ["127.0.0.1", "169.254.169.254"],
                                 "empty.lan": [], "down.lan": OSError("nxdomain"), "tailnet.lan": ["100.88.1.2", "fd7a:115c::1"]})

        async def go():
            return {h: await discovery.classify_host(h, 80, resolver) for h in ("llm.lan", "mixed.lan", "rebind.lan", "empty.lan", "down.lan", "tailnet.lan")}

        verdicts = asyncio.run(go())
        self.assertEqual(verdicts["llm.lan"], ("local", ["10.0.0.5"]))
        self.assertEqual(verdicts["mixed.lan"][0], "mixed", "one public address means the host is not probed")
        self.assertEqual(verdicts["rebind.lan"][0], "blocked", "one metadata address blocks the whole host")
        self.assertEqual(verdicts["empty.lan"][0], "unresolved")
        self.assertEqual(verdicts["down.lan"][0], "unresolved")
        self.assertEqual(verdicts["tailnet.lan"][0], "local")

    def test_ip_literals_never_reach_the_resolver(self):
        def boom(host, port):
            raise AssertionError("resolver must not run for IP literals")

        for host, expected in (("127.0.0.1", "local"), ("::1", "local"), ("8.8.8.8", "public"), ("169.254.169.254", "blocked")):
            self.assertEqual(asyncio.run(discovery.classify_host(host, 80, boom))[0], expected)

    def test_a_hanging_resolver_is_bounded(self):
        async def hang(host, port):
            await asyncio.sleep(5)

        with mock.patch.object(discovery, "DNS_TIMEOUT", 0.05):
            self.assertEqual(asyncio.run(discovery.classify_host("slow.lan", 80, hang))[0], "unresolved")

    def test_pins_prefer_ipv4_and_are_capped(self):
        self.assertEqual(discovery._order_pins(["::1", "127.0.0.1"]), ["127.0.0.1", "::1"])
        self.assertEqual(discovery._order_pins(["10.0.0.1", "10.0.0.2", "10.0.0.3"]), ["10.0.0.1", "10.0.0.2"])


# ------------------------------------------------------------------ base URL and key
class BaseUrl(Base):
    def test_valid_bases_are_normalized(self):
        cases = {
            "http://127.0.0.1:1234/v1": ("http", "127.0.0.1", 1234, "", "127.0.0.1:1234"),
            "http://host.docker.internal:8080": ("http", "host.docker.internal", 8080, "", "host.docker.internal:8080"),
            "https://LLM.LAN/V1/": ("https", "llm.lan", 443, "", "llm.lan:443"),
            "http://[::1]:8080/v1": ("http", "::1", 8080, "", "[::1]:8080"),
            "http://llm.lan/proxy/llama/v1": ("http", "llm.lan", 80, "/proxy/llama", "llm.lan:80"),
            "http://llm.lan/a/./b/../c": ("http", "llm.lan", 80, "/a/c", "llm.lan:80"),
            "  http://llm.lan:9//v1//  ": ("http", "llm.lan", 9, "", "llm.lan:9"),
        }
        for text, (scheme, host, port, path, display) in cases.items():
            with self.subTest(text=text):
                base = discovery.parse_base(text)
                self.assertEqual((base["scheme"], base["host"], base["port"], base["path"], base["display"]), (scheme, host, port, path, display))

    def test_idna_hosts_become_ascii(self):
        self.assertEqual(discovery.parse_base("http://bücher.lan:8080")["host"], "xn--bcher-kva.lan")

    def test_unusable_bases_are_rejected(self):
        for text in ("", "   ", "http://u:p@llm.lan/v1", "http://:p@llm.lan", "http://llm.lan/v1?x=1", "http://llm.lan/v1#frag", "ftp://llm.lan",
                     "file:///etc/passwd", "localhost:1234/v1", "http://", "http://llm.lan:0", "http://llm.lan:99999", "http://llm lan/v1",
                     "http://llm.lan\\v1", "http://llm.lan/v\n1", "javascript:alert(1)", None):
            with self.subTest(text=text):
                with self.assertRaises(discovery.DiscoveryError) as raised:
                    discovery.parse_base(text)
                self.assertEqual(raised.exception.category, "invalid_base")


class KeyHandling(Base):
    def test_clean_key_takes_the_first_real_key(self):
        cases = {"k1": "k1", "k1,k2": "k1", " k1 , k2": "k1", "None": None, "none": None, "NULL": None, "": None, "  ": None, None: None, 12: None,
                 "lm-studio": None, "llama-cpp": None, "omlx": None, "vllm": None, "k\n1": None, "kéy": None, "k\x00": None, ",k2": None}
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(discovery.clean_key(raw), expected)


# ------------------------------------------------------------------ real endpoints, every server shape
class ServerShapes(Base):
    def run_kind(self, kind, provider=None, suffix="/v1", **kw):
        with FakeEndpoint(kind, **kw.pop("endpoint", {})) as ep:
            result = call({"provider": provider or KIND_PROVIDERS[kind], "api_base": ep.url + suffix}, **kw)
            return result, ep.paths(), ep

    def test_llama_cpp_router_is_one_request_with_states_and_aliases(self):
        result, paths, _ = self.run_kind("llamacpp_router")
        self.assertEqual(paths, ["/v1/models"])
        self.assertEqual((result["endpoint"]["kind"], result["endpoint"]["label"], result["endpoint"]["requests"]), ("llama_cpp_router", "llama.cpp router", 1))
        rows = {e["id"]: e for e in result["entries"]}
        self.assertEqual(len(rows), 7, "chat: the embedding configuration is left to the embedding field")
        self.assertEqual((rows["qwen38-27b-apex-mini"]["state"], rows["qwen38-27b-apex-mini"]["aliases"]), ("loaded", ["qwen38-mini"]))
        self.assertEqual(rows["gemma-4-12b-qat"]["state"], "downloading")
        self.assertIn("qwen-image-edit-2509-q4", rows, "no name-based filtering of local configurations")
        self.assertTrue(rows["crashing-config"]["failed"])

    def test_the_router_embedding_tag_decides_not_the_name(self):
        with FakeEndpoint("llamacpp_router") as ep:
            chat = call({"provider": "llama_cpp", "api_base": ep.url + "/v1"})
            embedding = call({"provider": "llama_cpp", "api_base": ep.url + "/v1", "model_type": "embedding"})
        self.assertNotIn("qwen3-embedding-0.6b", ids(chat), "tagged embedding: left to the embedding field")
        self.assertIn("qwen3-embedding-0.6b", ids(embedding))
        self.assertEqual(set(ids(chat)) - set(ids(embedding)), set(), "untagged rows stay selectable in both fields: a guess from the name would hide real configurations")

    def test_llama_cpp_single_server_adds_props(self):
        result, paths, _ = self.run_kind("llamacpp_single")
        self.assertEqual(paths, ["/v1/models", "/props"])
        entry = result["entries"][0]
        self.assertEqual((result["endpoint"]["kind"], entry["state"], entry["context"]["served"], result["endpoint"]["requests"]), ("llama_cpp", "loaded", 65536, 2))

    def test_lm_studio_uses_its_rest_api_first(self):
        result, paths, _ = self.run_kind("lmstudio")
        self.assertEqual(paths, ["/api/v1/models"])
        rows = {e["id"]: e for e in result["entries"]}
        self.assertEqual((result["endpoint"]["kind"], rows["qwen/qwen3-30b-a3b"]["state"], rows["google/gemma-3-12b"]["vision"]), ("lm_studio", "loaded", True))

    def test_lm_studio_without_the_v1_rest_api_falls_back_to_v0(self):
        result, paths, _ = self.run_kind("lmstudio_legacy")
        self.assertEqual(paths, ["/api/v1/models", "/api/v0/models"])
        self.assertEqual((result["endpoint"]["kind"], result["endpoint"]["requests"]), ("lm_studio", 2))
        self.assertEqual({e["id"]: e["state"] for e in result["entries"]}["qwen/qwen3-30b-a3b"], "loaded")

    def test_ollama_merges_the_running_models(self):
        result, paths, _ = self.run_kind("ollama", suffix="")
        self.assertEqual(paths, ["/api/tags", "/api/ps"])
        rows = {e["id"]: e for e in result["entries"]}
        self.assertEqual((rows["llama3.1:8b"]["state"], rows["llama3.1:8b-instruct-q8_0"]["state"]), ("loaded", "unloaded"))

    def test_ollama_with_a_v1_base_still_gets_the_native_list(self):
        result, paths, _ = self.run_kind("ollama", suffix="/v1")
        self.assertEqual(paths[0], "/api/tags")
        self.assertEqual(result["endpoint"]["kind"], "ollama")

    def test_llama_swap_unsloth_and_generic_servers_are_one_request(self):
        for kind, expected in (("llama_swap", "llama_swap"), ("unsloth", "unsloth"), ("openai_generic", "openai_compatible")):
            with self.subTest(kind=kind):
                result, paths, _ = self.run_kind(kind)
                self.assertEqual((paths, result["endpoint"]["kind"]), (["/v1/models"], expected))

    def test_strata_router_adds_its_status(self):
        result, paths, _ = self.run_kind("strata_router")
        self.assertEqual(paths, ["/v1/models", "/status"])
        rows = {e["id"]: e for e in result["entries"]}
        self.assertEqual((rows[payloads.STRATA_VISION_160K]["state"], rows[payloads.STRATA_VISION_160K]["context"]["served"]), ("loaded", 163328))
        self.assertEqual(len(rows), 3)

    def test_a_base_without_v1_or_with_a_models_only_server(self):
        result, paths, _ = self.run_kind("openai_generic", suffix="")
        self.assertEqual(paths, ["/v1/models"])
        with FakeEndpoint(payloads.openai_generic_without_v1()) as ep:
            found = call({"provider": "other", "api_base": ep.url + "/v1"})
            self.assertEqual(ep.paths(), ["/v1/models", "/models"])
        self.assertEqual(ids(found), ["my-served-model", "another-model"])

    def test_defaults_come_from_the_provider_configuration(self):
        with FakeEndpoint("lmstudio") as ep:
            cases = (({"provider": "lm_studio"}, {"lm_studio": {"kwargs": {"api_base": ep.url + "/v1"}}}),
                     ({"provider": "lm_studio"}, {"lm_studio": {"models_list": {"default_base": ep.url}}}),
                     ({"provider": "lm_studio", "api_base": ep.url}, {"lm_studio": {"kwargs": {"api_base": "http://10.9.9.9:1/v1"}}}))
            for payload, configs in cases:
                discovery.clear_cache()
                before = len(ep.requests)
                result = call(payload, configs=configs)
                self.assertEqual(result["endpoint"]["kind"], "lm_studio")
                self.assertEqual(len(ep.requests), before + 1, "the request reached this endpoint, not the configured decoy")

    def test_every_shape_obeys_the_request_contract(self):
        for kind, provider in KIND_PROVIDERS.items():
            with self.subTest(kind=kind), FakeEndpoint(kind) as ep:
                result = call({"provider": provider, "api_base": ep.url + "/v1"})
                self.assertIsNone(result["error"], result["error"])
                self.assertLessEqual(len(ep.requests), discovery.MAX_REQUESTS)
                for record in ep.requests:
                    self.assertEqual(record["method"], "GET")
                    self.assertEqual(record["query"], "", "no query strings: llama.cpp would treat ?reload=1 as a command")
                    self.assertIn(record["path"], ALLOWED_PATHS)
                    self.assertEqual(record["headers"]["host"], f"127.0.0.1:{ep.port}")
                    self.assertTrue(record["headers"]["user-agent"].startswith("provider-profiles-discovery/"))
                    self.assertNotIn("authorization", record["headers"])
                    self.assertNotIn("cookie", record["headers"])
                dump = json.dumps(result)
                self.assertNotIn(payloads.SECRET_MARKER, dump, "router command lines and presets never leave the server")
                self.assertNotIn('"args"', dump)
                self.assertNotIn('"preset"', dump)

    def test_the_source_can_only_issue_read_only_requests_to_the_known_paths(self):
        source = (PLUGIN_DIR / "helpers" / "endpoint_discovery.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        docstrings = {id(node.body[0].value) for node in ast.walk(tree)
                      if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                      and node.body and isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, ast.Constant)}
        literals = {n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docstrings}
        attributes = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        self.assertEqual({s for s in literals if s.startswith("/")} - {"/", "/v1"}, ALLOWED_PATHS,
                         "every request path is a fixed literal: no load/unload/reload/props?model= style endpoint can be built")
        self.assertFalse(attributes & {"post", "put", "patch", "delete", "request", "send"}, attributes & {"post", "put", "patch", "delete", "request", "send"})
        self.assertFalse(literals & {"POST", "PUT", "PATCH", "DELETE"})
        self.assertIn("GET", literals)
        self.assertFalse(any("?" in s and "://" in s for s in literals), "no query string is ever built into a URL")
        for required in ("follow_redirects=False", "trust_env=False"):
            self.assertTrue(required in source, required)


# ------------------------------------------------------------------ authentication
class Authentication(Base):
    def test_a_missing_key_is_reported_with_the_provider_to_save_it_for(self):
        with FakeEndpoint("lmstudio", token="k1") as ep:
            result = call({"provider": "lm_studio", "api_base": ep.url + "/v1"})
        error = result["error"]
        self.assertEqual(error["category"], "unauthorized")
        self.assertIn("lm_studio", error["hint"])
        self.assertNotIn("Invalid API key", json.dumps(result), "the server's answer body is never relayed")
        self.assertEqual(result["entries"], [])

    def test_the_saved_key_is_sent_as_a_bearer_token(self):
        with FakeEndpoint("lmstudio", token="k1") as ep:
            result = call({"provider": "lm_studio", "api_base": ep.url + "/v1"}, key="k1")
            self.assertEqual(ep.requests[0]["headers"]["authorization"], "Bearer k1")
        self.assertIsNone(result["error"])

    def test_only_the_first_of_several_keys_is_used(self):
        with FakeEndpoint("lmstudio", token="k1") as ep:
            result = call({"provider": "lm_studio", "api_base": ep.url + "/v1"}, key="k1, k2, k3")
            self.assertEqual({r["headers"]["authorization"] for r in ep.requests}, {"Bearer k1"})
        self.assertIsNone(result["error"])

    def test_placeholder_keys_are_not_sent(self):
        for placeholder in ("lm-studio", "None", "llama-cpp", ""):
            with self.subTest(placeholder=placeholder), FakeEndpoint("lmstudio") as ep:
                call({"provider": "lm_studio", "api_base": ep.url + "/v1"}, key=placeholder)
                self.assertNotIn("authorization", ep.requests[0]["headers"])
            discovery.clear_cache()

    def test_the_key_is_sent_on_every_request_of_the_call(self):
        with FakeEndpoint("llamacpp_single", token=KEY) as ep:
            call({"provider": "llama_cpp", "api_base": ep.url + "/v1"}, key=KEY)
            self.assertEqual(len(ep.requests), 2)
            self.assertEqual({r["headers"]["authorization"] for r in ep.requests}, {f"Bearer {KEY}"})

    def test_a_key_never_reaches_a_host_that_failed_the_gate(self):
        made = []
        factory = mock_factory(models_response, made=made)
        resolver = resolver_for({"meta.lan": ["169.254.169.254"], "cloud.lan": ["93.184.216.34"], "mixed.lan": ["10.0.0.5", "93.184.216.34"]})
        for base in ("http://meta.lan/v1", "http://cloud.lan/v1", "http://mixed.lan/v1", "http://169.254.169.254/v1", "http://8.8.8.8/v1", "http://0.0.0.0:8080/v1"):
            with self.subTest(base=base):
                call({"provider": "other", "api_base": base}, key=KEY, resolver=resolver, factory=factory)
        self.assertEqual(made, [], "no client was even created, so no request and no Authorization header could be sent")

    def test_the_key_appears_in_no_response_and_in_no_cache_key(self):
        with FakeEndpoint("lmstudio", token=KEY) as ep:
            ok = call({"provider": "lm_studio", "api_base": ep.url + "/v1"}, key=KEY)
            discovery.clear_cache()
            bad = call({"provider": "lm_studio", "api_base": ep.url + "/v1"}, key="wrong-key-777")
            call({"provider": "lm_studio", "api_base": ep.url + "/v1"}, key=KEY)
            cache_dump = repr(list(discovery._cache.keys()))
        for text in (json.dumps(ok), json.dumps(bad), cache_dump):
            self.assertNotIn(KEY, text)
            self.assertNotIn("wrong-key-777", text)

    def test_a_forbidden_client_is_reported_as_forbidden(self):
        with FakeEndpoint("lmstudio", forbid=lambda record: True) as ep:
            result = call({"provider": "lm_studio", "api_base": ep.url + "/v1"})
        self.assertEqual(result["error"]["category"], "forbidden")


# ------------------------------------------------------------------ request budget, redirects, failures
class Budget(Base):
    def test_everything_missing_costs_at_most_three_requests(self):
        with FakeEndpoint({}) as ep:
            result = call({"provider": "other", "api_base": ep.url + "/v1"})
            self.assertEqual(ep.paths(), ["/v1/models", "/models", "/api/v1/models"])
        self.assertEqual(result["error"]["category"], "not_found")

    def test_non_json_answers_cost_at_most_three_requests_and_say_so(self):
        with FakeEndpoint({"/v1/models": Route(raw=b"<html>login %s</html>" % payloads.SECRET_MARKER.encode()),
                           "/models": Route(raw=b"<html>x</html>"), "/api/v1/models": Route(raw=b"nope")}) as ep:
            result = call({"provider": "other", "api_base": ep.url + "/v1"})
            self.assertLessEqual(len(ep.requests), 3)
        self.assertEqual(result["error"]["category"], "bad_payload")
        self.assertNotIn(payloads.SECRET_MARKER, json.dumps(result))

    def test_a_valid_empty_list_is_an_answer_not_an_error(self):
        with FakeEndpoint({"/v1/models": {"object": "list", "data": []}}) as ep:
            result = call({"provider": "other", "api_base": ep.url + "/v1"})
            self.assertEqual(ep.paths(), ["/v1/models"])
        self.assertIsNone(result["error"])
        self.assertEqual(result["entries"], [])
        self.assertEqual(result["endpoint"]["kind"], "openai_compatible")

    def test_ollama_with_a_failing_ps_keeps_the_list(self):
        routes = payloads.ollama()
        routes["/api/ps"] = Route(status=500, body={"error": "boom"})
        with FakeEndpoint(routes) as ep:
            result = call({"provider": "ollama", "api_base": ep.url})
        self.assertIsNone(result["error"])
        self.assertEqual({e["state"] for e in result["entries"]}, {"unknown"})

    def test_a_server_error_names_the_status_only(self):
        with FakeEndpoint({"/v1/models": Route(status=500, body={"error": payloads.SECRET_MARKER}),
                           "/models": Route(status=500, body={}), "/api/v1/models": Route(status=500, body={})}) as ep:
            result = call({"provider": "other", "api_base": ep.url + "/v1"})
        self.assertEqual(result["error"]["category"], "server_error")
        self.assertIn("HTTP 500", result["error"]["message"])
        self.assertNotIn(payloads.SECRET_MARKER, json.dumps(result))

    def test_rate_limiting_has_its_own_hint(self):
        factory = mock_factory(lambda request: httpx.Response(429, json={}))
        result = call({"provider": "other", "api_base": "http://10.0.0.5:1/v1"}, factory=factory)
        self.assertIn("rate limiting", result["error"]["hint"])


class Redirects(Base):
    def test_redirects_are_reported_not_followed(self):
        for status in (301, 302, 307, 308):
            with self.subTest(status=status), FakeEndpoint("openai_generic") as target:
                with FakeEndpoint({"/v1/models": redirect(f"{target.url}/v1/models", status)}) as ep:
                    result = call({"provider": "other", "api_base": ep.url + "/v1"})
                    self.assertEqual(ep.paths(), ["/v1/models"])
                self.assertEqual(target.requests, [], "the redirect target was never contacted")
                self.assertEqual(result["error"]["category"], "redirect")
            discovery.clear_cache()

    def test_a_redirect_to_a_metadata_address_is_never_followed(self):
        log = []
        factory = mock_factory(lambda request: httpx.Response(302, headers={"Location": "http://169.254.169.254/latest/meta-data/"}), log=log)
        result = call({"provider": "other", "api_base": "http://10.0.0.5:8000/v1"}, factory=factory)
        self.assertEqual(result["error"]["category"], "redirect")
        self.assertEqual([r.url.host for r in log], ["10.0.0.5"])


class Failures(Base):
    def test_unreachable_hosts_in_both_address_families(self):
        def refuse(request):
            raise httpx.ConnectError("refused", request=request)

        for base in ("http://10.0.0.5:1/v1", "http://[::1]:1/v1"):
            with self.subTest(base=base):
                result = call({"provider": "other", "api_base": base}, factory=mock_factory(refuse))
                self.assertEqual(result["error"]["category"], "unreachable")
                self.assertEqual(result["entries"], [])

    def test_a_closed_port_on_localhost_hints_at_docker(self):
        with FakeEndpoint("openai_generic") as ep:
            port = ep.port
        result = call({"provider": "other", "api_base": f"http://127.0.0.1:{port}/v1"})
        self.assertEqual(result["error"]["category"], "unreachable")
        self.assertIn("host.docker.internal", result["error"]["hint"])

    def test_timeouts(self):
        with FakeEndpoint({"/v1/models": Route(body={"data": [{"id": "x"}]}, delay=3.0)}) as ep:
            with mock.patch.object(discovery, "REQUEST_TIMEOUT", 0.3):
                result = call({"provider": "other", "api_base": ep.url + "/v1"})
        self.assertEqual(result["error"]["category"], "timeout")

    def test_a_server_that_never_finishes_the_body_is_bounded_by_the_total_timeout(self):
        async def endless():
            while True:
                await asyncio.sleep(0.05)
                yield b" "

        factory = mock_factory(lambda request: httpx.Response(200, content=endless()))
        with mock.patch.object(discovery, "REQUEST_TIMEOUT", 0.2):
            result = call({"provider": "other", "api_base": "http://10.0.0.5:1/v1"}, factory=factory)
        self.assertEqual(result["error"]["category"], "timeout")

    def test_oversized_answers_are_rejected(self):
        big = b'{"data": [' + b'{"id": "x"},' * 300000 + b'{"id": "y"}]}'
        self.assertGreater(len(big), discovery.MAX_BYTES)
        with FakeEndpoint({"/v1/models": Route(raw=big), "/models": Route(raw=big), "/api/v1/models": Route(raw=big)}) as ep:
            result = call({"provider": "other", "api_base": ep.url + "/v1"})
        self.assertEqual(result["error"]["category"], "bad_payload")

    def test_the_cap_applies_while_streaming_without_a_content_length(self):
        async def chunks():
            for _ in range(10):
                yield b"x" * (400 * 1024)

        log = []
        factory = mock_factory(lambda request: httpx.Response(200, content=chunks()), log=log)
        result = call({"provider": "other", "api_base": "http://10.0.0.5:1/v1"}, factory=factory)
        self.assertEqual(result["error"]["category"], "bad_payload")

    def test_dns_failures_never_create_a_client(self):
        made = []
        result = call({"provider": "other", "api_base": "http://nowhere.lan/v1"}, resolver=resolver_for({}), factory=mock_factory(models_response, made=made))
        self.assertEqual(result["error"]["category"], "dns")
        self.assertEqual(made, [])

    def test_unexpected_exceptions_become_unreachable_not_a_traceback(self):
        def explode(request):
            raise RuntimeError("secret internals " + payloads.SECRET_MARKER)

        result = call({"provider": "other", "api_base": "http://10.0.0.5:1/v1"}, factory=mock_factory(explode))
        self.assertEqual(result["error"]["category"], "unreachable")
        self.assertNotIn(payloads.SECRET_MARKER, json.dumps(result))

    def test_every_error_is_json_and_body_free(self):
        for status in (400, 401, 403, 404, 410, 418, 429, 500, 503):
            with self.subTest(status=status):
                discovery.clear_cache()
                factory = mock_factory(lambda request, s=status: httpx.Response(s, text=f"<b>{payloads.SECRET_MARKER}</b>"))
                result = call({"provider": "other", "api_base": "http://10.0.0.5:1/v1"}, factory=factory, key=KEY)
                text = json.dumps(result)
                self.assertNotIn(payloads.SECRET_MARKER, text)
                self.assertNotIn(KEY, text)
                self.assertIn(result["error"]["category"], {"unauthorized", "forbidden", "not_found", "server_error"})


# ------------------------------------------------------------------ connection pinning
class Pinning(Base):
    def test_the_connection_goes_to_the_checked_address_with_the_entered_name_in_host(self):
        log = []
        resolver = resolver_for({"llm.lan": ["10.0.0.5"]})
        result = call({"provider": "other", "api_base": "http://llm.lan:1234/v1"}, resolver=resolver, factory=mock_factory(models_response, log=log))
        self.assertIsNone(result["error"])
        self.assertEqual([r.url.host for r in log], ["10.0.0.5"])
        self.assertEqual(log[0].headers["host"], "llm.lan:1234")
        self.assertEqual((log[0].url.query, log[0].url.userinfo, log[0].method), (b"", b"", "GET"))

    def test_the_default_port_is_left_out_of_the_host_header(self):
        log = []
        call({"provider": "other", "api_base": "http://llm.lan/v1"}, resolver=resolver_for({"llm.lan": ["10.0.0.5"]}), factory=mock_factory(models_response, log=log))
        self.assertEqual(log[0].headers["host"], "llm.lan")

    def test_ipv6_literals_are_bracketed(self):
        log = []
        call({"provider": "other", "api_base": "http://[::1]:8080/v1"}, factory=mock_factory(models_response, log=log))
        self.assertEqual((log[0].url.host, log[0].headers["host"]), ("::1", "[::1]:8080"))

    def test_dns_is_asked_once_so_a_rebinding_answer_cannot_matter(self):
        asked = []

        async def resolve(host, port):
            asked.append(host)
            return ["10.0.0.5"] if len(asked) == 1 else ["169.254.169.254"]

        log = []
        result = call({"provider": "lm_studio", "api_base": "http://llm.lan:1234/v1"}, resolver=resolve,
                      factory=mock_factory(lambda request: httpx.Response(404, json={}) if "/api/v1" in request.url.path else models_response(request), log=log))
        self.assertIsNone(result["error"])
        self.assertEqual(asked, ["llm.lan"])
        self.assertEqual({r.url.host for r in log}, {"10.0.0.5"})
        self.assertGreater(len(log), 1)

    def test_a_refusing_first_address_falls_back_to_the_second_and_stays_there(self):
        log = []

        def handler(request):
            if request.url.host == "10.0.0.5":
                raise httpx.ConnectError("refused", request=request)
            return models_response(request) if request.url.path.endswith("/v1/models") else httpx.Response(404, json={})

        resolver = resolver_for({"llm.lan": ["10.0.0.5", "10.0.0.6"]})
        result = call({"provider": "lm_studio", "api_base": "http://llm.lan:1234/v1"}, resolver=resolver, factory=mock_factory(handler, log=log))
        self.assertIsNone(result["error"])
        hosts = [r.url.host for r in log]
        self.assertEqual(hosts[:2], ["10.0.0.5", "10.0.0.6"])
        self.assertEqual(set(hosts[2:]), {"10.0.0.6"})

    def test_ipv4_is_tried_before_ipv6_and_at_most_two_addresses(self):
        log = []

        def refuse(request):
            raise httpx.ConnectError("refused", request=request)

        resolver = resolver_for({"llm.lan": ["::1", "10.0.0.5", "10.0.0.6", "10.0.0.7"]})
        result = call({"provider": "other", "api_base": "http://llm.lan/v1"}, resolver=resolver, factory=mock_factory(refuse, log=log))
        self.assertEqual(result["error"]["category"], "unreachable")
        self.assertEqual([r.url.host for r in log], ["10.0.0.5", "10.0.0.6"])

    def test_a_timeout_on_the_first_address_does_not_double_the_wait(self):
        log = []

        def slow(request):
            raise httpx.ConnectTimeout("slow", request=request)

        result = call({"provider": "other", "api_base": "http://llm.lan/v1"}, resolver=resolver_for({"llm.lan": ["10.0.0.5", "10.0.0.6"]}), factory=mock_factory(slow, log=log))
        self.assertEqual(result["error"]["category"], "timeout")
        self.assertEqual(len(log), 1)

    def test_a_real_server_is_reached_through_a_resolved_name(self):
        with FakeEndpoint("openai_generic") as ep:
            result = call({"provider": "other", "api_base": f"http://llm.lan:{ep.port}/v1"}, resolver=resolver_for({"llm.lan": ["127.0.0.1"]}))
            self.assertEqual(ep.requests[0]["headers"]["host"], f"llm.lan:{ep.port}")
        self.assertIsNone(result["error"])


# ------------------------------------------------------------------ TLS
class Tls(Base):
    def test_an_untrusted_certificate_is_a_tls_error_before_any_request(self):
        with TempCert() as cert:
            if not cert:
                self.skipTest("no TLS tooling (cryptography or openssl)")
            with FakeEndpoint("openai_generic", tls=cert) as ep:
                result = call({"provider": "other", "api_base": ep.url + "/v1"})
                self.assertEqual(ep.requests, [])
        self.assertEqual(result["error"]["category"], "tls")
        self.assertIn("SSL_CERT_FILE", result["error"]["hint"])

    def test_a_certificate_trusted_through_ssl_cert_file_is_accepted_like_in_the_host(self):
        with TempCert() as cert:
            if not cert:
                self.skipTest("no TLS tooling (cryptography or openssl)")
            fresh = load_helper("endpoint_discovery")
            with FakeEndpoint("openai_generic", tls=cert) as ep, mock.patch.dict(os.environ, {"SSL_CERT_FILE": cert[0]}):
                by_ip = call({"provider": "other", "api_base": ep.url + "/v1"}, module=fresh)
                fresh.clear_cache()
                by_name = call({"provider": "other", "api_base": f"https://localhost:{ep.port}/v1"}, module=fresh, resolver=resolver_for({"localhost": ["127.0.0.1"]}))
                fresh.clear_cache()
                wrong_name = call({"provider": "other", "api_base": f"https://llm.lan:{ep.port}/v1"}, module=fresh, resolver=resolver_for({"llm.lan": ["127.0.0.1"]}))
        self.assertIsNone(by_ip["error"], by_ip["error"])
        self.assertIsNone(by_name["error"], by_name["error"])
        self.assertEqual(wrong_name["error"]["category"], "tls", "the certificate is verified for the name that was entered, not for the pinned address")

    def test_https_to_a_plain_http_port_is_a_protocol_error(self):
        with FakeEndpoint("openai_generic") as ep:
            result = call({"provider": "other", "api_base": ep.url.replace("http://", "https://") + "/v1"})
        self.assertIn(result["error"]["category"], {"tls_protocol", "unreachable"})


# ------------------------------------------------------------------ cache
class Cache(Base):
    def counting(self):
        log = []
        return log, mock_factory(models_response, log=log)

    def test_a_repeat_call_is_served_from_the_cache_until_it_expires(self):
        log, factory = self.counting()
        now = [100.0]
        payload = {"provider": "other", "api_base": "http://10.0.0.5:1/v1"}
        first = call(payload, factory=factory, clock=lambda: now[0])
        second = call(payload, factory=factory, clock=lambda: now[0] + 14)
        self.assertEqual((first["endpoint"]["cached"], first["endpoint"]["requests"]), (False, 1))
        self.assertEqual((second["endpoint"]["cached"], second["endpoint"]["requests"]), (True, 0))
        self.assertEqual(len(log), 1)
        self.assertEqual(ids(first), ids(second))
        call(payload, factory=factory, clock=lambda: now[0] + 16)
        self.assertEqual(len(log), 2, "the entry expired after 15 seconds")

    def test_refresh_bypasses_the_cache_but_is_throttled(self):
        log, factory = self.counting()
        now = [100.0]
        payload = {"provider": "other", "api_base": "http://10.0.0.5:1/v1"}
        call(payload, factory=factory, clock=lambda: now[0])
        call({**payload, "refresh": True}, factory=factory, clock=lambda: now[0] + 0.2)
        self.assertEqual(len(log), 1, "a refresh right after a probe is served from the cache")
        call({**payload, "refresh": True}, factory=factory, clock=lambda: now[0] + 2)
        self.assertEqual(len(log), 2, "an older entry is probed again")

    def test_scheme_port_and_path_prefix_separate_cache_entries(self):
        log, factory = self.counting()
        for base in ("http://10.0.0.5:8443/v1", "https://10.0.0.5:8443/v1", "http://10.0.0.5:8444/v1"):
            call({"provider": "other", "api_base": base}, factory=factory)
        self.assertEqual(len(log), 3)

    def test_a_path_prefix_is_probed_and_cached_on_its_own(self):
        log = []

        def handler(request):
            return httpx.Response(200, json={"data": [{"id": request.url.path}]}) if request.url.path.endswith("/v1/models") else httpx.Response(404, json={})

        factory = mock_factory(handler, log=log)
        a = call({"provider": "other", "api_base": "http://10.0.0.5:1/a/v1"}, factory=factory)
        b = call({"provider": "other", "api_base": "http://10.0.0.5:1/b/v1"}, factory=factory)
        self.assertEqual((ids(a), ids(b)), (["/a/v1/models"], ["/b/v1/models"]))

    def test_a_host_with_local_and_public_addresses_is_reported_not_probed(self):
        made = []
        result = call({"provider": "other", "api_base": "http://dual.lan/v1"}, resolver=resolver_for({"dual.lan": ["192.168.1.10", "93.184.216.34"]}),
                      factory=mock_factory(models_response, made=made))
        self.assertEqual(result["error"]["category"], "mixed")
        self.assertEqual(made, [])

    def test_errors_are_never_cached(self):
        state = {"fail": True}
        log = []

        def handler(request):
            return httpx.Response(500, json={}) if state["fail"] else models_response(request)

        factory = mock_factory(handler, log=log)
        payload = {"provider": "other", "api_base": "http://10.0.0.5:1/v1"}
        self.assertEqual(call(payload, factory=factory)["error"]["category"], "server_error")
        failed_requests = len(log)
        state["fail"] = False
        recovered = call(payload, factory=factory)
        self.assertIsNone(recovered["error"])
        self.assertGreater(len(log), failed_requests, "the second call asked the server again")

    def test_different_keys_and_providers_do_not_share_entries(self):
        log, factory = self.counting()
        payload = {"provider": "other", "api_base": "http://10.0.0.5:1/v1"}
        call(payload, factory=factory, key="a")
        call(payload, factory=factory, key="b")
        call(payload, factory=factory, key=None)
        call({**payload, "provider": "ollama"}, factory=factory)
        self.assertEqual(len(log), 5, "three keys, then the ollama plan (/api/tags 404, then /v1/models)")
        self.assertEqual([r.headers.get("authorization") for r in log[:3]], ["Bearer a", "Bearer b", None])

    def test_chat_and_embedding_share_one_probe(self):
        with FakeEndpoint("llamacpp_router") as ep:
            chat = call({"provider": "llama_cpp", "api_base": ep.url + "/v1"})
            embedding = call({"provider": "llama_cpp", "api_base": ep.url + "/v1", "model_type": "embedding"})
            self.assertEqual(len(ep.requests), 1)
        self.assertNotEqual(ids(chat), ids(embedding))
        self.assertTrue(embedding["endpoint"]["cached"])

    def test_the_cache_is_bounded(self):
        _log, factory = self.counting()
        with mock.patch.object(discovery, "MAX_CACHE", 3):
            for index in range(8):
                call({"provider": "other", "api_base": f"http://10.0.0.{index + 1}:1/v1"}, factory=factory)
        self.assertLessEqual(len(discovery._cache), 3)

    def test_concurrent_calls_are_independent(self):
        with FakeEndpoint("llamacpp_router") as ep:
            async def both():
                payload = {"provider": "llama_cpp", "api_base": ep.url + "/v1"}
                kwargs = dict(settings={"discovery_enabled": True}, provider_config=lambda t, p: None, stored_key=lambda p: None)
                return await asyncio.gather(*(discovery.handle(payload, **kwargs) for _ in range(4)))

            results = asyncio.run(both())
        self.assertTrue(all(r["error"] is None and len(r["entries"]) == 7 for r in results))


# ------------------------------------------------------------------ request validation and switches
class Validation(Base):
    def test_requests_that_cannot_be_served_are_skipped_without_a_client(self):
        made = []
        factory = mock_factory(models_response, made=made)
        cases = [
            ({"provider": "other", "api_base": "http://10.0.0.5/v1"}, {"discovery_enabled": False}, "disabled"),
            ({"provider": "", "api_base": "http://10.0.0.5/v1"}, None, "no_provider"),
            ({"provider": "../etc", "api_base": "http://10.0.0.5/v1"}, None, "no_provider"),
            ({"provider": "A B", "api_base": "http://10.0.0.5/v1"}, None, "no_provider"),
            ({"api_base": "http://10.0.0.5/v1"}, None, "no_provider"),
            ({"provider": "other"}, None, "no_base"),
            ({"provider": "other", "api_base": "   "}, None, "no_base"),
            ({"provider": "other", "api_base": "http://8.8.8.8/v1"}, None, "public_host"),
        ]
        for payload, settings, expected in cases:
            with self.subTest(payload=payload):
                result = call(payload, settings=settings, factory=factory)
                self.assertEqual((result["ok"], result["skipped"], result["error"], result["entries"]), (True, expected, None, []))
        self.assertEqual(made, [])

    def test_a_non_object_body_is_an_invalid_request(self):
        for body in (None, [], "x", 5):
            result = call(body)
            self.assertFalse(result["ok"])
            self.assertEqual(result["error"]["category"], "invalid_request")

    def test_unusable_bases_and_blocked_hosts_are_reported(self):
        made = []
        factory = mock_factory(models_response, made=made)
        for base, category in (("http://u:p@10.0.0.5/v1", "invalid_base"), ("http://10.0.0.5/v1?reload=1", "invalid_base"), ("ftp://10.0.0.5", "invalid_base"),
                               ("http://169.254.169.254/latest", "blocked"), ("http://0.0.0.0:8080/v1", "blocked"), ("http://[fe80::1]:8080/v1", "blocked")):
            with self.subTest(base=base):
                result = call({"provider": "other", "api_base": base}, factory=factory)
                self.assertEqual(result["error"]["category"], category)
                self.assertEqual(result["entries"], [])
        self.assertEqual(made, [])

    def test_a_failing_provider_lookup_or_key_store_does_not_break_discovery(self):
        def broken_config(model_type, provider):
            raise RuntimeError("config store unavailable")

        def broken_key(provider):
            raise RuntimeError("key store unavailable")

        with FakeEndpoint("openai_generic") as ep:
            result = asyncio.run(discovery.handle({"provider": "other", "api_base": ep.url + "/v1"}, settings={"discovery_enabled": True},
                                                  provider_config=broken_config, stored_key=broken_key))
        self.assertIsNone(result["error"])
        self.assertEqual(len(result["entries"]), 2)

    def test_the_provider_id_and_model_type_are_normalized(self):
        with FakeEndpoint("lmstudio") as ep:
            result = call({"provider": "  LM_Studio ", "api_base": ep.url + "/v1", "model_type": "Embedding"})
        self.assertEqual(ids(result), ["text-embedding-nomic-embed-text-v1.5"])
        with FakeEndpoint("lmstudio") as ep:
            weird = call({"provider": "lm_studio", "api_base": ep.url + "/v1", "model_type": "utility"})
        self.assertIn("qwen/qwen3-30b-a3b", ids(weird), "anything but 'embedding' is a chat request")

    def test_responses_are_always_json_serializable_with_a_fixed_shape(self):
        with FakeEndpoint("llamacpp_router") as ep:
            ok = call({"provider": "llama_cpp", "api_base": ep.url + "/v1"})
        blocked = call({"provider": "other", "api_base": "http://169.254.169.254/v1"})
        skipped = call({"provider": "other"})
        for result in (ok, blocked, skipped):
            self.assertEqual(set(result), {"ok", "skipped", "endpoint", "entries", "error"})
            json.dumps(result)
        self.assertEqual(set(ok["endpoint"]), {"kind", "label", "host", "requests", "cached"})
        self.assertEqual(set(ok["entries"][0]), {"id", "label", "aliases", "state", "failed", "context", "vision", "kind", "quant"})
        self.assertEqual(set(blocked["error"]), {"category", "message", "hint"})


if __name__ == "__main__":
    unittest.main()
