// Check-in diario (5 preguntas 1-5), pregunta doble semanal y PVT-B de 3 minutos.
// El astronauta no ve ningún resultado hasta completar el check-in y el test.
import { api, card, h, REFERENCES } from "../assets/core.js";

export async function renderCheckin(root) {
  const info = await api("/checkin/today");
  if (info.checkin_done && info.pvt_done) {
    root.append(card("Check-in de hoy", h("p", {}, "Ya has completado el check-in y el PVT-B de hoy. Gracias."),
      h("p", { class: "muted small" }, `Día de misión ${info.mission_day}`)));
    return;
  }
  if (info.checkin_done) { renderPvt(root); return; }

  const answers = {};
  let weekly = null, known = false;
  const form = card("Check-in diario", h("p", { class: "muted small" }, "Cinco preguntas, siempre a la misma hora. Responde de 1 a 5."));
  for (const q of info.questions) {
    const scale = h("div", { class: "scale", role: "radiogroup", "aria-label": q.text });
    for (let v = 1; v <= 5; v++) {
      const b = h("button", { type: "button", onclick: () => {
        answers[q.id] = v; [...scale.children].forEach((c) => c.classList.toggle("on", c === b));
      } }, String(v));
      scale.append(b);
    }
    form.append(h("div", {}, h("label", {}, `${q.text} (${q.scale})`), scale));
  }
  if (info.weekly_question_due) {
    const scale = h("div", { class: "scale" });
    for (let v = 1; v <= 5; v++) {
      const b = h("button", { type: "button", onclick: () => {
        weekly = v; [...scale.children].forEach((c) => c.classList.toggle("on", c === b));
      } }, String(v));
      scale.append(b);
    }
    form.append(h("div", {}, h("label", {}, `Pregunta semanal: ${info.weekly_question}`), scale,
      h("p", { class: "muted small" }, "Tu respuesta nunca se muestra al resto de la tripulación.")));
  }
  const knownBox = h("input", { type: "checkbox", id: "known", onchange: (e) => { known = e.target.checked; } });
  form.append(h("div", { class: "row" }, knownBox,
    h("label", { for: "known", style: "margin:0" }, "Hoy hay un motivo conocido (no hace falta decir cuál)")));
  const msg = h("p", { class: "error" });
  form.append(h("button", { onclick: async () => {
    msg.textContent = "";
    if (Object.keys(answers).length < 5) { msg.textContent = "Responde las cinco preguntas."; return; }
    try {
      await api("/checkin", { method: "POST", body: { answers, known_reason: known, predicted_team_mean: weekly } });
      root.innerHTML = ""; renderPvt(root);
    } catch (e) { msg.textContent = e.message; }
  } }, "Enviar y empezar el PVT-B"), msg);
  root.append(form);
}

export function renderPvt(root) {
  const fast = new URLSearchParams(location.search).has("pvt30");
  const duration = fast ? 30 : 180;
  const rts = []; let falseStarts = 0;
  const area = h("div", { class: "pvt-area", tabindex: "0" }, "Pulsa aquí o la barra espaciadora para empezar");
  const bar = h("div", { class: "bar" }, h("span", { style: "width:0%" }));
  const wrap = card("PVT-B", h("p", { class: "muted small" },
    `Cuando aparezca el contador, pulsa lo antes posible. Dura ${duration / 60 < 1 ? duration + " s" : "3 minutos"}.`),
    area, bar, h("p", { class: "ref" }, REFERENCES.pvt),
    fast ? h("p", { class: "pill warn" }, "Modo demo de 30 s (?pvt30)") : null);
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
    area.textContent = "Enviando…";
    try {
      const r = await api("/pvt", { method: "POST", body: { reaction_times_ms: rts, false_starts: falseStarts,
        duration_s: (performance.now() - started) / 1000 } });
      area.textContent = "";
      wrap.append(h("div", { class: "notice" }, `Test completado: ${r.trials} respuestas, tiempo medio ${Math.round(r.mean_rt_ms)} ms, ${r.lapses} lapsos.`,
        h("p", { class: "muted small" }, r.note)));
    } catch (e) { area.textContent = e.message; }
  };
  const press = () => {
    if (!running) {
      running = true; started = performance.now(); schedule();
      const tick = setInterval(() => {
        const p = Math.min(1, (performance.now() - started) / (duration * 1000));
        bar.firstChild.style.width = `${p * 100}%`;
        if (p >= 1) { clearInterval(tick); finish(); }
      }, 200);
      return;
    }
    if (stimAt == null) { falseStarts++; return; }
    rts.push(performance.now() - stimAt); stimAt = null; clearInterval(counter); schedule();
  };
  area.addEventListener("pointerdown", press);
  area.addEventListener("keydown", (e) => { if (e.code === "Space") { e.preventDefault(); press(); } });
}
