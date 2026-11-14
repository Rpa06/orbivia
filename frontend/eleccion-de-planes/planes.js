// Vista de los 3 planes propuestos, elección y registro de rechazos.
import { api, card, h, REFERENCES } from "../assets/core.js";

export async function renderPlans(root, role, date = "today") {
  let data;
  try { data = await api(`/plans/${date}`); }
  catch (e) {
    root.append(card("Planes del día", h("p", { class: "muted" }, e.status === 404
      ? "Todavía no hay planes para hoy. El médico o el comandante pueden ejecutar el colapso diario."
      : e.message)));
    return;
  }
  const canDecide = role === "astronaut" || role === "commander";
  root.append(card(`Planes del ${data.date}`,
    h("p", { class: "muted small" }, "Tres alternativas que cumplen las mismas restricciones duras. El grafo social no se usa para repartir."),
    data.decision ? h("div", { class: "notice" },
      data.decision.decision === "selected" ? `Decisión registrada: plan ${data.decision.option_id}` :
        `Rechazados todos (${data.decision.reason_category === "personal" ? "motivo personal" : data.decision.reason || data.decision.reason_category})`) : null,
    data.status !== "ok" ? h("p", { class: "error" }, `Sin plan factible: ${(data.notes || []).filter((n) => typeof n === "string").join("; ")}`) : null,
    data.status === "ok" ? (data.notes || []).filter((n) => typeof n === "string").map((n) => h("p", { class: "notice" }, n)) : null,
    h("p", { class: "ref" }, REFERENCES.workload)));

  const grid = h("div", { class: "grid" });
  for (const o of data.options) {
    const chosen = data.decision?.option_id === o.id;
    grid.append(h("article", { class: `plan stack${chosen ? " chosen" : ""}` },
      h("h3", {}, `${o.id} · ${o.label}`), h("p", { class: "muted small" }, o.description),
      h("div", {}, h("strong", {}, "Ventajas"), h("ul", {}, o.advantages.map((a) => h("li", {}, a)))),
      h("div", {}, h("strong", {}, "Inconvenientes"), h("ul", {}, o.disadvantages.map((a) => h("li", {}, a)))),
      h("details", {}, h("summary", {}, `Asignaciones (${o.assignments.length})`),
        h("table", {}, h("tr", {}, h("th", {}, "Hora"), h("th", {}, "Tarea"), h("th", {}, "Quién")),
          o.assignments.map((a) => h("tr", {}, h("td", {}, `${a.start}–${a.end}`), h("td", {}, a.name), h("td", {}, a.people.join(", ")))))),
      h("details", {}, h("summary", {}, `Cambios frente al plan de referencia (${o.changes.length})`),
        o.changes.length ? h("ul", {}, o.changes.map((c) => h("li", {},
          `${c.name}: ${c.from.join(", ") || "—"} → ${c.to.join(", ") || "sin cubrir"}. `, h("span", { class: "muted" }, c.explanation))))
          : h("p", { class: "muted small" }, "Sin cambios.")),
      h("details", {}, h("summary", {}, "Comparativa de carga"),
        h("table", {}, h("tr", {}, h("th", {}, "Astronauta"), h("th", {}, "Horas"), h("th", {}, "Referencia"), h("th", {}, "Δ")),
          Object.entries(o.workload).map(([a, w]) => h("tr", {}, h("td", {}, a), h("td", {}, w.hours),
            h("td", {}, w.reference_hours ?? "—"), h("td", {}, w.delta_h ?? "—"))))),
      canDecide && !data.decision ? h("button", { onclick: () => decide({ decision: "selected", option_id: o.id }) },
        `Elegir plan ${o.id}`) : null));
  }
  root.append(grid);

  if (canDecide && !data.decision && data.options.length) {
    const reason = h("input", { placeholder: "Motivo del rechazo (opcional si es personal)" });
    const category = h("select", {}, ["operational", "safety", "workload"].map((c) => h("option", { value: c }, c)));
    const priv = h("input", { type: "checkbox", id: "priv" });
    root.append(card("Rechazar los tres planes",
      h("div", { class: "row" }, category, reason),
      h("div", { class: "row" }, priv, h("label", { for: "priv", style: "margin:0" }, "Es un motivo personal (solo constará «motivo personal»)")),
      h("button", { class: "ghost", onclick: () => decide({ decision: "rejected_all", reason: reason.value,
        reason_category: category.value, private_reason: priv.checked }) }, "Rechazar todos")));
  }

  async function decide(body) {
    try {
      await api(`/plans/${data.date}/decision`, { method: "POST", body });
      root.innerHTML = ""; await renderPlans(root, role, date);
    } catch (e) { alert(e.message); }
  }
}
