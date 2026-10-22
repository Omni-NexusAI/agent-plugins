from __future__ import annotations

import json
import unittest

from . import endpoint_payloads as payloads
from .loader import load_helper

parsers = load_helper("endpoint_parsers")


def by_id(entries):
    return {e["id"]: e for e in entries}


class LlamaCpp(unittest.TestCase):
    def test_router_rows_keep_state_aliases_configuration_and_failures(self):
        kind, entries = parsers.parse_openai_models(payloads.llamacpp_router()["/v1/models"])
        self.assertEqual(kind, "llama_cpp_router")
        rows = by_id(entries)
        mini = rows["qwen38-27b-apex-mini"]
        self.assertEqual((mini["state"], mini["aliases"], mini["context"]["configured"]), ("loaded", ["qwen38-mini"], 131072))
        vision = rows["qwen38-27b-apex-mini-vision"]
        self.assertEqual((vision["state"], vision["context"]["configured"], vision["vision"]), ("unloaded", 81920, True))
        self.assertEqual(rows["ornith-1.5-35b-gpukv-128k-vision"]["state"], "sleeping")
        self.assertEqual(rows["ornith-1.5-35b-gpukv-128k-vision"]["context"]["configured"], 32768)
        self.assertEqual(rows["gemma-4-12b-qat"]["state"], "downloading")
        self.assertEqual(rows["half-downloaded-model"]["state"], "incomplete")
        self.assertTrue(rows["crashing-config"]["failed"])
        self.assertFalse(rows["qwen38-27b-apex-mini"]["failed"])
        self.assertEqual(rows["qwen3-embedding-0.6b"]["kind"], "embedding", "kind comes from the router's own tags")
        self.assertIsNone(rows["qwen-image-edit-2509-q4"]["kind"], "never guessed from the name")
        self.assertEqual(len(entries), 8, "every configuration is listed, including the ones the host's name filter drops")

    def test_command_lines_never_leave_the_parser(self):
        _kind, entries = parsers.parse_openai_models(payloads.llamacpp_router()["/v1/models"])
        dump = json.dumps(entries)
        self.assertNotIn(payloads.SECRET_MARKER, dump)
        for entry in entries:
            self.assertEqual(set(entry), {"id", "label", "aliases", "state", "failed", "context", "vision", "kind", "quant"})

    def test_single_server_and_props_enrichment(self):
        routes = payloads.llamacpp_single()
        kind, entries = parsers.parse_openai_models(routes["/v1/models"])
        self.assertEqual(kind, "llama_cpp")
        self.assertEqual(entries[0]["context"]["max"], 131072)
        self.assertTrue(entries[0]["vision"])
        merged = parsers.merge_llamacpp_props(entries, routes["/props"])
        self.assertEqual((merged[0]["context"]["served"], merged[0]["state"]), (65536, "loaded"))
        sleeping = parsers.merge_llamacpp_props(entries, {**routes["/props"], "is_sleeping": True})
        self.assertEqual(sleeping[0]["state"], "sleeping")

    def test_props_of_a_router_are_ignored(self):
        _kind, entries = parsers.parse_openai_models(payloads.llamacpp_single()["/v1/models"])
        self.assertEqual(parsers.merge_llamacpp_props(entries, {"role": "router"}), entries)

    def test_config_info_edge_cases(self):
        info = parsers._config_info
        self.assertEqual(info(["--ctx-size=4096"], None), (4096, None))
        self.assertEqual(info(["-c", "abc"], None), (None, None))
        self.assertEqual(info(None, "ctx-size = 9999999999999"), (None, None))
        self.assertEqual(info(["--mmproj=/x"], None), (None, True))
        self.assertEqual(info(["--ctx-size"], None), (None, None))
        self.assertEqual(info("not a list", 7), (None, None))


class LmStudio(unittest.TestCase):
    def test_v1_models(self):
        kind, entries = parsers.parse_lmstudio_v1(payloads.lmstudio()["/api/v1/models"])
        self.assertEqual(kind, "lm_studio")
        rows = by_id(entries)
        qwen = rows["qwen/qwen3-30b-a3b"]
        self.assertEqual((qwen["state"], qwen["context"], qwen["quant"], qwen["vision"], qwen["kind"], qwen["label"]),
                         ("loaded", {"served": 32768, "max": 262144, "configured": None}, "Q4_K_M", False, "chat", "Qwen3 30B A3B"))
        gemma = rows["google/gemma-3-12b"]
        self.assertEqual((gemma["state"], gemma["vision"], gemma["context"]["served"]), ("unloaded", True, None))
        self.assertEqual(rows["text-embedding-nomic-embed-text-v1.5"]["kind"], "embedding")

    def test_v0_models(self):
        kind, entries = parsers.parse_lmstudio_v0(payloads.lmstudio()["/api/v0/models"])
        self.assertEqual(kind, "lm_studio")
        rows = by_id(entries)
        self.assertEqual((rows["qwen/qwen3-30b-a3b"]["state"], rows["qwen/qwen3-30b-a3b"]["context"]["served"]), ("loaded", 32768))
        self.assertEqual((rows["google/gemma-3-12b"]["state"], rows["google/gemma-3-12b"]["vision"]), ("unloaded", True))
        self.assertEqual(rows["text-embedding-nomic-embed-text-v1.5"]["kind"], "embedding")

    def test_the_openai_list_is_ids_only(self):
        kind, entries = parsers.parse_openai_models(payloads.lmstudio()["/v1/models"])
        self.assertEqual(kind, "openai_compatible")
        self.assertEqual({e["state"] for e in entries}, {"unknown"})


class Ollama(unittest.TestCase):
    def test_tags_then_ps(self):
        routes = payloads.ollama()
        kind, entries = parsers.parse_ollama_tags(routes["/api/tags"])
        self.assertEqual(kind, "ollama")
        self.assertEqual({e["state"] for e in entries}, {"unknown"})
        rows = by_id(entries)
        self.assertEqual(rows["nomic-embed-text:latest"]["kind"], "embedding")
        self.assertEqual(rows["llama3.1:8b"]["quant"], "Q4_K_M")
        merged = by_id(parsers.merge_ollama_ps(entries, routes["/api/ps"]))
        self.assertEqual((merged["llama3.1:8b"]["state"], merged["llama3.1:8b"]["context"]["served"]), ("loaded", 8192))
        self.assertEqual(merged["llama3.1:8b-instruct-q8_0"]["state"], "unloaded")
        self.assertEqual(rows["llama3.1:8b"]["state"], "unknown", "merge returns copies")


class OtherServers(unittest.TestCase):
    def test_llama_swap(self):
        kind, entries = parsers.parse_openai_models(payloads.llama_swap()["/v1/models"])
        self.assertEqual(kind, "llama_swap")
        rows = by_id(entries)
        fast = rows["qwen-fast"]
        self.assertEqual((fast["state"], fast["aliases"], fast["context"]["configured"], fast["label"]), ("loaded", ["gpt-4o-mini"], 32768, "Qwen fast"))
        self.assertEqual((rows["gemma-vision"]["state"], rows["gemma-vision"]["vision"]), ("unloaded", True))
        self.assertEqual(rows["bge-embed"]["kind"], "embedding")

    def test_unsloth(self):
        kind, entries = parsers.parse_openai_models(payloads.unsloth()["/v1/models"])
        self.assertEqual(kind, "unsloth")
        rows = by_id(entries)
        loaded = rows["unsloth/Qwen3-8B-GGUF:Q4_K_XL"]
        self.assertEqual((loaded["state"], loaded["quant"], loaded["context"]["configured"], loaded["context"]["max"]), ("loaded", "Q4_K_XL", 32768, 40960))
        self.assertEqual(rows["my-qwen-alias"]["state"], "unloaded")
        self.assertEqual(rows["unsloth/embeddinggemma-300m"]["kind"], "embedding")

    def test_strata_router_with_status_enrichment(self):
        routes = payloads.strata_router()
        kind, entries = parsers.parse_openai_models(routes["/v1/models"])
        self.assertEqual(kind, "strata_router")
        rows = by_id(entries)
        vision = rows[payloads.STRATA_VISION_160K]
        self.assertEqual((vision["context"]["configured"], vision["vision"], vision["state"]), (163328, True, "unknown"))
        merged = by_id(parsers.merge_strata_status(entries, routes["/status"]))
        self.assertEqual((merged[payloads.STRATA_VISION_160K]["state"], merged[payloads.STRATA_VISION_160K]["context"]["served"]), ("loaded", 163328))
        self.assertEqual(merged["qwen3.8-flash-next-iq3_xxs-strata-mtp-text-128k"]["state"], "unloaded")

    def test_generic_openai_server(self):
        kind, entries = parsers.parse_openai_models(payloads.openai_generic()["/v1/models"])
        self.assertEqual(kind, "openai_compatible")
        self.assertEqual(by_id(entries)["my-served-model"]["context"]["max"], 32768)

    def test_payload_envelopes(self):
        rows = [{"id": "a"}, "b", {"id": "c"}]
        for payload in ({"data": rows}, {"models": rows}, rows):
            self.assertEqual([e["id"] for e in parsers.parse_openai_models(payload)[1]], ["a", "b", "c"])


class Robustness(unittest.TestCase):
    def test_garbage_never_raises(self):
        junk = [None, [], "x", 5, {}, {"data": "x"}, {"data": [None, 3, [], {"id": None}, {"id": ""}, {"id": 7}, {"nope": 1}]},
                {"models": [{"key": None}, {"name": ["x"]}]}]
        for payload in junk:
            with self.subTest(payload=payload):
                for fn in (parsers.parse_openai_models, parsers.parse_lmstudio_v1, parsers.parse_lmstudio_v0, parsers.parse_ollama_tags):
                    kind, entries = fn(payload)
                    self.assertIsInstance(kind, str)
                    self.assertEqual(entries, [])

    def test_ids_are_sanitized_deduped_and_capped(self):
        rows = [{"id": "ok"}, {"id": "ok"}, {"id": "bad\nid"}, {"id": "x" * 600}, {"id": "  padded  "}]
        self.assertEqual([e["id"] for e in parsers.parse_openai_models({"data": rows})[1]], ["ok", "padded"])
        many = [{"id": f"m{i}"} for i in range(3000)]
        self.assertEqual(len(parsers.parse_openai_models({"data": many})[1]), 1000)

    def test_numbers_are_bounded_and_typed(self):
        row = {"id": "m", "max_model_len": True, "supports_vision": "yes"}
        entry = parsers.parse_openai_models({"data": [row]})[1][0]
        self.assertEqual(entry["context"], {"served": None, "max": None, "configured": None})
        self.assertIsNone(entry["vision"])
        huge = parsers.parse_openai_models({"data": [{"id": "m", "max_model_len": 10**12}]})[1][0]
        self.assertIsNone(huge["context"]["max"])

    def test_unknown_states_collapse_to_unknown(self):
        row = {"id": "m", "status": {"value": "exploding"}, "aliases": []}
        self.assertEqual(parsers.parse_openai_models({"data": [row]})[1][0]["state"], "unknown")

    def test_entries_for_uses_endpoint_kind_only(self):
        entries = [parsers.make_entry("a", kind="chat"), parsers.make_entry("b", kind="embedding"), parsers.make_entry("c")]
        self.assertEqual([e["id"] for e in parsers.entries_for(entries, "chat")], ["a", "c"])
        self.assertEqual([e["id"] for e in parsers.entries_for(entries, "embedding")], ["b", "c"])
        self.assertEqual([e["id"] for e in parsers.entries_for(entries, "vision")], ["a", "c"])

    def test_every_state_is_in_the_vocabulary(self):
        self.assertEqual(set(parsers.STATES), {"loaded", "loading", "sleeping", "unloaded", "downloading", "incomplete", "downloaded", "unknown"})
        for route_table in (payloads.llamacpp_router(), payloads.lmstudio(), payloads.llama_swap(), payloads.unsloth(), payloads.strata_router()):
            for path in ("/v1/models",):
                if path in route_table:
                    for entry in parsers.parse_openai_models(route_table[path])[1]:
                        self.assertIn(entry["state"], parsers.STATES)


if __name__ == "__main__":
    unittest.main()
