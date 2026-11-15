"""Informe HTML: contenido por audiencia, escape y casos sin solución."""

import json

import pytest

from crew_planner.__main__ import main
from crew_planner.planner import plan_day
from crew_planner.report import CREW, GROUND, gantt_svg, render_html
from crew_planner.simulation import SCENARIOS
from crew_planner.inputs import from_dict


@pytest.fixture(scope="module")
def isolation(config):
    raw = SCENARIOS["nominal"](10, 42)
    return plan_day(from_dict(raw), config), raw


def test_ground_report_has_everything(isolation):
    plan, raw = isolation
    page = render_html(plan, raw, GROUND)
    assert page.startswith("<!doctype html>")
    assert "<svg" in page and "Carga de trabajo" in page and "Coste de la solución" in page
    for entry in plan["individual"] + plan["collective"]:
        assert entry["name"] in page
    assert "inclusión" not in page and "Interacción observada" not in page
    assert "http://" not in page and "https://" not in page  # autocontenido, sin conexión


def test_crew_report_omits_metrics_and_reasons(isolation):
    plan, raw = isolation
    page = render_html(plan, raw, CREW).lower()
    for entry in plan["individual"] + plan["collective"]:
        assert entry["crew_text"].lower() in page
    # No se oculta: no se escribe
    for word in ("justific", "inclusi", "interacci", "aislamiento", "review", "coste", "capacidad",
                 "desconocid", "no elegibles", "grafo"):
        assert word not in page, word


def test_gantt_draws_every_member_and_blocked_time(isolation):
    plan, raw = isolation
    svg = gantt_svg(plan, raw)
    slots = sum(len(e["members"]) for e in plan["collective"]) + len(plan["individual"])
    assert svg.count('<g class="task') == slots
    assert "no disponible" in svg and "fuera de turno" in svg


def test_report_without_input_still_renders(isolation):
    plan, _ = isolation
    assert "<svg" in render_html(plan, None, GROUND)


def test_infeasible_report(config):
    raw = SCENARIOS["infeasible"](10, 42)
    plan = plan_day(from_dict(raw), config)
    ground = render_html(plan, raw, GROUND)
    assert "Sin solución factible" in ground and "aplazar EVA_PREP" in ground
    crew = render_html(plan, raw, CREW)
    assert "EVA_PREP" not in crew and "No hay una propuesta" in crew


def test_text_is_escaped(isolation):
    plan, raw = isolation
    hostile = json.loads(json.dumps(plan))
    hostile["individual"][0]["name"] = "<script>alert(1)</script>"
    hostile["individual"][0]["justification"] = "<img src=x onerror=alert(1)>"
    page = render_html(hostile, raw, GROUND)
    assert "<script>alert" not in page and "<img src=x" not in page
    assert "&lt;script&gt;" in page


def test_unknown_audience(isolation):
    with pytest.raises(ValueError):
        render_html(isolation[0], None, "public")


def test_cli_writes_both_reports(tmp_path):
    source = tmp_path / "in.json"
    source.write_text(json.dumps(SCENARIOS["nominal"](10, 42)))
    ground, crew = tmp_path / "plan.html", tmp_path / "crew.html"
    assert main([str(source), "--html", str(ground), "--html-crew", str(crew)]) == 0
    assert "Cronograma" in ground.read_text() and "Horario" in crew.read_text()
