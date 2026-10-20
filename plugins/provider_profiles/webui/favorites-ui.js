// Model favorites UI for Agent Zero's model-name fields (additive DOM; nothing of the host is replaced).
//
// Per `input[x-model="model.name"]` field this adds:
//   * a star beside the input for the current value (covers manually typed names)
//   * a star on every host result row
//   * a plugin-owned favorites card that opens instantly (click / typing / search / Enter) and sits
//     flush above the host's results box
//   * debounced type-ahead through the field scope's own doSearch()
// Every step is guarded: on any failure the host dropdown keeps working unchanged.

// Sibling modules are imported by the loader with the same ?v=<version> query and injected into install()
// (no static sibling imports, no top-level await): a plugin upgrade can never pair a new entry with a stale
// cached module, and module evaluation cannot stall.
let core;
let api;
let installStorePatch;

const VERSION = "1.1.0";
const GLOBAL = "__providerProfilesFavorites";
const INPUT_SELECTOR = 'input[x-model="model.name"]';
const RESULTS = ".model-search-results";
const TYPE_AHEAD_MS = 350;
const KILL_FLAG = "pp_favorites_ui";

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function waitUntil(test, timeoutMs = 5000, stepMs = 25) {
  const started = Date.now();
  while (Date.now() - started < timeoutMs) {
    try { if (test()) return true; } catch { /* keep waiting */ }
    await sleep(stepMs);
  }
  return false;
}

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function toast(message) {
  if (typeof globalThis.toastFrontendError === "function") globalThis.toastFrontendError(message, "Provider Profiles");
  else if (typeof globalThis.justToast === "function") globalThis.justToast(message, "error");
  else console.warn("Provider Profiles:", message);
}

function killSwitch() {
  try { return localStorage.getItem(KILL_FLAG) === "off"; } catch { return false; }
}

function hostLabel(apiBase) {
  try { return new URL(apiBase).host; } catch { return ""; }
}

export async function install(deps) {
  ({ core, api, installStorePatch } = deps);
  const existing = globalThis[GLOBAL];
  if (existing && existing.version === VERSION && !existing.disposed) return existing;
  try { existing?.dispose?.(); } catch { /* ignore */ }
  if (killSwitch()) return null;

  const boot = await api.bootstrap();
  if (!boot.ok) return null; // favorites service unavailable: leave the host UI untouched
  const settings = boot.settings || {};
  if (settings.favorites_ui === "off") return null;

  const controller = new AbortController();
  const { signal } = controller;
  const state = { settings, types: boot.types || {}, rev: boot.rev || 0, index: new Map() };
  const fields = new Set();
  const attached = new WeakSet();
  const observers = [];
  let storePatch = null;
  let store = null;
  let yielded = false;
  let queue = Promise.resolve();

  const setTypes = (types, rev) => {
    state.types = types;
    if (typeof rev === "number") state.rev = rev;
    state.index = core.buildIndex(types);
  };
  setTypes(state.types, state.rev);

  const instance = {
    version: VERSION,
    disposed: false,
    state,
    fieldCount: () => fields.size,
    dispose() {
      instance.disposed = true;
      controller.abort();
      for (const observer of observers.splice(0)) observer.disconnect();
      for (const field of [...fields]) field.dispose();
      storePatch?.dispose();
      if (store && store.providerProfilesTyping) store.providerProfilesTyping = false;
      if (globalThis[GLOBAL] === instance) delete globalThis[GLOBAL];
    },
  };
  globalThis[GLOBAL] = instance;

  // ------------------------------------------------------------------ store
  const ensureStore = () => {
    if (yielded) return null;
    if (store) return store;
    const found = globalThis.Alpine?.store?.("modelConfig");
    if (!found) return null;
    if (state.settings.favorites_ui !== "on" && core.detectHostFavorites(Object.keys(found))) {
      console.info("Provider Profiles: host provides its own model favorites; favorites UI disabled.");
      yielded = true;
      instance.dispose();
      return null;
    }
    store = found;
    storePatch = installStorePatch(store, () => state.settings, { groupForTyping: core.groupForTyping });
    return store;
  };

  // ------------------------------------------------------------------ server ops (serialized)
  const enqueue = (task) => {
    const next = queue.then(task, task);
    queue = next.catch(() => {});
    return next;
  };

  // Fields whose input left the DOM (closed modal, rebuilt slot) must not linger: drop their listeners too.
  const prune = () => { for (const field of [...fields]) if (!field.isConnected()) field.dispose(); };
  const paintAll = () => {
    prune();
    for (const field of fields) field.refresh();
  };

  function applyOp(op) {
    const previous = { types: state.types, rev: state.rev };
    setTypes(core.applyOptimistic(state.types, op));
    paintAll();
    return enqueue(async () => {
      const result = op.kind === "set" ? await api.setFavorite(op) : await api.touchFavorite(op);
      if (result.ok) {
        setTypes(result.types, result.rev);
      } else {
        if (op.kind === "set") toast(result.message || "Could not update favorites");
        // Reload the server's truth instead of rolling back to a snapshot that predates other queued ops.
        const fresh = await api.bootstrap();
        if (fresh.ok) setTypes(fresh.types, fresh.rev);
        else setTypes(previous.types, previous.rev);
      }
      paintAll();
      return result;
    });
  }

  async function refreshFromServer() {
    const fresh = await api.bootstrap();
    if (!fresh.ok || instance.disposed) return;
    state.settings = fresh.settings || state.settings;
    setTypes(fresh.types || {}, fresh.rev);
    paintAll();
  }

  // ------------------------------------------------------------------ field controller
  function createField(input, fc) {
    const ac = new AbortController();
    const fieldSignal = ac.signal;
    const scope = () => globalThis.Alpine.$data(fc);
    const modelType = () => scope()?.modelType;
    const current = () => {
      const s = scope();
      return { ...core.effectiveField(s), name: String(s?.model?.name ?? "").trim() };
    };
    const typeName = () => (core.MODEL_TYPES.includes(modelType()) ? modelType() : null);

    const ctl = { open: false, showAll: false, lastQuery: null, token: 0, timer: null, typingLocal: false };
    const injected = [];

    const inputStar = el("button", "pp-star pp-star-input", "☆");
    inputStar.type = "button";
    inputStar.setAttribute("aria-label", "Favorite this model");
    input.after(inputStar);
    injected.push(inputStar);
    fc.classList.add("pp-has-star");

    const card = el("div", "pp-card");
    card.hidden = true;
    card.setAttribute("x-ignore", "");
    card.setAttribute("role", "listbox");
    card.setAttribute("aria-label", "Favorite models");
    fc.append(card);
    injected.push(card);

    // Keep the host results box flush below the card even when the card's height changes after render (fonts, wrapping).
    let resizeWatcher = null;
    try {
      resizeWatcher = new ResizeObserver(() => {
        if (!card.hidden) fc.style.setProperty("--pp-h", `${card.offsetHeight}px`);
      });
      resizeWatcher.observe(card);
    } catch { /* older engines: the height measured at render time is used */ }

    const paintStar = (button, on, usable, label) => {
      button.textContent = on ? "★" : "☆";
      button.classList.toggle("pp-star-on", on);
      button.setAttribute("aria-pressed", String(on));
      button.disabled = !usable && !on;
      // aria-label only: Agent Zero turns every title attribute into a Bootstrap tooltip, and removing such an
      // element while its tooltip is hiding throws inside Bootstrap.
      button.setAttribute("aria-label", on ? "Remove from favorites" : usable ? "Add to favorites" : label);
    };

    const isFav = (name) => {
      const t = typeName();
      const f = core.effectiveField(scope());
      return Boolean(t) && core.isFavorite(state.index, t, f.provider, f.apiBase, name);
    };

    const canFavorite = (name) => {
      const t = typeName();
      const f = core.effectiveField(scope());
      return Boolean(t && name && core.identityKey(t, f.provider, f.apiBase, name));
    };

    function paintInputStar() {
      const { name } = current();
      paintStar(inputStar, isFav(name), canFavorite(name), "Choose a provider, a valid API base and a model name first");
    }

    function decorateRows() {
      for (const row of fc.querySelectorAll(`:scope > ${RESULTS} > .model-search-item:not(.disabled)`)) {
        let star = row.querySelector(":scope > .pp-star");
        const id = globalThis.Alpine.$data(row)?.m;
        if (typeof id !== "string") continue;
        if (!star) {
          row.classList.add("pp-row");
          star = el("button", "pp-star", "☆");
          star.type = "button";
          star.addEventListener("click", (event) => {
            event.stopPropagation();
            event.preventDefault();
            toggle(star.dataset.ppId);
          }, { signal: fieldSignal });
          row.append(star);
        }
        star.dataset.ppId = id;
        paintStar(star, isFav(id), canFavorite(id), "Choose a provider and a valid API base first");
      }
    }

    function rowFor(entry) {
      const row = el("div", "pp-card-row");
      row.setAttribute("role", "option");
      row.dataset.ppKey = core.entryKey(modelType(), entry) || "";
      const cur = current();
      if (core.identityKey(modelType(), cur.provider, cur.apiBase, cur.name) === row.dataset.ppKey) row.classList.add("pp-current");
      row.append(el("span", "pp-card-name", entry.name));
      row.append(el("span", "pp-chip", entry.provider));
      const host = entry.api_base ? hostLabel(entry.api_base) : "";
      if (host) row.append(el("span", "pp-chip pp-chip-host", host));
      row.setAttribute("aria-label", `${entry.name} (${entry.provider}${entry.api_base ? ", " + entry.api_base : ""})`);
      const star = el("button", "pp-star pp-star-on", "★");
      star.type = "button";
      star.setAttribute("aria-pressed", "true");
      star.setAttribute("aria-label", "Remove from favorites");
      star.addEventListener("click", (event) => {
        event.stopPropagation();
        event.preventDefault();
        applyOp({ kind: "set", on: false, type: modelType(), provider: entry.provider, apiBase: entry.api_base, name: entry.name });
      }, { signal: fieldSignal });
      row.append(star);
      row.tabIndex = 0;
      row.addEventListener("click", () => applyFavorite(entry), { signal: fieldSignal });
      row.addEventListener("keydown", (event) => {
        if (event.target !== row) return;
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          applyFavorite(entry);
        } else if (event.key === "Escape") {
          closeCard();
          input.focus();
        }
      }, { signal: fieldSignal });
      return row;
    }

    function renderCard() {
      const t = typeName();
      const entries = t ? state.types[t] || [] : [];
      if (!ctl.open || !entries.length) {
        card.hidden = true;
        fc.classList.remove("pp-open");
        return;
      }
      const limit = Number(state.settings.favorites_shown) || 5;
      const typed = ctl.typingLocal ? current().name : "";
      const { rows, total } = core.cardRows(entries, { query: typed, limit, showAll: ctl.showAll });
      card.textContent = "";
      card.append(el("div", "pp-card-title", "Favorites"));
      for (const entry of rows) card.append(rowFor(entry));
      if (total > limit) {
        const more = el("button", "pp-card-more", ctl.showAll ? "Show fewer" : `Show all ${total}`);
        more.type = "button";
        more.addEventListener("click", (event) => {
          event.stopPropagation();
          ctl.showAll = !ctl.showAll;
          renderCard();
        }, { signal: fieldSignal });
        card.append(more);
      }
      card.hidden = false;
      fc.classList.add("pp-open");
      fc.style.setProperty("--pp-h", `${card.offsetHeight}px`);
    }

    function setTyping(on) {
      ctl.typingLocal = on;
      if (store) store.providerProfilesTyping = on;
    }

    function openCard() {
      ctl.open = true;
      renderCard();
    }

    function closeCard() {
      if (!ctl.open && !ctl.typingLocal) return;
      ctl.open = false;
      ctl.showAll = false;
      setTyping(false);
      renderCard();
    }

    async function toggle(name) {
      const t = typeName();
      const f = core.effectiveField(scope());
      if (!t || !core.identityKey(t, f.provider, f.apiBase, name)) {
        toast("Choose a provider, a valid API base and a model name before adding a favorite.");
        return;
      }
      const on = !core.isFavorite(state.index, t, f.provider, f.apiBase, name);
      await applyOp({ kind: "set", on, type: t, provider: f.provider, apiBase: f.apiBase, name });
    }

    async function applyFavorite(entry) {
      const s = scope();
      const model = s?.model;
      const t = typeName();
      if (!model || !t) return;
      const myToken = ++ctl.token;
      const select = fc.closest(".field")?.parentElement?.querySelector('select[x-model="model.provider"]');
      if (String(model.provider || "").toLowerCase() !== entry.provider) {
        const switcher = globalThis.__providerProfiles?.switchProvider;
        if (!select || typeof switcher !== "function") {
          toast("Switching provider is unavailable until the Provider Profiles hook has loaded.");
          return;
        }
        const result = await switcher(select, s, entry.provider);
        if (!result.ok) {
          toast(result.reason === "provider-unavailable"
            ? `Provider "${entry.provider}" is not available on this Agent Zero.`
            : "The model slot changed while switching provider; nothing was applied.");
          return;
        }
        if (myToken !== ctl.token || scope()?.model !== model) return;
      }
      model.api_base = entry.api_base;
      model.name = entry.name;
      setTyping(false);
      const sc = scope();
      if (sc && "open" in sc) sc.open = false;
      closeCard();
      applyOp({ kind: "touch", type: t, provider: entry.provider, apiBase: entry.api_base, name: entry.name });
    }

    // -- type-ahead through the host's own search
    async function kick() {
      const s = scope();
      if (!s || typeof s.doSearch !== "function") return;
      for (let i = 0; i < 4 && !fieldSignal.aborted; i += 1) {
        if (s.searching) await waitUntil(() => !s.searching, 15000);
        const query = s.model?.name;
        if (ctl.lastQuery === query && coreVisible()) return;
        ctl.lastQuery = query;
        s.doSearch();
        await waitUntil(() => !s.searching, 15000);
        if (s.model?.name === query) return;
      }
    }

    const coreVisible = () => [...fc.querySelectorAll(`:scope > ${RESULTS}`)].some((box) => getComputedStyle(box).display !== "none");

    // -- events
    fc.addEventListener("click", (event) => {
      const target = event.target;
      if (target === input || target.closest?.(".model-search-btn")) openCard();
      const row = target.closest?.(".model-search-item:not(.disabled)");
      if (row && !target.closest(".pp-star")) {
        const id = globalThis.Alpine.$data(row)?.m;
        const t = typeName();
        const f = core.effectiveField(scope());
        if (typeof id === "string" && t && core.isFavorite(state.index, t, f.provider, f.apiBase, id)) {
          applyOp({ kind: "touch", type: t, provider: f.provider, apiBase: f.apiBase, name: id });
        }
        setTyping(false);
      }
    }, { capture: true, signal: fieldSignal });
    inputStar.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      toggle(current().name);
    }, { signal: fieldSignal });
    input.addEventListener("keydown", (event) => {
      if (event.key === "Enter") openCard();
      if (event.key === "Escape") closeCard();
    }, { signal: fieldSignal });
    input.addEventListener("input", () => {
      setTyping(true);
      openCard();
      clearTimeout(ctl.timer);
      ctl.timer = setTimeout(kick, TYPE_AHEAD_MS);
      paintInputStar();
    }, { signal: fieldSignal });
    document.addEventListener("pointerdown", (event) => {
      if (ctl.open && !fc.contains(event.target)) closeCard();
    }, { capture: true, signal: fieldSignal });

    // Close with the host dropdown (selection / outside click) once it has been shown. The host swaps between
    // its two result boxes with a gap (one hides immediately, the other shows a frame later), so a "hidden"
    // reading only counts when it persists.
    let wasVisible = false;
    let closeTimer = null;
    const styleWatcher = new MutationObserver(() => {
      if (coreVisible()) {
        wasVisible = true;
        clearTimeout(closeTimer);
        return;
      }
      if (!wasVisible || !ctl.open || closeTimer) return;
      closeTimer = setTimeout(() => {
        closeTimer = null;
        if (!coreVisible() && ctl.open) {
          wasVisible = false;
          closeCard();
        }
      }, 300);
    });
    const rowWatcher = new MutationObserver(() => decorateRows());
    for (const box of fc.querySelectorAll(`:scope > ${RESULTS}`)) {
      styleWatcher.observe(box, { attributes: true, attributeFilter: ["style"] });
      rowWatcher.observe(box, { childList: true });
    }

    let effect = null;
    try {
      effect = globalThis.Alpine.effect(() => paintInputStar());
    } catch { /* events keep the star current */ }

    const field = {
      isConnected: () => input.isConnected,
      refresh() {
        paintInputStar();
        decorateRows();
        if (ctl.open) renderCard();
      },
      dispose() {
        ac.abort();
        clearTimeout(ctl.timer);
        clearTimeout(closeTimer);
        resizeWatcher?.disconnect();
        styleWatcher.disconnect();
        rowWatcher.disconnect();
        try { if (effect) globalThis.Alpine.release(effect); } catch { /* ignore */ }
        for (const node of injected) node.remove();
        for (const star of fc.querySelectorAll(".pp-star")) star.remove();
        fc.classList.remove("pp-has-star", "pp-open");
        fc.style.removeProperty("--pp-h");
        fields.delete(field);
        attached.delete(input);
      },
    };
    fields.add(field);
    field.refresh();
    return field;
  }

  async function attach(input) {
    prune();
    if (attached.has(input) || instance.disposed) return;
    const fc = input.parentElement;
    if (!fc?.classList.contains("field-control")) return;
    attached.add(input);
    const ready = await waitUntil(() => {
      const scope = globalThis.Alpine?.$data?.(fc);
      return scope && typeof scope.doSearch === "function" && scope.model && core.MODEL_TYPES.includes(scope.modelType);
    }, 8000, 50);
    if (!ready || instance.disposed || !input.isConnected) { attached.delete(input); return; }
    if (state.settings.favorites_ui !== "on" && fc.querySelector('[class*="favorite" i]:not([class*="pp-"])')) return;
    if (!ensureStore()) { attached.delete(input); return; }
    try { createField(input, fc); } catch (error) { console.warn("Provider Profiles: favorites unavailable for a field", error); }
  }

  function scan(root) {
    if (!root?.querySelectorAll) return;
    if (root.matches?.(INPUT_SELECTOR)) attach(root);
    root.querySelectorAll(INPUT_SELECTOR).forEach(attach);
  }

  function watch(root) {
    if (!root || instance.disposed) return;
    scan(root);
    const observer = new MutationObserver((mutations) => {
      if (!root.isConnected) { observer.disconnect(); return; }
      for (const mutation of mutations) mutation.addedNodes.forEach((node) => node.nodeType === 1 && scan(node));
    });
    observer.observe(root, { childList: true, subtree: true });
    observers.push(observer);
  }

  document.addEventListener("modal-content-loaded", (event) => {
    refreshFromServer();
    watch(event.detail?.modal?.element || event.detail?.modal?.body);
  }, { signal });
  document.querySelectorAll(".modal").forEach(watch);
  scan(document);

  return instance;
}
