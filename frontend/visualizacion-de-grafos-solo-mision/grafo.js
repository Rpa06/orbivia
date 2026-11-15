// Grafo de cohesión para misión en Tierra: solo ante una incidencia activa, con nodos seudonimizados
// por día. Es vigilancia: nunca se usa para repartir, agrupar ni separar a la tripulación.
import { api, barRow, card, h } from "../assets/core.js";

const lerp = (a, b, t) => a + (b - a) * t;
// rojo (débil) -> ámbar -> cian (fuerte)
function edgeColor(w) {
  const stops = [[248, 113, 113], [251, 191, 36], [76, 201, 240]];
  const t = Math.max(0, Math.min(1, w)) * 2;
  const [a, b] = t < 1 ? [stops[0], stops[1]] : [stops[1], stops[2]];
  const k = t < 1 ? t : t - 1;
  return `rgb(${a.map((v, i) => Math.round(lerp(v, b[i], k))).join(",")})`;
}

export async function renderCohesionGraph(root) {
  let g;
  try { g = await api("/mission/cohesion-graph"); }
  catch (e) {
    root.append(card(["Grafo de cohesión", "acceso restringido"],
      h("div", { class: "empty-ok" }, h("span", { style: "font-size:1.4rem" }, "🔒"),
        h("div", {}, h("strong", {}, "No disponible"), h("div", { class: "hint" }, e.message)))));
    return;
  }
  const strength = Object.fromEntries(g.nodes.map((n) => [n, 0]));
  g.edges.forEach((e) => { strength[e.a] += e.weight; strength[e.b] += e.weight; });
  const maxS = Math.max(...Object.values(strength), 0.01);
  const weakest = g.nodes.slice().sort((a, b) => strength[a] - strength[b])[0];

  const W = 520, H = 440, cx = W / 2, cy = H / 2 + 6, R = 150;
  const pos = Object.fromEntries(g.nodes.map((n, i) => {
    const a = (2 * Math.PI * i) / g.nodes.length - Math.PI / 2;
    return [n, [cx + R * Math.cos(a), cy + R * Math.sin(a)]];
  }));
  let s = `<defs><radialGradient id="halo"><stop offset="0%" stop-color="var(--warn)" stop-opacity=".45"/><stop offset="100%" stop-color="var(--warn)" stop-opacity="0"/></radialGradient></defs>`;
  s += `<circle cx="${cx}" cy="${cy}" r="${R}" fill="none" stroke="var(--border)" stroke-dasharray="3 6"/>`;
  let through = 0;
  for (const e of g.edges.slice().sort((a, b) => a.weight - b.weight)) {
    const [x1, y1] = pos[e.a], [x2, y2] = pos[e.b];
    const mx = (x1 + x2) / 2, my = (y1 + y2) / 2;
    let qx, qy;
    if (Math.hypot(mx - cx, my - cy) < 25) {
      // Arista que cruza por el centro: se curva hacia un lado (alternando) para no solaparse
      const len = Math.hypot(x2 - x1, y2 - y1) || 1, sign = through++ % 2 ? 1 : -1;
      qx = mx + sign * 70 * -(y2 - y1) / len; qy = my + sign * 70 * (x2 - x1) / len;
    } else {
      // Arista entre vecinos: curva suave hacia el centro
      qx = lerp(mx, cx, 0.25); qy = lerp(my, cy, 0.25);
    }
    const col = edgeColor(e.weight);
    s += `<path d="M${x1},${y1} Q${qx},${qy} ${x2},${y2}" fill="none" stroke="${col}" stroke-opacity="${0.35 + 0.65 * e.weight}" stroke-width="${2 + 10 * e.weight}" stroke-linecap="round"><title>${e.a}–${e.b}: ${e.weight.toFixed(2)}</title></path>`;
    const lx = lerp(mx, qx, 0.5), ly = lerp(my, qy, 0.5);
    s += `<rect x="${lx - 17}" y="${ly - 10}" width="34" height="18" rx="9" fill="var(--surface)" stroke="${col}" stroke-opacity=".7"/>`;
    s += `<text x="${lx}" y="${ly + 3.5}" text-anchor="middle" font-size="11" fill="var(--text)">${e.weight.toFixed(2)}</text>`;
  }
  for (const n of g.nodes) {
    const [x, y] = pos[n];
    const r = 18 + 12 * (strength[n] / maxS);
    if (n === weakest) s += `<circle cx="${x}" cy="${y}" r="${r + 22}" fill="url(#halo)"/>`;
    s += `<circle cx="${x}" cy="${y}" r="${r}" fill="var(--surface2)" stroke="${n === weakest ? "var(--warn)" : "var(--primary)"}" stroke-width="2.5"/>`;
    s += `<text x="${x}" y="${y + 4}" text-anchor="middle" font-size="12" font-weight="700" fill="var(--text)">${n}</text>`;
  }
  const graph = h("div", { html: `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Grafo de cohesión seudonimizado">${s}</svg>` }).firstChild;

  const mean = g.edges.length ? g.edges.reduce((t, e) => t + e.weight, 0) / g.edges.length : 0;
  const weakEdge = g.edges.slice().sort((a, b) => a.weight - b.weight)[0];
  const side = h("div", {},
    h("div", { class: "grid", style: "grid-template-columns:1fr 1fr;gap:12px;margin-bottom:14px" },
      h("div", { class: "card kpi" }, h("div", { class: "label" }, "Cohesión media"), h("div", { class: "value" }, mean.toFixed(2)),
        h("div", { class: `note ${mean < 0.35 ? "warn" : "ok"}` }, mean < 0.35 ? "Baja" : "Adecuada")),
      h("div", { class: "card kpi" }, h("div", { class: "label" }, "Vínculo más débil"),
        h("div", { class: "value", style: "font-size:1.1rem" }, weakEdge ? `${weakEdge.a}–${weakEdge.b}` : "—"),
        h("div", { class: "note warn" }, weakEdge ? weakEdge.weight.toFixed(2) : ""))),
    h("h3", {}, "Integración de cada nodo"),
    ...g.nodes.slice().sort((a, b) => strength[b] - strength[a]).map((n) =>
      barRow(n, strength[n] / maxS * 100, n === weakest ? "warn" : "info", strength[n].toFixed(2))),
    h("h3", {}, "Intensidad del vínculo"),
    h("div", { class: "scale-bar" }),
    h("div", { class: "ends" }, h("span", {}, "débil"), h("span", {}, "fuerte")),
    h("p", { class: "hint", style: "margin-top:10px" }, "Grosor y color de cada arista: tiempo de ocio compartido. Tamaño del nodo: integración total. Halo ámbar: nodo menos integrado."));

  root.append(card(["Grafo de cohesión", `incidencia social activa · ${g.date}`],
    h("div", { class: "graph-wrap" }, graph, side),
    h("p", { class: "ref" }, g.notice)));
}
