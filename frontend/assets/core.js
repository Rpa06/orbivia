// Núcleo del frontend: sesión, llamadas a la API y utilidades de interfaz.
// La interfaz solo oculta lo que el rol no usa; quien decide qué datos salen es la API.

const TOKEN_KEY = "orbivia.session";

export function session() {
  try { return JSON.parse(sessionStorage.getItem(TOKEN_KEY) || "null"); } catch { return null; }
}
export function saveSession(s) { sessionStorage.setItem(TOKEN_KEY, JSON.stringify(s)); }
export function clearSession() { sessionStorage.removeItem(TOKEN_KEY); }

export async function api(path, { method = "GET", body, headers = {}, raw } = {}) {
  const s = session();
  const h = { ...headers };
  if (s?.token) h.Authorization = `Bearer ${s.token}`;
  let payload = body;
  if (body !== undefined && !raw) { h["Content-Type"] = "application/json"; payload = JSON.stringify(body); }
  const res = await fetch(`/api/v1${path}`, { method, headers: h, body: payload });
  let data = null;
  try { data = await res.json(); } catch { /* sin cuerpo */ }
  if (res.status === 401 && s) { clearSession(); location.reload(); }
  if (!res.ok) {
    const detail = typeof data?.detail === "string" ? data.detail : data?.detail?.message || res.statusText;
    const err = new Error(detail); err.status = res.status; throw err;
  }
  return data;
}

export function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === false || v == null) continue;
    if (k === "class") el.className = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (k === "html") el.innerHTML = v; // solo con texto propio, nunca datos del servidor
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const c of children.flat()) {
    if (c == null || c === false) continue;
    el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return el;
}

export function card(title, ...children) {
  return h("section", { class: "card stack" }, title ? h("h3", {}, title) : null, ...children);
}

export function scoreClass(v) {
  if (v == null) return "";
  return v >= 85 ? "ok" : v >= 65 ? "warn" : "bad";
}

export function errorBox(e) { return h("p", { class: "error" }, e.message || String(e)); }

export async function guarded(container, fn) {
  try { await fn(); } catch (e) { container.append(errorBox(e)); }
}

export function sparkline(values, { width = 120, height = 28 } = {}) {
  const ns = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(ns, "svg");
  svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
  svg.setAttribute("class", "spark");
  const pts = values.map((v, i) => [i, v]).filter(([, v]) => v != null);
  if (pts.length < 2) return svg;
  const ys = pts.map(([, v]) => v);
  const lo = Math.min(-2, ...ys), hi = Math.max(2, ...ys);
  const x = (i) => (i / (values.length - 1)) * (width - 2) + 1;
  const y = (v) => height - 1 - ((v - lo) / (hi - lo)) * (height - 2);
  const zero = document.createElementNS(ns, "line");
  zero.setAttribute("x1", 0); zero.setAttribute("x2", width); zero.setAttribute("y1", y(0)); zero.setAttribute("y2", y(0));
  zero.setAttribute("stroke", "#2a3558");
  svg.append(zero);
  const path = document.createElementNS(ns, "polyline");
  path.setAttribute("points", pts.map(([i, v]) => `${x(i)},${y(v)}`).join(" "));
  path.setAttribute("fill", "none"); path.setAttribute("stroke", "#6ea8ff"); path.setAttribute("stroke-width", "1.5");
  svg.append(path);
  return svg;
}

export const REFERENCES = {
  availability: "Nota 0-100: desviaciones individuales en σ por área NASA (médico, fatiga y sueño, psicológico, social); penalización mayor sobre 1,5σ.",
  workload: "NASA-STD-3001: sobrecarga crítica con jornadas de 10 h tres días por semana o más de 60 h semanales.",
  pvt: "PVT-B de 3 minutos (NASA). Lapso: respuesta ≥ 500 ms.",
  gap: "Brecha de autopercepción: Van Dongen et al., 2003.",
};
