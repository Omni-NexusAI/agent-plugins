// Guarded patches of Alpine.store("modelConfig") used by the favorites UI.
// Rules: only wrap members that exist, forward every argument, fall back to the previous
// implementation on any error, and undo everything on dispose().
//
// normal_results_mode = "narrow" (default):
//   * searchModelsDetailed asks the host endpoint for the full list (empty query) so a field
//     that already holds a value can browse everything; results are cached briefly and
//     in-flight requests are shared. Errors are never cached.
//   * groupResults narrows to matching rows only while the user is typing (store.providerProfilesTyping),
//     otherwise it keeps the host's match-first split.
// normal_results_mode = "core": nothing is changed.

const { groupForTyping } = await import(`./favorites-core.js${new URL(import.meta.url).search}`);

const CACHE_TTL_MS = 6000;
const SEP = "\u001f";

function copyResult(result) {
  return { ...result, models: Array.isArray(result.models) ? [...result.models] : [] };
}

export function installStorePatch(store, getSettings) {
  const undo = [];
  const narrow = () => {
    try { return getSettings()?.normal_results_mode === "narrow"; } catch { return false; }
  };

  if (typeof store.providerProfilesTyping === "undefined") {
    store.providerProfilesTyping = false;
    undo.push(() => { delete store.providerProfilesTyping; });
  }

  const originalSearch = store.searchModelsDetailed;
  if (typeof originalSearch === "function") {
    const cache = new Map();
    const inflight = new Map();
    const wrapper = async function (provider, query, modelType, apiBase, ...rest) {
      if (!narrow()) return originalSearch.call(this, provider, query, modelType, apiBase, ...rest);
      const key = [provider || "", modelType || "", apiBase || ""].join(SEP);
      const hit = cache.get(key);
      if (hit && Date.now() - hit.at < CACHE_TTL_MS) return copyResult(hit.result);
      let pending = inflight.get(key);
      if (!pending) {
        pending = Promise.resolve(originalSearch.call(this, provider, "", modelType, apiBase, ...rest))
          .then((result) => {
            if (result && Array.isArray(result.models) && !result.error && result.source !== "error") {
              cache.set(key, { at: Date.now(), result: copyResult(result) });
            }
            return result;
          })
          .finally(() => inflight.delete(key));
        inflight.set(key, pending);
      }
      const result = await pending;
      return result && Array.isArray(result.models) ? copyResult(result) : result;
    };
    store.searchModelsDetailed = wrapper;
    undo.push(() => { if (store.searchModelsDetailed === wrapper) store.searchModelsDetailed = originalSearch; });
  }

  const originalGroup = store.groupResults;
  if (typeof originalGroup === "function") {
    const wrapper = function (models, query, ...rest) {
      if (narrow()) {
        try { return groupForTyping(models, query, Boolean(this?.providerProfilesTyping)); } catch { /* fall through */ }
      }
      return originalGroup.call(this, models, query, ...rest);
    };
    store.groupResults = wrapper;
    undo.push(() => { if (store.groupResults === wrapper) store.groupResults = originalGroup; });
  }

  return {
    dispose() {
      for (const fn of undo.splice(0).reverse()) {
        try { fn(); } catch { /* ignore */ }
      }
    },
  };
}
