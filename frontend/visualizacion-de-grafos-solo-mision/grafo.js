// Grafo de cohesión para misión en Tierra: solo ante una incidencia activa y con nodos seudonimizados.
import { api, card, h } from "../assets/core.js";

export async function renderCohesionGraph(root) {
  let g;
  try { g = await api("/mission/cohesion-graph"); }
  catch (e) { root.append(card("Grafo de cohesión", h("p", { class: "muted" }, e.message))); return; }
  const ns = "http://www.w3.org/2000/svg", size = 320, r = 120, c = size / 2;
  const svg = document.createElementNS(ns, "svg");
  svg.setAttribute("viewBox", `0 0 ${size} ${size}`); svg.setAttribute("width", "320"); svg.setAttribute("height", "320");
  const pos = Object.fromEntries(g.nodes.map((n, i) => {
    const a = (2 * Math.PI * i) / g.nodes.length - Math.PI / 2;
    return [n, [c + r * Math.cos(a), c + r * Math.sin(a)]];
  }));
  for (const e of g.edges) {
    const l = document.createElementNS(ns, "line");
    const [x1, y1] = pos[e.a], [x2, y2] = pos[e.b];
    l.setAttribute("x1", x1); l.setAttribute("y1", y1); l.setAttribute("x2", x2); l.setAttribute("y2", y2);
    l.setAttribute("stroke", "#6ea8ff"); l.setAttribute("stroke-opacity", String(0.25 + 0.75 * e.weight));
    l.setAttribute("stroke-width", String(1 + 6 * e.weight));
    svg.append(l);
  }
  for (const n of g.nodes) {
    const [x, y] = pos[n];
    const dot = document.createElementNS(ns, "circle");
    dot.setAttribute("cx", x); dot.setAttribute("cy", y); dot.setAttribute("r", "14"); dot.setAttribute("fill", "#1a2340");
    dot.setAttribute("stroke", "#94a0bf");
    const t = document.createElementNS(ns, "text");
    t.setAttribute("x", x); t.setAttribute("y", y + 4); t.setAttribute("text-anchor", "middle"); t.textContent = n;
    svg.append(dot, t);
  }
  root.append(card("Grafo de cohesión (incidencia activa)", svg, h("p", { class: "muted small" }, g.notice)));
}
