# -*- coding: utf-8 -*-
"""El contrato que todas las puertas cumplen. Si esto falla, nada de lo demás vale."""

from __future__ import annotations

import unittest

from core.model import (
    BLOCKED, BLOCKING, FAIL, NON_PASSING, NOT_APPLICABLE, NOT_EXECUTABLE, PASS, Result, STATUSES,
    blocked, not_applicable, not_executable,
)
from gates.base import GATES


class TestResultContract(unittest.TestCase):
    def test_solo_cinco_estados(self):
        """Eran cuatro. `NOT_APPLICABLE` es el quinto, y esta prueba se actualizó a propósito:
        afirmaba que los estados eran cuatro y eso dejó de ser cierto al añadirlo."""
        self.assertEqual(set(STATUSES),
                         {PASS, FAIL, BLOCKED, NOT_EXECUTABLE, NOT_APPLICABLE})

    def test_un_estado_invalido_se_rechaza_al_construir(self):
        """Colar un estado nuevo no debe ser posible: el informe se compone sobre estos cinco."""
        with self.assertRaises(ValueError):
            Result("X", "y", "VERDE")

    def test_no_aprueba_ninguno_de_los_cuatro_estados_restantes(self):
        self.assertEqual(NON_PASSING, {FAIL, BLOCKED, NOT_EXECUTABLE, NOT_APPLICABLE})
        for status in NON_PASSING:
            self.assertFalse(Result("X", "y", status, measure="motivo").passing,
                             f"{status} no puede considerarse aprobado")

    def test_no_aplica_no_retiene_pero_tampoco_aprueba(self):
        """Las dos mitades del estado, y las dos importan.

        Si `NOT_APPLICABLE` bloqueara, un espacio sin servidores MCP no podría integrar nunca.
        Si contara como aprobado, volveríamos al defecto que lo motivó: una puerta verde que
        no comprobó nada.
        """
        self.assertNotIn(NOT_APPLICABLE, BLOCKING)
        self.assertIn(NOT_APPLICABLE, NON_PASSING)

    def test_no_aplica_exige_motivo_declarado(self):
        """«No aplica» sin motivo es un aprobado cómodo con otro nombre."""
        with self.assertRaises(ValueError):
            Result("X", "y", NOT_APPLICABLE)
        with self.assertRaises(ValueError):
            Result("X", "y", NOT_APPLICABLE, measure="   ")
        r = not_applicable("X", "y", "no hay servidores MCP declarados")
        self.assertEqual(r.status, NOT_APPLICABLE)
        self.assertIn("no hay servidores MCP", r.measure)

    def test_una_corrida_sin_ambito_no_es_integrable(self):
        """Todas las puertas NOT_APPLICABLE: nada se comprobó, luego nada se aprueba."""
        from core.evidence import verdict_of
        vac = [not_applicable("G-A", "a", "sin sujeto"), not_applicable("G-B", "b", "sin sujeto")]
        self.assertNotIn("INTEGRABLE", verdict_of(vac).split("—")[0].replace("NO INTEGRABLE", ""))
        self.assertIn("SIN ÁMBITO", verdict_of(vac))
        mixto = [Result("G-C", "c", PASS), not_applicable("G-A", "a", "sin sujeto")]
        self.assertTrue(verdict_of(mixto).startswith("INTEGRABLE"))

    def test_una_corrida_con_bloqueo_no_es_integrable(self):
        """BLOCKED nunca permite integrar: lo que no se pudo comprobar no puede pasar por aprobado."""
        from core.evidence import verdict_of
        b = [Result("G-C", "c", PASS), blocked("G-A", "a", "falta algo")]
        v = verdict_of(b)
        self.assertIn("NO INTEGRABLE TODAVÍA", v)
        self.assertFalse(v.startswith("INTEGRABLE"))

    def test_una_corrida_con_error_de_ejecucion_no_es_integrable(self):
        """NOT_EXECUTABLE nunca permite integrar: si falló la propia puerta, la corrida no es válida."""
        from core.evidence import verdict_of
        ne = [Result("G-C", "c", PASS), not_executable("G-A", "a", "explotó", RuntimeError("boom"))]
        v = verdict_of(ne)
        self.assertIn("NO INTEGRABLE — hay verificaciones que no se pudieron ejecutar", v)
        self.assertFalse(v.startswith("INTEGRABLE"))

    def test_una_puerta_que_revienta_no_aprueba(self):
        r = not_executable("G", "puerta", "explotó", RuntimeError("boom"))
        self.assertEqual(r.status, NOT_EXECUTABLE)
        self.assertIn("boom", r.measure)

    def test_una_dependencia_ausente_bloquea_no_aprueba(self):
        self.assertEqual(blocked("G", "puerta", "falta X").status, BLOCKED)

    def test_toda_puerta_registrada_expone_run(self):
        import importlib
        for gate_id, (module, _, _) in GATES.items():
            mod = importlib.import_module(module)
            self.assertTrue(callable(getattr(mod, "run", None)),
                            f"{gate_id} ({module}) no expone run(ctx)")

    def test_toda_puerta_serializa_al_mismo_esquema(self):
        d = Result("G-X", "n", PASS).to_dict()
        for key in ("schema", "id", "name", "status", "severity", "measure",
                    "findings", "evidence", "provenance", "duration_ms"):
            self.assertIn(key, d)


class TestAdapterContract(unittest.TestCase):
    """Todo adapter cumple el mismo contrato, y ninguno miente sobre lo que no puede."""

    def setUp(self):
        from adapters.registry import all_specs
        self.specs = all_specs()

    def test_todos_declaran_lo_minimo(self):
        for s in self.specs:
            self.assertTrue(s.name and s.binary, f"{s} incompleto")
            self.assertTrue(s.version_args and s.start_args, f"{s.name} sin sondeo básico")

    def test_todos_declaran_como_hacer_el_handshake(self):
        for s in self.specs:
            has_acp = s.speaks_acp and s.acp_args
            has_native = type(s).native_handshake is not type(s).__mro__[-2].native_handshake
            self.assertTrue(has_acp or has_native or s.name == "codex",
                            f"{s.name} no dice cómo hacer un handshake")

    def test_compile_policy_devuelve_la_forma_del_contrato(self):
        from core.policy import Policy, compile_for
        p = Policy.default()
        for s in self.specs:
            out = compile_for(p, s)
            for key in ("supported", "artifacts", "unenforceable", "notes"):
                self.assertIn(key, out, f"{s.name}: falta {key}")
            self.assertIsInstance(out["unenforceable"], list)

    def test_un_adapter_que_no_soporta_politica_lo_declara(self):
        """Un adapter sin política NO puede devolver `unenforceable: []`: eso diría que lo
        aplica todo, que es exactamente la mentira que este contrato existe para impedir."""
        from core.policy import Policy, compile_for
        for s in self.specs:
            out = compile_for(Policy.default(), s)
            if not out["supported"]:
                self.assertTrue(out["unenforceable"],
                                f"{s.name} no soporta política y no declara qué no aplica")

    def test_normalize_event_nunca_revienta(self):
        for s in self.specs:
            for raw in ({}, {"type": "x"}, {"method": "session/update"}, {"message": None}):
                s.normalize_event(raw)


class TestInvariantePassSinHallazgos(unittest.TestCase):
    """El invariante que hace imposible, en las trece puertas a la vez, el defecto de G-HUMAN."""

    def test_pass_con_hallazgos_se_rechaza_al_construir(self):
        from core.model import Finding
        with self.assertRaises(ValueError) as cm:
            Result("G-X", "n", PASS, findings=[Finding("a.py", "algo va mal")])
        self.assertIn("no aprueba", str(cm.exception))

    def test_los_demas_estados_si_admiten_hallazgos(self):
        from core.model import Finding
        for status in (FAIL, BLOCKED, NOT_EXECUTABLE):
            Result("G-X", "n", status, findings=[Finding("a.py", "algo")])

    def test_pass_sin_hallazgos_es_valido(self):
        self.assertTrue(Result("G-X", "n", PASS).passing)

    def test_ninguna_puerta_real_devuelve_PASS_con_hallazgos(self):
        """Se comprueba sobre las trece puertas contra un espacio vacío: ninguna puede
        construir un resultado que viole el invariante, porque el constructor lo impide."""
        from tests.fixtures import Workspace
        from gates.base import GATES, run_gate
        with Workspace("inv") as ws:
            ws.manifest(gates=sorted(GATES))
            for gate_id in GATES:
                r = run_gate(gate_id, ws.context(offline=True))
                if r.status == PASS:
                    self.assertFalse(r.findings, f"{gate_id} aprobó con hallazgos")
