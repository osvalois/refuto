#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Resume una corrida y decide el código de salida de CI.

Existe para que el flujo NO tenga que interpretar el veredicto con `grep`. BLOCKED sale con 2 y
CI lo trata como fallo: en una tubería, «no se pudo comprobar» tiene que parar la integración.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.proc import force_utf8_io  # noqa: E402

# Estos guiones imprimen ✓ y ✗ y los ejecuta CI en cualquier sistema. En una consola
# cp1252 ese carácter no afeaba la salida: abortaba la comprobación con un Traceback,
# y una comprobación que no llega a hablar no dice «pasa» ni «falla».
force_utf8_io()


def main(argv) -> int:
    if len(argv) != 2:
        print("uso: gate_summary.py <run.json>", file=sys.stderr)
        return 64
    doc = json.loads(Path(argv[1]).read_text(encoding="utf-8"))
    counts = {}
    for gate in doc["gates"]:
        counts[gate["status"]] = counts.get(gate["status"], 0) + 1
        print(f"  {gate['status']:<15} {gate['id']:<12} {gate['measure'][:90]}")
    print(f"\n  {doc['verdict']}")
    print(f"  reparto: {counts}")
    if counts.get("FAIL") or counts.get("NOT_EXECUTABLE"):
        return 1
    if counts.get("BLOCKED"):
        print("\n  BLOCKED no es aprobado: hay verificaciones que no se pudieron correr.")
        return 2
    if not counts.get("PASS"):
        print("\n  Ninguna puerta encontró sujeto que comprobar. Ámbito vacío no es aprobado.")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
