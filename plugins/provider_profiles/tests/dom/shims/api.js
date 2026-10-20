// Test shim for Agent Zero's /js/api.js: fetchApi prefixes /api like the real one.
export async function fetchApi(url, options = {}) {
  return fetch("/api" + url, { credentials: "same-origin", ...options });
}

export async function callJsonApi(url, body) {
  const response = await fetchApi(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) throw new Error(await response.text());
  return response.json();
}
