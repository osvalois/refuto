# -*- coding: utf-8 -*-
"""Diario de evidencia. JSON Lines, append-only, con procedencia.

Regla de dirección, y es la que separa evidencia de informe:

    evidencia estructurada  →  informe humano
    NUNCA al revés

Un informe HTML del que después se extraen datos es una captura con pretensiones. Lo que se
audita dentro de un año es el JSONL.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from core.model import now, provenance

LEDGER = "ledger.jsonl"


def ledger_path(workspace: Path) -> Path:
    return workspace / ".harness" / "evidence" / LEDGER


def append_event(workspace: Path, event: dict) -> None:
    """Añade un evento al diario. Append atómico: una línea, una escritura.

    En POSIX, una escritura de menos de PIPE_BUF a un descriptor abierto en modo `a` no se
    entrelaza con la de otro proceso. Por eso los eventos del guardián —que corre en procesos
    distintos y concurrentes— no se corrompen entre sí.
    """
    path = ledger_path(workspace)
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {"ts": now(), **event}
    line = json.dumps(record, ensure_ascii=False) + "\n"
    with path.open("a", encoding="utf-8") as fh:
        fh.write(line)
        fh.flush()
        os.fsync(fh.fileno())


def read_events(workspace: Path, kinds: list | None = None) -> list:
    path = ledger_path(workspace)
    if not path.is_file():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if kinds and ev.get("kind") not in kinds:
            continue
        out.append(ev)
    return out


def write_run(workspace: Path, run_id: str, results: list, extra: dict | None = None) -> Path:
    """Escribe el informe estructurado de una corrida y devuelve su ruta."""
    from core.model import write_json
    payload = {
        "schema": "harness.run/v1",
        "run_id": run_id,
        "provenance": provenance(workspace, extra),
        "verdict": verdict_of(results),
        "gates": [r.to_dict() for r in results],
    }
    path = workspace / ".harness" / "evidence" / f"{run_id}.json"
    write_json(path, payload)
    append_event(workspace, {"kind": "run/complete", "run_id": run_id,
                             "verdict": payload["verdict"],
                             "gates": {r.id: r.status for r in results}})
    return path


def verdict_of(results: list) -> str:
    """Un veredicto por corrida, con las mismas palabras que las puertas.

    El orden importa: un NOT_EXECUTABLE manda sobre un FAIL porque significa que ni siquiera
    se sabe cuántos fallos hay.

    `NOT_APPLICABLE` no impide integrar, pero **tampoco cuenta como aprobado**: una corrida en
    la que ninguna puerta encontró sujeto no es INTEGRABLE, es una corrida sin ámbito. Ésa es
    la diferencia que un `PASS` de cortesía borraba.
    """
    from core.model import BLOCKED, FAIL, NOT_APPLICABLE, NOT_EXECUTABLE, PASS
    statuses = {r.status for r in results}
    if NOT_EXECUTABLE in statuses:
        return "NO INTEGRABLE — hay verificaciones que no se pudieron ejecutar"
    if FAIL in statuses:
        return "NO INTEGRABLE — hay puertas en rojo"
    if BLOCKED in statuses:
        return "NO INTEGRABLE TODAVÍA — hay puertas que no se pudieron comprobar"
    if not statuses:
        return "SIN PUERTAS EJECUTADAS"
    if PASS not in statuses:
        n = sum(1 for r in results if r.status == NOT_APPLICABLE)
        return (f"SIN ÁMBITO — ninguna puerta encontró nada que comprobar "
                f"({n} no aplican). Eso no es un aprobado")
    if statuses <= {PASS, NOT_APPLICABLE}:
        n = sum(1 for r in results if r.status == NOT_APPLICABLE)
        return "INTEGRABLE" + (f" — {n} puertas sin sujeto en este espacio" if n else "")
    return "SIN PUERTAS EJECUTADAS"
