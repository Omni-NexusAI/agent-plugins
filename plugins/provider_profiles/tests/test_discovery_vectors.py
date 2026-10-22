"""Golden vectors: what the Python parsers hand the browser, consumed unchanged by tests/js/discovery-merge.test.mjs.

The JS side validates the server's entries again; this file pins that real server output passes that validation
untouched. Regenerate after a deliberate parser change:  UPDATE_VECTORS=1 python -m unittest tests.test_discovery_vectors
"""
from __future__ import annotations

import json
import os
import unittest

from . import endpoint_payloads as payloads
from .loader import PLUGIN_DIR, load_helper

parsers = load_helper("endpoint_parsers")
VECTORS = PLUGIN_DIR / "tests" / "vectors" / "discovery_entries.json"


def build() -> dict:
    out = {}

    def add(name, kind, entries):
        out[name] = {"kind": kind, "entries": entries}

    router = payloads.llamacpp_router()
    add("llamacpp_router", *parsers.parse_openai_models(router["/v1/models"]))

    single = payloads.llamacpp_single()
    kind, entries = parsers.parse_openai_models(single["/v1/models"])
    add("llamacpp_single", kind, parsers.merge_llamacpp_props(entries, single["/props"]))

    lm = payloads.lmstudio()
    add("lmstudio_v1", *parsers.parse_lmstudio_v1(lm["/api/v1/models"]))
    add("lmstudio_v0", *parsers.parse_lmstudio_v0(lm["/api/v0/models"]))
    add("lmstudio_openai_only", *parsers.parse_openai_models(lm["/v1/models"]))

    ollama = payloads.ollama()
    kind, entries = parsers.parse_ollama_tags(ollama["/api/tags"])
    add("ollama", kind, parsers.merge_ollama_ps(entries, ollama["/api/ps"]))

    add("llama_swap", *parsers.parse_openai_models(payloads.llama_swap()["/v1/models"]))
    add("unsloth", *parsers.parse_openai_models(payloads.unsloth()["/v1/models"]))

    strata = payloads.strata_router()
    kind, entries = parsers.parse_openai_models(strata["/v1/models"])
    add("strata_router", kind, parsers.merge_strata_status(entries, strata["/status"]))

    add("openai_generic", *parsers.parse_openai_models(payloads.openai_generic()["/v1/models"]))
    return out


class DiscoveryVectors(unittest.TestCase):
    def test_vectors_match_the_parsers(self):
        text = json.dumps(build(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"
        if os.environ.get("UPDATE_VECTORS") == "1":
            VECTORS.write_text(text, encoding="utf-8", newline="\n")
        self.assertEqual(json.loads(VECTORS.read_text(encoding="utf-8")), json.loads(text),
                         "parser output changed: review the change, then regenerate with UPDATE_VECTORS=1")

    def test_vectors_carry_no_command_lines_or_secrets(self):
        self.assertNotIn(payloads.SECRET_MARKER, VECTORS.read_text(encoding="utf-8"))
        for server in json.loads(VECTORS.read_text(encoding="utf-8")).values():
            for entry in server["entries"]:
                self.assertEqual(set(entry), {"id", "label", "aliases", "state", "failed", "context", "vision", "kind", "quant"})


if __name__ == "__main__":
    unittest.main()
