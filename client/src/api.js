// Thin fetch wrapper: adds the bearer token, parses JSON, reports expired sessions.
let token = null, onExpired = () => {};
export const setToken = t => { token = t; };
export const setOnExpired = f => { onExpired = f; };

export async function api(method, url, body, raw) {
  const opt = { method, headers: { "Content-Type": "application/json" } };
  if (token) opt.headers.Authorization = "Bearer " + token;
  if (body !== undefined) opt.body = JSON.stringify(body);
  const r = await fetch(url, opt);
  if (r.status === 401 && token) { onExpired(); return { status: 401, ok: false, data: { error: "session expired" } }; }
  if (raw) return r;
  let data = {}; try { data = await r.json(); } catch (e) { /* empty body */ }
  return { status: r.status, data, ok: r.ok };
}

// streaming chat needs the raw Response
export function chatStream(payload) {
  return fetch("/api/chat/stream", {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: "Bearer " + token },
    body: JSON.stringify(payload),
  });
}
