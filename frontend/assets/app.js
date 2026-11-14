// Orbivia: arranque, inicio de sesión, pestañas por rol y vistas de cada rol.
import { api, card, clearSession, guarded, h, REFERENCES, saveSession, scoreClass, session, sparkline } from "./core.js";
import { renderCheckin } from "../check-in/checkin.js";
import { renderExercise } from "../check-in/ejercicio.js";
import { renderPlans } from "../eleccion-de-planes/planes.js";
import { renderCycle, renderSharedCycle } from "../registro-personal/ciclo.js";
import { renderRecommendations } from "../muestra-de-recomendaciones/recomendaciones.js";
import { renderInterview } from "../obtencion-de-audio/entrevista.js";
import { renderCohesionGraph } from "../visualizacion-de-grafos-solo-mision/grafo.js";

const view = document.getElementById("view");
const tabs = document.getElementById("tabs");

const ROLE_LABEL = {
  astronaut: "Astronauta", flight_surgeon: "Médico de a bordo", commander: "Comandante",
  earth_medical: "Equipo médico en Tierra", earth_mission: "Misión en Tierra",
};

const TABS = {
  astronaut: [
    ["Hoy", astronautHome], ["Check-in y PVT-B", renderCheckin], ["Entrevista", renderInterview],
    ["Ejercicio", renderExercise], ["Planes", (r) => renderPlans(r, "astronaut")],
    ["Recomendaciones", (r) => renderRecommendations(r, "astronaut", session().astronaut_id)],
    ["Registro privado", renderCycle],
  ],
  flight_surgeon: [
    ["Tripulación", surgeonHome], ["Recomendaciones", (r) => renderRecommendations(r, "flight_surgeon")],
    ["Planes", (r) => renderPlans(r, "flight_surgeon")], ["Historial", historyView], ["Ciclo compartido", renderSharedCycle],
  ],
  commander: [["Disponibilidad", commanderHome], ["Planes", (r) => renderPlans(r, "commander")], ["Decisiones", decisionsView]],
  earth_medical: [["Historial de vectores", historyView]],
  earth_mission: [["Estado agregado", missionHome], ["Grafo de cohesión", renderCohesionGraph], ["Decisiones", decisionsView]],
};

function loginView() {
  tabs.hidden = true;
  document.getElementById("demo-bar").hidden = true;
  const user = h("input", { autocomplete: "username", placeholder: "usuario" });
  const pass = h("input", { type: "password", autocomplete: "current-password", placeholder: "contraseña" });
  const msg = h("p", { class: "error" });
  const submit = async (e) => {
    e.preventDefault();
    try {
      const s = await api("/auth/login", { method: "POST", body: { username: user.value, password: pass.value } });
      saveSession(s); start();
    } catch (err) { msg.textContent = err.message; }
  };
  view.replaceChildren(h("form", { class: "card stack login", onsubmit: submit },
    h("h2", {}, "Acceso"), h("label", {}, "Usuario"), user, h("label", {}, "Contraseña"), pass,
    h("button", { type: "submit" }, "Entrar"), msg,
    h("p", { class: "muted small" }, "Demo: astro1…astro4 (astronautas A1-A4), surgeon, commander, earth.medical, earth.mission. ",
      "Las contraseñas las imprime el simulador (volumenes/demo/credenciales.txt).")));
}

async function start() {
  const s = session();
  if (!s) return loginView();
  document.getElementById("demo-bar").hidden = false;
  document.getElementById("who").textContent = `${ROLE_LABEL[s.role]}${s.astronaut_id ? " · " + s.astronaut_id : ""}`;
  try {
    const m = await api("/meta/mission");
    document.getElementById("mission-info").textContent = `${m.name} · día ${m.mission_day} · ${m.today}`;
  } catch (e) { document.getElementById("mission-info").textContent = e.message; }
  const collapse = document.getElementById("btn-collapse");
  collapse.hidden = !["flight_surgeon", "commander"].includes(s.role);
  collapse.onclick = async () => {
    collapse.disabled = true; collapse.textContent = "Ejecutando…";
    try {
      const r = await api("/ops/trigger-daily-collapse", { method: "POST", body: { plans: true } });
      collapse.textContent = `Hecho (planes: ${r.plans?.status || "—"})`;
      showTab(currentTab);
    } catch (e) { collapse.textContent = e.message; }
    setTimeout(() => { collapse.disabled = false; collapse.textContent = "Ejecutar colapso diario"; }, 4000);
  };
  document.getElementById("btn-logout").onclick = () => { clearSession(); loginView(); };
  tabs.hidden = false;
  tabs.replaceChildren(...TABS[s.role].map(([label], i) => h("button", { onclick: () => showTab(i) }, label)));
  showTab(0);
}

let currentTab = 0;
async function showTab(i) {
  currentTab = i;
  [...tabs.children].forEach((b, j) => b.classList.toggle("active", i === j));
  view.replaceChildren();
  await guarded(view, () => TABS[session().role][i][1](view));
}

// --- astronauta ----------------------------------------------------------------------

async function astronautHome(root) {
  const d = await api("/astronaut/dashboard");
  const last = d.availability[0];
  root.append(h("div", { class: "grid" },
    card("Tu disponibilidad",
      last ? h("div", { class: `score ${scoreClass(last.score)}` }, Math.round(last.score)) : h("p", { class: "muted" }, "Sin datos"),
      last ? h("p", { class: "muted small" }, `${last.date} · ${last.reason}`) : null,
      sparkline(d.availability.slice().reverse().map((a) => (a.score - 100) / 25)),
      h("p", { class: "ref" }, REFERENCES.availability)),
    card("Hoy", h("p", {}, d.checkin_done_today ? "Check-in completado." : "Te falta el check-in de hoy."),
      h("p", { class: "muted small" }, "Tus datos se comparan solo contigo mismo, nunca con otros.")),
    card("Recomendaciones activas", d.recommendations.length ?
      h("ul", {}, d.recommendations.map((r) => h("li", {}, h("strong", {}, r.label), `: ${r.text}`))) :
      h("p", { class: "muted" }, "Ninguna."))));
  if (d.latest_vector) {
    root.append(card("Tu último vector diario (desviación respecto a tu línea base, en σ)",
      h("table", {}, Object.entries(d.latest_vector).map(([k, v]) => h("tr", {}, h("td", {}, k), h("td", {}, v == null ? "—" : v.toFixed(2))))),
      d.simulated ? h("p", { class: "pill warn" }, "Contiene valores simulados") : null));
  }
}

// --- médico de a bordo -----------------------------------------------------------------

async function surgeonHome(root) {
  const d = await api("/crew/status");
  root.append(h("p", { class: "muted small" }, `${d.date} · ${d.nlp_notice}`));
  if (!d.crew.length) { root.append(card(null, h("p", { class: "muted" }, "Aún no hay colapso para hoy. Usa «Ejecutar colapso diario»."))); return; }
  for (const a of d.crew) {
    const areas = Object.entries(a.areas).map(([k, v]) => h("span", { class: `pill ${scoreClass(v)}` }, `${k}: ${v ?? "—"}`));
    root.append(card(`${a.astronaut_id}`,
      h("div", { class: "row" }, h("div", { class: `score ${scoreClass(a.availability)}` }, Math.round(a.availability)),
        h("div", {}, h("div", {}, `Motivo general: ${a.reason}`), h("div", { class: "row" }, areas))),
      a.alerts.length ? h("div", {}, h("strong", {}, "Avisos"), h("ul", {}, a.alerts.map((al) => h("li", {},
        `${al.criterion} · ${al.area} · ${al.variables.join(", ")}`, h("div", { class: "ref" }, al.reference))))) :
        h("p", { class: "muted small" }, "Sin avisos hoy."),
      a.checkin ? h("p", { class: "small" }, `Check-in: sueño ${a.checkin.sleep}, cansancio ${a.checkin.fatigue}, carga ${a.checkin.workload}, ánimo ${a.checkin.mood}, convivencia ${a.checkin.cohesion}${a.checkin.known_reason ? " · motivo conocido" : ""}`) :
        h("p", { class: "muted small" }, "Check-in de hoy pendiente."),
      a.latest_interview ? h("p", { class: "small" }, `Última entrevista (${a.latest_interview.date}, pregunta ${a.latest_interview.question_id}): `,
        `acústica ${JSON.stringify(a.latest_interview.acoustic)}`, a.latest_interview.nlp ? ` · texto ${JSON.stringify(a.latest_interview.nlp)}` : " · NLP desactivado") : null,
      h("details", {}, h("summary", {}, "Vector y auditoría de la nota"),
        h("table", {}, Object.entries(a.vector || {}).map(([k, v]) => h("tr", {}, h("td", {}, k), h("td", {}, v == null ? "—" : v.toFixed(2))))),
        h("table", {}, (a.availability_audit || []).filter((c) => c.penalty).map((c) =>
          h("tr", {}, h("td", {}, c.field), h("td", {}, `${c.sigma}σ × ${c.weight} → ${c.penalty}`), h("td", { class: "muted" }, (c.notes || []).join("; "))))))));
  }
}

async function historyView(root) {
  const ids = await api("/crew/ids");
  const select = h("select", {}, ids.map((i) => h("option", { value: i }, i)));
  const out = h("div");
  const load = async () => {
    out.replaceChildren();
    await guarded(out, async () => {
      const d = await api(`/earth/history?astronaut_id=${encodeURIComponent(select.value)}&days=30`);
      const names = d.vectors.length ? Object.keys(d.vectors[0].values) : [];
      out.append(card(`Historial de ${d.astronaut_id} (${d.vectors.length} días)`,
        h("p", { class: "muted small" }, d.excluded),
        h("table", {}, h("tr", {}, h("th", {}, "Campo"), h("th", {}, "Evolución (σ)"), h("th", {}, "Último")),
          names.map((n) => {
            const series = d.vectors.map((v) => v.values[n]);
            const lastVal = series[series.length - 1];
            return h("tr", {}, h("td", {}, n), h("td", {}, sparkline(series)), h("td", {}, lastVal == null ? "—" : lastVal.toFixed(2)));
          }))),
        card("Avisos", d.alerts.length ? h("ul", {}, d.alerts.map((a) => h("li", {}, `${a.date} · ${a.criterion} · ${a.area} · ${a.variables.join(", ")}`))) : h("p", { class: "muted" }, "Ninguno")),
        card("Entrevistas (solo números)", h("table", {}, d.interviews.map((i) => h("tr", {}, h("td", {}, i.date), h("td", {}, `P${i.question_id}`),
          h("td", {}, JSON.stringify(i.acoustic)), h("td", {}, i.nlp ? JSON.stringify(i.nlp) : "—"))))));
    });
  };
  select.onchange = load;
  root.append(card("Equipo médico: historial de vectores diarios", select), out);
  await load();
}

// --- comandante ---------------------------------------------------------------------------

async function commanderHome(root) {
  const d = await api("/crew/status");
  root.append(card(`Disponibilidad · ${d.date}`,
    h("p", { class: "muted small" }, "Solo nota y motivo general. Sin check-in, voz, texto ni ciclo."),
    h("div", { class: "grid" }, d.crew.map((a) => h("div", { class: "card tight" }, h("strong", {}, a.astronaut_id),
      h("div", { class: `score ${scoreClass(a.availability)}` }, Math.round(a.availability)), h("div", { class: "muted small" }, a.reason)))),
    h("p", { class: "ref" }, REFERENCES.availability)));
}

async function decisionsView(root) {
  const out = card("Registro de decisiones humanas");
  for (const offset of [0, 1, 2]) {
    const d = new Date(); d.setDate(d.getDate() - offset);
    const iso = d.toISOString().slice(0, 10);
    try {
      const r = await api(`/plans/${iso}/decisions`);
      for (const x of r.decisions) {
        out.append(h("p", {}, `${r.date}: ${x.decision === "selected" ? "elegido plan " + x.option_id : "rechazados todos"} · ${x.reason_category}${x.reason ? " (" + x.reason + ")" : ""} · ${x.by_role}`));
      }
    } catch { /* sin datos ese día */ }
  }
  if (out.children.length === 1) out.append(h("p", { class: "muted" }, "Sin decisiones registradas."));
  root.append(out);
}

// --- misión en Tierra -------------------------------------------------------------------------

async function missionHome(root) {
  const d = await api("/crew/status");
  root.append(card(`Estado agregado de avisos · ${d.date}`,
    h("p", { class: "muted small" }, "Sin datos individuales."),
    h("p", {}, `Tripulación: ${d.crew_size} · con avisos: ${d.astronauts_with_alerts} · disponibilidad media: ${d.mean_availability ?? "—"}`),
    h("table", {}, Object.entries(d.alerts_by_area).map(([k, v]) => h("tr", {}, h("td", {}, k), h("td", {}, v)))),
    h("p", { class: d.cohesion_incident_active ? "pill warn" : "pill" }, d.cohesion_incident_active ? "Incidencia social activa: grafo disponible" : "Sin incidencia social activa")));
}

start();
