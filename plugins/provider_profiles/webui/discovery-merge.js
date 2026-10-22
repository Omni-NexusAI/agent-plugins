// Pure logic for local endpoint discovery (no DOM, no Alpine, no network).
// Turns the discover_models response into rows, chips and the union with the host's own result list.
// Self-contained on purpose (no sibling imports): see the loader for why modules are injected, not imported.

const MAX_ID = 512;
const MAX_ENTRIES = 2000;
const MAX_ALIASES = 50;
const MAX_TOKENS = 1e9;

export const STATES = ["loaded", "loading", "sleeping", "unloaded", "downloading", "incomplete", "downloaded", "unknown"];

const isId = (value) => typeof value === "string" && value.length > 0 && value.length <= MAX_ID;
const toCount = (value) => (Number.isInteger(value) && value > 0 && value <= MAX_TOKENS ? value : null);

/** Validate the server's entries again on the client: ids are untrusted text, numbers are bounded. */
export function normalizeEntries(raw) {
  if (!Array.isArray(raw)) return [];
  const seen = new Set();
  const out = [];
  for (const item of raw.slice(0, MAX_ENTRIES)) {
    if (!item || typeof item !== "object" || !isId(item.id) || seen.has(item.id)) continue;
    seen.add(item.id);
    const context = item.context && typeof item.context === "object" ? item.context : {};
    const aliases = Array.isArray(item.aliases) ? [...new Set(item.aliases.filter(isId))].filter((alias) => alias !== item.id) : [];
    out.push({
      id: item.id,
      label: typeof item.label === "string" && item.label ? item.label.slice(0, 120) : null,
      aliases: aliases.slice(0, MAX_ALIASES),
      state: STATES.includes(item.state) ? item.state : "unknown",
      failed: item.failed === true,
      context: { served: toCount(context.served), max: toCount(context.max), configured: toCount(context.configured) },
      vision: typeof item.vision === "boolean" ? item.vision : null,
      kind: item.kind === "chat" || item.kind === "embedding" ? item.kind : null,
      quant: typeof item.quant === "string" && item.quant ? item.quant.slice(0, 64) : null,
    });
  }
  return out;
}

/** One selectable row per entry id and per alias; alias rows carry the parent's state and numbers. */
export function expandRows(entries) {
  const rows = [];
  const taken = new Set((entries || []).map((entry) => entry.id));
  for (const entry of entries || []) {
    rows.push({ ...entry, aliasOf: null });
    for (const alias of entry.aliases) {
      if (taken.has(alias)) continue;
      taken.add(alias);
      rows.push({ ...entry, id: alias, label: null, aliases: [], aliasOf: entry.id });
    }
  }
  return rows;
}

/** Same rule as the host search: a case-insensitive substring of the query (a parent also matches through its aliases). */
export function filterRows(rows, query) {
  const q = String(query ?? "").trim().toLowerCase();
  if (!q) return rows;
  return rows.filter((row) => row.id.toLowerCase().includes(q) || (row.aliasOf === null && row.aliases.some((alias) => alias.toLowerCase().includes(q))));
}

/** Case-insensitive order like the host's sorted(..., key=str.lower); ties keep a deterministic order. */
export function sortIds(ids) {
  return [...ids].sort((a, b) => {
    const x = a.toLowerCase();
    const y = b.toLowerCase();
    return x < y ? -1 : x > y ? 1 : a < b ? -1 : a > b ? 1 : 0;
  });
}

function uniqueIds(...lists) {
  const seen = new Set();
  const out = [];
  for (const list of lists) {
    for (const id of list) {
      if (!isId(id) || seen.has(id)) continue;
      seen.add(id);
      out.push(id);
    }
  }
  return out;
}

/** Context the server operates with: served now, else configured; the model maximum is only a ceiling. */
export function operatingContext(row) {
  return row.context.served ?? row.context.configured ?? null;
}

export function formatContext(tokens) {
  if (!Number.isInteger(tokens) || tokens <= 0) return "";
  const scaled = (value, unit) => `${Number.isInteger(value) ? value : value.toFixed(1)}${unit}`;
  if (tokens >= 1048576) return scaled(tokens / 1048576, "M");
  if (tokens >= 1024) return scaled(tokens / 1024, "k");
  return String(tokens);
}

/** Chips for one row: {text, tone}. Text is always present; the tone only colours it. */
export function chipsFor(row) {
  const chips = [];
  if (row.aliasOf) chips.push({ text: `alias of ${row.aliasOf}`, tone: "alias" });
  if (row.failed) chips.push({ text: "failed", tone: "failed" });
  else if (row.state !== "unknown") chips.push({ text: row.state, tone: `state-${row.state}` });
  const operating = formatContext(operatingContext(row));
  if (operating) chips.push({ text: `${operating} ctx`, tone: "ctx" });
  else if (row.context.max) chips.push({ text: `max ${formatContext(row.context.max)}`, tone: "ctx" });
  if (row.vision === true) chips.push({ text: "vision", tone: "vision" });
  if (row.kind === "embedding") chips.push({ text: "embedding", tone: "kind" });
  if (row.quant) chips.push({ text: row.quant, tone: "quant" });
  if (row.label && row.label !== row.id) chips.push({ text: row.label, tone: "label" });
  return chips;
}

/**
 * Union of the host's result and the discovered rows.
 *   mode "narrow": the host result is the full list, discovery adds everything it knows.
 *   mode "core":   discovery is filtered with the host's own query rule, so it only adds what the host dropped
 *                  (router aliases, ids the host's name filter removed).
 * Catalog suggestions (the host's registry fallback) are dropped once the endpoint itself answered: they would
 * be unrelated cloud model names for a local server.
 */
export function mergeSearch(hostResult, snapshot, { query = "", mode = "core" } = {}) {
  const host = hostResult && typeof hostResult === "object" ? hostResult : { models: [], source: "", error: "" };
  const rows = snapshot?.rows || [];
  if (!rows.length) return { result: host, rows: [] };
  const hostIds = Array.isArray(host.models) ? host.models : [];
  const catalog = host.source === "litellm_registry";
  const visible = mode === "narrow" ? rows : filterRows(rows, query);
  const models = sortIds(uniqueIds(catalog ? [] : hostIds, visible.map((row) => row.id)));
  return { result: { ...host, models, source: catalog ? "provider_endpoint" : host.source, error: "" }, rows };
}

/** What a selected row may fill into the model form (opt-in): operating numbers only, never the model maximum. */
export function fillFor(row) {
  const fill = {};
  const context = operatingContext(row);
  if (context) fill.ctx_length = context;
  if (row.vision === true) fill.vision = true;
  return fill;
}

/** The categorized reason shown instead of the silent "No models found". */
export function reasonFor(snapshot) {
  const error = snapshot?.error;
  if (!error || typeof error !== "object" || typeof error.message !== "string" || !error.message) return null;
  return { message: error.message.slice(0, 300), hint: typeof error.hint === "string" ? error.hint.slice(0, 400) : "" };
}

/** One muted line about what answered, e.g. "llama.cpp router · host.docker.internal:8080 · 7 models". */
export function summaryFor(snapshot) {
  const endpoint = snapshot?.endpoint;
  const entries = snapshot?.entries || [];
  if (!endpoint || !entries.length || typeof endpoint.host !== "string") return "";
  const label = typeof endpoint.label === "string" && endpoint.label ? endpoint.label : "server";
  const unit = entries.length === 1 ? "model" : "models";
  return `${label} · ${endpoint.host} · ${entries.length} ${unit}`;
}

/** Index rows by id (first wins) for decoration. */
export function indexRows(rows) {
  const map = new Map();
  for (const row of rows || []) if (!map.has(row.id)) map.set(row.id, row);
  return map;
}
