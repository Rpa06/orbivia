"""Catálogo de tareas por entorno: estructura, validación, traducción y simulación."""

import copy
import math
from dataclasses import replace

import pytest

from crew_planner.catalog import (
    COGNITIVE, ENVIRONMENTS, PHYSICAL, derive_requirements, load_catalog, load_mapping,
    planner_tasks_for_day, select_day, to_planner_tasks, validate_catalog, validate_task,
)
from crew_planner.inputs import from_dict
from crew_planner.planner import plan_day
from crew_planner.simulation import environment_input, simulate
from crew_planner.teams import compatibility_cost, team_compatibility

EXPECTED = {
    "iss": [f"ISS_IND_{k:03d}" for k in range(1, 25)] + [f"ISS_COL_{k:03d}" for k in range(1, 25)],
    "moon": [f"MOON_IND_{k:03d}" for k in range(1, 20)] + [f"MOON_COL_{k:03d}" for k in range(1, 23)],
    "mars": [f"MARS_IND_{k:03d}" for k in range(1, 21)] + [f"MARS_COL_{k:03d}" for k in range(1, 21)],
    "satellite": [f"SAT_IND_{k:03d}" for k in range(1, 17)] + [f"SAT_COL_{k:03d}" for k in range(1, 16)],
}


@pytest.fixture(scope="module")
def catalog():
    return load_catalog()


@pytest.fixture(scope="module")
def mapping():
    return load_mapping()


def broken(catalog, task_id, change):
    """Copia de una tarea con un cambio, y sus errores de validación."""
    task = copy.deepcopy(catalog.task(task_id))
    change(task)
    return validate_task(task, catalog, task["environment"])


# --- estructura e integridad ---------------------------------------------------------


def test_catalog_is_valid(catalog):
    assert validate_catalog(catalog) == []


@pytest.mark.parametrize("env", ENVIRONMENTS)
def test_no_task_lost_and_ids_unchanged(catalog, env):
    assert [t["task_id"] for t in catalog.environment_tasks(env)] == EXPECTED[env]


def test_ids_are_unique_across_environments(catalog):
    ids = [t["task_id"] for t in catalog.all_tasks()]
    assert len(ids) == len(set(ids)) == 160


def test_every_crew_task_has_both_vectors_in_range(catalog):
    for t in catalog.all_tasks():
        if t["crew_role"] == "none":
            assert t["requirements"] is None
            continue
        assert set(t["requirements"]["physical"]) == set(PHYSICAL)
        assert set(t["requirements"]["cognitive"]) == set(COGNITIVE)
        for v in list(t["requirements"]["physical"].values()) + list(t["requirements"]["cognitive"].values()):
            assert isinstance(v, (int, float)) and math.isfinite(v) and 0 <= v <= 1


def test_metadata_and_traceability(catalog):
    for t in catalog.all_tasks():
        meta = t["requirements_metadata"]
        assert meta["evidence_type"] in ("official", "derived", "theoretical")
        assert 0 <= meta["confidence"] <= 1 and meta["justification"]
        if t["source_type"] in ("real", "planned"):
            assert t["nasa_reference"], t["task_id"]
        for ref in t["nasa_reference"]:
            assert catalog.references[ref]["url"] or catalog.references[ref]["verified"] == "not_public"


def test_no_numeric_value_is_presented_as_official(catalog):
    # NASA no publica puntuaciones de exigencia por tarea: todas son teóricas
    assert {t["requirements_metadata"]["evidence_type"] for t in catalog.all_tasks()} == {"theoretical"}
    unverified = [r for r in catalog.references.values() if r["verified"] == "not_public"]
    for ref in unverified:  # citada pero no consultada: no respalda ninguna tarea
        assert all(ref["id"] not in t["nasa_reference"] for t in catalog.all_tasks())


def test_collective_tasks_have_coordination_requirements(catalog):
    for t in catalog.all_tasks():
        if t["type"] == "collective":
            team = t["team_requirements"]
            assert set(team) == {"team_coordination", "communication_requirement", "interdependence",
                                 "leadership_requirement"}
            assert all(0 <= v <= 1 for v in team.values())


def test_satellite_execution_modes(catalog):
    modes = {t["task_id"]: (t["execution_mode"], t["crew_role"]) for t in catalog.environment_tasks("satellite")}
    assert all(m in ("human", "robotic", "remote_controlled") for m, _ in modes.values())
    robotic = [tid for tid, (m, _) in modes.items() if m == "robotic"]
    assert robotic and all(modes[tid][1] == "none" for tid in robotic)
    # La supervisión humana de lo robótico existe como tarea propia
    assert modes["SAT_IND_015"] == ("human", "performer")
    # Brazo operado por la tripulación: exigencias del operador, no esfuerzo físico
    capture = catalog.task("SAT_COL_001")
    assert capture["crew_role"] == "operator" and capture["requirements"]["physical"]["physical_effort"] <= 0.25


def test_safety_requirements_are_not_soft_scores(catalog):
    for t in catalog.all_tasks():
        if t["requirements"]:
            assert set(t["requirements"]) == {"physical", "cognitive"}
        assert "required_qualifications" in t["technical_requirements"]
        if t["requires_eva"]:
            assert t["safety_critical"] and t["min_crew"] >= 2
            assert "eva_certified" in t["technical_requirements"]["required_qualifications"]


def test_comparable_tasks_across_environments(catalog):
    """Calibración: una EVA lunar y una marciana parten del mismo perfil."""
    moon, mars = catalog.task("MOON_COL_001"), catalog.task("MARS_COL_001")
    assert moon["requirements"]["physical"] == mars["requirements"]["physical"]
    tele = catalog.task("SAT_IND_001")["requirements"]
    assert tele["physical"]["physical_effort"] <= 0.1 and tele["cognitive"]["concentration"] >= 0.6


# --- validador: detecta cada tipo de error -----------------------------------------------


@pytest.mark.parametrize("task_id, change, message", [
    ("ISS_IND_001", lambda t: t["requirements"]["physical"].update(physical_effort=1.2), "fuera de [0, 1]"),
    ("ISS_IND_001", lambda t: t["requirements"]["cognitive"].update(concentration=float("nan")), "fuera de [0, 1]"),
    ("ISS_IND_001", lambda t: t["requirements"]["physical"].pop("mobility"), "exactamente"),
    ("ISS_IND_001", lambda t: t["requirements"].update(eva_certified=1), "sobran"),
    ("ISS_COL_012", lambda t: t.pop("team_requirements"), "team_requirements"),
    ("ISS_IND_001", lambda t: t.update(max_crew=2), "individual"),
    ("ISS_IND_001", lambda t: t["technical_requirements"].update(required_qualifications=["jedi"]), "desconocida"),
    ("ISS_IND_001", lambda t: t.update(frequency={"kind": "monthly"}), "frecuencia"),
    ("ISS_IND_001", lambda t: t.update(frequency={"kind": "periodic"}), "every_days"),
    ("ISS_IND_001", lambda t: t.update(nasa_reference=[]), "referencia"),
    ("ISS_IND_001", lambda t: t.update(nasa_reference=["inventada_2030"]), "desconocida"),
    ("ISS_IND_001", lambda t: t["requirements_metadata"].update(evidence_type="official", sources=[]), "oficial"),
    ("ISS_IND_001", lambda t: t["requirements"]["cognitive"].update(working_memory=0.95), "sin ajuste"),
    ("SAT_COL_002", lambda t: t.update(execution_mode="teleport"), "execution_mode"),
    ("SAT_COL_002", lambda t: t.update(requirements={"physical": {}, "cognitive": {}}), "robótica"),
    ("ISS_COL_018", lambda t: t.update(min_crew=1), "dos personas"),
    ("ISS_IND_001", lambda t: t.pop("source_type"), "faltan campos"),
])
def test_validator_catches(catalog, task_id, change, message):
    errors = broken(catalog, task_id, change)
    assert any(message in e for e in errors), errors


def test_duplicate_ids_are_detected(catalog):
    dup = replace(catalog, tasks={**catalog.tasks, "moon": catalog.tasks["moon"] + [catalog.task("ISS_IND_001")]})
    assert any("repetido" in e for e in validate_catalog(dup))


# --- traducción a requisitos -----------------------------------------------------------------


def test_higher_demand_means_stricter_threshold(catalog, mapping):
    task = copy.deepcopy(catalog.task("ISS_IND_007"))
    reqs = lambda: {d.requirement.parameter: d.requirement for d in derive_requirements(task, mapping)}
    task["requirements"]["cognitive"]["concentration"] = 0.5
    low = reqs()["pvt_lapses"].max
    task["requirements"]["cognitive"]["concentration"] = 0.9
    assert reqs()["pvt_lapses"].max < low


def test_descriptive_and_medical_dimensions_are_not_translated(catalog, mapping):
    params = {d.requirement.parameter for t in catalog.all_tasks() for d in derive_requirements(t, mapping)}
    assert params <= {"pvt_lapses", "sleep_duration_h", "sleep_quality", "fatigue_self", "grip_strength",
                      "work_hours_3d"}
    assert "stress_tolerance" not in mapping.mapping


def test_critical_only_for_safety_critical_high_demand(catalog, mapping):
    eva = derive_requirements(catalog.task("ISS_COL_018"), mapping)
    assert eva and all(d.requirement.critical for d in eva)
    exercise = derive_requirements(catalog.task("ISS_IND_019"), mapping)
    assert exercise and not any(d.requirement.critical for d in exercise)


def test_per_astronaut_tasks_are_restricted(catalog, mapping):
    tasks = to_planner_tasks(catalog.task("ISS_IND_019"), mapping, (8 * 3600.0, 17 * 3600.0), ["A1", "A2"])
    assert [t.id for t in tasks] == ["ISS_IND_019:A1", "ISS_IND_019:A2"]
    assert tasks[0].only_for == frozenset({"A1"}) and tasks[0].category == "ISS_IND_019"


def test_interdependence_scales_compatibility(catalog, mapping, config):
    from crew_planner.social import from_daily_result
    from conftest import social_doc

    snap = from_daily_result(social_doc(9, ["A1", "A2", "A3"], [[None, 0.8, 0.1], [0.8, None, 0.1], [0.1, 0.1, None]]))
    compat = team_compatibility(["A1", "A2"], snap)
    window = (0.0, 86400.0)
    eva = to_planner_tasks(catalog.task("ISS_COL_018"), mapping, window, [])[0]
    unload = to_planner_tasks(catalog.task("ISS_COL_012"), mapping, window, [])[0]
    assert eva.interdependence > unload.interdependence
    per_importance = lambda t: compatibility_cost(t, compat, 0.3, True, config) / config.importance.normalize(t.importance)
    assert per_importance(eva) < per_importance(unload) < 0


# --- selección del día ------------------------------------------------------------------------


def test_frequencies(catalog):
    days = [select_day(catalog, "iss", d) for d in range(28)]
    count = lambda tid: sum(tid in s.reasons for s in days)
    assert count("ISS_IND_014") == 28          # diaria
    assert count("ISS_IND_016") == 4           # semanal
    assert count("ISS_IND_011") in (5, 6)      # cada 5 días
    assert count("ISS_COL_018") == 2           # EVA: solo cuando el plan la programa
    assert count("ISS_COL_006") == 0           # contingencia: solo si ocurre
    with_event = select_day(catalog, "iss", 0, extra_events=["ISS_COL_006"])
    assert with_event.reasons["ISS_COL_006"] == "contingencia"


def test_robotic_tasks_are_never_given_to_the_crew(catalog):
    for d in range(7):
        selection = select_day(catalog, "satellite", d)
        assert all(t["crew_role"] != "none" for t in selection.scheduled)
    assert {t["task_id"] for t in select_day(catalog, "satellite", 6).automated} == {
        "SAT_COL_002", "SAT_COL_006", "SAT_COL_009"}


# --- simulación por entorno -------------------------------------------------------------------


@pytest.mark.parametrize("env", ENVIRONMENTS)
def test_each_environment_plans_valid_days(env, config):
    plans = simulate(4, config, environment=env, first_day=0)
    for plan in plans:
        assert plan["status"] == "ok", (env, plan.get("conflicts"))
        assert plan["global"]["violations"] == []
        assert plan["meta"]["environment"] == env


def test_exercise_is_done_by_each_astronaut(config):
    raw = environment_input("iss", 3)
    plan = plan_day(from_dict(raw), config)
    exercise = {e["task"]: e["astronaut"] for e in plan["individual"] if e["task"].startswith("ISS_IND_019")}
    assert exercise == {f"ISS_IND_019:{a}": a for a in ("A1", "A2", "A3", "A4", "A5", "A6")}


def test_fatigued_astronaut_never_does_the_eva(config):
    raw = environment_input("iss", 7)  # día de EVA en el plan de la misión
    for a in raw["crew"]:
        if a["id"] == "A1":
            for m in a["measurements"]:
                if m["parameter"] == "fatigue_self":
                    m["value"] = 4.5
    plan = plan_day(from_dict(raw), config)
    eva = next(e for e in plan["collective"] if e["task"] == "ISS_COL_018")
    assert "A1" not in eva["members"]
    assert any(d["astronaut"] == "A1" and "fatigue_self" in " ".join(d["reasons"]) for d in eva["not_eligible"])


def test_switching_environment_does_not_touch_the_optimizer(config):
    # Mismo optimizador y configuración: solo cambian las tareas de entrada
    ids = {env: {t["category"] for t in environment_input(env, 1)["tasks"]} for env in ENVIRONMENTS}
    assert all(i.startswith({"iss": "ISS", "moon": "MOON", "mars": "MARS", "satellite": "SAT"}[env])
               for env, s in ids.items() for i in s)


def test_planner_tasks_for_day_reports_reasons(catalog):
    tasks, selection = planner_tasks_for_day(catalog, "moon", 1, ["A1", "A2", "A3", "A4"])
    assert selection.reasons["MOON_COL_001"] == "plan de la misión"
    assert {t.category for t in tasks} == set(selection.reasons)


def test_requirements_table_covers_every_task(catalog):
    from crew_planner.catalog_report import render

    text = render(catalog)
    assert all(t["task_id"] in text for t in catalog.all_tasks())
    assert "Informe de calibración" in text and "estimaciones teóricas" in text


def test_report_shows_environment_and_automated_tasks(config):
    from crew_planner.report import GROUND, render_html

    raw = environment_input("satellite", 6)
    page = render_html(plan_day(from_dict(raw), config), raw, GROUND)
    assert "Servicio de satélites en órbita" in page and "Operaciones sin tripulación" in page
    assert "SAT_COL_002" in page
