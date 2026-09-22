# -*- coding: utf-8 -*-
"""G-ROLES · El registro de roles es válido y todo lo que cita existe.

Un rol que declara una restricción que refuto no sabe aplicar es una restricción que **no
existe**, y declararla es peor que no tenerla: se cita en las revisiones como si protegiera.
"""

from __future__ import annotations

from core.model import FAIL, Finding, MEDIUM, PASS, Result
from core.roles import load, validate_registry

GATE_ID = "G-ROLES"
TITLE = "Registro de roles válido"
THRESHOLD = "esquema válido · restricciones aplicables · traspasos y puertas que existen"


def run(ctx) -> Result:
    problems = validate_registry()
    roles = {} if problems else load()
    findings = [Finding("roles/registry.json", p) for p in problems]
    observations = []
    if roles:
        groups: dict = {}
        for r in roles.values():
            groups[r.group] = groups.get(r.group, 0) + 1
        observations.append("grupos: " + " · ".join(f"{g}({n})" for g, n in sorted(groups.items())))
        sin_gates = [r.id for r in roles.values() if not r.quality_gates]
        if sin_gates:
            observations.append(f"{len(sin_gates)} roles sin puerta declarada: "
                                f"{', '.join(sin_gates[:8])}. Su salida no la comprueba nadie.")
    return Result(GATE_ID, TITLE, PASS if not findings else FAIL, severity=MEDIUM,
                  threshold=THRESHOLD,
                  measure=f"{len(roles)} roles · {len(findings)} problemas",
                  findings=findings, observations=observations)
