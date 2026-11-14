// Registro diario de ejercicio y asistente privado "si pasa X, haré Y" tras dos omisiones seguidas.
import { api, card, h } from "../assets/core.js";

export async function renderExercise(root) {
  const data = await api("/exercise");
  const minutes = h("input", { type: "number", min: "0", max: "240", value: "60" });
  root.append(card("Ejercicio de hoy",
    h("div", { class: "row" }, h("div", { style: "max-width:140px" }, h("label", {}, "Minutos"), minutes),
      h("button", { onclick: async () => { await api("/exercise", { method: "POST", body: { done: true, minutes: Number(minutes.value) } }); reload(); } }, "Hecho"),
      h("button", { class: "ghost", onclick: async () => { await api("/exercise", { method: "POST", body: { done: false } }); reload(); } }, "Hoy no lo he hecho")),
    h("p", { class: "muted small" }, data.history.slice(0, 7).map((d) => `${d.date.slice(5)} ${d.done ? "✓" : "✗"}`).join("  ·  "))));

  if (data.offer_implementation_intention) {
    const x = h("input", { placeholder: "Si pasa… (p. ej. termino la última tarea tarde)" });
    const y = h("input", { placeholder: "haré… (p. ej. 20 minutos de cicloergómetro antes de cenar)" });
    root.append(card("¿Preparamos un plan?",
      h("p", {}, "Llevas dos días sin ejercicio. Un plan concreto ayuda a mantenerlo."),
      h("p", { class: "muted small" }, "Solo tú puedes ver este plan."),
      h("label", {}, "Si pasa X"), x, h("label", {}, "haré Y"), y,
      h("button", { onclick: async () => { await api("/intentions", { method: "POST", body: { if: x.value, then: y.value } }); reload(); } }, "Guardar mi plan")));
  }
  const intentions = await api("/intentions");
  if (intentions.length) {
    root.append(card("Mis planes «si… entonces…»", h("ul", {}, intentions.map((i) => h("li", {},
      `Si ${i.if}, haré ${i.then}. `, h("button", { class: "ghost small", onclick: async () => { await api(`/intentions/${i.id}`, { method: "DELETE" }); reload(); } }, "Borrar"))))));
  }
  function reload() { root.innerHTML = ""; renderExercise(root); }
}
