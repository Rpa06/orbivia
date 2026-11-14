"""Acciones recomendadas por combinación de avisos, con cooldown (README §2.E.1).

Cada acción es operativa (ajuste de carga, luz, recuperación, seguimiento con el
médico de a bordo). Ninguna es un tratamiento ni un diagnóstico.

Cooldown: si una acción ya está activa para la misma combinación de avisos y la
severidad de hoy no empeora (se estabiliza o mejora), no se vuelve a notificar.
Si empeora, se notifica de nuevo. Si la combinación desaparece, la acción se cierra.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from .alerts import Alert

CATALOG = {
    "LOAD_ADJUST": {
        "label": "Ajuste de carga",
        "text": "Revisar la carga del día y priorizar tareas de menor exigencia.",
        "reference": "NASA-STD-3001: límites de carga de trabajo",
    },
    "LIGHT_EXPOSURE": {
        "label": "Exposición a la luz",
        "text": "Pauta de luz y horario para realinear el ritmo de sueño con la tripulación.",
        "reference": "NASA HRP, riesgo de sueño y fatiga (Sleep-102)",
    },
    "RECOVERY": {
        "label": "Recuperación",
        "text": "Bloque de recuperación o descanso adicional dentro del horario.",
        "reference": "NASA HRP, riesgo de sueño y fatiga",
    },
    "SURGEON_FOLLOWUP": {
        "label": "Seguimiento con el médico de a bordo",
        "text": "El médico de a bordo revisa los datos y decide si hace falta algo más.",
        "reference": "README §2.E: lo clínico lo decide el personal médico",
    },
}


def actions_for(alerts: Iterable[Alert]) -> dict[str, list[str]]:
    """Firma de la combinación de avisos → acciones."""
    alerts = list(alerts)
    if not alerts:
        return {}
    areas = {a.area for a in alerts}
    fields = {v for a in alerts for v in a.variables}
    codes: list[str] = []
    if "fatigue_sleep" in areas:
        codes += ["LOAD_ADJUST", "RECOVERY"]
    if "circadian_desync_z" in fields or "sleep_duration_z" in fields:
        codes.append("LIGHT_EXPOSURE")
    if areas & {"medical", "psychological", "social_team"}:
        codes.append("SURGEON_FOLLOWUP")
    if len({a.criterion for a in alerts}) >= 2 and "SURGEON_FOLLOWUP" not in codes:
        codes.append("SURGEON_FOLLOWUP")
    signature = "+".join(sorted(f"{a.criterion}:{a.area}" for a in alerts))
    return {signature: list(dict.fromkeys(codes))}


def severity(alerts: Iterable[Alert]) -> float:
    total = 0.0
    for a in alerts:
        values = a.detail.get("values_sigma") or list(a.detail.get("fields", {}).values()) or [
            a.detail.get("slope_sigma_per_day", 0) * a.detail.get("window_days", 0)]
        total += max(values) if values else 0.0
    return round(total, 3)


@dataclass(frozen=True)
class ActionDecision:
    signature: str
    action_code: str
    notify: bool
    status: str        # 'new', 'worsening', 'cooldown'
    severity: float


def apply_cooldown(proposed: Mapping[str, list[str]], today_severity: float,
                   active: Mapping[tuple[str, str], float]) -> list[ActionDecision]:
    """`active[(firma, acción)]` = severidad del último aviso notificado."""
    out = []
    for signature, codes in proposed.items():
        for code in codes:
            last = active.get((signature, code))
            if last is None:
                out.append(ActionDecision(signature, code, True, "new", today_severity))
            elif today_severity > last + 0.25:
                out.append(ActionDecision(signature, code, True, "worsening", today_severity))
            else:
                out.append(ActionDecision(signature, code, False, "cooldown", today_severity))
    return out
