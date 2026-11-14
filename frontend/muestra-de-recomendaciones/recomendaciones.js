// Acciones recomendadas y tareas del tripulante. El médico ve las de toda la tripulación;
// cada tripulante (también el comandante), solo las suyas.
import { api, avatar, card, crewName, h } from "../assets/core.js";

const ICON = { LOAD_ADJUST: "⚖", LIGHT_EXPOSURE: "☀", RECOVERY: "☾", SURGEON_FOLLOWUP: "✚" };

export async function renderRecommendations(root, mode, astronautId) {
  const data = await api("/recommendations");
  root.append(card(["Acciones recomendadas", "operativas, no clínicas"],
    data.actions.length ? h("div", { class: "alert-grid" }, data.actions.map((a) => h("div", { class: "alert-card", style: "border-left-color:var(--primary);cursor:default" },
      mode === "flight_surgeon" ? h("span", { class: "al-av", html: avatar(a.astronaut_id, 46) })
        : h("span", { class: "al-av badge b-info", style: "display:grid;place-items:center;font-size:1.3rem" }, ICON[a.code] || "★"),
      h("div", {}, h("div", { class: "al-head" }, mode === "flight_surgeon" ? h("span", { class: "al-title" }, crewName(a.astronaut_id)) : null,
        h("span", { class: "badge b-info" }, `${ICON[a.code] || "★"} ${a.label || a.code}`)),
        h("div", { class: "al-body" }, a.text || ""),
        h("div", { class: "ref" }, `${a.reference || ""} · activa desde ${a.since}. No se repite mientras la tendencia se estabilice o mejore.`)))))
      : h("p", { class: "muted" }, "No hay acciones recomendadas activas."),
    h("p", { class: "hint", style: "margin-top:10px" }, "Lo clínico lo decide el médico de a bordo.")));

  if (mode === "self") {
    try {
      const plans = await api("/plans/today");
      const chosen = plans.options.find((o) => o.id === plans.decision?.option_id);
      const plan = chosen || plans.options[0];
      if (plan) {
        const mine = plan.assignments.filter((a) => a.people.includes(astronautId));
        root.append(card([chosen ? `Tus tareas · plan ${plan.id}` : "Tus tareas", chosen ? "elegido por el comandante" : "pendiente de decisión (se muestra la opción A)"],
          mine.length ? h("ul", { class: "list" }, mine.map((a) => h("li", {}, h("span", { class: "t" }, a.start), h("div", {}, a.name, h("small", {}, `hasta las ${a.end}${a.people.length > 1 ? " · con " + a.people.filter((p) => p !== astronautId).join(", ") : ""}`)))))
            : h("p", { class: "muted" }, "Sin tareas asignadas.")));
      }
    } catch { /* sin planes todavía */ }
  }
}
