// Registro privado del ciclo menstrual y avisos individualizados, solo visibles para la astronauta.
// No entra en la nota de disponibilidad ni en el reparto, y no se envía a Tierra.
import { api, card, h } from "../assets/core.js";

const PHASES = { menstrual: "Menstrual", follicular: "Folicular", ovulatory: "Ovulatoria", luteal: "Lútea", unknown: "No lo sé" };
const SYMPTOMS = { pain: "Dolor", sleep: "Sueño", mood: "Ánimo", fatigue: "Cansancio", headache: "Cefalea", other: "Otro" };
const FLOW = { none: "Ninguno", spotting: "Manchado", light: "Leve", medium: "Moderado", heavy: "Abundante" };

export async function renderCycle(root) {
  root.append(h("div", { class: "notice private" },
    "Registro opcional y privado. Solo lo ves tú. No cambia tu nota de disponibilidad ni el reparto de tareas, y no sale de la nave."));
  const [insights, entries, share] = await Promise.all([api("/cycle/insights"), api("/cycle/entries"), api("/cycle/share")]);

  if (insights.notice) root.append(card("Aviso para ti", h("p", {}, insights.notice)));

  const phase = h("select", {}, Object.entries(PHASES).map(([v, t]) => h("option", { value: v }, t)));
  const flow = h("select", {}, Object.entries(FLOW).map(([v, t]) => h("option", { value: v }, t)));
  const boxes = Object.entries(SYMPTOMS).map(([v, t]) => {
    const id = `s-${v}`;
    return h("span", { class: "row" }, h("input", { type: "checkbox", id, value: v, style: "width:auto" }),
      h("label", { for: id, style: "margin:0" }, t));
  });
  const unexpected = h("input", { type: "checkbox", id: "unexp", style: "width:auto" });
  root.append(card("Nuevo registro",
    h("div", { class: "grid" }, h("div", {}, h("label", { class: "lbl" }, "Fase"), phase), h("div", {}, h("label", { class: "lbl" }, "Sangrado"), flow)),
    h("div", { class: "row" }, boxes),
    h("div", { class: "row" }, unexpected, h("label", { for: "unexp", style: "margin:0" }, "Sangrado inesperado")),
    h("button", { class: "btn", onclick: async () => {
      const symptoms = boxes.map((b) => b.querySelector("input")).filter((i) => i.checked).map((i) => i.value);
      await api("/cycle/entries", { method: "POST", body: { phase: phase.value, flow: flow.value, symptoms,
        unexpected_bleeding: unexpected.checked } });
      root.innerHTML = ""; renderCycle(root);
    } }, "Guardar")));

  root.append(card("Compartir con el médico de a bordo",
    h("p", { class: "muted small" }, share.active ? `Compartido hasta ${new Date(share.expires_at).toLocaleString()}` : "No compartido."),
    h("div", { class: "row" },
      h("button", { class: "btn btn-sec", onclick: async () => { await api("/cycle/share", { method: "POST", body: { hours: 24 } }); root.innerHTML = ""; renderCycle(root); } }, "Compartir 24 h"),
      share.active ? h("button", { class: "btn btn-sec", onclick: async () => { await api("/cycle/share", { method: "DELETE" }); root.innerHTML = ""; renderCycle(root); } }, "Dejar de compartir") : null)));

  root.append(card(`Tu historial (${entries.length})`,
    h("table", {}, h("tr", {}, h("th", {}, "Fecha"), h("th", {}, "Fase"), h("th", {}, "Sangrado"), h("th", {}, "Síntomas")),
      entries.slice().reverse().map((e) => h("tr", {}, h("td", {}, e.date), h("td", {}, PHASES[e.phase] || e.phase),
        h("td", {}, (FLOW[e.flow] || e.flow) + (e.unexpected_bleeding ? " (inesperado)" : "")),
        h("td", {}, e.symptoms.map((s) => SYMPTOMS[s] || s).join(", "))))),
    h("button", { class: "btn btn-danger", onclick: async () => {
      if (!confirm("Se borrará todo tu registro del ciclo. No se puede deshacer.")) return;
      await api("/cycle/entries", { method: "DELETE" }); root.innerHTML = ""; renderCycle(root);
    } }, "Borrar todo mi registro")));
}

export async function renderSharedCycle(root) {
  const data = await api("/cycle/shared");
  const names = Object.keys(data.shared);
  root.append(card("Registros del ciclo compartidos contigo",
    names.length ? names.map((a) => h("div", {}, h("strong", {}, a),
      h("ul", {}, data.shared[a].slice(-8).map((e) => h("li", {}, `${e.date}: ${PHASES[e.phase] || e.phase}, ${e.symptoms.map((s) => SYMPTOMS[s] || s).join(", ") || "sin síntomas"}${e.unexpected_bleeding ? ", sangrado inesperado" : ""}`)))))
      : h("p", { class: "muted" }, "Ninguna astronauta comparte ahora su registro.")));
}
