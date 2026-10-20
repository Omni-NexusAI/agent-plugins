// Pure logic for model favorites (no DOM, no Alpine, no network).
// Identity/canonicalization rules mirror helpers/favorites_store.py and are pinned by
// tests/vectors/identity_vectors.json (consumed by both test suites).

export const MODEL_TYPES = ["chat", "vision", "utility", "embedding"];
const MAX_BASE = 512;
const SEP = "\u001f";

/** Canonical API base used for identity. "" = provider default; null = not acceptable. */
export function canonicalBase(apiBase) {
  const text = String(apiBase ?? "").trim();
  if (!text) return "";
  if (text.length > MAX_BASE || /[?#]/.test(text)) return null;
  let url;
  try {
    url = new URL(text);
  } catch {
    return null;
  }
  if ((url.protocol !== "http:" && url.protocol !== "https:") || !url.hostname) return null;
  if (url.username || url.password) return null;
  const segments = [];
  for (const segment of url.pathname.split("/")) { // resolve dot/empty segments exactly like the Python mirror
    if (segment === "" || segment === ".") continue;
    if (segment === "..") { segments.pop(); continue; }
    segments.push(segment);
  }
  if (segments.length && segments[segments.length - 1].toLowerCase() === "v1") segments.pop();
  const path = segments.length ? `/${segments.join("/")}` : "";
  return `${url.protocol}//${url.host}${path}`;
}

/** Stable identity key, or null when the API base is unusable. */
export function identityKey(type, provider, apiBase, name) {
  const base = canonicalBase(apiBase);
  const model = String(name ?? "").trim();
  const prov = String(provider ?? "").trim().toLowerCase();
  if (base === null || !prov || !model || !MODEL_TYPES.includes(type)) return null;
  return [type, prov, base, model].join(SEP);
}

export function entryKey(type, entry) {
  return identityKey(type, entry?.provider, entry?.api_base, entry?.name);
}

export function buildIndex(types) {
  const index = new Map();
  for (const type of MODEL_TYPES) {
    for (const entry of types?.[type] || []) {
      const key = entryKey(type, entry);
      if (key) index.set(key, entry);
    }
  }
  return index;
}

export function isFavorite(index, type, provider, apiBase, name) {
  const key = identityKey(type, provider, apiBase, name);
  return key !== null && index.has(key);
}

export function recencySort(entries) {
  return [...(entries || [])].sort((a, b) =>
    (b.last_used_at || 0) - (a.last_used_at || 0)
    || (b.starred_at || 0) - (a.starred_at || 0)
    || String(a.name).toLowerCase().localeCompare(String(b.name).toLowerCase())
    || String(a.provider).localeCompare(String(b.provider)));
}

export function matchesQuery(entry, query) {
  const q = String(query ?? "").trim().toLowerCase();
  if (!q) return false;
  return String(entry.name).toLowerCase().includes(q) || String(entry.provider).toLowerCase().includes(q);
}

/** Rows for the favorites card: the `limit` most recent, matching entries first (stable); all when showAll. */
export function cardRows(entries, { query = "", limit = 5, showAll = false } = {}) {
  const recent = recencySort(entries);
  const picked = showAll ? recent : recent.slice(0, Math.max(0, limit));
  const matching = picked.filter((entry) => matchesQuery(entry, query));
  const rest = picked.filter((entry) => !matchesQuery(entry, query));
  const rows = [...matching, ...rest];
  return { rows, total: recent.length, hidden: recent.length - rows.length };
}

/** Union of model ids keeping first-seen order; ignores empty and non-string values. */
export function mergeModelIds(...lists) {
  const seen = new Set();
  const out = [];
  for (const list of lists) {
    for (const id of list || []) {
      if (typeof id !== "string" || !id || seen.has(id)) continue;
      seen.add(id);
      out.push(id);
    }
  }
  return out;
}

/**
 * Same contract as the host's groupResults(): { matched, rest }.
 * While the user is typing, non-matching rows are dropped (narrowing); otherwise the host's
 * match-first split is kept so a filled field still browses everything.
 */
export function groupForTyping(models, query, typing) {
  const q = String(query ?? "").trim().toLowerCase();
  const list = models || [];
  if (!q) return { matched: [], rest: list };
  const matched = [];
  const rest = [];
  for (const model of list) (String(model).toLowerCase().includes(q) ? matched : rest).push(model);
  return typing ? { matched, rest: [] } : { matched, rest };
}

/** True when the host itself exposes favorites-like public members (so this plugin should yield). */
export function detectHostFavorites(storeKeys) {
  return (storeKeys || []).some((key) =>
    typeof key === "string" && !key.startsWith("_") && !key.startsWith("providerProfiles") && /favou?rite/i.test(key));
}

/** Optimistic local update mirroring the server ops. Returns a new `types` object. */
export function applyOptimistic(types, op, now = Date.now() / 1000) {
  const next = {};
  for (const type of MODEL_TYPES) next[type] = [...(types?.[type] || [])];
  const key = identityKey(op.type, op.provider, op.apiBase, op.name);
  if (!key) return next;
  const list = next[op.type];
  const index = list.findIndex((entry) => entryKey(op.type, entry) === key);
  if (op.kind === "set" && op.on) {
    if (index === -1) {
      list.push({ provider: String(op.provider).toLowerCase(), api_base: String(op.apiBase ?? "").trim(), name: String(op.name).trim(), starred_at: now, last_used_at: now });
    }
  } else if (op.kind === "set" && index !== -1) {
    list.splice(index, 1);
  } else if (op.kind === "touch" && index !== -1) {
    list[index] = { ...list[index], last_used_at: Math.max(now, list[index].last_used_at || 0) };
  }
  next[op.type] = recencySort(list);
  return next;
}

/** Effective provider/base of a field scope: honours the host's fallback getters (utility slot). */
export function effectiveField(scope) {
  const model = scope?.model || {};
  return {
    provider: String(scope?._prov ?? model.provider ?? "").trim().toLowerCase(),
    apiBase: String(scope?._apiBase ?? model.api_base ?? "").trim(),
  };
}
