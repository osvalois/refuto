# -*- coding: utf-8 -*-
"""El metodo del espacio. Cada prueba fija una forma de dejar al agente sin disciplina.

Medido en un espacio real: el espacio declaraba siete etapas, cinco niveles de
evidencia y un contrato de vacuidad, y el informe de sesion de 104 lineas mencionaba AUDIT
cero veces, «etapa» cero y «atestacion» cero. El agente abria sin saber que existia una escala
de evidencia, asi que afirmaba en E0 creyendo haber terminado.
"""

from __future__ import annotations

import unittest

from core.metodo import leer, seccion
from tests.fixtures import Workspace


MINIMO = {
    "schema": "x:pipeline:v1",
    "etapas": [
        {"id": "AUDIT", "requiere": [], "porque": "que puede salir"},
        {"id": "TEST", "requiere": ["AUDIT"], "porque": "prueba adversarial"},
    ],
    "niveles_evidencia": {"E0": "CLAIMED", "E3": "TESTED"},
    "rutas": {"ledger": "evidencia/cadena.jsonl"},
}


class TestLeer(unittest.TestCase):

    def test_sin_declaracion_no_se_inventa_metodo(self):
        """Un metodo supuesto es peor que ninguno: se obedece igual."""
        with Workspace("m-vacio") as ws:
            m = leer(ws.root)
            self.assertFalse(m)
            self.assertEqual([], seccion(ws.root))

    def test_lee_etapas_niveles_y_rutas(self):
        with Workspace("m-min") as ws:
            ws.json(".harness/pipeline.json", MINIMO)
            m = leer(ws.root)
            self.assertTrue(m)
            self.assertEqual(["AUDIT", "TEST"], [e.id for e in m.etapas])
            self.assertEqual(["AUDIT"], m.etapas[1].requiere)
            self.assertEqual(2, len(m.niveles))
            self.assertEqual("evidencia/cadena.jsonl", m.rutas["ledger"])

    def test_denuncia_una_cadena_que_no_cierra(self):
        """Una etapa que exige otra inexistente es una cadena rota, y callarlo la da por buena."""
        with Workspace("m-rota") as ws:
            doc = dict(MINIMO)
            doc["etapas"] = [{"id": "TEST", "requiere": ["FANTASMA"], "porque": "x"}]
            ws.json(".harness/pipeline.json", doc)
            m = leer(ws.root)
            self.assertIn("FANTASMA", m.aviso)
            self.assertIn("no cierra", m.aviso)

    def test_un_json_roto_se_dice_en_vez_de_callarse(self):
        with Workspace("m-roto") as ws:
            ws.file(".harness/pipeline.json", "{ esto no es json")
            m = leer(ws.root)
            self.assertIn("no se pudo leer", m.aviso)

    def test_detecta_el_instrumento_del_espacio(self):
        with Workspace("m-inst") as ws:
            ws.json(".harness/pipeline.json", MINIMO)
            ws.file(".harness/hz", "#!/bin/sh\n")
            self.assertEqual(".harness/hz", leer(ws.root).instrumento)

    def test_acepta_etapas_como_lista_de_cadenas(self):
        """Otro espacio declarara su metodo de otra forma; leerlo no puede exigir la nuestra."""
        with Workspace("m-str") as ws:
            ws.json(".harness/pipeline.json", {"etapas": ["UNO", "DOS"]})
            self.assertEqual(["UNO", "DOS"], [e.id for e in leer(ws.root).etapas])


class TestSeccion(unittest.TestCase):

    def test_el_informe_nombra_las_etapas_y_su_orden(self):
        with Workspace("s-etapas") as ws:
            ws.json(".harness/pipeline.json", MINIMO)
            texto = "\n".join(seccion(ws.root))
            self.assertIn("AUDIT", texto)
            self.assertIn("exige `AUDIT`", texto)
            self.assertIn("no es una sugerencia", texto)

    def test_el_informe_nombra_la_escala_de_evidencia(self):
        with Workspace("s-niveles") as ws:
            ws.json(".harness/pipeline.json", MINIMO)
            texto = "\n".join(seccion(ws.root))
            self.assertIn("E0", texto)
            self.assertIn("E3", texto)
            self.assertIn("en qué nivel está", texto)

    def test_el_contrato_de_vacuidad_llega_entero(self):
        with Workspace("s-vac") as ws:
            doc = dict(MINIMO)
            doc["contrato_vacuidad"] = {
                "_reason": "Ambito vacio NUNCA da PASS.",
                "inaplicable_declarado": {"G-X": {"desde": "2026-09-17", "porque": "no hay"}}}
            ws.json(".harness/pipeline.json", doc)
            texto = "\n".join(seccion(ws.root))
            self.assertIn("Ambito vacio NUNCA da PASS", texto)
            self.assertIn("G-X", texto)
            self.assertIn("2026-09-17", texto)

    def test_las_clases_declaran_lo_que_prohiben(self):
        with Workspace("s-clases") as ws:
            doc = dict(MINIMO)
            doc["clases"] = {"literatura": {"formatos": [".md"], "prohibe": [".pdf"]},
                             "papers": {"formatos": [".md"], "exige_arte_previo": True}}
            ws.json(".harness/pipeline.json", doc)
            texto = "\n".join(seccion(ws.root))
            self.assertIn("PROHÍBE", texto)
            self.assertIn(".pdf", texto)
            self.assertIn("arte previo", texto)


if __name__ == "__main__":
    unittest.main()
