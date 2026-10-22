import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

import * as merge from "../../webui/discovery-merge.js";

const here = dirname(fileURLToPath(import.meta.url));
const vectors = JSON.parse(readFileSync(join(here, "..", "vectors", "discovery_entries.json"), "utf8"));
const entriesOf = (name) => merge.normalizeEntries(vectors[name].entries);
const rowsOf = (name) => merge.expandRows(entriesOf(name));
const ids = (rows) => rows.map((row) => row.id);

test("real server output passes the client validation unchanged", () => {
  for (const [name, server] of Object.entries(vectors)) {
    assert.deepEqual(merge.normalizeEntries(server.entries), server.entries, name);
  }
});

test("normalizeEntries hardens untrusted input", () => {
  const huge = { id: "huge", context: { served: 10 ** 12, max: -5, configured: 1.5 }, state: "exploding", vision: "yes", kind: "other", quant: "q".repeat(500), label: "l".repeat(500) };
  const [entry] = merge.normalizeEntries([huge]);
  assert.deepEqual(entry.context, { served: null, max: null, configured: null });
  assert.equal(entry.state, "unknown");
  assert.equal(entry.vision, null);
  assert.equal(entry.kind, null);
  assert.equal(entry.quant.length, 64);
  assert.equal(entry.label.length, 120);
  for (const junk of [null, undefined, "x", 5, {}, [null, 3, "a", [], { id: "" }, { id: 7 }, { id: "x".repeat(600) }, { nope: 1 }]]) {
    assert.deepEqual(merge.normalizeEntries(junk), [], String(junk));
  }
  assert.deepEqual(merge.normalizeEntries([{ id: "a" }, { id: "a" }, { id: "b", aliases: ["b", "c", "c", 4, "", "d"] }]).map((e) => [e.id, e.aliases]), [["a", []], ["b", ["c", "d"]]]);
  assert.equal(merge.normalizeEntries(Array.from({ length: 5000 }, (_, i) => ({ id: `m${i}` }))).length, 2000);
});

test("aliases become rows that inherit the parent's state and numbers", () => {
  const rows = rowsOf("llamacpp_router");
  assert.equal(rows.length, 9, "8 configurations plus the alias qwen38-mini");
  const alias = rows.find((row) => row.id === "qwen38-mini");
  assert.equal(alias.aliasOf, "qwen38-27b-apex-mini");
  assert.equal(alias.state, "loaded");
  assert.equal(alias.context.configured, 131072);
  assert.deepEqual(alias.aliases, []);
  const clash = merge.expandRows(merge.normalizeEntries([{ id: "a", aliases: ["b"] }, { id: "b" }]));
  assert.deepEqual(ids(clash), ["a", "b"], "an alias that is also an entry id is not listed twice");
});

test("filterRows follows the host rule and matches a parent through its aliases", () => {
  const rows = rowsOf("llamacpp_router");
  assert.deepEqual(ids(merge.filterRows(rows, "MINI-vision")), ["qwen38-27b-apex-mini-vision"]);
  assert.deepEqual(ids(merge.filterRows(rows, "qwen38-mini")).sort(), ["qwen38-27b-apex-mini", "qwen38-mini"].sort());
  assert.equal(merge.filterRows(rows, "  ").length, rows.length);
  assert.equal(merge.filterRows(rows, "zzz").length, 0);
});

test("sortIds orders like the host: case-insensitive, deterministic", () => {
  assert.deepEqual(merge.sortIds(["b", "A", "c", "B", "a"]), ["A", "a", "B", "b", "c"]);
});

test("context formatting", () => {
  const table = { 131072: "128k", 163328: "159.5k", 130560: "127.5k", 262144: "256k", 32768: "32k", 8192: "8k", 1000: "1000", 1048576: "1M", 2097152: "2M", 0: "", [-1]: "", 1.5: "" };
  for (const [tokens, expected] of Object.entries(table)) assert.equal(merge.formatContext(Number(tokens)), expected, tokens);
  assert.equal(merge.formatContext(null), "");
});

test("chips carry text for every signal, the max context only as a ceiling", () => {
  const rows = new Map(rowsOf("llamacpp_router").map((row) => [row.id, row]));
  const text = (id) => merge.chipsFor(rows.get(id)).map((chip) => chip.text);
  assert.deepEqual(text("qwen38-27b-apex-mini"), ["loaded", "128k ctx"]);
  assert.deepEqual(text("qwen38-27b-apex-mini-vision"), ["unloaded", "80k ctx", "vision"]);
  assert.deepEqual(text("qwen38-mini"), ["alias of qwen38-27b-apex-mini", "loaded", "128k ctx"]);
  assert.deepEqual(text("crashing-config"), ["failed"]);
  assert.deepEqual(text("gemma-4-12b-qat"), ["downloading"]);
  assert.deepEqual(text("qwen3-embedding-0.6b"), ["unloaded", "embedding"]);
  const lm = new Map(rowsOf("lmstudio_v1").map((row) => [row.id, row]));
  assert.deepEqual(merge.chipsFor(lm.get("qwen/qwen3-30b-a3b")).map((chip) => chip.text), ["loaded", "32k ctx", "Q4_K_M", "Qwen3 30B A3B"]);
  assert.deepEqual(merge.chipsFor(lm.get("google/gemma-3-12b")).map((chip) => chip.text), ["unloaded", "max 128k", "vision", "Q4_0", "Gemma 3 12B"]);
  const plain = new Map(rowsOf("lmstudio_openai_only").map((row) => [row.id, row]));
  assert.deepEqual(merge.chipsFor(plain.get("google/gemma-3-12b")), [], "an ids-only server shows no chips");
  assert.ok(merge.chipsFor(rows.get("crashing-config")).every((chip) => chip.tone !== "state-unloaded"), "failed replaces the state chip");
});

test("mergeSearch (narrow) adds everything discovery knows, sorted, without duplicates", () => {
  const snapshot = { rows: rowsOf("llamacpp_router") };
  const host = { models: ["qwen38-27b-apex-mini", "gemma-4-12b-qat", "host-only"], provider: "llama_cpp", source: "provider_endpoint", error: "" };
  const { result } = merge.mergeSearch(host, snapshot, { query: "ignored in narrow mode", mode: "narrow" });
  assert.equal(result.models.length, new Set(result.models).size);
  assert.ok(result.models.includes("host-only"), "host-only ids stay");
  assert.ok(result.models.includes("qwen38-mini"), "router aliases are added");
  assert.ok(result.models.includes("qwen-image-edit-2509-q4"), "ids the host's name filter dropped are added");
  assert.deepEqual(result.models, merge.sortIds(result.models));
  assert.equal(result.provider, "llama_cpp");
  assert.deepEqual(host.models, ["qwen38-27b-apex-mini", "gemma-4-12b-qat", "host-only"], "the host result is not mutated");
});

test("mergeSearch (core) only adds what the host's own query rule would show", () => {
  const snapshot = { rows: rowsOf("llamacpp_router") };
  const host = { models: [], provider: "llama_cpp", source: "provider_endpoint", error: "" };
  const { result } = merge.mergeSearch(host, snapshot, { query: "qwen38-mini", mode: "core" });
  assert.deepEqual(result.models, ["qwen38-27b-apex-mini", "qwen38-mini"]);
  const everything = merge.mergeSearch(host, snapshot, { query: "", mode: "core" }).result;
  assert.equal(everything.models.length, 9);
});

test("mergeSearch drops catalog suggestions once the endpoint answered and clears the host error", () => {
  const snapshot = { rows: rowsOf("openai_generic") };
  const host = { models: ["gpt-4o", "gpt-4o-mini"], provider: "other", source: "litellm_registry", error: "HTTP 404" };
  const { result } = merge.mergeSearch(host, snapshot, { query: "", mode: "narrow" });
  assert.deepEqual(result.models, ["another-model", "my-served-model"]);
  assert.equal(result.source, "provider_endpoint");
  assert.equal(result.error, "");
});

test("mergeSearch leaves the host result untouched when discovery has nothing", () => {
  const host = { models: ["a"], provider: "p", source: "litellm_registry", error: "boom" };
  for (const snapshot of [null, undefined, {}, { rows: [] }]) {
    const { result, rows } = merge.mergeSearch(host, snapshot, { mode: "narrow" });
    assert.equal(result, host, "same object: nothing was changed");
    assert.deepEqual(rows, []);
  }
  assert.deepEqual(merge.mergeSearch(null, { rows: rowsOf("openai_generic") }, { mode: "narrow" }).result.models, ["another-model", "my-served-model"]);
});

test("fillFor uses operating numbers only and never forces vision off", () => {
  const router = new Map(rowsOf("llamacpp_router").map((row) => [row.id, row]));
  assert.deepEqual(merge.fillFor(router.get("qwen38-27b-apex-mini")), { ctx_length: 131072 });
  assert.deepEqual(merge.fillFor(router.get("qwen38-27b-apex-mini-vision")), { ctx_length: 81920, vision: true });
  assert.deepEqual(merge.fillFor(router.get("qwen38-mini")), { ctx_length: 131072 }, "an alias fills like its parent");
  const lm = new Map(rowsOf("lmstudio_v1").map((row) => [row.id, row]));
  assert.deepEqual(merge.fillFor(lm.get("qwen/qwen3-30b-a3b")), { ctx_length: 32768 }, "served context, not the 256k maximum");
  assert.deepEqual(merge.fillFor(lm.get("google/gemma-3-12b")), { vision: true }, "an unloaded model's maximum is not an operating context");
  const strata = new Map(rowsOf("strata_router").map((row) => [row.id, row]));
  assert.equal(merge.fillFor(strata.get("qwen3.8-flash-next-iq3_xxs-strata-mtp-text-128k")).vision, undefined);
});

test("reason and summary lines", () => {
  assert.deepEqual(merge.reasonFor({ error: { category: "unauthorized", message: "m", hint: "h" } }), { message: "m", hint: "h" });
  assert.deepEqual(merge.reasonFor({ error: { message: "only" } }), { message: "only", hint: "" });
  for (const bad of [null, {}, { error: null }, { error: "x" }, { error: { message: "" } }, { error: { message: 5 } }]) assert.equal(merge.reasonFor(bad), null);
  const snapshot = { endpoint: { label: "llama.cpp router", host: "host.docker.internal:8080" }, entries: entriesOf("llamacpp_router") };
  assert.equal(merge.summaryFor(snapshot), "llama.cpp router · host.docker.internal:8080 · 8 models");
  assert.equal(merge.summaryFor({ endpoint: { label: "Ollama", host: "h:1" }, entries: entriesOf("llamacpp_single") }), "Ollama · h:1 · 1 model");
  assert.equal(merge.summaryFor({ endpoint: null, entries: [] }), "");
  assert.equal(merge.summaryFor(null), "");
});

test("indexRows keeps the first row per id", () => {
  const map = merge.indexRows([{ id: "a", n: 1 }, { id: "a", n: 2 }, { id: "b", n: 3 }]);
  assert.equal(map.get("a").n, 1);
  assert.equal(map.size, 2);
});

test("the module is self-contained (no sibling imports, no DOM or network)", () => {
  const source = readFileSync(join(here, "..", "..", "webui", "discovery-merge.js"), "utf8");
  const code = source.split("\n").filter((line) => !line.trim().startsWith("//") && !line.trim().startsWith("*") && !line.trim().startsWith("/**")).join("\n");
  assert.ok(!/^\s*import\s/m.test(code), "no imports");
  assert.ok(!/\b(document|window|fetch|Alpine|localStorage)\b/.test(code), "no DOM, Alpine or network access");
});
