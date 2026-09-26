#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Las cifras que el README declara MEDIDAS tienen que seguir dando eso.

Por qué existe, y por qué no bastaba `check_citas.py`
------------------------------------------------------
Este repositorio ya vigila dos clases de afirmación: `check_citas.py` comprueba que una cita a
código siga apuntando a lo que dice, y `check_wiring.py` que las cifras ESTRUCTURALES (13
puertas, 22 roles, 13 fases, 5 adapters) sigan siendo ciertas. Las dos funcionan: el 2026-09-25
las siete cifras estructurales del README cuadraban todas.

Lo que no tenía vigilante son las cifras de CORRIDA —cuántas pruebas hay, cuántos controles
ejecuta el preflight—, que son justamente las que el README cita como `E3` y `E4`. Medido ese
mismo día sobre `69bcd6a`:

    afirmación del README          dice              medido
    suite                          685/685           748/748
    reparto adversarial            137               200
    preflight                      13 controles      14 controles

Las tres llevan fecha `2026-09-25`. El commit que las puso al día (`bf9f061`) fue seguido de
cinco commits que añadieron 730 líneas de pruebas sin tocar la tabla. No es descuido de quien
escribió: es que una cifra que cambia con cada commit y que nadie comprueba **sólo puede
envejecer**, y este repositorio sostiene que «una cifra sin su orden, su fecha y su máquina no
es una medición». Éstas tenían orden, fecha y máquina, y eran falsas — que es peor, porque la
procedencia hace que se lean como verificadas.

Qué NO comprueba
----------------
Los tiempos (`188 s`, `368 s`). Dependen de la máquina y de la carga, así que exigir que
coincidan haría fallar el control en el portátil de cualquier otro — y un control que falla por
motivos que no son el defecto se desactiva. Se comprueban los RECUENTOS, que son propiedades
del árbol y no de quien lo ejecuta.
"""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

SUITES = ("unit", "contract", "selftest", "adversarial")


def _pruebas_por_suite() -> dict:
    """El recuento del CARGADOR, que es el que decide qué se ejecuta.

    No `grep -c "def test_"`: el propio README documenta que esa cuenta daba 686 contra 685
    reales porque una cadena contenía el texto. Se pregunta a quien manda.
    """
    fuera = {}
    for s in SUITES:
        fuera[s] = unittest.TestLoader().discover(
            str(RAIZ / "tests" / s), top_level_dir=str(RAIZ)).countTestCases()
    return fuera


def _controles_del_preflight() -> int:
    import importlib.util

    spec = importlib.util.spec_from_file_location("_pf", RAIZ / "scripts" / "preflight.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return len(mod._chequeos())                                       # noqa: SLF001


#: Cada afirmación: cómo se localiza en el README, qué la mide, y cómo se llama en el mensaje.
#:
#: El patrón captura UN número. Se busca en el fichero entero y no en una línea fija: anclar a
#: un número de línea convertiría cualquier edición del README en un fallo de este control, que
#: es como se enseña a ignorarlo.
COMPROBACIONES = (
    ("total de la suite", r"selftest`\s*→\s*\*\*(\d+)/\d+",
     lambda: sum(_pruebas_por_suite().values())),
    ("reparto: unit", r"\bunit (\d+) ·", lambda: _pruebas_por_suite()["unit"]),
    ("reparto: contract", r"· contract (\d+) ·", lambda: _pruebas_por_suite()["contract"]),
    ("reparto: selftest", r"· selftest (\d+) ·", lambda: _pruebas_por_suite()["selftest"]),
    ("reparto: adversarial", r"· adversarial (\d+) =",
     lambda: _pruebas_por_suite()["adversarial"]),
    ("suma del reparto", r"adversarial \d+ = \*\*(\d+)\*\*",
     lambda: sum(_pruebas_por_suite().values())),
    ("controles del preflight", r"→ \*\*PASS, (\d+) controles\*\*", _controles_del_preflight),
)


def revisar(readme: str, comprobaciones=None) -> tuple:
    """`(problemas, comprobadas)` sobre un texto. La lógica, separada del fichero.

    Recibe el TEXTO y no la ruta para poder ejercitar los bordes —una afirmación que ya no está,
    una cifra que cambió— sin reescribir el README del repositorio. Un control que sólo se puede
    probar sobre su propio objeto real se prueba en el caso bueno y se supone el malo, que es
    justo el que importa.
    """
    comprobaciones = COMPROBACIONES if comprobaciones is None else comprobaciones
    problemas, comprobadas = [], 0
    for nombre, patron, medir in comprobaciones:
        m = re.search(patron, readme)
        if not m:
            problemas.append(
                f"«{nombre}»: no se encontró la afirmación en README.md con el patrón "
                f"`{patron}`. O se reescribió la tabla y hay que actualizar este control, o la "
                f"afirmación desapareció — las dos cosas las decide una persona, no este guion.")
            continue
        declarado, real = int(m.group(1)), medir()
        comprobadas += 1
        if declarado != real:
            problemas.append(f"«{nombre}»: el README declara {declarado} y hoy son {real}")
    return problemas, comprobadas


def main() -> int:
    if not COMPROBACIONES:
        print("  no hay ninguna afirmación que comprobar: un ámbito vacío no aprueba",
              file=sys.stderr)
        return 2

    readme = (RAIZ / "README.md").read_text(encoding="utf-8")
    problemas, comprobadas = revisar(readme)

    for p in problemas:
        print(f"  ✗ {p}", file=sys.stderr)
    if problemas:
        print(f"\n  {len(problemas)} de {len(COMPROBACIONES)} mediciones del README ya no dan "
              f"eso. Vuelva a medirlas y actualice la tabla; una cifra con fecha de hoy que hoy "
              f"es falsa se lee como verificada, y eso es peor que no ponerla.", file=sys.stderr)
        return 1
    print(f"  ✓ {comprobadas} mediciones del README siguen dando lo que declaran")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
