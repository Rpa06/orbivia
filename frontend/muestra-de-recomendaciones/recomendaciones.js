// Vista de acciones recomendadas y tareas asignadas al astronauta.
import { api, card, h } from "../assets/core.js";

export async function renderRecommendations(root, role, astronautId) {
  const data = await api("/recommendations");
  const list = data.actions.length ? h("ul", {}, data.actions.map((a) => h("li", {},
    h("strong", {}, a.label || a.code), role !== "astronaut" ? ` · ${a.astronaut_id}` : "", `: ${a.text || ""}`,
    h("div", { class: "ref" }, `${a.reference || ""} · activa desde ${a.since}; no se repite mientras la tendencia se estabilice o mejore`))))
    : h("p", { class: "muted" }, "No hay acciones recomendadas activas.");
  root.append(card("Acciones recomendadas", h("p", { class: "muted small" }, "Operativas, no clínicas. Lo clínico lo decide el médico de a bordo."), list));

  if (role === "astronaut") {
    try {
      const plans = await api("/plans/today");
      const chosen = plans.options.find((o) => o.id === plans.decision?.option_id);
      const plan = chosen || plans.options[0];
      if (plan) {
        const mine = plan.assignments.filter((a) => a.people.includes(astronautId));
        root.append(card(chosen ? `Tus tareas (plan ${plan.id} elegido)` : "Tus tareas (pendiente de elegir plan; se muestra la opción A)",
          mine.length ? h("ul", {}, mine.map((a) => h("li", {}, `${a.start}–${a.end} · ${a.name}`))) : h("p", { class: "muted" }, "Sin tareas asignadas.")));
      }
    } catch { /* sin planes todavía */ }
  }
}
