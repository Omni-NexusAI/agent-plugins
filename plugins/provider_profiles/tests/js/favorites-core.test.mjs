import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

import * as core from "../../webui/favorites-core.js";

const here = dirname(fileURLToPath(import.meta.url));
const vectors = JSON.parse(readFileSync(join(here, "..", "vectors", "identity_vectors.json"), "utf8"));
const pluginDir = join(here, "..", "..");

test("canonicalBase matches the shared vectors", () => {
  for (const [source, expected] of vectors.canonical_base) {
    assert.equal(core.canonicalBase(source), expected, `canonicalBase(${JSON.stringify(source)})`);
  }
});

test("canonicalBase rejects the shared invalid vectors", () => {
  for (const [source] of vectors.invalid_base) {
    assert.equal(core.canonicalBase(source), null, `canonicalBase(${JSON.stringify(source)})`);
  }
});

test("identityKey agrees with the shared same-identity vectors", () => {
  for (const [a, b, same] of vectors.same_identity) {
    const ka = core.identityKey(a.type, a.provider, a.api_base, a.name);
    const kb = core.identityKey(b.type, b.provider, b.api_base, b.name);
    assert.equal(ka === kb, same, JSON.stringify([a, b]));
  }
});

test("identityKey refuses unusable input", () => {
  assert.equal(core.identityKey("bogus", "p", "", "m"), null);
  assert.equal(core.identityKey("chat", "", "", "m"), null);
  assert.equal(core.identityKey("chat", "p", "", "  "), null);
  assert.equal(core.identityKey("chat", "p", "http://u:pw@h", "m"), null);
});

const entry = (name, used, starred = used, provider = "other", api_base = "") => ({ provider, api_base, name, starred_at: starred, last_used_at: used });

test("cardRows pins the most recent N, matching first, and reports hidden", () => {
  const entries = ["a", "b", "c", "d", "e", "f", "g"].map((n, i) => entry(n, i + 1));
  const plain = core.cardRows(entries, { limit: 5 });
  assert.deepEqual(plain.rows.map((r) => r.name), ["g", "f", "e", "d", "c"]);
  assert.equal(plain.total, 7);
  assert.equal(plain.hidden, 2);
  const typed = core.cardRows(entries, { limit: 5, query: "d" });
  assert.deepEqual(typed.rows.map((r) => r.name), ["d", "g", "f", "e", "c"]);
  const all = core.cardRows(entries, { limit: 5, showAll: true });
  assert.equal(all.rows.length, 7);
  assert.equal(all.hidden, 0);
});

test("a favorite outside the pinned set is not pulled in by typing", () => {
  const entries = ["a", "b", "c", "d", "e", "f"].map((n, i) => entry(n, i + 1));
  const rows = core.cardRows(entries, { limit: 5, query: "a" }).rows.map((r) => r.name);
  assert.deepEqual(rows, ["f", "e", "d", "c", "b"]);
});

test("recencySort breaks ties by star time then name", () => {
  const sorted = core.recencySort([entry("b", 5, 1), entry("a", 5, 1), entry("c", 5, 2)]);
  assert.deepEqual(sorted.map((e) => e.name), ["c", "a", "b"]);
});

test("mergeModelIds is an order-preserving union", () => {
  assert.deepEqual(core.mergeModelIds(["a", "b"], ["b", "c", "", 7, null], undefined, ["a", "d"]), ["a", "b", "c", "d"]);
});

test("groupForTyping narrows only while typing", () => {
  const models = ["alpha", "beta", "alphabet"];
  assert.deepEqual(core.groupForTyping(models, "alp", true), { matched: ["alpha", "alphabet"], rest: [] });
  assert.deepEqual(core.groupForTyping(models, "alp", false), { matched: ["alpha", "alphabet"], rest: ["beta"] });
  assert.deepEqual(core.groupForTyping(models, "", true), { matched: [], rest: models });
});

test("detectHostFavorites ignores internals and this plugin's own members", () => {
  assert.equal(core.detectHostFavorites(["searchModels", "_presetEditorSelectionPinned", "providerProfilesFavorites"]), false);
  assert.equal(core.detectHostFavorites(["favoriteModels"]), true);
  assert.equal(core.detectHostFavorites(["toggleFavourite"]), true);
  assert.equal(core.detectHostFavorites(["_favorites"]), false);
});

test("applyOptimistic mirrors server ops and is idempotent", () => {
  let types = { chat: [], vision: [], utility: [], embedding: [] };
  const op = { kind: "set", on: true, type: "chat", provider: "Other", apiBase: "http://h:1/v1", name: "m" };
  types = core.applyOptimistic(types, op, 10);
  types = core.applyOptimistic(types, op, 11);
  assert.equal(types.chat.length, 1);
  assert.equal(types.chat[0].provider, "other");
  types = core.applyOptimistic(types, { kind: "set", on: true, type: "chat", provider: "other", apiBase: "", name: "z" }, 12);
  assert.deepEqual(types.chat.map((e) => e.name), ["z", "m"]);
  types = core.applyOptimistic(types, { kind: "touch", type: "chat", provider: "other", apiBase: "http://h:1", name: "m" }, 13);
  assert.deepEqual(types.chat.map((e) => e.name), ["m", "z"]);
  types = core.applyOptimistic(types, { ...op, on: false }, 14);
  assert.deepEqual(types.chat.map((e) => e.name), ["z"]);
  const untouched = core.applyOptimistic(types, { kind: "set", on: true, type: "nope", provider: "p", apiBase: "", name: "x" });
  assert.deepEqual(untouched.chat.map((e) => e.name), ["z"]);
});

test("buildIndex/isFavorite use canonical identity", () => {
  const index = core.buildIndex({ chat: [entry("m", 1, 1, "other", "http://h:1/v1")] });
  assert.equal(core.isFavorite(index, "chat", "OTHER", "http://H:1", "m"), true);
  assert.equal(core.isFavorite(index, "utility", "other", "http://h:1", "m"), false);
});

test("effectiveField uses the field scope's fallback getters", () => {
  assert.deepEqual(core.effectiveField({ model: { provider: "", api_base: "" }, _prov: "OpenRouter", _apiBase: " http://x " }), { provider: "openrouter", apiBase: "http://x" });
  assert.deepEqual(core.effectiveField({ model: { provider: "ollama", api_base: "" } }), { provider: "ollama", apiBase: "" });
});

test("the module is pure: no DOM or network globals are touched on import", () => {
  const source = readFileSync(join(pluginDir, "webui", "favorites-core.js"), "utf8")
    .split(/\r?\n/).filter((line) => !line.trim().startsWith("//")).join("\n");
  for (const word of ["document.", "window.", "fetch(", "Alpine", "localStorage"]) {
    assert.ok(!source.includes(word), `favorites-core.js must not reference ${word}`);
  }
});
