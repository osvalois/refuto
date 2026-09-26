# -*- coding: utf-8 -*-
"""Qué de la norma del motor llega a un espacio ya instalado, y qué no.

La hipótesis que esto falsa a medias
------------------------------------
`init`/`install` escriben la norma ENTERA copiada y `upgrade` **no toca la política** por
diseño. De ahí se sigue, aparentemente, que ninguna corrección de la norma base llega a un
espacio ya instalado. Medido el 2026-09-24, y es falso en la mitad que más importa:

    `Policy.load` compone TODA política con la raíz del motor (`core.trust.componer_con_raiz`)
    y `protected_paths` ACUMULA → el efectivo es la UNIÓN.

Así que una protección NUEVA se propaga sola, sin `upgrade` y sin tocar el fichero del espacio.
Lo que no se propaga es la EXCEPCIÓN, y por la razón contraria: `writable_paths` es `REDUCE` y
la lista del hijo manda, así que un espacio que declaró la excepción anclada a la raíz se queda
con ella y **no se enfrentaba de nada**.

Estas pruebas fijan las dos mitades por separado. Juntarlas en una sola afirmación
—«la norma se propaga» o «no se propaga»— es exactamente el error que se cometió al razonarlo
sin medirlo, y el que costó una retractación.
"""

from __future__ import annotations

import json
import unittest

from core.policy import DEFAULT_PROTECTED, DEFAULT_WRITABLE, Policy, decide_write
from tests.fixtures import Workspace

#: La política tal como la escribía el instalador ANTES de que los patrones cubrieran el
#: anidamiento. Se escribe literal a propósito: derivarla de las constantes de hoy haría que la
#: prueba se moviera con ellas y dejara de describir a ningún espacio real.
NORMA_ANTERIOR = {
    "schema": "harness.policy/v1",
    "version": "1",
    "protected_paths": [
        "verification/**", "verificacion/**", ".kiro/steering/**", ".harness/**",
        "inputs/**", "insumos/**", "evidence/**", "evidencia/**", "gates/**", "policies/**",
        "*.lock.json", "harness.manifest.json", "harness.lock.json",
    ],
    "writable_paths": [".harness/memory/**"],
}


class TestLaProteccionNuevaSePropagaSola(unittest.TestCase):
    """`ACUMULA` + composición con la raíz del motor ⟹ el efectivo es la unión."""

    def _cargar(self, ws):
        ruta = ws.json(".harness/policy.json", NORMA_ANTERIOR)
        return Policy.load(ruta)

    def test_un_espacio_con_la_norma_anterior_protege_los_repos_hijos(self):
        """Sin `upgrade`, sin tocar su fichero, y aunque su fichero no lo diga."""
        with Workspace("norma-anterior") as ws:
            pol = self._cargar(ws)
            for ruta in ("repo-hijo/.harness/bin/guard",
                         "repo-hijo/.harness/policy.json",
                         "repo-hijo/evidence/run.json",
                         "a/b/repo-nieto/gates/g.py"):
                with self.subTest(ruta=ruta):
                    self.assertEqual("deny", decide_write(pol, ws.root, ruta).outcome,
                                     "la protección del motor no llegó al espacio instalado")

    def test_y_el_fichero_del_espacio_NO_lo_declara(self):
        """La contraparte: sin esto, lo de arriba lo satisfaría un fichero ya corregido."""
        self.assertNotIn("**/.harness/**", NORMA_ANTERIOR["protected_paths"])
        with Workspace("norma-anterior-decl") as ws:
            escrito = json.loads((ws.json(".harness/policy.json", NORMA_ANTERIOR))
                                 .read_text(encoding="utf-8"))
            self.assertEqual(NORMA_ANTERIOR["protected_paths"], escrito["protected_paths"])

    def test_toda_proteccion_de_fabrica_acaba_cubierta(self):
        with Workspace("norma-anterior-todas") as ws:
            pol = self._cargar(ws)
            faltan = [p for p in DEFAULT_PROTECTED
                      if not pol.is_protected(p.removeprefix("**/").removesuffix("/**")
                                              .replace("*", "sonda"))]
            self.assertEqual([], faltan, f"no se propagaron: {faltan}")


class TestLaExcepcionNoSePropagaYSeDeclara(unittest.TestCase):
    """`REDUCE`: la lista del hijo manda, así que una excepción nueva NO le llega."""

    def test_los_repos_hijos_se_quedan_sin_memoria_de_agente(self):
        with Workspace("excepcion-vieja") as ws:
            pol = Policy.load(ws.json(".harness/policy.json", NORMA_ANTERIOR))
            self.assertEqual("allow", decide_write(pol, ws.root,
                                                   ".harness/memory/nota.md").outcome)
            self.assertEqual("deny", decide_write(pol, ws.root,
                                                  "repo-hijo/.harness/memory/nota.md").outcome,
                             "la excepción del motor se propagó, y `REDUCE` dice que no puede")

    def test_upgrade_lo_MIDE_y_lo_nombra(self):
        """Una denegación colateral que el dueño no pidió tiene que ser visible.

        No es un agujero —es más estricto, no menos— y precisamente por eso nada la señalaba: no
        rompe ninguna puerta, sólo impide callando que los repositorios hijos recuerden.
        """
        import refuto

        with Workspace("deriva-medida") as ws:
            ws.json(".harness/policy.json", NORMA_ANTERIOR)
            deriva = refuto._deriva_de_norma(ws.root)
            self.assertIn("**/.harness/memory/**", deriva,
                          f"la deriva real no se detectó; medido: {deriva}")

    def test_un_espacio_al_dia_no_declara_deriva(self):
        """Sin esta mitad, la de arriba se satisface declarando deriva siempre."""
        import refuto

        with Workspace("sin-deriva") as ws:
            ws.json(".harness/policy.json", Policy.default().to_dict())
            self.assertEqual([], refuto._deriva_de_norma(ws.root))

    def test_la_excepcion_de_fabrica_cubre_cualquier_profundidad(self):
        """La corrección que el espacio se está perdiendo, enunciada sobre la norma de hoy."""
        pol = Policy.default()
        self.assertEqual(("**/.harness/memory/**",), tuple(DEFAULT_WRITABLE))
        self.assertTrue(pol.is_writable("repo-hijo/.harness/memory/nota.md"))


if __name__ == "__main__":
    unittest.main()
