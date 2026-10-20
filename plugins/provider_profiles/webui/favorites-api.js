// Client for POST /api/plugins/provider_profiles/favorites. Never throws: every call
// resolves to {ok:false, error, message} on failure so the UI can fail soft.

const ENDPOINT = "/plugins/provider_profiles/favorites";
const TIMEOUT_MS = 8000;

async function call(body) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);
  try {
    const { fetchApi } = await import("/js/api.js");
    const response = await fetchApi(ENDPOINT, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal: controller.signal,
    });
    if (!response.ok) return { ok: false, error: `http_${response.status}`, message: `Favorites service returned HTTP ${response.status}` };
    const data = await response.json().catch(() => null);
    if (!data || typeof data !== "object") return { ok: false, error: "bad_response", message: "Favorites service returned an unreadable response" };
    return data;
  } catch (error) {
    return { ok: false, error: error?.name === "AbortError" ? "timeout" : "network", message: "Favorites service is unreachable" };
  } finally {
    clearTimeout(timer);
  }
}

export const bootstrap = () => call({ action: "bootstrap" });

export const setFavorite = ({ type, provider, apiBase, name, on }) =>
  call({ action: "set", model_type: type, provider, api_base: apiBase, name, on: Boolean(on) });

export const touchFavorite = ({ type, provider, apiBase, name }) =>
  call({ action: "touch", model_type: type, provider, api_base: apiBase, name });
