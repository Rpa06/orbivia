// Núcleo del frontend: sesión, llamadas a la API, retratos, gráficos y componentes comunes.
// La interfaz solo oculta lo que el rol no usa; quien decide qué datos salen es la API.

const TOKEN_KEY = "orbivia.session";

export function session() {
  try { return JSON.parse(sessionStorage.getItem(TOKEN_KEY) || "null"); } catch { return null; }
}
export function saveSession(s) { try { sessionStorage.setItem(TOKEN_KEY, JSON.stringify(s)); } catch { /* sin almacenamiento */ } }
export function clearSession() { try { sessionStorage.removeItem(TOKEN_KEY); } catch { /* sin almacenamiento */ } }

export async function api(path, { method = "GET", body, headers = {}, raw } = {}) {
  const s = session();
  const hd = { ...headers };
  if (s?.token) hd.Authorization = `Bearer ${s.token}`;
  let payload = body;
  if (body !== undefined && !raw) { hd["Content-Type"] = "application/json"; payload = JSON.stringify(body); }
  const res = await fetch(`/api/v1${path}`, { method, headers: hd, body: payload });
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
    else if (k === "html") el.innerHTML = v; // solo con marcado propio (SVG generado aquí), nunca texto del servidor
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const c of children.flat()) {
    if (c == null || c === false) continue;
    el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return el;
}

export const esc = (s) => String(s).replace(/[&<>"]/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[ch]));

export function card(title, ...children) {
  const small = Array.isArray(title) ? title[1] : null;
  const text = Array.isArray(title) ? title[0] : title;
  return h("section", { class: "card" }, text ? h("h2", {}, text, small ? h("small", {}, small) : null) : null, ...children);
}

export function toast(message) {
  const t = document.getElementById("toast");
  t.textContent = message; t.classList.add("show");
  setTimeout(() => t.classList.remove("show"), 2800);
}

export function errorBox(e) { return h("p", { class: "error" }, e.message || String(e)); }
export async function guarded(container, fn) {
  try { await fn(); } catch (e) { container.append(card(null, errorBox(e))); }
}

// --- tripulación (seudónimos; los retratos son ilustraciones, no fotos) -------------------

export const CREW = {
  A1: { rol: "Comandante", skin: "#f0c8a4", hair: "#5a3a22", st: "long" },
  A2: { rol: "Especialista de misión", skin: "#f3d3b6", hair: "#c9a45c", st: "short", beard: true },
  A3: { rol: "Ingeniera de vuelo", skin: "#8d5a3b", hair: "#1a1412", st: "curly" },
  A4: { rol: "Especialista EVA", skin: "#c68e66", hair: "#2a1a14", st: "long" },
};
export const crewName = (id) => `Tripulante ${id}`;
export const crewRole = (id) => CREW[id]?.rol || "Tripulante";

// Retrato ilustrado (adaptado de pagina_inicial.html)
export function avatar(id, size = 64) {
  const p = CREW[id] || { skin: "#c9a27f", hair: "#333", st: "short" };
  const hairBack = p.st === "long"
    ? `<path d="M26 46C22 74 27 82 34 84L66 84C73 82 78 74 74 46C74 22 63 13 50 13S26 22 26 46z" fill="${p.hair}"/>` : "";
  const hairTop = ({
    short: `<path d="M30 42C28 22 38 15 50 15s22 7 20 27c-2-9-6-14-20-14s-18 5-20 14z" fill="${p.hair}"/>`,
    long: `<path d="M30 44C28 22 38 15 50 15s22 7 20 29c-3-10-9-17-22-17-9 0-15 5-18 17z" fill="${p.hair}"/>`,
    curly: [[34, 34, 9], [41, 24, 9], [50, 20, 10], [59, 24, 9], [66, 34, 9], [31, 44, 6], [69, 44, 6]]
      .map(([x, y, r]) => `<circle cx="${x}" cy="${y}" r="${r}" fill="${p.hair}"/>`).join(""),
    bald: "",
  })[p.st] || "";
  const beard = p.beard ? `<path d="M32 50c1 17 10 22 18 22s17-5 18-22c-4 7-10 9-18 9s-14-2-18-9z" fill="${p.hair}"/>` : "";
  return `<svg viewBox="0 0 100 100" width="${size}" height="${size}" role="img" aria-label="Retrato ilustrado de ${esc(crewName(id))}">
    <circle cx="50" cy="50" r="50" fill="#1d2d49"/>${hairBack}
    <rect x="43" y="60" width="14" height="22" fill="${p.skin}"/>
    <path d="M6 100c2-17 15-25 30-27 4 7 9 10 14 10s10-3 14-10c15 2 28 10 30 27z" fill="#e3eaf5"/>
    <path d="M35 74c4 8 9 11 15 11s11-3 15-11" fill="none" stroke="#9fb1cc" stroke-width="3.5" stroke-linecap="round"/>
    <circle cx="74" cy="92" r="5" fill="#2563eb"/><rect x="26" y="90" width="9" height="3" rx="1.5" fill="#ef4444"/>
    <ellipse cx="31" cy="46" rx="3.5" ry="5" fill="${p.skin}"/><ellipse cx="69" cy="46" rx="3.5" ry="5" fill="${p.skin}"/>
    <ellipse cx="50" cy="44" rx="19" ry="22" fill="${p.skin}"/>${beard}${hairTop}
    <circle cx="42" cy="45" r="2.2" fill="#1b1b1f"/><circle cx="58" cy="45" r="2.2" fill="#1b1b1f"/>
    <path d="M37 39q5-3 9 0M54 39q5-3 9 0" stroke="${p.hair}" stroke-width="2" fill="none" stroke-linecap="round"/>
    <path d="M50 47v6" stroke="rgba(0,0,0,.18)" stroke-width="1.6" stroke-linecap="round"/>
    <path d="M44 58q6 4.5 12 0" stroke="${p.beard ? "#f3dcd0" : "#8a4636"}" stroke-width="1.8" fill="none" stroke-linecap="round"/>
  </svg>`;
}

// --- colores y estado ---------------------------------------------------------------------

export const COLOR = { ok: "var(--ok)", warn: "var(--warn)", danger: "var(--danger)", violet: "var(--violet)", info: "var(--primary)" };
export function scoreState(v) {
  if (v == null) return "info";
  return v >= 85 ? "ok" : v >= 65 ? "warn" : "danger";
}
export const STATE_LABEL = { ok: "Nominal", warn: "Vigilar", danger: "Atención", info: "Sin datos" };

export const CRITERIA = {
  C1: { label: "Desviación aguda", sev: "danger", icon: "⚠" },
  C2: { label: "Deterioro progresivo", sev: "warn", icon: "↘" },
  C3: { label: "Señales combinadas", sev: "violet", icon: "◎" },
  C4: { label: "Similitud histórica", sev: "info", icon: "≈" },
};
export const AREA_ICON = { "Médico": "✚", "Fatiga y sueño": "☾", "Psicológico": "◐", "Social y equipo": "⚇",
  medical: "✚", fatigue_sleep: "☾", psychological: "◐", social_team: "⚇" };

export const FIELD_LABEL = {
  sleep_duration_z: "sueño", pvt_rt_z: "PVT-B", self_perception_gap: "brecha de autopercepción",
  checkin_sleep_z: "sueño declarado", checkin_fatigue_z: "cansancio declarado", checkin_workload_z: "carga percibida",
  checkin_mood_z: "ánimo declarado", checkin_cohesion_z: "convivencia declarada", grip_strength_z: "fuerza de agarre",
  spo2_z: "SpO₂", sleep_heart_rate_z: "FC nocturna", sleep_hrv_z: "VFC nocturna", social_centrality_z: "centralidad social",
  circadian_desync_z: "desincronización circadiana", nlp_neutral_z: "texto: neutral", nlp_low_mood_z: "texto: ánimo bajo",
  nlp_anxiety_z: "texto: ansiedad", nlp_stable_z: "texto: estable", acoustic_f0_z: "voz: tono", acoustic_pause_z: "voz: pausas",
};
export const fieldLabel = (f) => FIELD_LABEL[f] || f;

// --- gráficos (adaptado de pagina_inicial.html) --------------------------------------------

export function lineChart(series, o) {
  const W = 600, H = 230, L = 44, R = 12, T = 12, B = 28;
  const n = Math.max(...series.map((s) => s.data.length), 2);
  const x = (i) => L + i * (W - L - R) / (n - 1);
  const y = (v) => T + (o.max - v) / (o.max - o.min) * (H - T - B);
  let s = "";
  for (let k = 0; k <= 4; k++) {
    const v = o.min + (o.max - o.min) * k / 4, yy = y(v);
    s += `<line x1="${L}" y1="${yy}" x2="${W - R}" y2="${yy}" stroke="var(--border)"/>`;
    s += `<text x="${L - 6}" y="${yy + 4}" fill="var(--muted)" font-size="11" text-anchor="end">${Math.round(v * 10) / 10}</text>`;
  }
  if (o.band) s += `<rect x="${L}" y="${y(o.band[1])}" width="${W - L - R}" height="${Math.max(0, y(o.band[0]) - y(o.band[1]))}" fill="var(--ok)" opacity=".09"/>`;
  [0, Math.floor((n - 1) / 2), n - 1].forEach((i) => {
    const txt = i === n - 1 ? "hoy" : `hace ${n - 1 - i} d`;
    s += `<text x="${x(i)}" y="${H - 8}" fill="var(--muted)" font-size="11" text-anchor="${i === 0 ? "start" : i === n - 1 ? "end" : "middle"}">${txt}</text>`;
  });
  series.forEach((se) => {
    const pts = se.data.map((v, i) => [i + (n - se.data.length), v]).filter(([, v]) => v != null);
    if (!pts.length) return;
    s += `<polyline fill="none" stroke="${se.color}" stroke-width="2.5" stroke-linejoin="round" stroke-linecap="round" points="${pts.map(([i, v]) => `${x(i)},${y(v)}`).join(" ")}"/>`;
    const [li, lv] = pts[pts.length - 1];
    s += `<circle cx="${x(li)}" cy="${y(lv)}" r="4.5" fill="${se.color}"><title>${esc(se.name)}: ${lv}</title></circle>`;
  });
  const svg = h("div", { html: `<svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(o.label || "Gráfico")}">${s}</svg>` });
  return svg.firstChild;
}

export function legend(series, band) {
  return h("div", { class: "legend" },
    series.map((s) => h("span", {}, h("i", { style: `background:${s.color}` }), s.name)),
    band ? h("span", {}, h("i", { style: "background:var(--ok);opacity:.35" }), band) : null);
}

export function barRow(name, pct, state, right, onclick) {
  return h("div", { class: `bar-row${onclick ? " click" : ""}`, onclick },
    h("span", { class: "name" }, name),
    h("div", { class: "track" }, h("div", { class: "fill", style: `width:${Math.max(0, Math.min(100, pct))}%;background:${COLOR[state]}` })),
    h("span", { class: "pct" }, right));
}

// Anillo de disponibilidad 0-100
export function ring(value, size = 92) {
  const st = scoreState(value), r = 36, c = 2 * Math.PI * r, v = value == null ? 0 : Math.max(0, Math.min(100, value));
  return h("div", { html: `<svg width="${size}" height="${size}" viewBox="0 0 100 100" role="img" aria-label="Disponibilidad ${value ?? "sin datos"}">
    <circle cx="50" cy="50" r="${r}" fill="none" stroke="var(--surface2)" stroke-width="10"/>
    <circle cx="50" cy="50" r="${r}" fill="none" stroke="${COLOR[st]}" stroke-width="10" stroke-linecap="round"
      stroke-dasharray="${c * v / 100} ${c}" transform="rotate(-90 50 50)"/>
    <text x="50" y="56" text-anchor="middle" font-size="22" font-weight="700" fill="var(--text)">${value == null ? "—" : Math.round(value)}</text>
  </svg>` }).firstChild;
}

// Mini gráfico de desviaciones en σ (barras), para los avisos
export function sigmaBars(values, threshold = 2) {
  const w = 120, hgt = 34, max = Math.max(threshold + 0.5, ...values.map(Math.abs));
  const bw = w / values.length - 4;
  const bars = values.map((v, i) => {
    const bh = Math.abs(v) / max * (hgt - 4);
    const col = v > threshold ? "var(--danger)" : v > 1 ? "var(--warn)" : "var(--primary)";
    return `<rect x="${i * (bw + 4)}" y="${hgt - bh}" width="${bw}" height="${bh}" rx="2" fill="${col}"><title>${v.toFixed(2)}σ</title></rect>`;
  }).join("");
  const ty = hgt - threshold / max * (hgt - 4);
  return h("div", { html: `<svg width="${w}" height="${hgt}" viewBox="0 0 ${w} ${hgt}">${bars}
    <line x1="0" x2="${w}" y1="${ty}" y2="${ty}" stroke="var(--danger)" stroke-dasharray="3 3" opacity=".7"/></svg>` }).firstChild;
}

// Flecha de tendencia para el deterioro progresivo
export function trendViz(slope, days) {
  const total = slope * days, w = 120, hgt = 34;
  const y2 = Math.max(4, hgt - 4 - Math.min(1, total / 3) * (hgt - 8));
  return h("div", { html: `<svg width="${w}" height="${hgt}" viewBox="0 0 ${w} ${hgt}">
    <line x1="4" y1="${hgt - 4}" x2="${w - 10}" y2="${y2}" stroke="var(--warn)" stroke-width="3" stroke-linecap="round"/>
    <circle cx="${w - 10}" cy="${y2}" r="4" fill="var(--warn)"/></svg>` }).firstChild;
}

// Tarjeta visual de aviso
export function alertCard(a, onclick) {
  const crit = CRITERIA[a.criterion] || CRITERIA.C3;
  const vars = (a.variables || []).map(fieldLabel);
  let viz = null, body = "";
  if (a.criterion === "C1" && a.detail?.values_sigma) {
    body = `${vars.join(", ")} fuera de ±2σ tres días seguidos`;
    viz = sigmaBars(a.detail.values_sigma);
  } else if (a.criterion === "C2" && a.detail?.slope_sigma_per_day != null) {
    body = `${vars.join(", ")} empeora ${a.detail.slope_sigma_per_day.toFixed(2)}σ/día en ${a.detail.window_days} días`;
    viz = trendViz(a.detail.slope_sigma_per_day, a.detail.window_days);
  } else if (a.criterion === "C3" && a.detail?.fields) {
    body = "Varias señales empeoran a la vez";
    viz = h("div", { class: "sigma-chips" }, Object.entries(a.detail.fields).map(([f, v]) => h("span", { class: "sigma-chip" }, `${fieldLabel(f)} ${v.toFixed(1)}σ`)));
  } else {
    body = vars.join(", ");
  }
  return h("div", { class: `alert-card sev-${crit.sev}`, onclick, title: a.reference || "" },
    a.astronaut_id ? h("span", { class: "al-av", style: `box-shadow:0 0 0 2px ${COLOR[crit.sev]}`, html: avatar(a.astronaut_id, 46) }) : h("span", { class: "al-av badge b-" + crit.sev, style: "display:grid;place-items:center;font-size:1.3rem" }, crit.icon),
    h("div", {},
      h("div", { class: "al-head" },
        a.astronaut_id ? h("span", { class: "al-title" }, crewName(a.astronaut_id)) : null,
        h("span", { class: `badge b-${crit.sev}` }, `${crit.icon} ${a.criterion} · ${crit.label}`),
        (a.areas || [a.area]).map((ar) => h("span", { class: "badge b-info" }, `${AREA_ICON[ar] || ""} ${ar}`))),
      h("div", { class: "al-body" }, body),
      viz ? h("div", { class: "al-viz" }, viz) : null,
      a.reference ? h("div", { class: "ref" }, a.reference) : null));
}

export const REFERENCES = {
  availability: "Nota 0-100: desviaciones individuales en σ por área NASA (médico, fatiga y sueño, psicológico, social); penalización mayor sobre 1,5σ.",
  workload: "NASA-STD-3001: sobrecarga crítica con jornadas de 10 h tres días por semana o más de 60 h semanales.",
  pvt: "PVT-B de 3 minutos (NASA). Lapso: respuesta ≥ 500 ms.",
  band: "Banda: percentiles 5-95 de la línea base terrestre de este tripulante.",
};
