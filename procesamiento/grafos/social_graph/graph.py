"""Grafo diario, layout comparable entre días y exportación para Tierra.

El dibujo es una ayuda visual. La distancia entre nodos NO es una métrica: el
layout de fuerzas tiene mínimos locales y la posición de un nodo aislado es
arbitraria. Solo son interpretables el grosor de las aristas y los valores.
"""

import json
import math
import os
from pathlib import Path
from typing import Any

import networkx as nx
import numpy as np

Document = dict[str, Any]
Positions = dict[str, list[float]]

DISCLAIMER = (
    "Indicador estimativo de convivencia por proximidad en tiempo de ocio; no es un "
    "diagnóstico. La distancia entre nodos no es una métrica: solo el grosor de las "
    "aristas y los valores numéricos son interpretables."
)

STATUS_LABELS = {
    "normal": "normal",
    "follow_up": "seguimiento",
    "review": "revisión",
    "warming_up": "calentando",
    "no_data": "sin datos",
    "not_evaluable": "no evaluable",
}

LAYOUTS = ("spring", "circular")
_SPRING_K = 0.8
# Separación mínima entre nodos en el dibujo (coordenadas en [-1, 1]) y fracción
# del desplazamiento diario que se aplica: amortigua el baile entre días
_MIN_DISTANCE = 0.5
_DAMPING = 0.5


def build_graph(doc: Document) -> nx.Graph:
    """Grafo ponderado no dirigido del día. Incluye todos los nodos, también los aislados."""
    crew = doc["crew"]
    graph = nx.Graph(day=doc["day"])
    for i, astronaut in enumerate(crew):
        graph.add_node(
            astronaut,
            strength=doc["strength"][i],
            strength_norm=doc["strength_norm"][i],
            accompanied=doc["accompanied"][i],
            data_status=doc["node_status"][i],
        )
    for i in range(len(crew)):
        for j in range(i + 1, len(crew)):
            weight = doc["weights"][i][j]
            if doc["evaluable"][i][j] and weight > 0:
                graph.add_edge(crew[i], crew[j], weight=weight)
    return graph


def _circular(nodes: list[str]) -> Positions:
    n = len(nodes)
    return {
        node: [math.cos(2 * math.pi * k / n), math.sin(2 * math.pi * k / n)]
        for k, node in enumerate(nodes)
    }


def compute_layout(
    graph: nx.Graph, previous: Positions | None = None, seed: int = 42, mode: str = "spring"
) -> Positions:
    """Posiciones de los nodos.

    Con `spring`, el peso de la arista actúa como atracción. Se parte de las
    posiciones del día anterior (o de un círculo fijo el primer día) con semilla
    fija, para que los dibujos de días consecutivos sean comparables.
    """
    if mode not in LAYOUTS:
        raise ValueError(f"Layout desconocido: {mode}. Opciones: {LAYOUTS}")
    nodes = list(graph.nodes)
    initial = _circular(nodes)
    if mode == "circular":
        return initial
    if previous:
        initial.update({n: list(previous[n]) for n in nodes if n in previous})
    positions = nx.spring_layout(
        graph,
        pos=initial,
        weight="weight",
        k=_SPRING_K,
        iterations=30 if previous else 60,
        seed=seed,
    )
    points = np.array([positions[node] for node in nodes], dtype=float)
    if previous and all(node in previous for node in nodes):
        before = np.array([previous[node] for node in nodes], dtype=float)
        points = before + _DAMPING * (points - before)
    points = _separate(points)
    return {node: [round(float(x), 4), round(float(y), 4)] for node, (x, y) in zip(nodes, points)}


def _separate(points: np.ndarray, min_distance: float = _MIN_DISTANCE, rounds: int = 60) -> np.ndarray:
    """Centra, ajusta al círculo unidad y aparta los nodos que se solapan.

    Es solo legibilidad: refuerza que la distancia en el dibujo no es una métrica.
    """
    points = points.copy()
    n = len(points)
    for _ in range(rounds):
        points -= points.mean(axis=0)
        radius = np.linalg.norm(points, axis=1).max()
        if radius > 0:
            points /= radius
        moved = False
        for i in range(n):
            for j in range(i + 1, n):
                delta = points[j] - points[i]
                distance = float(np.linalg.norm(delta))
                if distance >= min_distance - 1e-6:
                    continue
                if distance < 1e-9:  # coincidentes: dirección fija según el índice
                    angle = 2 * math.pi * (i * n + j) / (n * n)
                    direction = np.array([math.cos(angle), math.sin(angle)])
                else:
                    direction = delta / distance
                push = (min_distance - distance) / 2
                points[i] -= direction * push
                points[j] += direction * push
                moved = True
        if not moved:
            break
    return points


def _mean(values: list[float | None]) -> float | None:
    defined = [v for v in values if v is not None]
    return sum(defined) / len(defined) if defined else None


def export_graph(doc: Document, positions: Positions) -> Document:
    """Documento JSON para el panel de Tierra: nodos, aristas, posiciones y métricas."""
    crew = doc["crew"]
    n = len(crew)
    isolation = doc.get("isolation") or {}
    assessments = isolation.get("astronauts", {})
    structure = isolation.get("structure") or {}
    communities = structure.get("communities", []) if structure.get("clear") else []
    community_of = {a: k for k, members in enumerate(communities) for a in members}

    nodes = []
    for i, astronaut in enumerate(crew):
        assessment = assessments.get(astronaut, {})
        alignment = _mean([doc["alignment"][i][j] for j in range(n) if j != i])
        nodes.append({
            "id": astronaut,
            "x": positions[astronaut][0],
            "y": positions[astronaut][1],
            "strength": doc["strength"][i],
            "strength_norm": doc["strength_norm"][i],
            "accompanied": doc["accompanied"][i],
            "leisure_h": doc["leisure_s"][i] / 3600,
            "data_status": doc["node_status"][i],
            "status": assessment.get("status"),
            "signals": assessment.get("signals", []),
            "score": assessment.get("score"),
            # Sobre el grafo suavizado de varios días; None si no hay grupos claros
            "community": community_of.get(astronaut),
            "betweenness": structure.get("betweenness", {}).get(astronaut),
            "bridge": astronaut in structure.get("bridges", []),
            # Desajuste de horarios: indicador aparte, no entra en W
            "schedule_mismatch": None if alignment is None else 1 - alignment,
        })

    edges, masked = [], []
    for i in range(n):
        for j in range(i + 1, n):
            pair = {"source": crew[i], "target": crew[j], "status": doc["status"][i][j]}
            if not doc["evaluable"][i][j]:
                masked.append(pair)
                continue
            edges.append({
                **pair,
                "weight": doc["weights"][i][j],
                "r_overlap": doc["r_overlap"][i][j],
                "r_leisure": doc["r_leisure"][i][j],
                "alignment": doc["alignment"][i][j],
                "interaction_min": doc["interaction_s"][i][j] / 60,
                "coverage": doc["coverage"][i][j],
            })

    crew_alignment = _mean([doc["alignment"][i][j] for i in range(n) for j in range(i + 1, n)])
    return {
        "day": doc["day"],
        "params_version": doc.get("params_version"),
        "disclaimer": DISCLAIMER,
        "nodes": nodes,
        "edges": edges,
        "masked_pairs": masked,
        # Propuestas de actividades voluntarias para el día siguiente, a revisar
        "recommendations": doc.get("recommendations"),
        "crew": {
            "drop": isolation.get("crew", {}).get("drop"),
            "score": isolation.get("crew", {}).get("score"),
            "communities": communities,
            "modularity": structure.get("modularity"),
            "schedule_mismatch": None if crew_alignment is None else 1 - crew_alignment,
        },
    }


# --- imagen ---------------------------------------------------------------------

_SURFACE = "#fcfcfb"
_INK = "#0b0b0b"
_INK_SECONDARY = "#52514e"
_MUTED = "#898781"
_HAIRLINE = "#c3c2b7"
# Estado -> (relleno, color de la etiqueta interior). El estado va siempre escrito
# bajo el nodo: el color nunca es la única pista.
_NODE_STYLE = {
    "normal": ("#2a78d6", "#ffffff"),
    "warming_up": ("#9ec5f4", _INK),
    "follow_up": ("#fab219", _INK),
    "review": ("#ec835a", "#ffffff"),
}
_UNKNOWN = {"no_data", "not_evaluable"}
_MAX_EDGE_WIDTH = 9.0


def _node_state(node: Document) -> str:
    if node["data_status"] != "ok":
        return node["data_status"]
    return node["status"] or "normal"


def render_png(export: Document, path: Path) -> None:
    """Dibuja el grafo. Grosor de arista proporcional a W."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D

    nodes = {node["id"]: node for node in export["nodes"]}
    fig, ax = plt.subplots(figsize=(8, 8.6), dpi=120)
    fig.patch.set_facecolor(_SURFACE)
    ax.set_facecolor(_SURFACE)
    ax.set_aspect("equal")
    ax.axis("off")
    ax.set_xlim(-1.3, 1.3)
    ax.set_ylim(-1.4, 1.25)

    def xy(node_id: str) -> tuple[float, float]:
        return nodes[node_id]["x"], nodes[node_id]["y"]

    for pair in export["masked_pairs"]:
        (x0, y0), (x1, y1) = xy(pair["source"]), xy(pair["target"])
        ax.plot([x0, x1], [y0, y1], color=_HAIRLINE, linewidth=1, linestyle=(0, (2, 4)), zorder=1)
    for edge in sorted(export["edges"], key=lambda e: e["weight"]):
        if edge["weight"] <= 0:
            continue
        (x0, y0), (x1, y1) = xy(edge["source"]), xy(edge["target"])
        ax.plot(
            [x0, x1], [y0, y1], color=_INK_SECONDARY, alpha=0.75, solid_capstyle="round",
            linewidth=max(0.6, _MAX_EDGE_WIDTH * edge["weight"]), zorder=2,
        )

    states_seen: list[str] = []
    for node in export["nodes"]:
        state = _node_state(node)
        if state not in states_seen:
            states_seen.append(state)
        x, y = node["x"], node["y"]
        if state in _UNKNOWN:
            ax.scatter([x], [y], s=1150, facecolors=_SURFACE, edgecolors=_MUTED,
                       linewidths=1.6, linestyle="--", zorder=3)
            label_color = _INK_SECONDARY
        else:
            fill, label_color = _NODE_STYLE[state]
            ax.scatter([x], [y], s=1150, c=fill, edgecolors=_SURFACE, linewidths=2.5, zorder=3)
        ax.text(x, y, node["id"], ha="center", va="center", fontsize=12,
                fontweight="bold", color=label_color, zorder=4)
        detail = STATUS_LABELS[state]
        if node["strength_norm"] is not None and state not in _UNKNOWN:
            detail += f" · S={node['strength_norm']:.2f}"
        ax.text(x, y - 0.135, detail, ha="center", va="top", fontsize=8.5,
                color=_INK_SECONDARY, zorder=4,
                bbox={"facecolor": _SURFACE, "edgecolor": "none", "pad": 1.5, "alpha": 0.85})

    handles = []
    for state in states_seen:
        if state in _UNKNOWN:
            handles.append(Line2D([], [], marker="o", linestyle="", markersize=11,
                                  markerfacecolor=_SURFACE, markeredgecolor=_MUTED,
                                  label=STATUS_LABELS[state]))
        else:
            handles.append(Line2D([], [], marker="o", linestyle="", markersize=11,
                                  markerfacecolor=_NODE_STYLE[state][0],
                                  markeredgecolor=_SURFACE, label=STATUS_LABELS[state]))
    for weight in (0.2, 0.6, 1.0):
        handles.append(Line2D([], [], color=_INK_SECONDARY, alpha=0.75,
                              linewidth=_MAX_EDGE_WIDTH * weight, label=f"W = {weight:.1f}"))
    if export["masked_pairs"]:
        handles.append(Line2D([], [], color=_HAIRLINE, linewidth=1, linestyle=(0, (2, 4)),
                              label="pareja sin datos o no evaluable"))
    # La leyenda va fuera del área del grafo para no tapar nodos
    fig.legend(handles=handles, loc="lower left", bbox_to_anchor=(0.04, 0.075), ncol=4,
               frameon=False, fontsize=8.5, labelcolor=_INK_SECONDARY,
               handlelength=2.4, labelspacing=0.9, columnspacing=2.0)

    title = f"Interacción social de la tripulación · día {export['day']}"
    fig.text(0.05, 0.965, title, fontsize=14, fontweight="bold", color=_INK, va="top")
    notes = []
    mismatch = export["crew"].get("schedule_mismatch")
    if mismatch is not None:
        notes.append(f"Desajuste de horarios de la tripulación: {mismatch:.0%}")
    if export["crew"].get("drop"):
        notes.append("Descenso de toda la tripulación")
    if notes:
        fig.text(0.05, 0.93, " · ".join(notes), fontsize=9.5, color=_INK_SECONDARY, va="top")
    fig.text(0.05, 0.035, DISCLAIMER, fontsize=8, color=_MUTED, va="bottom", wrap=True)

    fig.subplots_adjust(left=0.03, right=0.97, top=0.91, bottom=0.17)
    fig.savefig(path, format="png", facecolor=_SURFACE)
    plt.close(fig)


# --- exportador -----------------------------------------------------------------


def _write_atomic(path: Path, write) -> None:
    temporary = path.with_name(path.name + ".tmp")
    write(temporary)
    os.replace(temporary, path)


class GraphExporter:
    """Genera el grafo del día y, si hay directorio de salida, guarda JSON e imagen."""

    def __init__(
        self,
        output_dir: str | Path | None = None,
        layout: str = "spring",
        seed: int = 42,
        render: bool = True,
    ) -> None:
        if layout not in LAYOUTS:
            raise ValueError(f"Layout desconocido: {layout}. Opciones: {LAYOUTS}")
        self.output_dir = Path(output_dir) if output_dir else None
        self.layout = layout
        self.seed = seed
        self.render = render
        if self.output_dir:
            self.output_dir.mkdir(parents=True, exist_ok=True)

    def export(self, doc: Document, previous: Document | None = None) -> Document:
        """`previous` es el grafo exportado del día anterior, si existe."""
        previous_positions = None
        if previous:
            previous_positions = {node["id"]: [node["x"], node["y"]] for node in previous["nodes"]}
        graph = build_graph(doc)
        positions = compute_layout(graph, previous_positions, self.seed, self.layout)
        export = export_graph(doc, positions)
        if self.output_dir:
            self._save(export)
        return export

    def _save(self, export: Document) -> None:
        text = json.dumps(export, allow_nan=False, ensure_ascii=False, indent=1)
        for stem in (f"day_{export['day']:04d}", "latest"):
            _write_atomic(
                self.output_dir / f"{stem}.json",
                lambda p: p.write_text(text, encoding="utf-8"),
            )
            if self.render:
                _write_atomic(self.output_dir / f"{stem}.png", lambda p: render_png(export, p))
