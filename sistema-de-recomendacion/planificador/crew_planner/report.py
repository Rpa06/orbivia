"""Informe HTML de un plan: cronograma, carga y justificaciones.

Un único fichero autocontenido, sin dependencias externas, que se abre sin
conexión. Dos audiencias:

- `ground` (Tierra): todo, incluidas justificaciones, costes e indicadores sociales.
- `crew` (tripulación): solo el horario y el texto neutro de cada tarea. Lo que no
  debe ver la tripulación no se escribe en el fichero, no se oculta con CSS.
"""

import html
from collections.abc import Mapping
from typing import Any

from .model import parse_clock

Document = dict[str, Any]

GROUND = "ground"
CREW = "crew"
AUDIENCES = (GROUND, CREW)

_HUES = (212, 160, 32, 280, 350, 190, 100, 15, 245, 60)
_LABEL_W = 64
_CHART_W = 860
_ROW_H = 40
_AXIS_H = 26


def _e(value: Any) -> str:
    return html.escape("" if value is None else str(value))


def _h(clock: str) -> float:
    return parse_clock(clock, "hora") / 3600.0


def _entries(plan: Document) -> list[Document]:
    out = []
    for e in plan.get("individual", []):
        out.append({**e, "members": [e["astronaut"]], "collective": False})
    for e in plan.get("collective", []):
        out.append({**e, "collective": True})
    return sorted(out, key=lambda e: (e["start"], e["task"]))


def _crew_ids(plan: Document, raw_input: Mapping[str, Any] | None) -> list[str]:
    if raw_input:
        return [a["id"] for a in raw_input.get("crew", [])]
    workload = plan.get("global", {}).get("workload")
    if workload:
        return list(workload)
    return sorted({m for e in _entries(plan) for m in e["members"]})


def _blocked(raw_input: Mapping[str, Any] | None) -> dict[str, list[tuple[float, float, str]]]:
    """Franjas en que cada astronauta no puede recibir tareas, para dibujarlas."""
    out: dict[str, list[tuple[float, float, str]]] = {}
    for a in (raw_input or {}).get("crew", []):
        spans = []
        work = sorted((_h(s), _h(e)) for s, e in a.get("work", []))
        cursor = 0.0
        for s, e in work:
            if s > cursor:
                spans.append((cursor, s, "fuera de turno"))
            cursor = max(cursor, e)
        if cursor < 24:
            spans.append((cursor, 24.0, "fuera de turno"))
        spans += [(_h(s), _h(e), "no disponible") for s, e in a.get("unavailable", [])]
        out[a["id"]] = spans
    return out


def _range(entries: list[Document], raw_input) -> tuple[int, int]:
    hours = [_h(e["start"]) for e in entries] + [_h(e["end"]) for e in entries]
    for a in (raw_input or {}).get("crew", []):
        hours += [_h(x) for span in a.get("work", []) for x in span]
    if not hours:
        return 7, 18
    return max(0, int(min(hours)) - 1), min(24, int(max(hours) + 0.999) + 1)


def gantt_svg(plan: Document, raw_input: Mapping[str, Any] | None = None) -> str:
    entries = _entries(plan)
    crew = _crew_ids(plan, raw_input)
    blocked = _blocked(raw_input)
    first, last = _range(entries, raw_input)
    span = last - first
    width = _LABEL_W + _CHART_W + 24  # margen para la última hora del eje
    height = _AXIS_H + _ROW_H * len(crew) + 4
    color = {t: k % len(_HUES) for k, t in enumerate(sorted({e["task"] for e in entries}))}

    def x(hour: float) -> float:
        return _LABEL_W + (min(max(hour, first), last) - first) / span * _CHART_W

    parts = [
        f'<svg class="gantt" viewBox="0 0 {width} {height}" role="img" '
        f'aria-label="Cronograma del día por astronauta" preserveAspectRatio="xMinYMin meet">'
    ]
    for hour in range(first, last + 1):
        gx = x(hour)
        parts.append(f'<line class="grid" x1="{gx:.1f}" y1="{_AXIS_H - 6}" x2="{gx:.1f}" y2="{height}"/>')
        parts.append(f'<text class="axis" x="{gx:.1f}" y="{_AXIS_H - 10}" text-anchor="middle">{hour:02d}:00</text>')
    for row, astronaut in enumerate(crew):
        y = _AXIS_H + row * _ROW_H
        parts.append(f'<rect class="row{row % 2}" x="{_LABEL_W}" y="{y}" width="{_CHART_W}" height="{_ROW_H}"/>')
        parts.append(f'<text class="who" x="{_LABEL_W - 10}" y="{y + _ROW_H / 2 + 5}" text-anchor="end">{_e(astronaut)}</text>')
        for s, e, label in blocked.get(astronaut, []):
            if e <= first or s >= last:
                continue
            parts.append(
                f'<rect class="blocked" x="{x(s):.1f}" y="{y + 4}" width="{x(e) - x(s):.1f}" '
                f'height="{_ROW_H - 8}"><title>{_e(astronaut)}: {label}</title></rect>'
            )
    for e in entries:
        s, t = _h(e["start"]), _h(e["end"])
        for member in e["members"]:
            if member not in crew:
                continue
            y = _AXIS_H + crew.index(member) * _ROW_H
            bx, bw = x(s), max(x(t) - x(s), 2)
            others = [m for m in e["members"] if m != member]
            tip = f'{e["name"]} · {e["start"]}–{e["end"]}' + (f' · con {", ".join(others)}' if others else "")
            cls = f'task c{color[e["task"]]}' + (" team" if e["collective"] else "")
            parts.append(
                f'<g class="{cls}"><rect x="{bx + 1:.1f}" y="{y + 6}" width="{bw - 2:.1f}" height="{_ROW_H - 12}" rx="5"/>'
                f'<title>{_e(tip)}</title>'
            )
            if bw > 34:
                label = e["task"] if bw > 9 * len(e["task"]) else e["task"][:max(3, int(bw / 9))] + "…"
                parts.append(f'<text x="{bx + 7:.1f}" y="{y + _ROW_H / 2 + 4}">{_e(label)}</text>')
            parts.append("</g>")
    parts.append("</svg>")
    return "".join(parts)


def _legend(plan: Document) -> str:
    entries = _entries(plan)
    color = {t: k % len(_HUES) for k, t in enumerate(sorted({e["task"] for e in entries}))}
    items = []
    for e in sorted(entries, key=lambda e: e["start"]):
        kind = "equipo" if e["collective"] else "individual"
        items.append(
            f'<li><span class="swatch c{color[e["task"]]}"></span><b>{_e(e["task"])}</b> '
            f'{_e(e["name"])} <span class="muted">· {kind} · {_e(e["start"])}–{_e(e["end"])}</span></li>'
        )
    items.append('<li><span class="swatch blocked"></span>No disponible o fuera de turno</li>')
    return f'<ul class="legend">{"".join(items)}</ul>'


def _workload(plan: Document) -> str:
    workload = plan["global"]["workload"]
    top = max([max(w["load"], w["target_load"]) for w in workload.values()] + [0.01])
    rows = []
    for a, w in workload.items():
        load = w["load"] / top * 100
        target = w["target_load"] / top * 100
        rows.append(
            f'<div class="bar-row"><span class="who">{_e(a)}</span>'
            f'<div class="bar"><div class="fill" style="width:{load:.1f}%"></div>'
            f'<div class="target" style="left:{target:.1f}%" title="Carga objetivo"></div></div>'
            f'<span class="num">{w["load"]:.2f} <span class="muted">/ {w["target_load"]:.2f}</span></span>'
            f'<span class="muted small">{w["hours"]:.2f} h · capacidad {w["capacity"]:.0%}'
            + (f' · {w["demanding"]} exigente{"s" if w["demanding"] != 1 else ""}' if w["demanding"] else "")
            + "</span></div>"
        )
    return (
        '<p class="muted small">Barra: carga asignada (horas ponderadas por intensidad). '
        'Marca: carga objetivo según disponibilidad y capacidad.</p>' + "".join(rows)
    )


def _card(e: Document) -> str:
    who = " + ".join(e["members"])
    chips = []
    if e.get("mandatory") is False:
        chips.append('<span class="chip">aplazable</span>')
    if e["collective"]:
        chips.append('<span class="chip">equipo</span>')
        if e.get("low_load"):
            chips.append('<span class="chip">baja carga</span>')
        if e.get("inclusion"):
            chips.append(f'<span class="chip accent">inclusión: {_e(", ".join(e["inclusion"]))}</span>')
    adequacy = e.get("operational_adequacy") if e["collective"] else e.get("adequacy")
    facts = [f'<div><span class="muted">Adecuación</span> <b>{adequacy:.0%}</b></div>']
    if e["collective"]:
        inter = e.get("interaction") or {}
        if inter.get("used") and inter.get("score") is not None:
            facts.append(
                f'<div><span class="muted">Interacción observada</span> <b>{inter["score"]:.2f}</b> '
                f'<span class="muted">(mediana {inter["crew_median"]:.2f})</span></div>'
            )
        facts.append(f'<div><span class="muted">Coste operativo</span> <b>{e["cost"]["operational"]:.3f}</b></div>')
    else:
        facts.append(f'<div><span class="muted">Coste</span> <b>{e["cost"]["total"]:.3f}</b></div>')
        if e.get("unknown_parameters"):
            facts.append(f'<div><span class="muted">Desconocidos</span> {_e(", ".join(e["unknown_parameters"]))}</div>')
    alternatives = "".join(
        f'<li>{_e(" + ".join(a["members"]))} <span class="muted">({a["delta"]:+.3f})</span></li>'
        for a in e.get("alternatives", [])
    )
    discarded = "".join(
        f'<li><b>{_e(d["astronaut"])}</b>: {_e("; ".join(d["reasons"]))}</li>' for d in e.get("not_eligible", [])
    )
    details = ""
    if alternatives or discarded:
        details = (
            "<details><summary>Alternativas y descartes</summary>"
            + (f"<p class='muted small'>Alternativas (diferencia de coste)</p><ul>{alternatives}</ul>" if alternatives else "")
            + (f"<p class='muted small'>No elegibles</p><ul>{discarded}</ul>" if discarded else "")
            + "</details>"
        )
    return (
        f'<article class="card"><header><h3>{_e(e["name"])}</h3>'
        f'<span class="muted">{_e(e["start"])}–{_e(e["end"])} · {_e(who)}</span></header>'
        f'<div class="chips">{"".join(chips)}</div><div class="facts">{"".join(facts)}</div>'
        f'<p>{_e(e["justification"])}</p>{details}</article>'
    )


def _costs(plan: Document) -> str:
    names = {
        "state": "Estado frente a requisitos", "repetition": "Repetición", "uncertainty": "Incertidumbre",
        "compatibility": "Compatibilidad", "equity": "Equidad", "integration": "Inclusión", "total": "Total",
    }
    rows = "".join(
        f'<tr{" class=total" if k == "total" else ""}><td>{names.get(k, k)}</td><td class="num">{v:+.3f}</td></tr>'
        for k, v in plan["global"]["costs"].items()
    )
    stages = ", ".join(f'{_e(s["stage"])} {_e(s["status"]).lower()}' for s in plan["global"]["solver"])
    return f'<table class="costs">{rows}</table><p class="muted small">Etapas: {stages}</p>'


def _status(plan: Document) -> str:
    g = plan.get("global", {})
    items = []
    if plan["status"] == "ok":
        items.append(f'<div class="kpi"><b>{len(g["covered"])}</b><span>tareas cubiertas</span></div>')
        items.append(f'<div class="kpi"><b>{len(g["pending"])}</b><span>pendientes</span></div>')
        items.append(f'<div class="kpi"><b>{len(g["unassigned"])}</b><span>sin asignación</span></div>')
        social = g["social"]
        items.append(
            f'<div class="kpi"><b>{"sí" if social["used"] else "no"}</b><span>grafo social'
            + (f' (día {social["graph_day"]})' if social["used"] else "") + "</span></div>"
        )
    return f'<div class="kpis">{"".join(items)}</div>'


def _conflicts(plan: Document) -> str:
    out = []
    for c in plan.get("conflicts", []):
        suggestions = "".join(f"<li>{_e(s)}</li>" for s in c.get("suggestions", []))
        discarded = "".join(
            f'<li><b>{_e(d["astronaut"])}</b>: {_e("; ".join(d["reasons"]))}</li>' for d in c.get("discarded", [])
        )
        out.append(
            f'<article class="card conflict"><h3>{_e(c["summary"])}</h3>'
            + (f"<p class='muted small'>Descartes</p><ul>{discarded}</ul>" if discarded else "")
            + f"<p class='muted small'>Decisiones posibles (las toma una persona)</p><ul>{suggestions}</ul></article>"
        )
    return "".join(out)


def render_html(plan: Document, raw_input: Mapping[str, Any] | None = None, audience: str = GROUND) -> str:
    if audience not in AUDIENCES:
        raise ValueError(f"audience debe ser una de {AUDIENCES}")
    ok = plan["status"] == "ok"
    title = f"Plan del día {plan['day']}"
    body = [f'<header class="top"><h1>{_e(title)}</h1>']
    if audience == CREW:
        body.append('<p class="muted">Propuesta de reparto. La decisión final la toma la tripulación con el centro de control.</p></header>')
        if ok:
            body.append(f'<section><h2>Horario</h2>{gantt_svg(plan, raw_input)}{_legend(plan)}</section>')
            items = "".join(f"<li>{_e(e['crew_text'])}</li>" for e in _entries(plan))
            body.append(f'<section><h2>Tareas</h2><ul class="plain">{items}</ul></section>')
        else:
            body.append('<section><p>No hay una propuesta para este día. El centro de control está revisando el reparto.</p></section>')
    else:
        badge = {"ok": "Plan generado", "infeasible": "Sin solución factible", "timeout": "Sin respuesta a tiempo"}
        body.append(
            f'<p><span class="status {plan["status"]}">{badge.get(plan["status"], plan["status"])}</span> '
            f'<span class="muted">configuración {_e(plan.get("config_version"))} · uso exclusivo de personal autorizado</span></p>'
            f'{_status(plan)}</header>'
        )
        if ok:
            g = plan["global"]
            body.append(f'<section><h2>Cronograma</h2>{gantt_svg(plan, raw_input)}{_legend(plan)}</section>')
            body.append(
                '<div class="two"><section><h2>Carga de trabajo</h2>' + _workload(plan) + "</section>"
                '<section><h2>Coste de la solución</h2>' + _costs(plan) + "</section></div>"
            )
            if g["pending"]:
                pending = "".join(f'<li><b>{_e(p["task"])}</b>: {_e(p["reason"])}</li>' for p in g["pending"])
                body.append(f'<section><h2>Pendientes</h2><ul>{pending}</ul></section>')
            body.append('<section><h2>Asignaciones</h2><div class="cards">'
                        + "".join(_card(e) for e in _entries(plan)) + "</div></section>")
            notes = list(g["warnings"])
            unknown = {a: p for a, p in g["uncertainty"]["unknown_parameters"].items() if p}
            if unknown:
                notes += [f"{a}: datos desconocidos ({', '.join(p)})" for a, p in unknown.items()]
            if notes:
                body.append('<section><h2>Avisos y datos</h2><ul>'
                            + "".join(f"<li>{_e(n)}</li>" for n in notes) + "</ul></section>")
        else:
            body.append(f'<section><h2>Conflictos</h2>{_conflicts(plan)}'
                        '<p class="muted small">No se ha relajado ninguna restricción.</p></section>')
    body.append('<footer class="muted small">ORBIVIA · Planificador de tareas · Herramienta de apoyo: propone, no decide.</footer>')
    return _PAGE.format(title=_e(title), css=_css(), body="".join(body))


def _css() -> str:
    swatches = "".join(
        f".c{k}{{--h:{h}}}" for k, h in enumerate(_HUES)
    )
    return _CSS + swatches


_CSS = """
:root{--bg:#f7f7f5;--surface:#fff;--ink:#16171a;--muted:#5d6068;--line:#e3e3df;--row:#fafaf8;
--accent:#2d6cdf;--ok:#1f7a4d;--bad:#b3261e;--warn:#a15c00;--task-l:88%;--task-s:70%;--task-ink:#111;--edge-l:38%}
@media (prefers-color-scheme:dark){:root{--bg:#121316;--surface:#1b1d21;--ink:#eceef2;--muted:#9aa0aa;
--line:#2c2f35;--row:#17191c;--accent:#7aa7ff;--ok:#5fcf98;--bad:#ff8a80;--warn:#ffb74d;--task-l:34%;--task-s:45%;
--task-ink:#f4f5f7;--edge-l:68%}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);
font:15px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
main{max-width:1100px;margin:0 auto;padding:24px 16px 48px}
h1{font-size:26px;margin:0 0 4px}h2{font-size:17px;margin:0 0 12px}h3{font-size:15px;margin:0}
section{background:var(--surface);border:1px solid var(--line);border-radius:12px;padding:16px;margin:16px 0}
.top{margin-bottom:8px}.muted{color:var(--muted)}.small{font-size:13px}
.status{display:inline-block;padding:2px 10px;border-radius:999px;font-weight:600;font-size:13px;border:1px solid}
.status.ok{color:var(--ok)}.status.infeasible,.status.timeout{color:var(--bad)}
.kpis{display:flex;gap:12px;flex-wrap:wrap;margin-top:12px}
.kpi{background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:8px 14px;min-width:120px}
.kpi b{display:block;font-size:20px}.kpi span{color:var(--muted);font-size:13px}
.gantt{width:100%;height:auto;display:block}
.gantt .grid{stroke:var(--line)}.gantt .axis{fill:var(--muted);font-size:12px}
.gantt .who{fill:var(--ink);font-size:14px;font-weight:600}
.gantt .row0{fill:var(--surface)}.gantt .row1{fill:var(--row)}
.gantt .blocked{fill:var(--line);opacity:.7}
.task rect{fill:hsl(var(--h) var(--task-s) var(--task-l));stroke:hsl(var(--h) 60% var(--edge-l));stroke-width:1.5}
.task.team rect{stroke-dasharray:5 3}
.task text{fill:var(--task-ink);font-size:12px;font-weight:600;pointer-events:none}
.legend{list-style:none;padding:0;margin:12px 0 0;display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:4px 16px;font-size:13px}
.swatch{display:inline-block;width:12px;height:12px;border-radius:3px;margin-right:6px;vertical-align:-1px;
background:hsl(var(--h) var(--task-s) var(--task-l));border:1.5px solid hsl(var(--h) 60% var(--edge-l))}
.swatch.blocked{background:var(--line);border-color:var(--line)}
.two{display:grid;grid-template-columns:3fr 2fr;gap:16px}.two section{margin:0}
@media (max-width:760px){.two{grid-template-columns:1fr}}
.bar-row{display:grid;grid-template-columns:36px 1fr 96px;gap:4px 10px;align-items:center;margin:8px 0}
.bar-row .small{grid-column:2/4}
.bar{position:relative;height:14px;background:var(--row);border:1px solid var(--line);border-radius:7px}
.bar .fill{height:100%;background:var(--accent);border-radius:7px;opacity:.8}
.bar .target{position:absolute;top:-4px;bottom:-4px;width:2px;background:var(--ink)}
.num{font-variant-numeric:tabular-nums;text-align:right}
table.costs{width:100%;border-collapse:collapse}table.costs td{padding:5px 0;border-bottom:1px solid var(--line)}
table.costs tr.total td{font-weight:700;border-bottom:0}
.cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:12px}
.card{border:1px solid var(--line);border-radius:10px;padding:12px 14px;background:var(--surface)}
.card header{display:flex;flex-direction:column;gap:2px;margin-bottom:6px}
.card p{margin:8px 0;font-size:14px}.card ul{margin:4px 0 8px;padding-left:18px;font-size:13px}
.card.conflict{border-color:var(--bad)}
.facts{display:flex;flex-wrap:wrap;gap:4px 16px;font-size:13px}
.chips{display:flex;gap:6px;flex-wrap:wrap;margin:4px 0}
.chip{font-size:12px;padding:1px 8px;border-radius:999px;border:1px solid var(--line);color:var(--muted)}
.chip.accent{color:var(--accent);border-color:var(--accent)}
details summary{cursor:pointer;color:var(--accent);font-size:13px}
ul.plain{padding-left:18px}footer{margin-top:24px;text-align:center}
"""

_PAGE = """<!doctype html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title><style>{css}</style></head>
<body><main>{body}</main></body></html>
"""
