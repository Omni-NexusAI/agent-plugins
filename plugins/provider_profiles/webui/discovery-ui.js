// Local endpoint discovery for Agent Zero's model-name fields (additive; nothing of the host is replaced).
//
//   * wraps Alpine.store("modelConfig").searchModelsDetailed: asks the discover_models API in parallel with the
//     host's own search and returns the union (router aliases, ids the host's filters dropped) within a deadline;
//   * decorates the host's result rows with state / context / vision chips and adds a reason line instead of the
//     silent "No models found" plus a muted line saying which server answered;
//   * optionally (discovery_fill_on_select) fills the context length and vision flag from the server's numbers.
// Every step is guarded: on any failure the host dropdown keeps working unchanged.

const DEADLINE_MS = 3000; // the dropdown never waits longer than this for discovery
const TTL_MS = { ok: 5000, skipped: 120000, error: 3000, unavailable: 30000 };
const MAX_REQUESTS = 50;
const SEP = "\u001f";
const ROW = ":scope > .model-search-item:not(.disabled)";

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function withDeadline(promise, ms) {
  return new Promise((resolve) => {
    const timer = setTimeout(() => resolve(null), ms);
    promise.then((value) => { clearTimeout(timer); resolve(value); }, () => { clearTimeout(timer); resolve(null); });
  });
}

export function createDiscovery({ merge, api, getSettings }) {
  const requests = new Map(); // key -> { at, ttl, promise }: in-flight sharing plus a short cache
  const latest = new Map(); // key -> last settled snapshot (bounded like requests)
  const hostSources = new Map(); // key -> "source" of the host's last result (catalog suggestions are marked there)
  const listeners = new Set();

  const settings = () => { try { return getSettings() || {}; } catch { return {}; } };
  const enabled = () => settings().discovery_enabled !== false;
  const keyFor = (provider, apiBase, modelType) =>
    [String(provider ?? "").trim().toLowerCase(), String(apiBase ?? "").trim(), modelType === "embedding" ? "embedding" : "chat"].join(SEP);

  function toSnapshot(response) {
    const entries = merge.normalizeEntries(response?.entries);
    const rows = merge.expandRows(entries);
    return {
      unavailable: typeof response?.unavailable === "string" ? response.unavailable : null,
      skipped: typeof response?.skipped === "string" ? response.skipped : null,
      endpoint: response?.endpoint && typeof response.endpoint === "object" ? response.endpoint : null,
      error: response?.error && typeof response.error === "object" ? response.error : null,
      entries,
      rows,
      byId: merge.indexRows(rows),
    };
  }

  function request(provider, apiBase, modelType) {
    const key = keyFor(provider, apiBase, modelType);
    const hit = requests.get(key);
    if (hit && Date.now() - hit.at < hit.ttl) return { key, promise: hit.promise };
    const record = { at: Date.now(), ttl: Infinity, promise: null }; // Infinity while in flight: concurrent opens share it
    record.promise = Promise.resolve(api.discover({ provider, apiBase, modelType })).then((response) => {
      let snapshot;
      try {
        snapshot = toSnapshot(response);
      } catch {
        snapshot = toSnapshot({ ok: false, unavailable: "bad_response" }); // never leave a rejected promise in the cache
      }
      record.at = Date.now();
      record.ttl = snapshot.unavailable ? TTL_MS.unavailable : snapshot.error ? TTL_MS.error : snapshot.skipped ? TTL_MS.skipped : TTL_MS.ok;
      remember(latest, key, snapshot);
      for (const listener of [...listeners]) {
        try { listener(key); } catch { /* a field that went away */ }
      }
      return snapshot;
    }).catch(() => {
      record.at = Date.now();
      record.ttl = TTL_MS.unavailable;
      return toSnapshot({ ok: false, unavailable: "network" });
    });
    requests.set(key, record);
    while (requests.size > MAX_REQUESTS) requests.delete(requests.keys().next().value);
    return { key, promise: record.promise };
  }

  function remember(map, key, value) {
    map.delete(key);
    map.set(key, value);
    while (map.size > MAX_REQUESTS) map.delete(map.keys().next().value);
  }

  // ------------------------------------------------------------------ store patch
  function installStorePatch(store, { getMode }) {
    const original = store.searchModelsDetailed;
    if (typeof original !== "function") return { dispose() {} };
    let active = true;
    const wrapper = async function (provider, query, modelType, apiBase, ...rest) {
      if (!active || !enabled() || !provider) return original.call(this, provider, query, modelType, apiBase, ...rest);
      const started = Date.now();
      const { key, promise } = request(provider, apiBase, modelType);
      let host;
      try {
        host = await original.call(this, provider, query, modelType, apiBase, ...rest);
      } catch (error) {
        host = { models: [], provider, source: "error", error: String(error?.message || error) };
      }
      remember(hostSources, key, host?.source || ""); // known even when discovery answers after the deadline
      const snapshot = await withDeadline(promise, Math.max(0, DEADLINE_MS - (Date.now() - started)));
      if (!snapshot) return host; // too slow: the host result stands; the late answer still fills the cache
      try {
        return merge.mergeSearch(host, snapshot, { query, mode: getMode() }).result;
      } catch {
        return host;
      }
    };
    store.searchModelsDetailed = wrapper;
    return {
      dispose() {
        active = false;
        if (store.searchModelsDetailed === wrapper) store.searchModelsDetailed = original;
      },
    };
  }

  // ------------------------------------------------------------------ DOM decoration (idempotent)
  function renderMeta(row, chips) {
    let meta = row.querySelector(":scope > .pp-meta");
    if (!chips.length) {
      meta?.remove();
      row.classList.remove("pp-has-meta");
      return;
    }
    const signature = chips.map((chip) => `${chip.tone}:${chip.text}`).join("|");
    if (meta && meta.dataset.sig === signature) return;
    if (!meta) {
      meta = el("div", "pp-meta");
      meta.setAttribute("x-ignore", "");
      row.append(meta);
    }
    meta.textContent = "";
    for (const chip of chips) meta.append(el("span", `pp-tag pp-tag-${chip.tone}`, chip.text));
    meta.dataset.sig = signature;
    row.classList.add("pp-has-meta");
  }

  function renderNote(box, className, lines, { first = false } = {}) {
    let note = box.querySelector(`:scope > .${className}`);
    if (!lines) {
      note?.remove();
      return;
    }
    const signature = lines.join("\n");
    if (note && note.dataset.sig === signature) return;
    if (!note) {
      note = el("div", className);
      note.setAttribute("x-ignore", "");
      if (first) box.prepend(note);
      else box.append(note);
    }
    note.textContent = "";
    lines.forEach((line, index) => note.append(el("span", index === 0 ? `${className}-main` : `${className}-more`, line)));
    note.dataset.sig = signature;
  }

  function paint(fc, ctx) {
    const [listBox, emptyBox] = fc.querySelectorAll(":scope > .model-search-results");
    const key = keyFor(ctx.provider, ctx.apiBase, ctx.modelType);
    const snapshot = enabled() ? latest.get(key) || null : null;
    if (listBox) {
      for (const row of listBox.querySelectorAll(ROW)) {
        const id = globalThis.Alpine?.$data?.(row)?.m;
        const meta = snapshot && typeof id === "string" ? snapshot.byId.get(id) : null;
        renderMeta(row, meta ? merge.chipsFor(meta) : []);
      }
      const reason = merge.reasonFor(snapshot);
      const catalogOnly = Boolean(reason) && hostSources.get(key) === "litellm_registry";
      renderNote(listBox, "pp-reason", catalogOnly ? [reason.message, reason.hint].filter(Boolean) : null, { first: true });
      const summary = snapshot && snapshot.rows.length && !reason ? merge.summaryFor(snapshot) : "";
      renderNote(listBox, "pp-endpoint", summary ? [summary] : null);
    }
    if (emptyBox) {
      const reason = merge.reasonFor(snapshot);
      renderNote(emptyBox, "pp-reason", reason ? [reason.message, reason.hint].filter(Boolean) : null);
    }
  }

  function clear(fc) {
    for (const node of fc.querySelectorAll(".pp-meta, .pp-reason, .pp-endpoint")) node.remove();
    for (const row of fc.querySelectorAll(".pp-has-meta")) row.classList.remove("pp-has-meta");
  }

  // ------------------------------------------------------------------ opt-in fill of numbers from the server
  function afterSelect(ctx, id, slotType, getModel, getCtx) {
    if (!enabled() || settings().discovery_fill_on_select !== true) return;
    if (slotType !== "chat" && slotType !== "utility") return; // only these slots have a context length
    const key = keyFor(ctx.provider, ctx.apiBase, ctx.modelType);
    const row = latest.get(key)?.byId.get(id);
    if (!row) return;
    const fill = merge.fillFor(row);
    // the host's own click handler (bubble phase) sets the name first
    setTimeout(() => {
      const model = getModel();
      if (!model || model.name !== id) return;
      try {
        const now = getCtx();
        if (keyFor(now.provider, now.apiBase, now.modelType) !== key) return; // the field moved to another server meanwhile
      } catch { return; }
      if (fill.ctx_length) model.ctx_length = fill.ctx_length;
      if (fill.vision === true && slotType === "chat") model.vision = true;
    }, 0);
  }

  function subscribe(listener) {
    listeners.add(listener);
    return () => listeners.delete(listener);
  }

  return { enabled, keyFor, installStorePatch, paint, clear, afterSelect, subscribe };
}
