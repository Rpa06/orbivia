"""Optimizador CP-SAT (diseño, sección 5).

Variables: una binaria por opción (persona o equipo que cubre una tarea) y su
tramo de inicio. Restricciones duras: cobertura, sin solapes por persona (con
descanso tras tareas exigentes), recursos compartidos, horas y tareas exigentes
por día. Todo lo que es seguridad está aquí como restricción, nunca como peso.

Modo `lexicographic` (por defecto), en etapas:

1. Cobertura: maximizar la importancia de las tareas aplazables cubiertas.
2. Coste operativo: estado + repetición + incertidumbre + equidad.

No hay ningún término social: el grafo social no es una variable del
optimizador, ni directa ni indirectamente (README, sección 2.D).

Modo `weighted`: una sola resolución de la suma ponderada.

CP-SAT trabaja con enteros: los costes se multiplican por COST_SCALE.
"""

import math
from collections import defaultdict
from dataclasses import dataclass, field

from ortools.sat.python import cp_model

from .context import Option, PlanningContext

COST_SCALE = 10**12
LOAD_SCALE = 1000    # cargas en milésimas de hora
SHARE_SCALE = 1000   # cuotas en milésimas

FEASIBLE_STATUSES = (cp_model.OPTIMAL, cp_model.FEASIBLE)


def allowed_starts(free, duration_s: float, slot_s: float) -> list[int]:
    """Tramos de inicio en los que la tarea cabe entera en un hueco libre."""
    starts = set()
    for start, end in free:
        k = math.ceil(start / slot_s - 1e-9)
        while k * slot_s + duration_s <= end + 1e-6:
            starts.add(k)
            k += 1
    return sorted(starts)


@dataclass
class StageResult:
    name: str
    status: str
    objective: float | None
    wall_time_s: float

    @property
    def optimal(self) -> bool:
        return self.status == "OPTIMAL"


@dataclass
class Chosen:
    option: Option
    start_s: float


@dataclass
class Solution:
    feasible: bool
    chosen: list[Chosen] = field(default_factory=list)
    stages: list[StageResult] = field(default_factory=list)
    status: str = ""


class PlanModel:
    """Modelo CP-SAT de un día. Se puede resolver varias veces añadiendo restricciones."""

    def __init__(self, ctx: PlanningContext, coverage_assumptions: bool = False) -> None:
        self.ctx = ctx
        cfg = ctx.config
        self.model = cp_model.CpModel()
        m = self.model
        self.slot_s = cfg.limits.slot_min * 60.0
        rest_slots = math.ceil(cfg.limits.rest_after_demanding_min * 60.0 / self.slot_s - 1e-9)
        crew = [a.id for a in ctx.problem.crew]
        tasks = ctx.problem.tasks

        self.z: dict[tuple[str, int], cp_model.IntVar] = {}
        self.start: dict[tuple[str, int], cp_model.IntVar] = {}
        self.options: dict[tuple[str, int], Option] = {}
        person_iv = defaultdict(list)
        resource_iv = defaultdict(list)
        by_person = defaultdict(list)  # astronauta -> claves de opción

        for t in tasks:
            size = math.ceil(t.duration_s / self.slot_s - 1e-9)
            for k, option in enumerate(ctx.options[t.id]):
                starts = allowed_starts(option.free, t.duration_s, self.slot_s)
                if not starts:
                    continue
                key = (t.id, k)
                z = m.new_bool_var(f"z[{t.id},{k}]")
                s = m.new_int_var_from_domain(cp_model.Domain.from_values(starts), f"s[{t.id},{k}]")
                iv = m.new_optional_fixed_size_interval_var(s, size, z, f"iv[{t.id},{k}]")
                # Tras una tarea exigente, la persona queda bloqueada el tiempo de descanso
                piv = iv
                if t.demanding and rest_slots > 0:
                    piv = m.new_optional_fixed_size_interval_var(s, size + rest_slots, z, f"rest[{t.id},{k}]")
                for member in option.members:
                    person_iv[member].append(piv)
                    by_person[member].append(key)
                for resource in t.resources:
                    resource_iv[resource].append(iv)
                self.z[key], self.start[key], self.options[key] = z, s, option

        self.task_keys = {t.id: [k for k in self.z if k[0] == t.id] for t in tasks}
        self.covered = {t.id: sum(self.z[k] for k in self.task_keys[t.id]) for t in tasks}
        self.coverage_literals: dict[str, cp_model.IntVar] = {}
        for t in tasks:
            if t.mandatory:
                if coverage_assumptions:
                    lit = m.new_bool_var(f"cover[{t.id}]")
                    m.add(self.covered[t.id] == 1).only_enforce_if(lit)
                    m.add(self.covered[t.id] <= 1)
                    self.coverage_literals[t.id] = lit
                else:
                    m.add(self.covered[t.id] == 1)
            else:
                m.add(self.covered[t.id] <= 1)

        for ivs in list(person_iv.values()) + list(resource_iv.values()):
            if len(ivs) > 1:
                m.add_no_overlap(ivs)

        by_id = {t.id: t for t in tasks}
        self.limit_literals: dict[str, cp_model.IntVar] = {}
        for a in ctx.problem.crew:
            keys = by_person[a.id]
            if not keys:
                continue
            seconds = sum(round(by_id[k[0]].duration_s) * self.z[k] for k in keys)
            limit_h = a.max_work_h if a.max_work_h is not None else cfg.limits.max_work_h
            demanding = sum(self.z[k] for k in keys if by_id[k[0]].demanding)
            hours_c = m.add(seconds <= round(limit_h * 3600))
            dem_c = m.add(demanding <= cfg.limits.max_demanding_per_day)
            if coverage_assumptions:
                lit = m.new_bool_var(f"limits[{a.id}]")
                hours_c.only_enforce_if(lit)
                dem_c.only_enforce_if(lit)
                self.limit_literals[a.id] = lit

        self._build_costs(crew, by_person, by_id)

    # --- costes ---------------------------------------------------------------------

    def _build_costs(self, crew, by_person, by_id) -> None:
        ctx, cfg, m = self.ctx, self.ctx.config, self.model
        w = cfg.weights
        ref_h = cfg.limits.max_work_h

        individual = sum(round(o.operational * COST_SCALE) * self.z[k] for k, o in self.options.items())

        # Equidad (sección 4.6): desviación respecto a la cuota y diferencia entre extremos
        load = {
            a: sum(round(ctx.loads[k[0]] * LOAD_SCALE) * self.z[k] for k in by_person[a]) for a in crew
        }
        total = sum(load.values())
        max_total = sum(round(ctx.loads[t.id] * LOAD_SCALE) * t.max_people for t in ctx.problem.tasks) or 1
        deviations = []
        relative = []
        for a in crew:
            share = round(ctx.shares[a] * SHARE_SCALE)
            dev = m.new_int_var(0, 2 * SHARE_SCALE * max_total, f"dev[{a}]")
            m.add(dev >= SHARE_SCALE * load[a] - share * total)
            m.add(dev >= share * total - SHARE_SCALE * load[a])
            deviations.append(dev)
            if ctx.shares[a] > 0:
                q = round(SHARE_SCALE / ctx.shares[a])
                relative.append(q * load[a])
        # Unidades: dev y relative están en millonésimas de hora
        unit = COST_SCALE / 1e6 / ref_h
        equity = round(w.alpha_equity * unit) * sum(deviations)
        if len(relative) >= 2:
            bound = max(round(SHARE_SCALE / ctx.shares[a]) for a in crew if ctx.shares[a] > 0) * max_total
            hi = m.new_int_var(0, bound, "rel_max")
            lo = m.new_int_var(0, bound, "rel_min")
            for r in relative:
                m.add(hi >= r)
                m.add(lo <= r)
            equity = equity + round(w.beta_spread * unit) * (hi - lo)
        self.operational = individual + equity

        self.coverage_value = sum(
            round(cfg.importance.normalize(t.importance) * 1000) * self.covered[t.id]
            for t in ctx.problem.tasks if not t.mandatory
        )

    # --- resolución -----------------------------------------------------------------

    def solver(self, workers: int | None = None) -> cp_model.CpSolver:
        cfg = self.ctx.config.solver
        solver = cp_model.CpSolver()
        solver.parameters.num_workers = workers or cfg.workers
        solver.parameters.random_seed = cfg.seed
        solver.parameters.max_time_in_seconds = cfg.time_limit_s
        return solver

    def _solve(self, name: str, stages: list[StageResult], scale: float):
        solver = self.solver()
        status = solver.solve(self.model)
        objective = solver.objective_value / scale if status in FEASIBLE_STATUSES else None
        stages.append(StageResult(name, solver.status_name(status), objective, solver.wall_time))
        if status in FEASIBLE_STATUSES:
            self._hint(solver)
        return solver, status

    def _hint(self, solver: cp_model.CpSolver) -> None:
        self.model.clear_hints()
        for k, z in self.z.items():
            self.model.add_hint(z, solver.value(z))
            self.model.add_hint(self.start[k], solver.value(self.start[k]))

    def _extract(self, solver: cp_model.CpSolver, stages: list[StageResult]) -> Solution:
        chosen = [
            Chosen(self.options[k], solver.value(self.start[k]) * self.slot_s)
            for k in sorted(self.z) if solver.boolean_value(self.z[k])
        ]
        return Solution(True, chosen, stages, stages[-1].status)

    def solve(self) -> Solution:
        if self.ctx.config.stages.mode == "weighted":
            return self._solve_weighted()
        return self._solve_lexicographic()

    def _solve_weighted(self) -> Solution:
        cfg = self.ctx.config
        uncovered = sum(
            round(cfg.stages.uncovered_penalty * cfg.importance.normalize(t.importance) * COST_SCALE)
            * (1 - self.covered[t.id])
            for t in self.ctx.problem.tasks if not t.mandatory
        )
        stages: list[StageResult] = []
        self.model.minimize(self.operational + uncovered)
        solver, status = self._solve("weighted", stages, COST_SCALE)
        if status not in FEASIBLE_STATUSES:
            return Solution(False, stages=stages, status=stages[-1].status)
        return self._extract(solver, stages)

    def _solve_lexicographic(self) -> Solution:
        m, cfg = self.model, self.ctx.config
        stages: list[StageResult] = []

        # Etapa 1: cobertura de las aplazables
        optional = [t for t in self.ctx.problem.tasks if not t.mandatory and self.task_keys[t.id]]
        if optional:
            m.maximize(self.coverage_value)
            solver, status = self._solve("coverage", stages, 1000)
            if status not in FEASIBLE_STATUSES:
                return Solution(False, stages=stages, status=stages[-1].status)
            m.add(self.coverage_value >= round(solver.objective_value))

        # Etapa 2: coste operativo
        m.minimize(self.operational)
        solver, status = self._solve("operational", stages, COST_SCALE)
        if status not in FEASIBLE_STATUSES:
            return Solution(False, stages=stages, status=stages[-1].status)
        return self._extract(solver, stages)


def optimize(ctx: PlanningContext) -> Solution:
    return PlanModel(ctx).solve()
