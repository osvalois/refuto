# -*- coding: utf-8 -*-
"""Ejecutor de las suites. `unittest` de la biblioteca estándar: nada que instalar.

    python3 refuto.py selftest
    python3 refuto.py selftest --suite adversarial --verbose
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SUITES = ("unit", "contract", "selftest", "adversarial")


def run_suites(only: list | None = None, verbose: bool = False) -> int:
    """Corre las suites pedidas. Devuelve 0 sólo si se ejecutó algo y todo pasó.

    Ámbito vacío no aprueba
    -----------------------
    Esto devolvía 0 cuando `bad == 0`, sin mirar `total`. Así, `selftest --suite zzz`
    —una suite que no existe— imprimía `NO TESTS RAN`, `0/0 pruebas pasan` y salía con **0**:
    un aprobado vacuo dentro del programa cuyo propósito declarado es impedirlos. En CI, una
    suite renombrada dejaba el trabajo en verde sin ejecutar una sola prueba.

    Un nombre de suite que no existe se declara aparte de «la suite existe y está vacía»:
    son dos errores distintos y se arreglan distinto.
    """
    sys.path.insert(0, str(ROOT))
    names = [s for s in SUITES if not only or s in only]
    desconocidas = [s for s in (only or []) if s not in SUITES]
    if desconocidas:
        print(f"\n  suite desconocida: {', '.join(desconocidas)}. "
              f"Las que hay: {', '.join(SUITES)}.")
        return 1
    loader = unittest.TestLoader()
    master = unittest.TestSuite()
    for name in names:
        directory = ROOT / "tests" / name
        if not directory.is_dir():
            continue
        master.addTests(loader.discover(str(directory), pattern="test_*.py",
                                        top_level_dir=str(ROOT)))
    runner = unittest.TextTestRunner(verbosity=2 if verbose else 1, stream=sys.stdout)
    result = runner.run(master)
    total = result.testsRun
    bad = len(result.failures) + len(result.errors)
    print(f"\n  {total - bad}/{total} pruebas pasan · suites: {', '.join(names) or '(ninguna)'}")
    if total == 0:
        print("  0 pruebas ejecutadas. Eso NO es un aprobado: es que no se comprobó nada. "
              "Revise el nombre de la suite o el patrón de descubrimiento.")
        return 1
    if bad:
        print(f"  {bad} fallan. Un juez que no se prueba a sí mismo deja de ser un juez.")
    return 0 if bad == 0 else 1
