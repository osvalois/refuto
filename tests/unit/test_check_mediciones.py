# -*- coding: utf-8 -*-
"""Al vigilante de las cifras del README lo vigila esto.

Por qué, y es la segunda mitad de una retractación
---------------------------------------------------
`scripts/check_mediciones.py` se añadió el 2026-09-25 porque las cifras de corrida del README
llevaban cinco commits desfasadas **con fecha del propio día** —declaraba 685 pruebas y 13
controles cuando eran 748 y 14—, y porque las cifras estructurales sí tenían quien las mirara
(`check_wiring`, `check_citas`) y éstas no.

Se entregó sin ninguna prueba. Es decir: el arreglo de «un control que nadie vigila» fue un
control que nadie vigilaba. Un guion de verificación que sólo se ha ejercitado en el caso bueno
—el README de hoy, que está al día— no ha demostrado lo único que importa de él: que **sabe
decir que no**.

Es el mismo criterio que `scripts/mutate_probe.py` aplica a sí mismo con sus controles
negativos `NC1`/`NC2`: sin demostrar que sabe informar `VIVA`, un 6/6 de mutaciones muertas es
`INCONCLUSIVE` y no un dato.
"""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
GUION = RAIZ / "scripts" / "check_mediciones.py"


def _cargar():
    spec = importlib.util.spec_from_file_location("check_mediciones", GUION)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["check_mediciones"] = mod
    spec.loader.exec_module(mod)
    return mod


CM = _cargar()

#: Comprobaciones de juguete, para ejercitar el criterio sin depender del README real.
FALSAS = (("una cifra", r"hay \*\*(\d+)\*\* cosas", lambda: 7),)


class TestSabeDecirQueNo(unittest.TestCase):
    """El control negativo. Sin él, un guion que devolviera 0 siempre pasaría por bueno."""

    def test_detecta_una_cifra_que_ya_no_da_eso(self):
        problemas, comprobadas = CM.revisar("hay **5** cosas", FALSAS)
        self.assertEqual(1, len(problemas), "una cifra falsa pasó por buena")
        self.assertEqual(1, comprobadas)
        self.assertIn("declara 5", problemas[0])
        self.assertIn("hoy son 7", problemas[0])

    def test_no_marca_una_cifra_que_sigue_dando_eso(self):
        problemas, comprobadas = CM.revisar("hay **7** cosas", FALSAS)
        self.assertEqual([], problemas)
        self.assertEqual(1, comprobadas)

    def test_una_afirmacion_que_desaparecio_no_se_da_por_buena(self):
        """El modo de fallo silencioso: si el patrón deja de casar, «no hay problema» sería
        indistinguible de «ya no se comprueba nada»."""
        problemas, comprobadas = CM.revisar("el README ya no dice eso", FALSAS)
        self.assertEqual(1, len(problemas))
        self.assertEqual(0, comprobadas, "no se comprobó ninguna y aun así habría aprobado")
        self.assertIn("no se encontró", problemas[0])


class TestSobreElREADMEDeVerdad(unittest.TestCase):
    def test_las_afirmaciones_declaradas_siguen_estando_en_el_readme(self):
        """Cada patrón tiene que CASAR. Un patrón que no casa no aprueba: informa de que la
        tabla se reescribió y nadie actualizó el control."""
        readme = (RAIZ / "README.md").read_text(encoding="utf-8")
        problemas, comprobadas = CM.revisar(readme)
        self.assertEqual(len(CM.COMPROBACIONES), comprobadas,
                         f"{len(CM.COMPROBACIONES) - comprobadas} afirmación(es) del README ya "
                         f"no se localizan: {problemas}")

    def test_y_todas_dan_lo_que_declaran(self):
        readme = (RAIZ / "README.md").read_text(encoding="utf-8")
        problemas, _ = CM.revisar(readme)
        self.assertEqual([], problemas)

    def test_el_ambito_no_puede_estar_vacio(self):
        """Un control con cero comprobaciones aprobaría siempre, que es lo contrario de un
        control. `main()` devuelve 2 en ese caso; aquí se fija que no llegue a ocurrir."""
        self.assertGreater(len(CM.COMPROBACIONES), 0)

    def test_no_comprueba_tiempos_a_proposito(self):
        """Un umbral de milisegundos falla en la máquina de otro, y un control que falla por
        motivos que no son el defecto se desactiva. La decisión se fija para que no se
        reintroduzca sin discutirla."""
        for nombre, _, _ in CM.COMPROBACIONES:
            with self.subTest(afirmacion=nombre):
                self.assertNotIn("segundo", nombre.lower())
                self.assertNotIn(" ms", nombre.lower())


class TestLoQueMideEsElCargadorYNoUnGrep(unittest.TestCase):
    def test_el_recuento_coincide_con_quien_decide_que_se_ejecuta(self):
        """`grep -c "def test_"` daba uno de más: el texto aparece dentro de una cadena. El
        cargador de `unittest` es el que decide qué corre, así que es el que cuenta."""
        import unittest as ut

        por_suite = CM._pruebas_por_suite()                            # noqa: SLF001
        for suite, n in por_suite.items():
            with self.subTest(suite=suite):
                real = ut.TestLoader().discover(str(RAIZ / "tests" / suite),
                                                top_level_dir=str(RAIZ)).countTestCases()
                self.assertEqual(real, n)


if __name__ == "__main__":
    unittest.main()
