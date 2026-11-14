// Orbivia: acceso, navegación lateral por rol y vistas de cada rol.
import {
  AREA_ICON, COLOR, REFERENCES, STATE_LABEL, alertCard, api, avatar, barRow, card, clearSession, crewName, crewRole,
  fieldLabel, guarded, h, legend, lineChart, ring, saveSession, scoreState, session, toast,
} from "./core.js";
import { renderCheckin } from "../check-in/checkin.js";
import { renderExercise } from "../check-in/ejercicio.js";
import { renderPlans } from "../eleccion-de-planes/planes.js";
import { renderCycle, renderSharedCycle } from "../registro-personal/ciclo.js";
import { renderRecommendations } from "../muestra-de-recomendaciones/recomendaciones.js";
import { renderInterview } from "../obtencion-de-audio/entrevista.js";
import { renderCohesionGraph } from "../visualizacion-de-grafos-solo-mision/grafo.js";

const view = document.getElementById("view");
const ROLE_LABEL = {
  astronaut: "Astronauta", flight_surgeon: "Médico de a bordo", commander: "Comandante",
  earth_medical: "Equipo médico en Tierra", earth_mission: "Misión en Tierra",
};

// Funciones personales de cualquier tripulante (astronautas y comandante)
const PERSONAL = [
  ["sep", "Mi día"],
  ["mi-dia", "◉", "Mi estado", myDay],
  ["checkin", "✓", "Check-in y PVT-B", renderCheckin],
  ["entrevista", "🎙", "Entrevista", renderInterview],
  ["ejercicio", "⚡", "Ejercicio", renderExercise],
  ["recomendaciones", "★", "Mis recomendaciones", (r) => renderRecommendations(r, "self", session().astronaut_id)],
  ["registro", "🔒", "Registro privado", renderCycle],
];

const NAV = {
  astronaut: [...PERSONAL.slice(1), ["planes", "▤", "Planes del día", (r) => renderPlans(r, "astronaut")]],
  commander: [
    ["sep", "Mando"],
    ["disponibilidad", "◎", "Disponibilidad", commanderHome],
    ["planes", "▤", "Elegir plan", (r) => renderPlans(r, "commander")],
    ["decisiones", "☰", "Decisiones", decisionsView],
    ...PERSONAL,
  ],
  flight_surgeon: [
    ["tripulacion", "✚", "Tripulación", surgeonHome],
    ["recomendaciones", "★", "Recomendaciones", (r) => renderRecommendations(r, "flight_surgeon")],
    ["planes", "▤", "Planes del día", (r) => renderPlans(r, "flight_surgeon")],
    ["ciclo", "🔒", "Ciclo compartido", renderSharedCycle],
  ],
  earth_medical: [["historial", "✚", "Historial médico", earthMedical]],
  earth_mission: [
    ["agregado", "◎", "Estado agregado", missionHome],
    ["grafo", "⚇", "Grafo de cohesión", renderCohesionGraph],
    ["decisiones", "☰", "Decisiones", decisionsView],
  ],
};

// --- acceso ---------------------------------------------------------------------------------

function loginView() {
  document.body.className = "login";
  document.getElementById("sidebar").hidden = true;
  document.getElementById("top").hidden = true;
  const user = h("input", { autocomplete: "username", placeholder: "usuario" });
  const pass = h("input", { type: "password", autocomplete: "current-password", placeholder: "contraseña" });
  const msg = h("p", { class: "error" });
  const submit = async (e) => {
    e.preventDefault();
    try {
      saveSession(await api("/auth/login", { method: "POST", body: { username: user.value, password: pass.value } }));
      start();
    } catch (err) { msg.textContent = err.message; }
  };
  view.replaceChildren(h("div", { class: "login-box" },
    h("div", { class: "logo" }, h("div", { class: "logo-mark" }), "Orbivia"),
    h("form", { class: "card stack", onsubmit: submit },
      h("h2", {}, "Acceso", h("small", {}, "Salud y planificación de la tripulación")),
      h("label", { class: "lbl" }, "Usuario"), user, h("label", { class: "lbl" }, "Contraseña"), pass,
      h("button", { class: "btn block", type: "submit" }, "Entrar"), msg,
      h("p", { class: "hint" }, "Demo: commander (comandante, tripulante A1), astro2…astro4, surgeon, earth.medical, earth.mission. ",
        "Contraseñas en volumenes/demo/credenciales.txt."))));
}

let mission = null;
async function start() {
  const s = session();
  if (!s) return loginView();
  document.body.className = "app";
  document.getElementById("sidebar").hidden = false;
  document.getElementById("top").hidden = false;
  try { mission = await api("/meta/mission"); } catch (e) { mission = null; }

  const title = s.role === "commander" || s.role === "astronaut"
    ? `${crewName(s.astronaut_id)} · ${ROLE_LABEL[s.role]}` : ROLE_LABEL[s.role];
  document.getElementById("title").textContent = title;
  document.getElementById("subtitle").textContent = mission ? mission.name : "Orbivia";
  const pills = document.getElementById("pills");
  pills.replaceChildren(...[
    h("span", { class: "pill warn" }, "Datos simulados"),
    mission ? h("span", { class: "pill" }, "Día de misión ", h("b", {}, mission.mission_day), ` / ${mission.duration_days}`) : null,
    h("span", { class: "pill" }, "Tripulantes ", h("b", {}, "4")),
    h("span", { class: "pill" }, "Contacto con Tierra ", h("b", {}, "Activo")),
    ["flight_surgeon", "commander"].includes(s.role)
      ? h("button", { class: "pill", title: "POST /api/v1/ops/trigger-daily-collapse", onclick: collapse }, "↻ Ejecutar colapso diario") : null,
    h("button", { class: "pill", onclick: () => { clearSession(); loginView(); } }, "Salir")].filter(Boolean));
  document.getElementById("orbit").replaceChildren(...[
    h("strong", {}, ROLE_LABEL[s.role]),
    s.astronaut_id ? h("div", {}, `${crewName(s.astronaut_id)} · ${crewRole(s.astronaut_id)}`) : null,
    mission ? h("div", {}, `Entorno: ${mission.environment === "moon" ? "superficie lunar" : mission.environment}`) : null,
    h("div", {}, "Adaptación: ", mission ? `${mission.adaptation_days} días` : "—")].filter(Boolean));

  const nav = document.getElementById("nav");
  nav.replaceChildren(...NAV[s.role].map((item) => item[0] === "sep"
    ? h("div", { class: "sep" }, item[1])
    : h("a", { "data-k": item[0], onclick: () => show(item[0]) }, h("span", { class: "ic" }, item[1]), item[2])));
  const wanted = location.hash.slice(1);
  show(NAV[s.role].some((i) => i[0] === wanted) ? wanted : NAV[s.role].find((i) => i[0] !== "sep")[0]);
}

let current = null;
async function show(key) {
  current = key;
  history.replaceState(null, "", `${location.pathname}${location.search}#${key}`);
  document.querySelectorAll("nav a").forEach((a) => a.classList.toggle("active", a.dataset.k === key));
  const item = NAV[session().role].find((i) => i[0] === key);
  view.replaceChildren();
  await guarded(view, () => item[3](view));
}

async function collapse(e) {
  const b = e.currentTarget; b.disabled = true; b.textContent = "Ejecutando…";
  try {
    const r = await api("/ops/trigger-daily-collapse", { method: "POST", body: { plans: true } });
    toast(`Colapso diario hecho · planes: ${r.plans?.status || "—"}`);
    show(current);
  } catch (err) { toast(err.message); }
  b.disabled = false; b.textContent = "↻ Ejecutar colapso diario";
}

window.addEventListener("hashchange", () => {
  const key = location.hash.slice(1), s = session();
  if (s && key !== current && NAV[s.role].some((i) => i[0] === key)) show(key);
});

function tick() { document.getElementById("clock").textContent = new Date().toISOString().slice(0, 16).replace("T", " ") + " UTC"; }
tick(); setInterval(tick, 30000);

// --- piezas comunes -----------------------------------------------------------------------

function crewGrid(items, selected, onSelect) {
  return h("section", { class: "crew", "aria-label": "Selección de tripulante" }, items.map((m) => {
    const st = m.state || scoreState(m.availability);
    return h("button", { class: `member${m.astronaut_id === selected ? " sel" : ""}`, onclick: () => onSelect(m.astronaut_id) },
      h("div", { class: "av", html: avatar(m.astronaut_id, 64) }, h("span", { class: "dot", style: `background:${COLOR[st]}` })),
      h("div", {}, h("strong", {}, crewName(m.astronaut_id)), h("span", {}, crewRole(m.astronaut_id)), h("br"),
        h("span", { class: st }, m.availability != null ? `${Math.round(m.availability)} · ${STATE_LABEL[st]}` : STATE_LABEL[st])));
  }));
}

const last = (arr) => (arr && arr.length ? arr[arr.length - 1] : null);
const lastVal = (series, key) => last(series.measurements[key] || [])?.value ?? null;
const r1 = (v) => (v == null ? "—" : Math.round(v * 10) / 10);

function kpi(label, value, unit, note, state) {
  return h("div", { class: "card kpi" }, h("div", { class: "label" }, label),
    h("div", { class: "value" }, value ?? "—", h("span", {}, unit)), h("div", { class: `note ${state || ""}` }, note));
}

function bandState(v, b, higherBetter = true) {
  if (v == null || !b) return ["", ""];
  if (v < b.p05) return higherBetter ? ["Por debajo de su rango", "warn"] : ["Por debajo de su rango", "ok"];
  if (v > b.p95) return higherBetter ? ["Por encima de su rango", "ok"] : ["Por encima de su rango", "warn"];
  return ["Dentro de su rango", "ok"];
}

function kpiRow(series) {
  const b = series.baselines || {};
  const sl = lastVal(series, "sleep_duration_h"), grip = lastVal(series, "grip_strength_kg");
  const spo2 = lastVal(series, "spo2_pct"), hr = lastVal(series, "resting_hr_bpm");
  const pvt = last(series.pvt), av = last(series.availability);
  return h("section", { class: "grid kpis" },
    kpi("Disponibilidad", av ? Math.round(av.score) : null, "/100", STATE_LABEL[scoreState(av?.score)], scoreState(av?.score)),
    kpi("Sueño anoche", r1(sl), "h", ...bandState(sl, b.sleep_duration_h)),
    kpi("PVT-B", pvt ? Math.round(pvt.mean_rt_ms) : null, "ms", pvt ? `${pvt.lapses} lapsos` : "Pendiente", pvt && pvt.lapses > 3 ? "warn" : "ok"),
    kpi("Fuerza de agarre", r1(grip), "kg", ...bandState(grip, b.grip_strength_kg)),
    kpi("SpO₂", r1(spo2), "%", ...bandState(spo2, b.spo2_pct)),
    kpi("FC en reposo", hr ? Math.round(hr) : null, "lpm", ...bandState(hr, b.resting_hr_bpm, false)));
}

const PHYS = {
  sleep: { label: "Sueño", key: "sleep_duration_h", unit: "h", color: "var(--violet)" },
  pvt: { label: "PVT-B", key: "pvt", unit: "ms", color: "var(--warn)" },
  grip: { label: "Agarre", key: "grip_strength_kg", unit: "kg", color: "var(--ok)" },
  spo2: { label: "SpO₂", key: "spo2_pct", unit: "%", color: "var(--primary)" },
  hr: { label: "FC reposo", key: "resting_hr_bpm", unit: "lpm", color: "var(--danger)" },
  hrv: { label: "VFC nocturna", key: "sleep_hrv_ms", unit: "ms", color: "var(--violet)" },
};

function physicalCard(series) {
  const holder = h("div");
  let tab = "sleep";
  const tabs = h("div", { class: "tabs" });
  const draw = () => {
    tabs.replaceChildren(...Object.entries(PHYS).map(([k, v]) => h("button", { class: k === tab ? "active" : "", onclick: () => { tab = k; draw(); } }, v.label)));
    const f = PHYS[tab];
    const data = f.key === "pvt" ? series.pvt.map((p) => p.mean_rt_ms) : (series.measurements[f.key] || []).map((m) => m.value);
    const b = series.baselines?.[f.key === "pvt" ? "pvt_mean_rt_ms" : f.key];
    const vals = data.filter((v) => v != null).concat(b ? [b.p05, b.p95] : []);
    if (!vals.length) { holder.replaceChildren(h("p", { class: "muted" }, "Sin datos")); return; }
    const pad = (Math.max(...vals) - Math.min(...vals)) * 0.25 || 1;
    const se = [{ name: `${f.label} (${f.unit})`, color: f.color, data }];
    holder.replaceChildren(lineChart(se, { min: Math.min(...vals) - pad, max: Math.max(...vals) + pad, band: b ? [b.p05, b.p95] : null, label: f.label }),
      legend(se, b ? "Su rango de referencia" : null));
  };
  draw();
  return card(["Salud física", `Últimos ${series.days} días`], tabs, holder, h("p", { class: "ref" }, REFERENCES.band));
}

const PSI = {
  mood: { name: "Ánimo", color: "var(--ok)" }, fatigue: { name: "Cansancio", color: "var(--warn)" },
  workload: { name: "Carga", color: "var(--danger)" }, cohesion: { name: "Convivencia", color: "var(--primary)" },
  sleep: { name: "Sueño declarado", color: "var(--violet)" },
};

function checkinCard(series) {
  const holder = h("div");
  let tab = "all";
  const tabs = h("div", { class: "tabs" });
  const ck = (series.checkins || []).slice(-14);
  const draw = () => {
    tabs.replaceChildren(...[["all", "Todo"], ...Object.entries(PSI).map(([k, v]) => [k, v.name])]
      .map(([k, l]) => h("button", { class: k === tab ? "active" : "", onclick: () => { tab = k; draw(); } }, l)));
    const keys = tab === "all" ? Object.keys(PSI) : [tab];
    const se = keys.map((k) => ({ name: PSI[k].name, color: PSI[k].color, data: ck.map((c) => c[k]) }));
    holder.replaceChildren(ck.length ? lineChart(se, { min: 1, max: 5, label: "Check-in" }) : h("p", { class: "muted" }, "Sin check-ins"), legend(se));
  };
  draw();
  return card(["Check-in diario", "Últimos 14 días · escala 1–5"], tabs, holder,
    h("p", { class: "ref" }, "Autoinforme. Cansancio y carga: 5 = más alto. Se compara con su propia línea base, no con otros."));
}

function availabilityCard(series) {
  const data = series.availability.map((a) => a.score);
  const se = [{ name: "Disponibilidad", color: "var(--primary)", data }];
  return card(["Disponibilidad", "0–100"], data.length ? lineChart(se, { min: 0, max: 100, band: [85, 100], label: "Disponibilidad" }) : h("p", { class: "muted" }, "Sin datos"),
    legend(se, "Nominal (≥ 85)"), h("p", { class: "ref" }, REFERENCES.availability));
}

function areaBars(areas) {
  return Object.entries(areas || {}).map(([name, v]) => barRow(`${AREA_ICON[name] || ""} ${name}`, v ?? 0, scoreState(v), v == null ? "—" : Math.round(v)));
}

// --- tripulante: mi estado ------------------------------------------------------------------

async function myDay(root) {
  const [d, series] = await Promise.all([api("/astronaut/dashboard"), api("/me/series")]);
  const me = d.astronaut_id;
  if (!d.checkin_done_today) {
    root.append(h("div", { class: "notice warn", style: "margin-bottom:18px" }, "Te falta el check-in de hoy. ",
      h("a", { href: "#checkin", onclick: (e) => { e.preventDefault(); show("checkin"); }, style: "color:var(--primary)" }, "Hacerlo ahora →")));
  }
  root.append(alertsSection(d.alerts.map((a) => ({ ...a, astronaut_id: me })), "Tus avisos activos",
    "Tus datos se comparan solo contigo mismo. Solo tú y el equipo médico veis estos avisos."));
  root.append(kpiRow(series));
  root.append(h("section", { class: "grid two" }, physicalCard(series), checkinCard(series)));
  root.append(h("section", { class: "grid two" }, availabilityCard(series),
    card("Recomendaciones activas", d.recommendations.length
      ? h("ul", { class: "list" }, d.recommendations.map((r) => h("li", {}, h("span", { class: "t" }, "★"), h("div", {}, h("strong", {}, r.label), h("small", {}, r.text)))))
      : h("p", { class: "muted" }, "No tienes recomendaciones activas."))));
}

function alertsSection(alerts, title, hint, onSelect) {
  const sec = card([title, alerts.length ? `${new Set(alerts.map((a) => `${a.astronaut_id}|${a.criterion}|${a.variables}`)).size} activos` : "0 activos"]);
  sec.classList.add("alerts-top");
  if (!alerts.length) sec.classList.add("limpio");
  const order = { C1: 0, C3: 1, C2: 2, C4: 3 };
  const grouped = new Map();
  for (const a of alerts) {
    const key = `${a.astronaut_id}|${a.criterion}|${(a.variables || []).join(",")}`;
    if (grouped.has(key)) grouped.get(key).areas.push(a.area);
    else grouped.set(key, { ...a, areas: [a.area] });
  }
  alerts = [...grouped.values()];
  sec.append(h("div", { class: "alert-grid" }, alerts.length
    ? alerts.slice().sort((a, b) => order[a.criterion] - order[b.criterion]).map((a) => alertCard(a, onSelect ? () => onSelect(a.astronaut_id) : null))
    : h("div", { class: "empty-ok" }, h("span", { class: "ok", style: "font-size:1.4rem" }, "✔"),
      h("div", {}, h("strong", { class: "ok" }, "Todo está bien"), h("div", { class: "hint" }, "No hay avisos activos.")))));
  if (hint) sec.append(h("p", { class: "hint", style: "margin-top:10px" }, hint));
  return sec;
}

// --- médico de a bordo ----------------------------------------------------------------------

let selected = null;
async function surgeonHome(root) {
  const [status, radiation] = await Promise.all([api("/crew/status"), api("/crew/radiation")]);
  if (!status.crew.length) {
    root.append(card(null, h("p", { class: "muted" }, "Aún no hay colapso de hoy. Pulsa «Ejecutar colapso diario».")));
    return;
  }
  selected = selected && status.crew.some((c) => c.astronaut_id === selected) ? selected : status.crew[0].astronaut_id;
  const all = status.crew.flatMap((m) => m.alerts.map((a) => ({ ...a, astronaut_id: m.astronaut_id })));
  const crewState = (m) => (m.alerts.some((a) => a.criterion === "C1") ? "danger" : scoreState(m.availability));
  const body = h("div");
  const render = async () => {
    const m = status.crew.find((c) => c.astronaut_id === selected);
    const series = await api(`/crew/${selected}/series`);
    body.replaceChildren(
      crewGrid(status.crew.map((c) => ({ ...c, state: crewState(c) })), selected, (id) => { selected = id; render(); }),
      kpiRow(series),
      h("section", { class: "grid two" }, physicalCard(series), checkinCard(series)),
      h("section", { class: "grid two" },
        card(["Disponibilidad por área", crewName(selected)], ...areaBars(m.areas), h("p", { class: "ref" }, REFERENCES.availability)),
        card(["Dosis de radiación acumulada", "% del límite de referencia"],
          ...radiation.doses.map((d) => {
            const pct = d.mSv / radiation.reference_limit_mSv * 100;
            return barRow(crewName(d.astronaut_id), pct, pct > 85 ? "danger" : pct > 70 ? "warn" : "ok", `${Math.round(pct)}%`, () => { selected = d.astronaut_id; render(); });
          }), h("p", { class: "hint" }, radiation.note))),
      h("section", { class: "grid two" }, summaryCard(m), auditCard(m)));
  };
  root.append(alertsSection(all, "Avisos activos de la tripulación", "Pulsa un aviso para ver al tripulante. " + status.nlp_notice,
    (id) => { selected = id; render(); body.scrollIntoView({ behavior: "smooth" }); }));
  root.append(body);
  await render();
}

function summaryCard(m) {
  const ck = m.checkin, iv = m.latest_interview;
  return card(["Resumen del tripulante", crewName(m.astronaut_id)], h("ul", { class: "list" },
    h("li", {}, h("span", { class: "t" }, "Rol"), h("div", {}, crewRole(m.astronaut_id))),
    h("li", {}, h("span", { class: "t" }, "Estado"), h("div", {}, h("span", { class: `badge b-${scoreState(m.availability)}` }, `${Math.round(m.availability)} · ${m.reason}`))),
    h("li", {}, h("span", { class: "t" }, "Check-in"), h("div", {}, ck ? `sueño ${ck.sleep} · cansancio ${ck.fatigue} · carga ${ck.workload} · ánimo ${ck.mood} · convivencia ${ck.cohesion}` : "Pendiente hoy",
      ck?.known_reason ? h("small", {}, "Motivo conocido marcado") : null)),
    h("li", {}, h("span", { class: "t" }, "Entrevista"), h("div", {}, iv ? `${iv.date} · pregunta ${iv.question_id}` : "Sin entrevistas recientes",
      iv ? h("small", {}, `Voz: tono ${r1(iv.acoustic?.f0_mean)} st · pausas ${r1(iv.acoustic?.pause_mean_s)} s · ${iv.nlp ? "texto analizado" : "NLP desactivado"}`) : null)),
    h("li", {}, h("span", { class: "t" }, "Acciones"), h("div", {}, m.actions.length ? m.actions.map((a) => a.code).join(", ") : "Ninguna activa"))));
}

function auditCard(m) {
  const contrib = (m.availability_audit || []).filter((c) => c.penalty > 0).sort((a, b) => b.penalty - a.penalty);
  return card(["Por qué esta nota", "aportación de cada señal"],
    contrib.length ? contrib.slice(0, 8).map((c) => barRow(fieldLabel(c.field), Math.min(100, c.penalty * 25), c.sigma > 1.5 ? "danger" : "warn",
      `${c.sigma}σ`)) : h("p", { class: "muted" }, "Ninguna señal penaliza hoy."),
    h("p", { class: "ref" }, "p(s) = s + 1,5·max(0, s − 1,5). El autoinforme pesa la mitad con deseabilidad social alta."));
}

// --- comandante -------------------------------------------------------------------------------

async function commanderHome(root) {
  const d = await api("/crew/status");
  root.append(h("p", { class: "hint", style: "margin-bottom:12px" }, "Solo nota de disponibilidad y motivo general. Nunca check-in, voz, texto ni ciclo de otros tripulantes."));
  root.append(h("section", { class: "grid", style: "grid-template-columns:repeat(auto-fill,minmax(220px,1fr))" },
    d.crew.map((a) => h("div", { class: "card ring-card" },
      h("div", { class: "row", style: "justify-content:center;margin-bottom:8px" }, h("span", { html: avatar(a.astronaut_id, 44) }),
        h("div", { style: "text-align:left" }, h("strong", {}, crewName(a.astronaut_id)), h("div", { class: "hint" }, crewRole(a.astronaut_id)))),
      ring(a.availability),
      h("span", { class: `badge b-${scoreState(a.availability)}` }, a.reason)))));
  root.append(card(null, h("p", { class: "ref" }, REFERENCES.availability),
    h("div", { class: "row", style: "margin-top:10px" }, h("button", { class: "btn", onclick: () => show("planes") }, "Ir a elegir el plan del día →"))));
}

async function decisionsView(root) {
  const c = card(["Registro de decisiones humanas", "últimos días"]);
  const list = h("ul", { class: "list" });
  for (let offset = 0; offset < 5; offset++) {
    const d = new Date(); d.setDate(d.getDate() - offset);
    try {
      const r = await api(`/plans/${d.toISOString().slice(0, 10)}/decisions`);
      r.decisions.forEach((x) => list.append(h("li", {}, h("span", { class: "t" }, r.date.slice(5)),
        h("div", {}, x.decision === "selected" ? `Plan ${x.option_id} elegido` : "Rechazados los tres planes",
          h("small", {}, `${x.reason_category === "personal" ? "motivo personal" : x.reason || x.reason_category} · ${x.by_role}`)))));
    } catch { /* sin datos ese día */ }
  }
  c.append(list.children.length ? list : h("p", { class: "muted" }, "Sin decisiones registradas."));
  root.append(c);
}

// --- Tierra -------------------------------------------------------------------------------------

async function earthMedical(root) {
  const ids = await api("/crew/ids");
  selected = selected && ids.includes(selected) ? selected : ids[0];
  const body = h("div");
  const render = async () => {
    const [series, hist] = await Promise.all([api(`/crew/${selected}/series`), api(`/earth/history?astronaut_id=${encodeURIComponent(selected)}&days=30`)]);
    body.replaceChildren(
      crewGrid(ids.map((id) => ({ astronaut_id: id, availability: id === selected ? last(series.availability)?.score : null, state: id === selected ? undefined : "info" })), selected, (id) => { selected = id; render(); }),
      alertsSection(hist.alerts.slice(-6).map((a) => ({ ...a, astronaut_id: selected })), "Avisos de los últimos días", hist.excluded),
      kpiRow(series),
      h("section", { class: "grid two" }, physicalCard(series), checkinCard(series)),
      h("section", { class: "grid two" }, availabilityCard(series),
        card(["Entrevistas", "solo valores numéricos"], hist.interviews.length ? h("ul", { class: "list" }, hist.interviews.slice(-6).reverse().map((i) => h("li", {},
          h("span", { class: "t" }, i.date.slice(5)), h("div", {}, `Pregunta ${i.question_id}`,
            h("small", {}, `tono ${r1(i.acoustic?.f0_mean)} st · pausas ${r1(i.acoustic?.pause_mean_s)} s · ${i.nlp ? "texto: " + Object.entries(i.nlp).map(([k, v]) => `${k} ${v.toFixed(2)}`).join(", ") : "NLP desactivado"}`)))))
          : h("p", { class: "muted" }, "Sin entrevistas"))));
  };
  root.append(body);
  await render();
}

async function missionHome(root) {
  const d = await api("/crew/status");
  root.append(h("section", { class: "grid kpis", style: "grid-template-columns:repeat(4,1fr)" },
    kpi("Tripulantes", d.crew_size, "", "seudonimizados", ""),
    kpi("Con avisos", d.astronauts_with_alerts, `/ ${d.crew_size}`, d.astronauts_with_alerts ? "Seguimiento a bordo" : "Sin avisos", d.astronauts_with_alerts ? "warn" : "ok"),
    kpi("Disponibilidad media", d.mean_availability, "/100", STATE_LABEL[scoreState(d.mean_availability)], scoreState(d.mean_availability)),
    kpi("Incidencia social", d.cohesion_incident_active ? "Sí" : "No", "", d.cohesion_incident_active ? "Grafo disponible" : "Grafo restringido", d.cohesion_incident_active ? "warn" : "ok")));
  const total = Object.values(d.alerts_by_area).reduce((s, v) => s + v, 0) || 1;
  root.append(h("section", { class: "grid two" },
    card(["Avisos por área", "sin datos individuales"], ...["Médico", "Fatiga y sueño", "Psicológico", "Social y equipo"]
      .map((a) => barRow(`${AREA_ICON[a]} ${a}`, (d.alerts_by_area[a] || 0) / total * 100, d.alerts_by_area[a] ? "warn" : "ok", d.alerts_by_area[a] || 0))),
    card(["Avisos por criterio", "C1 agudo · C2 progresivo · C3 combinado"], ...["C1", "C2", "C3"]
      .map((c) => barRow(c, (d.alerts_by_criterion[c] || 0) / total * 100, c === "C1" ? "danger" : "warn", d.alerts_by_criterion[c] || 0)))));
  if (d.cohesion_incident_active) {
    root.append(h("div", { class: "row" }, h("button", { class: "btn", onclick: () => show("grafo") }, "Ver grafo de cohesión →")));
  }
}

start();
