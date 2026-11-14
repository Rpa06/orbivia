"""Contexto de planificación: todo lo que el optimizador necesita, ya calculado.

Reúne estados, elegibilidad, costes individuales, carga objetivo y las opciones
de cada tarea (una persona en las individuales, un equipo en las colectivas).
El optimizador solo elige entre estas opciones y fija horarios.
"""

from dataclasses import dataclass, field

from social_graph.intervals import Interval, total

from .config import PlannerConfig
from .costs import IndividualCost, capacity, individual_cost, target_shares, task_load
from .eligibility import Eligibility, eligibility, free_time, max_hours
from .inputs import PlanningInput, validate
from .state import StateValue, astronaut_state
from .teams import candidate_teams, is_low_load


@dataclass(frozen=True)
class Option:
    """Una forma de cubrir una tarea: quién la hace y su coste operativo."""

    task: str
    members: tuple[str, ...]
    free: tuple[Interval, ...]          # tramos en que todos están libres
    individual: float                   # media de C_ij de los miembros

    @property
    def operational(self) -> float:
        return self.individual


@dataclass
class PlanningContext:
    problem: PlanningInput
    config: PlannerConfig
    states: dict[str, dict[str, StateValue]]
    eligibility: dict[tuple[str, str], Eligibility]
    costs: dict[tuple[str, str], IndividualCost]
    free: dict[str, list[Interval]]
    available_h: dict[str, float]
    capacity: dict[str, float]
    shares: dict[str, float]
    loads: dict[str, float]
    low_load: dict[str, bool]
    options: dict[str, list[Option]]
    warnings: list[str] = field(default_factory=list)

    def eligible(self, task_id: str) -> list[str]:
        return [a.id for a in self.problem.crew if self.eligibility[(a.id, task_id)].eligible]


def build_context(problem: PlanningInput, config: PlannerConfig) -> PlanningContext:
    warnings = validate(problem, config)
    crew, tasks = problem.crew, problem.tasks

    states = {a.id: astronaut_state(a, config.parameters, problem.reference_s) for a in crew}
    elig = {(a.id, t.id): eligibility(a, t, states[a.id], config) for a in crew for t in tasks}
    costs = {
        (a.id, t.id): individual_cost(t, a.id, states[a.id], problem.history, problem.day, config)
        for a in crew for t in tasks
    }
    free = {a.id: free_time(a) for a in crew}
    available = {a.id: min(total(free[a.id]) / 3600.0, max_hours(a, config)) for a in crew}
    caps = {a.id: capacity(states[a.id], config.parameters, config) for a in crew}

    options: dict[str, list[Option]] = {}
    for t in tasks:
        eligible = [a for a in crew if elig[(a.id, t.id)].eligible]
        if not t.collective:
            options[t.id] = [
                Option(t.id, (a.id,), elig[(a.id, t.id)].free, costs[(a.id, t.id)].total)
                for a in sorted(eligible, key=lambda a: a.id)
            ]
            continue
        window_free = {a.id: elig[(a.id, t.id)].free for a in eligible}
        team_options = []
        for team in candidate_teams(t, eligible, window_free, config):
            mean_cost = sum(costs[(m, t.id)].total for m in team.members) / len(team.members)
            team_options.append(Option(t.id, team.members, team.common_free, mean_cost))
        options[t.id] = team_options

    return PlanningContext(
        problem=problem, config=config, states=states, eligibility=elig, costs=costs, free=free,
        available_h=available, capacity=caps, shares=target_shares(available, caps),
        loads={t.id: task_load(t) for t in tasks},
        low_load={t.id: is_low_load(t, config) for t in tasks},
        options=options, warnings=warnings,
    )
