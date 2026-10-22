// Client for POST /api/plugins/provider_profiles/discover_models. Never throws: every call resolves to the
// server's response or to {ok:false, unavailable:<reason>} so the UI can stay silent and fail soft.

const ENDPOINT = "/plugins/provider_profiles/discover_models";
const TIMEOUT_MS = 11000; // the server gives up after 10 s

const unavailable = (reason) => ({ ok: false, unavailable: reason, skipped: null, endpoint: null, entries: [], error: null });

export async function discover({ provider, apiBase, modelType }) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);
  try {
    const { fetchApi } = await import("/js/api.js");
    const response = await fetchApi(ENDPOINT, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ provider, api_base: apiBase || "", model_type: modelType === "embedding" ? "embedding" : "chat" }),
      signal: controller.signal,
    });
    if (!response.ok) return unavailable(`http_${response.status}`);
    const data = await response.json().catch(() => null);
    if (!data || typeof data !== "object" || data.ok === false) return unavailable("bad_response");
    return data;
  } catch (error) {
    return unavailable(error?.name === "AbortError" ? "timeout" : "network");
  } finally {
    clearTimeout(timer);
  }
}
