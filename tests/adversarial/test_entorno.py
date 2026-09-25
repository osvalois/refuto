# -*- coding: utf-8 -*-
"""La credencial que vive en una variable de entorno, no en un fichero.

La asimetría que esto cierra, medida el 2026-09-25
--------------------------------------------------
En el entorno de una sesión gobernada real: **70 variables y 7 credenciales de verdad** —una
clave de API de 164 caracteres, un token personal de GitHub, tres claves más y una contraseña—,
todas legibles con un `printenv`. Mientras tanto `.env` estaba protegido contra escritura y su
lectura pasó a `ask` en la Capa 1.

Es decir: el fichero vigilado y el mismo secreto en `$OPENAI_API_KEY`, libre. `printenv` era un
`cat` de todos los secretos de la máquina.

Las dos vías, y por qué hay que cerrar las dos
----------------------------------------------
1. **Nombrada**: `printenv OPENAI_API_KEY`, `echo $GITHUB_TOKEN`. Se atrapa comparando el NOMBRE
   contra `secret_env_deny`. Nunca el valor: mirar el valor de cada variable para decidir si es
   un secreto obligaría a leer todos los secretos para protegerlos.
2. **A granel**: `env`, `printenv`, `set`. No declaran ninguna lectura —medido,
   `efectos("env").lecturas == set()`— porque no hay argumento que derivar. Es la vía MÁS FÁCIL,
   así que cerrar sólo la primera habría sido cerrar la puerta y dejar la ventana.

Lo que estas pruebas vigilan por el otro lado
---------------------------------------------
Que no marque lo que no es. El sondeo inicial con `SESSION|AUTH|KEY` marcaba `SSH_AUTH_SOCK`
—la ruta de un socket, y quitarla rompe el agente de ssh—, `TERM_SESSION_ID` y `HARNESS_SESSION`,
que es de refuto. Un detector que marca lo normal enseña a ignorarlo, y entonces deja de proteger
de lo que sí.
"""

from __future__ import annotations

import os
import unittest
from pathlib import Path

from core.effects import efectos
from core.policy import ALLOW, ASK, DENY, Policy, decide_command

RAIZ = Path(__file__).resolve().parents[2]


class TestLaViaNombrada(unittest.TestCase):
    def setUp(self):
        self.p = Policy.default()

    def test_leer_una_variable_con_forma_de_credencial_lo_decide_una_persona(self):
        for orden in ("printenv OPENAI_API_KEY", "echo $GITHUB_TOKEN",
                      "printenv AWS_SECRET_ACCESS_KEY", "echo $MI_SERVICIO_PASSWORD",
                      "printenv ANTHROPIC_AUTH_TOKEN"):
            with self.subTest(orden=orden):
                self.assertEqual(ASK, decide_command(self.p, orden, RAIZ).outcome)

    def test_NO_marca_lo_que_no_es_una_credencial(self):
        """La mitad que evita que el control se desactive por ruidoso."""
        for orden in ("printenv PATH", "printenv HOME", "printenv SSH_AUTH_SOCK",
                      "printenv HARNESS_SESSION", "printenv TERM_SESSION_ID",
                      "echo $PWD", "echo $USER"):
            with self.subTest(orden=orden):
                self.assertEqual(ALLOW, decide_command(self.p, orden, RAIZ).outcome)

    def test_la_comparacion_es_por_nombre_y_no_por_valor(self):
        """Mirar el valor obligaría a leer todos los secretos para protegerlos."""
        self.assertTrue(self.p.is_secret_env("cualquier_cosa_TOKEN"))
        self.assertTrue(self.p.is_secret_env("github_token"), "debe ser insensible a mayúsculas")
        self.assertFalse(self.p.is_secret_env("PATH"))
        self.assertFalse(self.p.is_secret_env(""))


class TestLaViaAGranel(unittest.TestCase):
    def setUp(self):
        self.p = Policy.default()

    def test_un_volcado_del_entorno_se_pregunta(self):
        for orden in ("env", "printenv", "set", "declare -p", "env | grep KEY"):
            with self.subTest(orden=orden):
                self.assertEqual(ASK, decide_command(self.p, orden, RAIZ).outcome)

    def test_el_modelo_de_efectos_NO_deriva_nada_de_un_volcado(self):
        """Por eso hace falta enumerarlos: no hay argumento del que derivar la lectura."""
        self.assertEqual(set(), efectos("env").lecturas)

    def test_env_como_ENVOLTORIO_no_es_un_volcado(self):
        """`env FOO=1 orden` ajusta el entorno, no lo imprime. Marcarlo sería marcar la mitad
        de los lanzamientos con entorno ajustado."""
        self.assertEqual(ALLOW, decide_command(self.p, "env FOO=1 ls", RAIZ).outcome)

    def test_volcar_el_entorno_Y_escribir_fuera_es_exfiltracion(self):
        """La vía más fácil de todas, y la última en cerrarse: la redirección rompía la
        comprobación de «sólo banderas», así que `env > …` salía `allow`."""
        for orden in ("env > /tmp/claude-x/todo", "env >> /tmp/claude-x/t",
                      "printenv > ~/.claude/projects/p/memory/n.md",
                      "env | tee /tmp/claude-x/t"):
            with self.subTest(orden=orden):
                self.assertEqual(DENY, decide_command(self.p, orden, RAIZ).outcome)

    def test_escribir_algo_que_NO_es_el_entorno_sigue_pasando(self):
        self.assertEqual(ALLOW, decide_command(self.p, "echo hola > /tmp/claude-x/n",
                                               RAIZ).outcome)

    def test_sin_credenciales_en_el_entorno_un_volcado_no_molesta(self):
        """En una máquina limpia `env` es inofensivo, y preguntarlo sería ruido."""
        previo = dict(os.environ)
        try:
            for k in [k for k in os.environ if self.p.is_secret_env(k)]:
                os.environ.pop(k, None)
            self.assertEqual(ALLOW, decide_command(self.p, "env", RAIZ).outcome)
        finally:
            os.environ.clear()
            os.environ.update(previo)


class TestLaMonotoniaYElContrato(unittest.TestCase):
    def test_secret_env_deny_acumula(self):
        from core.refinement import ACUMULA, REGLAS
        self.assertEqual(ACUMULA, REGLAS["secret_env_deny"],
                         "marcar de más cuesta una consulta; marcar de menos cuesta el secreto")

    def test_un_espacio_puede_anadir_patrones_y_no_retirarlos(self):
        from core.refinement import refinar
        r = refinar({"schema": "harness.policy/v1", "version": "1"},
                    {"schema": "harness.policy/v1", "version": "1",
                     "secret_env_deny": ["MI_COSA_RARA"]})
        self.assertEqual("PASS", r.status, r.violaciones)
        efectivo = set(r.politica.secret_env_deny)
        self.assertIn("MI_COSA_RARA", efectivo)
        self.assertIn("*_API_KEY", efectivo, "la unión perdió lo que traía la raíz")

    def test_la_raiz_no_esta_vacia_asi_que_ACUMULA_no_cae_en_la_trampa(self):
        """`REDUCE` con raíz vacía convierte un campo en código muerto — pasó dos veces en dos
        días (`writable_paths` en ADR-0014, `privilege_grants` en ADR-0016). `ACUMULA` no tiene
        ese problema, y que la raíz traiga patrones es lo que hace útil el campo sin declararlo."""
        self.assertGreater(len(Policy.default().secret_env_deny), 20)


if __name__ == "__main__":
    unittest.main()
