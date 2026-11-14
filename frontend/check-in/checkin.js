// Check-in diario (5 preguntas 1-5), pregunta doble semanal y PVT-B de 3 minutos.
// Lo usa cualquier tripulante, también el comandante. No se muestra ningún resultado
// hasta completar el check-in y el test.
import { REFERENCES, api, avatar, card, crewName, crewRole, h, session, toast } from "../assets/core.js";

const ENDS = {
  sleep: ["Muy mal", "Muy bien"], fatigue: ["Nada", "Agotado"], workload: ["Muy baja", "Muy alta"],
  mood: ["Muy bajo", "Muy bueno"], cohesion: ["Tensión", "Muy unido"],
};

function who() {
  const id = session().astronaut_id;
  return h("div", { class: "who" }, h("span", { html: avatar(id, 72) }),
    h("div", {}, h("h1", { style: "font-size:1.35rem" }, crewName(id)),
      h("p", {}, `${crewRole(id)} · ${new Date().toLocaleDateString("es-ES", { weekday: "long", day: "numeric", month: "long" })}`)));
}

function scaleQuestion(id, text, ends, onPick) {
  const out = h("output", {}, "–");
  const scale = h("div", { class: "scale", role: "radiogroup", "aria-label": text });
  for (let v = 1; v <= 5; v++) {
    const b = h("button", { type: "button", role: "radio", "aria-checked": "false", onclick: () => {
      [...scale.children].forEach((c) => { c.classList.toggle("on", c === b); c.setAttribute("aria-checked", String(c === b)); });
      out.textContent = String(v); onPick(v);
    } }, String(v));
    scale.append(b);
  }
  return h("div", { class: "q" }, h("div", { class: "q-head" }, h("label", {}, text), out), scale,
    h("div", { class: "ends" }, h("span", {}, ends[0]), h("span", {}, ends[1])));
}

export async function renderCheckin(root) {
  const info = await api("/checkin/today");
  root.append(who());
  if (info.checkin_done && info.pvt_done) {
    root.append(h("section", { class: "card done" }, h("div", { class: "tick" }, "✔"), h("h2", { style: "justify-content:center" }, "Check-in completado"),
      h("p", { class: "muted" }, `Ya has hecho el check-in y el PVT-B del día ${info.mission_day} de misión. Gracias.`)));
    return;
  }
  if (info.checkin_done) { renderPvt(root); return; }

  const answers = {};
  let weekly = null, known = false;
  const form = h("form", { novalidate: true });
  form.append(card(["¿Cómo te sientes hoy?", "Cinco preguntas, siempre a la misma hora"],
    h("p", { class: "hint", style: "margin-bottom:6px" }, "Responde de 1 a 5. No hay respuestas correctas."),
    ...info.questions.map((q) => scaleQuestion(q.id, q.text, ENDS[q.id] || ["1", "5"], (v) => { answers[q.id] = v; }))));
  if (info.weekly_question_due) {
    form.append(card(["Pregunta semanal", "convivencia"],
      scaleQuestion("weekly", info.weekly_question, ["1", "5"], (v) => { weekly = v; }),
      h("p", { class: "hint" }, "Tu respuesta nunca se muestra al resto de la tripulación.")));
  }
  const knownBox = h("input", { type: "checkbox", id: "known", onchange: (e) => { known = e.target.checked; } });
  form.append(card("Contexto",
    h("label", { class: "check", for: "known" }, knownBox,
      h("span", {}, "Hoy hay un motivo conocido que puede bajar mis respuestas",
        h("small", {}, "No hace falta decir cuál. Tu nota de disponibilidad no penalizará esas caídas subjetivas.")))));
  const msg = h("p", { class: "error", role: "alert" });
  form.append(msg, h("button", { class: "btn block", type: "submit" }, "Enviar y empezar el PVT-B"));
  form.addEventListener("submit", async (e) => {
    e.preventDefault(); msg.textContent = "";
    if (Object.keys(answers).length < 5) { msg.textContent = "Responde las cinco preguntas."; return; }
    try {
      await api("/checkin", { method: "POST", body: { answers, known_reason: known, predicted_team_mean: weekly } });
      toast("Check-in enviado");
      root.replaceChildren(who()); renderPvt(root);
    } catch (err) { msg.textContent = err.message; }
  });
  root.append(form);
}

export function renderPvt(root) {
  const fast = new URLSearchParams(location.search).has("pvt30");
  const duration = fast ? 30 : 180;
  const rts = []; let falseStarts = 0;
  const area = h("div", { class: "pvt-area", tabindex: "0" }, "Pulsa aquí o la barra espaciadora para empezar");
  const bar = h("div", { class: "progress" }, h("span", { style: "width:0%" }));
  const wrap = card(["PVT-B · test de atención", fast ? "modo demo de 30 s" : "3 minutos"],
    h("p", { class: "hint", style: "margin-bottom:10px" }, "Cuando aparezca el contador, pulsa lo antes posible. Si pulsas antes, cuenta como salida en falso."),
    area, bar, h("p", { class: "ref" }, REFERENCES.pvt));
  root.append(wrap);

  let running = false, stimAt = null, timer = null, counter = null, started = 0;
  const schedule = () => {
    area.classList.remove("stim"); area.textContent = "";
    timer = setTimeout(() => {
      stimAt = performance.now(); area.classList.add("stim");
      const c = h("span", { class: "pvt-counter" }, "0"); area.append(c);
      counter = setInterval(() => { c.textContent = String(Math.round(performance.now() - stimAt)); }, 16);
    }, 1000 + Math.random() * 3000);
  };
  const finish = async () => {
    running = false; clearTimeout(timer); clearInterval(counter);
    area.classList.remove("stim"); area.textContent = "Enviando…";
    try {
      const r = await api("/pvt", { method: "POST", body: { reaction_times_ms: rts, false_starts: falseStarts,
        duration_s: (performance.now() - started) / 1000 } });
      area.replaceChildren(h("div", { style: "text-align:center" }, h("div", { class: "tick ok", style: "font-size:2.2rem" }, "✔"),
        h("div", {}, `${r.trials} respuestas · ${Math.round(r.mean_rt_ms)} ms de media · ${r.lapses} lapsos`),
        h("div", { class: "hint" }, r.note)));
      toast("PVT-B registrado");
    } catch (e) { area.textContent = e.message; }
  };
  const press = () => {
    if (!running) {
      running = true; started = performance.now(); schedule();
      const t = setInterval(() => {
        const p = Math.min(1, (performance.now() - started) / (duration * 1000));
        bar.firstChild.style.width = `${p * 100}%`;
        if (p >= 1) { clearInterval(t); finish(); }
      }, 200);
      return;
    }
    if (stimAt == null) { falseStarts++; return; }
    rts.push(performance.now() - stimAt); stimAt = null; clearInterval(counter); schedule();
  };
  area.addEventListener("pointerdown", press);
  area.addEventListener("keydown", (e) => { if (e.code === "Space") { e.preventDefault(); press(); } });
}
