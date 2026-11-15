// Demo estática: responde a las llamadas de api() con respuestas grabadas de la API real
// (demo-estatica/capturar.py) y simula en el navegador lo que la tripulación escribe.
// Nada sale del navegador. El estado se guarda en sessionStorage y es común a todos los
// roles de la pestaña, para poder elegir un plan como comandante y verlo como médico.

const STATE_KEY = "orbivia.demo.state";
const DATA = new URL("./data/", import.meta.url);
const NOT_AVAILABLE = "No disponible en la demo estática: necesita el backend de Orbivia.";

export const DEMO_USERS = [
  ["commander", "Comandante", "Tripulante A1"],
  ["astro2", "Astronauta", "Tripulante A2"],
  ["astro3", "Astronauta", "Tripulante A3"],
  ["astro4", "Astronauta", "Tripulante A4"],
  ["flight_surgeon", "Médico de a bordo", ""],
  ["earth_medical", "Equipo médico en Tierra", ""],
  ["earth_mission", "Misión en Tierra", ""],
];

const cache = new Map();
async function recording(user) {
  if (!cache.has(user)) {
    cache.set(user, fetch(new URL(`${user}.json`, DATA)).then((r) => {
      if (!r.ok) throw new Error("No se encuentran los datos de la demo");
      return r.json();
    }));
  }
  return cache.get(user);
}

function load() { try { return JSON.parse(sessionStorage.getItem(STATE_KEY) || "{}"); } catch { return {}; } }
function save(s) { try { sessionStorage.setItem(STATE_KEY, JSON.stringify(s)); } catch { /* sin almacenamiento */ } }
export function resetDemo() { try { sessionStorage.removeItem(STATE_KEY); } catch { /* sin almacenamiento */ } }

const clone = (x) => (x == null ? x : JSON.parse(JSON.stringify(x)));
function fail(status, message) { const e = new Error(message); e.status = status; throw e; }

// Las vistas piden fechas reales (new Date()); se trasladan al "hoy" de la grabación.
function shiftDate(date, today) {
  const real = new Date(); real.setHours(12, 0, 0, 0);
  const asked = new Date(`${date}T12:00:00`);
  const offset = Math.round((real - asked) / 86400000);
  const d = new Date(`${today}T12:00:00`); d.setDate(d.getDate() - offset);
  return d.toISOString().slice(0, 10);
}

export async function demoLogin(user) {
  const rec = await recording(user);
  return { ...rec.session, user, demo: true };
}

export async function demoApi(sess, path, { method = "GET", body } = {}) {
  const rec = await recording(sess.user);
  const today = rec.today;
  const me = sess.astronaut_id;
  const st = load();
  const bucket = (k, init) => (st[k] ??= init);
  const recorded = (p) => {
    const r = rec.responses[`GET ${p}`];
    if (!r) fail(404, "Sin datos para esta vista en la demo");
    if (r.status !== 200) fail(r.status, r.body?.detail || "Error");
    return clone(r.body);
  };
  const done = (out) => { save(st); return out; };

  // --- planes y decisiones (comunes a todos los roles) --------------------------------------
  let m = path.match(/^\/plans\/(today|\d{4}-\d{2}-\d{2})(\/decisions?)?$/);
  if (m) {
    const date = m[1] === "today" ? today : shiftDate(m[1], today);
    const decisions = bucket("decisions", {});
    if (m[2] === "/decision" && method === "POST") {
      if (sess.role !== "commander") fail(403, "Solo el comandante decide");
      if (decisions[date]) fail(409, "Ya hay una decisión registrada para ese día");
      const personal = body.private_reason || body.reason_category === "personal";
      decisions[date] = {
        decision: body.decision, option_id: body.option_id ?? null,
        reason_category: body.decision === "selected" ? "none" : personal ? "personal" : body.reason_category,
        reason: body.decision === "selected" || personal ? null : body.reason || null,
        by_role: "commander", at: new Date().toISOString(),
      };
      return done({ status: "recorded" });
    }
    if (m[2] === "/decisions") {
      const out = recorded(`/plans/${date}/decisions`);
      if (decisions[date]) out.decisions.push(decisions[date]);
      return out;
    }
    const out = recorded(`/plans/${date}`);
    if (decisions[date] && !out.decision) out.decision = decisions[date];
    return out;
  }

  // --- check-in, PVT-B y entrevista ------------------------------------------------------------
  const mine = bucket("crew", {});
  const own = (mine[me] ??= {});
  if (path === "/checkin/today") {
    const out = recorded(path);
    if (own.checkin) out.checkin_done = true;
    if (own.pvt) out.pvt_done = true;
    return out;
  }
  if (path === "/checkin" && method === "POST") { own.checkin = body; return done({ status: "recorded" }); }
  if (path === "/pvt" && method === "POST") {
    const rts = body.reaction_times_ms || [];
    const mean = rts.length ? rts.reduce((s, v) => s + v, 0) / rts.length : 0;
    own.pvt = true;
    return done({ trials: rts.length, mean_rt_ms: mean, lapses: rts.filter((v) => v > 500).length,
      note: "Demo: calculado en tu navegador, no se guarda en ningún servidor." });
  }
  if (path.startsWith("/ingest/")) fail(501, "La demo estática no procesa audio ni vídeo: la grabación se ha descartado sin enviarse.");
  if (path === "/ops/trigger-daily-collapse") fail(501, NOT_AVAILABLE);

  // --- ejercicio e intenciones -----------------------------------------------------------------
  if (path === "/exercise") {
    if (method === "POST") { own.exercise = { date: today, done: !!body.done, minutes: body.done ? body.minutes : null }; return done({ status: "recorded" }); }
    const out = recorded(path);
    if (own.exercise) {
      out.history = [own.exercise, ...out.history.filter((d) => d.date !== today)];
      const last2 = out.history.slice(0, 2);
      out.offer_implementation_intention = last2.length === 2 && last2.every((d) => !d.done);
    }
    return out;
  }
  if (path === "/intentions") {
    const list = (own.intentions ??= null) ?? recorded(path);
    if (method === "POST") {
      list.push({ id: Date.now(), if: body.if, then: body.then, created_at: new Date().toISOString() });
      own.intentions = list; return done({ id: list.at(-1).id });
    }
    return list;
  }
  if ((m = path.match(/^\/intentions\/(\d+)$/)) && method === "DELETE") {
    own.intentions = (own.intentions ?? recorded("/intentions")).filter((i) => String(i.id) !== m[1]);
    return done({ status: "deleted" });
  }

  // --- registro privado del ciclo --------------------------------------------------------------
  if (path.startsWith("/cycle/") && path !== "/cycle/shared") {
    const entries = (own.cycle ??= null) ?? recorded("/cycle/entries");
    if (path === "/cycle/entries") {
      if (method === "POST") {
        own.cycle = [...entries.filter((e) => e.date !== today), { date: today, ...body }];
        return done({ status: "recorded" });
      }
      if (method === "DELETE") { own.cycle = []; own.share = null; return done({ status: "deleted" }); }
      return entries;
    }
    if (path === "/cycle/insights") {
      const out = recorded(path);
      if (own.cycle) {
        out.entries = own.cycle.length;
        out.unexpected_bleeding_days = own.cycle.filter((e) => e.unexpected_bleeding).length;
      }
      return out;
    }
    if (path === "/cycle/share") {
      if (method === "POST") {
        own.share = { active: true, expires_at: new Date(Date.now() + body.hours * 3600000).toISOString() };
        return done(own.share);
      }
      if (method === "DELETE") { own.share = null; return done({ active: false, expires_at: null }); }
      return own.share !== undefined ? own.share ?? { active: false, expires_at: null } : recorded(path);
    }
  }
  if (path === "/cycle/shared") {
    const out = recorded(path);
    for (const [id, s] of Object.entries(mine)) {
      if (s.share?.active && s.cycle?.length) out.shared[id] = s.cycle;
      else if (s.share === null || s.cycle?.length === 0) delete out.shared[id];
    }
    return out;
  }

  if (method !== "GET") fail(501, NOT_AVAILABLE);
  return recorded(path);
}
