// Vista de los 3 planes propuestos. Solo el comandante elige uno o rechaza los tres;
// el resto de la tripulación los consulta.
import { REFERENCES, api, avatar, barRow, card, crewName, h, toast } from "../assets/core.js";

export async function renderPlans(root, role, date = "today") {
  let data;
  try { data = await api(`/plans/${date}`); }
  catch (e) {
    root.append(card("Planes del día", h("p", { class: "muted" }, e.status === 404
      ? "Todavía no hay planes para hoy. El comandante o el médico pueden ejecutar el colapso diario." : e.message)));
    return;
  }
  const canDecide = role === "commander";
  const texts = (data.notes || []).filter((n) => typeof n === "string");
  const head = card([`Planes del ${data.date}`, "tres alternativas con las mismas restricciones duras"],
    h("p", { class: "hint" }, "Ninguna alternativa usa el grafo social. La investigación especializada no se reasigna."),
    data.decision ? h("div", { class: "notice", style: "margin-top:10px" }, h("span", { class: "badge b-ok" }, "✔ Decisión registrada"), " ",
      data.decision.decision === "selected" ? `El comandante eligió el plan ${data.decision.option_id}.`
        : `Rechazados los tres (${data.decision.reason_category === "personal" ? "motivo personal" : data.decision.reason || data.decision.reason_category}).`) : null,
    !canDecide && !data.decision ? h("div", { class: "notice", style: "margin-top:10px" }, "Pendiente de la decisión del comandante.") : null,
    data.status !== "ok" ? h("p", { class: "error" }, `Sin plan factible: ${texts.join("; ")}`) : null,
    data.status === "ok" ? texts.map((n) => h("div", { class: "notice warn", style: "margin-top:10px" }, n)) : null,
    h("p", { class: "ref" }, REFERENCES.workload));
  root.append(head);

  const grid = h("section", { class: "grid three" });
  for (const o of data.options) {
    const chosen = data.decision?.option_id === o.id;
    const hours = Object.entries(o.workload);
    grid.append(h("article", { class: `plan${chosen ? " chosen" : ""}` },
      h("h3", {}, `${o.id} · ${o.label}`, chosen ? h("span", { class: "badge b-ok", style: "margin-left:8px" }, "elegido") : null),
      h("p", { class: "hint" }, o.description),
      h("div", { style: "margin-top:10px" }, hours.map(([a, w]) => {
        const pct = w.hours / 8 * 100;
        const delta = w.delta_h == null || w.delta_h === 0 ? "" : ` (${w.delta_h > 0 ? "+" : ""}${w.delta_h})`;
        const row = barRow(h("span", { class: "row", style: "gap:6px" }, h("span", { html: avatar(a, 22) }), a), pct, pct > 95 ? "warn" : "ok", `${w.hours} h${delta}`);
        row.classList.add("wide");
        return row;
      })),
      h("div", {}, h("strong", { class: "ok", style: "font-size:.85rem" }, "Ventajas"), h("ul", {}, o.advantages.map((a) => h("li", {}, a)))),
      h("div", {}, h("strong", { class: "warn", style: "font-size:.85rem" }, "Inconvenientes"), h("ul", {}, o.disadvantages.map((a) => h("li", {}, a)))),
      h("details", {}, h("summary", {}, `Asignaciones (${o.assignments.length})`),
        h("table", {}, h("tr", {}, h("th", {}, "Hora"), h("th", {}, "Tarea"), h("th", {}, "Quién")),
          o.assignments.map((a) => h("tr", {}, h("td", {}, `${a.start}–${a.end}`), h("td", {}, a.name), h("td", {}, a.people.join(", ")))))),
      h("details", {}, h("summary", {}, `Cambios frente al plan de referencia (${o.changes.length})`),
        o.changes.length ? h("ul", {}, o.changes.map((c) => h("li", {}, `${c.name}: ${c.from.join(", ") || "—"} → ${c.to.join(", ") || "sin cubrir"}. `,
          h("span", { class: "muted" }, c.explanation)))) : h("p", { class: "hint" }, "Sin cambios.")),
      canDecide && !data.decision ? h("button", { class: "btn block", style: "margin-top:12px", onclick: () => decide({ decision: "selected", option_id: o.id }) },
        `Elegir plan ${o.id}`) : null));
  }
  root.append(grid);

  if (canDecide && !data.decision && data.options.length) {
    const reason = h("input", { placeholder: "Motivo del rechazo" });
    const category = h("select", {}, [["operational", "Operativo"], ["safety", "Seguridad"], ["workload", "Carga de trabajo"]]
      .map(([v, l]) => h("option", { value: v }, l)));
    const priv = h("input", { type: "checkbox", id: "priv" });
    root.append(card(["Rechazar los tres planes", "la decisión queda registrada"],
      h("div", { class: "grid two", style: "margin-bottom:10px" }, category, reason),
      h("label", { class: "check", for: "priv" }, priv, h("span", {}, "Es un motivo personal", h("small", {}, "Solo constará «motivo personal»."))),
      h("button", { class: "btn btn-sec", style: "margin-top:12px", onclick: () => decide({ decision: "rejected_all", reason: reason.value,
        reason_category: category.value, private_reason: priv.checked }) }, "Rechazar todos")));
  }

  async function decide(body) {
    try {
      await api(`/plans/${data.date}/decision`, { method: "POST", body });
      toast("Decisión registrada");
      root.replaceChildren(); await renderPlans(root, role, date);
    } catch (e) { toast(e.message); }
  }
}
