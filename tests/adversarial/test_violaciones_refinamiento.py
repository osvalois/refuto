# -*- coding: utf-8 -*-
"""Las violaciones que el refinamiento tenía, y que ahora no puede tener.

Cinco encontradas el 2026-09-23 auditando la implementación recién hecha. Tres se cierran
aquí; dos quedan **declaradas y abiertas** por decisión, no por olvido — ver el final.

Lo que estas pruebas tienen de distinto
---------------------------------------
Las de `test_monotonia.py` atacan declarando campos en padre e hijo. **Todas pasaban** con el
código defectuoso, porque el agujero estaba justo en lo que ninguna escribía: **el campo que
el padre NO declara**. Un ataque sólo prueba lo que toca, y diez ataques que comparten el
mismo punto ciego no son diez pruebas.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from core.policy import (DEFAULT_COMMAND_DENY, HerenciaIrresoluble, Policy, decide_command)
from core.refinement import MODO, ORDEN_MODOS, REGLAS

PADRE_CALLA = {"schema": "harness.policy/v1", "name": "cliente", "version": "1",
               "protected_paths": ["del-cliente/**"]}


def _montar(hijo: dict, padre: dict = PADRE_CALLA) -> Path:
    d = Path(tempfile.mkdtemp())
    (d / ".harness").mkdir()
    (d / ".harness" / "cliente.json").write_text(json.dumps(padre), encoding="utf-8",
                                                 newline="\n")
    (d / ".harness" / "policy.json").write_text(json.dumps(hijo), encoding="utf-8",
                                                newline="\n")
    return d / ".harness" / "policy.json"


def _hijo(**campos) -> dict:
    return {"schema": "harness.policy/v1", "name": "proyecto", "version": "1",
            "extends": "cliente.json", **campos}


class TestElPadreAportaLoQueAPLICA_noLoQueESCRIBE(unittest.TestCase):
    """V1 y V6. El refinamiento comparaba documentos crudos.

    Los valores de fábrica sólo se materializan cuando `Policy.from_dict` rellena un campo
    AUSENTE, así que un padre que no los escribía aportaba el conjunto vacío a la unión. Medido
    antes del arreglo: hijo con una orden denegada → efectivo **1** entrada, y `rm -rf /` y
    `sudo` salían `allow`.

    El agujero NO lo introduce el refinamiento —un hijo sin `extends` que declara una lista
    corta pierde igual las 16—: lo aporta `from_dict`, donde declarar un campo lo sustituye.
    Lo que la herencia añade es convertirlo en el camino por defecto, porque el propósito de un
    hijo es declarar sólo lo suyo.
    """

    def test_el_hijo_no_puede_descartar_las_denegaciones_de_fabrica(self):
        pol = Policy.load(_montar(_hijo(command_deny=["mia:*"])))
        self.assertGreaterEqual(
            len(pol.command_deny), len(DEFAULT_COMMAND_DENY),
            "el hijo descartó las órdenes denegadas de fábrica declarando una lista corta")
        for peligrosa in ("rm -rf /", "sudo algo"):
            self.assertEqual("deny", decide_command(pol, peligrosa).outcome,
                             f"«{peligrosa}» pasó a permitida al heredar")
        self.assertEqual("deny", decide_command(pol, "mia x").outcome,
                         "lo que el hijo añade tiene que seguir aplicándose")

    def test_la_CIMA_de_la_cadena_si_puede_vaciar_un_campo(self):
        """V6 queda ABIERTA, y al medirla resultó no ser una violación del refinamiento.

        Un padre que declara `command_deny: []` está en la cima: no hay ninguna capa por
        encima a la que esté relajando. `from_dict` honra su declaración explícita, y eso es
        correcto — una capa de cliente tiene autoridad para decir exactamente lo que dice.

        Lo que sí es un hueco, y es ARQUITECTÓNICO y no de esta función: los valores de fábrica
        de refuto viven sólo como constantes en `core/policy.py`. No hay ninguna política base
        EN DISCO que un cliente pueda extender, así que la cima de toda cadena real es el
        cliente y nadie vigila lo que la cima retira.

        Lo cerraría un `policies/base.json` versionado —con `refuto` como capa 1 de verdad—,
        no un parche aquí. Esta prueba fija el comportamiento actual: si alguien lo cambia sin
        crear esa capa, cae y obliga a explicar por qué.
        """
        pol = Policy.load(_montar(_hijo(), {**PADRE_CALLA, "command_deny": []}))
        self.assertEqual("allow", decide_command(pol, "rm -rf /").outcome,
                         "el comportamiento documentado cambió: ¿existe ya la capa base?")


class TestEndureceNoSeBurlaPorOmision(unittest.TestCase):
    """V7 — no estaba en la lista y es la peor de la familia.

    El padre no escribe `block_secret_content` (de fábrica `True`); el hijo lo pone a `False`.
    Antes: la cadena resolvía **sin violación** y la detección de secretos quedaba apagada. El
    invariante que `core/refinement.py` declara en su propio docstring, falsado por una
    omisión — sin malicia y sin nada que lo reportara.
    """

    def test_apagar_una_comprobacion_que_el_padre_no_escribe_se_rechaza(self):
        self.assertTrue(Policy.default().block_secret_content,
                        "premisa: de fábrica la detección está encendida")
        with self.assertRaises(HerenciaIrresoluble) as cm:
            Policy.load(_montar(_hijo(block_secret_content=False)))
        self.assertIn("block_secret_content", str(cm.exception))

    def test_encenderla_cuando_el_padre_la_apaga_si_se_puede(self):
        """La otra mitad: endurecer siempre se puede."""
        pol = Policy.load(_montar(_hijo(block_secret_content=True),
                                  {**PADRE_CALLA, "block_secret_content": False}))
        self.assertTrue(pol.block_secret_content)


class TestElModoDelGuardianEsUnaRestriccion(unittest.TestCase):
    """V5. `default_modes` estaba clasificado como `PROPIO` — «no es seguridad sino
    interacción». Falsado midiendo: `adapters/claude.py` lo compila a
    `permissions.defaultMode`, así que un hijo podía pasar de `ask` a `bypassPermissions`.

    Matiz que la medición dio y que no se pierde: **NO está comprobado** que
    `bypassPermissions` anule el gancho `PreToolUse`. Eso es comportamiento de Claude Code y
    aquí está `NOT_RUN`. La reclasificación procede igual — lo que no se puede afirmar no se
    concede — pero el titular «apaga la consulta a la persona» sería más de lo que se midió.
    """

    def _con_modos(self, padre_modo, hijo_modo, runtime="claude"):
        return _montar(_hijo(default_modes={runtime: hijo_modo}),
                       {**PADRE_CALLA, "default_modes": {runtime: padre_modo}})

    def test_el_hijo_no_puede_ablandar_el_modo(self):
        with self.assertRaises(HerenciaIrresoluble) as cm:
            Policy.load(self._con_modos("ask", "bypassPermissions"))
        self.assertIn("más permisivo", str(cm.exception))

    def test_el_hijo_si_puede_endurecerlo(self):
        pol = Policy.load(self._con_modos("acceptEdits", "ask"))
        self.assertEqual("ask", pol.default_modes["claude"])

    def test_un_modo_no_rankeable_exige_igualdad(self):
        """`declared-in-agent` y `unknown` vienen de fábrica y no se pueden ordenar: su
        permisividad la decide otro fichero, o no se sabe. Sin orden no hay demostración."""
        self.assertNotIn("unknown", ORDEN_MODOS)
        with self.assertRaises(HerenciaIrresoluble) as cm:
            Policy.load(self._con_modos("unknown", "default", runtime="codex"))
        self.assertIn("no se puede demostrar", str(cm.exception))

    def test_lo_que_el_hijo_no_menciona_conserva_el_modo_del_padre(self):
        pol = Policy.load(_montar(_hijo(), {**PADRE_CALLA,
                                           "default_modes": {"claude": "ask"}}))
        self.assertEqual("ask", pol.default_modes["claude"])

    def test_default_modes_ya_no_esta_clasificado_como_propio(self):
        """Regresión de la clasificación, no del comportamiento.

        La guarda de monotonía comprueba que TODO campo tenga regla; no puede comprobar que
        la regla sea la correcta. `default_modes: PROPIO` pasó esa guarda y era el agujero.
        Esta prueba fija la decisión para que revertirla cueste explicarlo.
        """
        self.assertEqual(MODO, REGLAS["default_modes"])


class TestLoQueSIGUE_abierto(unittest.TestCase):
    """V2 / V3 / V4 · `extends` sale del espacio. **Declarado, no cerrado.**

    Por qué no se cierra, y no es pereza: el arreglo obvio —«exigir que el padre quede dentro
    del espacio»— **mata la arquitectura**. El padre legítimo de un proyecto es la política de
    su cliente, que vive un nivel por encima: la contención por espacio daría falso justo en
    el caso que la cadena existe para permitir.

    Severidad real, y por eso se puede dejar abierto con la cara descubierta: explotarlo exige
    escribir el `.harness/policy.json` del hijo, que está en `protected_paths`. Es una
    diferencia de defensa en profundidad respecto de `decide_write` —que sí aplica contención
    con `realpath`— no una escalada desde cero.

    Esta prueba **documenta el comportamiento actual**. Si alguien cierra la contención, cae, y
    ése es el momento de decidir a conciencia dónde se declara la raíz de políticas base.
    """

    def test_extends_a_una_ruta_de_fuera_del_espacio_resuelve_hoy(self):
        fuera = Path(tempfile.mkdtemp())
        (fuera / "ajena.json").write_text(json.dumps(
            {"schema": "harness.policy/v1", "name": "ajena", "version": "1",
             "protected_paths": ["z/**"]}), encoding="utf-8", newline="\n")
        d = Path(tempfile.mkdtemp())
        (d / ".harness").mkdir()
        (d / ".harness" / "policy.json").write_text(json.dumps(
            {"schema": "harness.policy/v1", "name": "p", "version": "1",
             "extends": str(fuera / "ajena.json")}), encoding="utf-8", newline="\n")
        pol = Policy.load(d / ".harness" / "policy.json")
        self.assertIn("z/**", pol.protected_paths,
                      "el comportamiento documentado cambió: revise la decisión de V2/V3/V4")


if __name__ == "__main__":
    unittest.main()
