# -*- coding: utf-8 -*-
"""H-03 · Política canónica. Se escribe una vez y se compila a cada runtime.

El hallazgo que motiva este módulo
----------------------------------
«Proteger al juez» estaba escrito dos veces, en dos vocabularios: `.kiro/hooks/*.json` con
`PreToolUse`/`fsWrite` (del IDE) y `hooks{}` de cada agente con `preToolUse`/`fs_write` (del
CLI). El guardián de rutas sólo estaba enganchado en el primero. Como el orquestador siempre
llama al CLI, **el control declarado nunca corría en la ruta que se usa**.

Una política escrita dos veces no es una política duplicada: es dos políticas, y divergen. Aquí
hay una fuente y N compilaciones, y cada compilación declara qué parte NO puede aplicar.

Las tres capas, y por qué hacen falta las tres
----------------------------------------------
1. **Compilada** al vocabulario del runtime (allow/deny de Claude, Policy Engine de Gemini,
   `allowedTools` de Kiro). Barata, la aplica el agente, y no ve el contenido.
2. **Guardián** (`core.guard`), un solo programa que todos los ganchos invocan. Ve el contenido
   y la ruta resuelta, así que atrapa lo que el patrón no ve: enlaces simbólicos, `..`,
   secretos dentro del texto.
3. **Fuera del alcance del agente**: rama protegida y CI. Es la única capa que el agente no
   puede tocar, y por eso las otras dos se declaran *preventivas*, no *garantías*.

Ninguna de las tres se presenta como suficiente. Declararlo es parte del control.
"""

from __future__ import annotations

import fnmatch
import json
import os
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

POLICY_SCHEMA = "harness.policy/v1"

#: Lo que un agente no puede escribir nunca, porque es lo que lo juzga o lo que prueba lo que
#: hizo. Un agente que puede editar su propia verificación no está pasando la verificación:
#: está moviendo la puerta.
#:
#: Estas rutas son GENÉRICAS a propósito, y ésa es una corrección. La lista llevaba
#: `.nucleo.lock.json` y `nucleo.json`: los ficheros de UN repositorio concreto que no se
#: publica. Fuera de él protegían el vacío, y una regla que no cubre nada se lee en el informe
#: de sesión —donde se enumeran una a una— como una protección que existe. `*.lock.json` ya
#: cubre cualquier lock, incluido aquél. Los nombres en español (`verificacion/`, `evidencia/`,
#: `insumos/`) se quedan porque son la palabra común, no el nombre de nadie; un espacio con
#: otra nomenclatura la declara en su `.harness/policy.json`, que se fusiona con ésta.
DEFAULT_PROTECTED = (
    "verification/**", "verificacion/**",
    ".kiro/steering/**", ".harness/**",
    "inputs/**", "insumos/**",
    "evidence/**", "evidencia/**",
    "gates/**", "policies/**",
    "*.lock.json",
    "harness.manifest.json", "harness.lock.json",
)

#: Excepciones DENTRO de lo protegido. Se comprueban ANTES que `protected_paths`.
#:
#: `.harness/**` protege la evidencia, la política y el estado — y con ellos arrastraba la
#: MEMORIA, que vive en `.harness/memory/` y cuyo contrato es el contrario. `core.memory` lo
#: dice en su primera línea: «memoria no es evidencia, y mezclarlas arruina las dos… la
#: política protege una y no la otra». No lo hacía: el mismo patrón cubría las dos, así que el
#: agente no podía recordar nada. Medido en un espacio real: `.harness/memory/` **no
#: existe** después de una semana de uso, porque toda escritura que lo habría creado se rechazó.
DEFAULT_WRITABLE = (
    ".harness/memory/**",
)

#: Raíces FUERA del espacio donde escribir SÍ es legítimo, declaradas una a una.
#:
#: `fuera-del-espacio` existe para atrapar travesía de directorios, y hace bien. Pero un agente
#: tiene dos sitios propios que por definición NO están en el espacio de trabajo: su memoria
#: persistente y su cuaderno de borrador de la sesión. Rechazarlos no impide ningún daño —no son
#: del proyecto— y sí impide justo lo que se le pide al agente: recordar entre sesiones y
#: calcular aparte sin ensuciar el árbol. Medido en un diario real: 39 rechazos por esta
#: regla, y los más repetidos son la memoria del propio agente y su cuaderno.
#:
#: Se declara por patrón y no con un «permite fuera del espacio»: la diferencia entre una
#: excepción nombrada y un agujero es que la excepción se puede leer y discutir.
DEFAULT_EXTERNAL_WRITE = (
    "~/.claude/projects/*/memory/**",     # la memoria persistente de Claude Code
    "/tmp/claude-*/**",                   # el cuaderno de la sesión
    "/private/tmp/claude-*/**",           # el mismo, como lo resuelve macOS
)

#: Rutas cuyo contenido nunca debe leerse, aunque el agente pida.
DEFAULT_SECRET_READ_DENY = (
    "**/.env", "**/.env.*", "**/secrets/**", "**/*.pem", "**/*.key",
    "**/id_rsa", "**/id_ed25519", "**/credentials", "**/.netrc",
    "**/auth.json", "**/.aws/credentials",
)

#: Órdenes que nunca se ejecutan. Cada una corresponde a una forma de perder trabajo o datos.
DEFAULT_COMMAND_DENY = (
    "rm -rf:*", "rm -fr:*", "rm -Rf:*", "rm --recursive --force:*",
    "sudo:*", "chmod -R 777:*", "dd:*", "mkfs:*",
    "git push --force:*", "git push -f:*",
    "curl* | sh", "curl* | bash", "wget* | sh", "wget* | bash",
    "git reset --hard:*", "git clean -fdx:*",
)

#: Órdenes que requieren confirmación humana: salen del repositorio o cambian algo remoto.
DEFAULT_COMMAND_ASK = (
    "git push:*", "gh pr:*", "glab mr:*", "npm publish:*",
    "docker push:*", "kubectl apply:*", "terraform apply:*", "aws *:*",
)


class PoliticaIlegible(ValueError):
    """El documento de política no es de este motor.

    Se distingue de «falta la política», que es un aviso y se resuelve con los valores por
    omisión, y de «la política está mal formada», que es un error de JSON. Esto es otra cosa:
    un documento bien formado, lleno, y de otro contrato. Tratarlo como ausente sería aplicar
    una política que nadie escribió mientras la escrita se ignora.
    """


class HerenciaIrresoluble(PoliticaIlegible):
    """No se pudo construir la política efectiva a partir de `extends`.

    Subclase a propósito: el guardián ya captura `PoliticaIlegible` y **deniega**. Heredar de
    ella hace que un fallo de herencia falle CERRADO sin tocar una línea del guardián, que es
    el sitio donde un `except` nuevo y mal puesto costaría más caro.

    Las tres razones se distinguen en el mensaje, no en el estado: quien lo recibe necesita
    saber cuál es, pero para el motor las tres significan lo mismo — no se puede afirmar cuál
    es la política, luego no se deja pasar nada.
    """


@dataclass
class Policy:
    """La política canónica. Un documento, N compilaciones."""

    schema: str = POLICY_SCHEMA
    version: str = "1"
    protected_paths: tuple = DEFAULT_PROTECTED
    #: Se comprueba ANTES que `protected_paths`: es la excepción, y una excepción que se
    #: evaluara después nunca ganaría.
    writable_paths: tuple = DEFAULT_WRITABLE
    #: Lo único escribible fuera del espacio. Vacío significa: nada.
    external_write_allow: tuple = DEFAULT_EXTERNAL_WRITE
    secret_read_deny: tuple = DEFAULT_SECRET_READ_DENY
    command_deny: tuple = DEFAULT_COMMAND_DENY
    command_ask: tuple = DEFAULT_COMMAND_ASK
    #: Bloquea la escritura si el contenido contiene un secreto reconocible.
    block_secret_content: bool = True
    #: Reglas de red. Hoy vacío: ninguno de los cinco runtimes ofrece allowlist de dominios
    #: verificada, y declarar una regla que no se aplica es peor que no tenerla.
    network_rules: tuple = ()
    #: Modo por defecto por runtime. No se homogeneiza: cada uno tiene su vocabulario.
    default_modes: dict = field(default_factory=lambda: {
        "claude": "acceptEdits", "kiro": "declared-in-agent", "gemini": "default",
        "opencode": "ask", "codex": "unknown",
    })

    # ── consultas ────────────────────────────────────────────────────────────────────
    def is_protected(self, rel_path: str) -> str:
        """Devuelve el patrón que protege esa ruta, o cadena vacía."""
        norm = _normalize(rel_path)
        for pattern in self.protected_paths:
            if _path_matches(norm, pattern):
                return pattern
        return ""

    def is_writable(self, rel_path: str) -> str:
        """El patrón de excepción que libera esa ruta, o cadena vacía."""
        norm = _normalize(rel_path)
        for pattern in self.writable_paths:
            if _path_matches(norm, pattern):
                return pattern
        return ""

    def external_allows(self, absolute: Path) -> str:
        """El patrón que autoriza esa ruta ABSOLUTA fuera del espacio, o cadena vacía.

        Se compara contra la ruta ya resuelta, igual que todo lo demás: una excepción que se
        pudiera alcanzar con un enlace simbólico no sería una excepción, sería la puerta.
        """
        target = str(absolute)
        for pattern in self.external_write_allow:
            pat = os.path.expanduser(pattern)
            if fnmatch.fnmatch(target, pat):
                return pattern
            # `raiz/**` cubre además la raíz misma, que `fnmatch` no da por incluida.
            if pat.endswith("/**") and (target == pat[:-3] or target.startswith(pat[:-3] + "/")):
                return pattern
        return ""

    def is_secret_path(self, rel_path: str) -> str:
        norm = _normalize(rel_path)
        for pattern in self.secret_read_deny:
            if _path_matches(norm, pattern):
                return pattern
        return ""

    def default_mode_for(self, runtime: str) -> str:
        return self.default_modes.get(runtime, "default")

    # ── serialización ────────────────────────────────────────────────────────────────
    def to_dict(self) -> dict:
        d = asdict(self)
        return {k: (list(v) if isinstance(v, tuple) else v) for k, v in d.items()}

    @classmethod
    def from_dict(cls, doc: dict) -> "Policy":
        """La política del documento. Levanta `PoliticaIlegible` si no reconoce NADA.

        El defecto que esto cierra
        --------------------------
        Las claves desconocidas se descartan y las ausentes toman su valor por omisión. Es
        tolerante, y esa tolerancia es correcta para un documento al que le falta un campo.
        Pero un documento del que no se reconoce NI UNA clave producía `Policy()` — es decir,
        exactamente `Policy.default()`, indistinguible de no tener política.

        Medido en un espacio real: su `.harness/policy.json` declaraba nueve secciones de otro
        contrato entero (`client_identifiers`, `pii_patterns`, `credential_shapes`,
        `boundary`…) porque ese fichero lo escribía OTRO programa que reclama la misma ruta. El
        guardián no falló: aplicó los valores de fábrica y siguió. El espacio parecía
        gobernado y lo gobernaba una política que nadie había escrito — y las secciones que sí
        se habían escrito, incluidas las dos que detectan credenciales y datos personales, no
        se aplicaban nunca.

        Un documento vacío `{}` SÍ es válido: dice «acepto lo que venga por omisión», y lo dice
        a propósito. Lo que no puede pasar en silencio es un documento lleno del que no se
        entiende una palabra.
        """
        known = {f for f in cls.__dataclass_fields__}                # noqa: SLF001
        kwargs = {}
        for key, value in doc.items():
            if key not in known:
                continue
            kwargs[key] = tuple(value) if isinstance(value, list) else value

        # `schema` y `version` son METADATOS: los lleva cualquier documento, incluido el de
        # otro programa, así que reconocerlos no es reconocer una política. Contarlos salvaba
        # justo al documento que este control existe para cazar.
        #
        # `extends` SÍ cuenta, y es lo contrario de un metadato: es una declaración
        # sustantiva —«mi política es la de mi padre, con lo que yo añada»— y un documento
        # ajeno no la lleva. Sin esto, un hijo que hereda TODO y no repite nada se rechazaba
        # como documento de otro programa; medido el 2026-09-23 contra el guardián real, que
        # denegaba con el motivo equivocado. `name` acompaña a `extends` en la identidad y no
        # cuenta por sí solo, como `schema`.
        sustantivas = set(kwargs) - {"schema", "version"}
        if doc.get("extends"):
            sustantivas.add("extends")
        if doc and not sustantivas:
            ajenas = sorted(k for k in doc if not k.startswith("_") and k not in
                            ("schema", "version", "name", "extends_digest"))
            raise PoliticaIlegible(
                f"el documento declara {len(ajenas)} campos de política y el motor no reconoce "
                f"ninguno: "
                f"{', '.join(ajenas[:6])}"
                f"{'…' if len(ajenas) > 6 else ''}. "
                f"Parece la política de OTRO programa ocupando esta ruta. "
                f"No se aplican valores por omisión: una política que no se entiende no "
                f"aprueba.")
        return cls(**kwargs)

    @classmethod
    def load(cls, path: Path) -> "Policy":
        """La política EFECTIVA de ese fichero, con `extends` ya resuelto.

        Por qué la resolución vive aquí y no en un comando aparte
        ---------------------------------------------------------
        `Policy.load` es lo que ejecuta el guardián (`core/guard.py`) antes de decidir cada
        escritura y cada orden. Si `extends` se resolviera sólo en un comando de consulta, un
        cliente podría declarar restricciones que **ningún proyecto aplica** mientras la
        herramienta informa de que la herencia está bien.

        No es hipotético: medido el 2026-09-23 contra el guardián real, con un padre que
        denegaba una orden y un hijo que declaraba `extends` sin repetirla:

            permissionDecision: "allow"      ← la orden del cliente se permitía

        Dos interpretaciones de la misma política son dos políticas. Aquí hay una.

        Qué pasa cuando no se puede resolver
        ------------------------------------
        Se levanta `PoliticaIlegible` —o una de sus subclases— y el guardián la trata como ya
        trataba cualquier política que no entiende: **deniega**. No hay valores por omisión,
        no hay política del hijo a secas, no hay `NOT_APPLICABLE`. Un espacio que dice heredar
        y corre sin su padre parece gobernado sin estarlo, y ése es el estado que no puede
        existir.
        """
        doc = json.loads(path.read_text(encoding="utf-8"))
        if not doc.get("extends"):
            pol = cls.from_dict(doc)
            # También sin herencia lleva identidad: si sólo la llevaran las heredadas, la
            # evidencia podría citar la política en unos espacios y no en otros, y «no hay
            # digest» sería indistinguible de «no se pudo calcular».
            from core.refinement import identidad_de
            pol.identidad_efectiva = identidad_de(doc)
            return pol
        # Tardío a propósito: `refinement` importa de este módulo. Importar aquí evita el
        # ciclo sin partir ninguno de los dos en un tercero artificial.
        from core.refinement import politica_efectiva
        return politica_efectiva(path, doc)

    @classmethod
    def default(cls) -> "Policy":
        return cls()


#: Dónde vive la capa 1 de la cadena `refuto → cliente → proyecto`, relativa a la raíz de
#: refuto. Está bajo `policies/**`, que la propia política de refuto protege — y eso es
#: deliberado, no un estorbo: materializar la norma raíz es un acto de persona. Un agente que
#: pudiera reescribir el documento del que cuelgan todos los clientes no estaría gobernado por
#: él.
RUTA_BASE = "policies/base.json"


def documento_base(nombre: str = "refuto") -> dict:
    """El documento de la capa `refuto`: los valores por omisión, materializados.

    Hasta ahora esta capa sólo existía como constantes de este módulo (`DEFAULT_PROTECTED`,
    `DEFAULT_COMMAND_DENY`…), así que ningún cliente podía extenderla: `refuto install`
    escribía una COPIA completa en cada espacio y a partir de ahí divergían en silencio. Un
    documento se puede heredar; una constante de Python, no.

    Se deriva de `Policy.default()` y no se escribe a mano a propósito: dos fuentes para la
    misma norma se separan, y la que se separa sin avisar es siempre la que nadie ejecuta.
    """
    return {**Policy.default().to_dict(), "name": nombre}


# ── decisión ─────────────────────────────────────────────────────────────────────────
def _normalize(rel_path: str) -> str:
    """Normaliza una ruta relativa para compararla contra patrones.

    NO se usa `lstrip("./")`: `str.lstrip` quita CARACTERES, no un prefijo, así que
    `.kiro/steering/metodo.md` se convertía en `kiro/steering/metodo.md` y dejaba de coincidir
    con `.kiro/steering/**`. El estándar quedaba desprotegido por un punto. Encontrado por la
    prueba `tests/unit/test_policy.py::protege_steering`.
    """
    norm = rel_path.replace(os.sep, "/")
    while norm.startswith("./"):
        norm = norm[2:]
    return norm.lstrip("/")


def _path_matches(norm: str, pattern: str) -> bool:
    """Coincidencia de ruta contra patrón, con las dos correcciones que `fnmatch` no trae.

    1. `dir/**` cubre `dir/a.py` y `dir/a/b.py`. `fnmatch` solo no lo garantiza.
    2. `**/.env` cubre también `.env` en la raíz. Sin esto, el patrón que todo el mundo
       escribe para «los .env, estén donde estén» dejaba fuera el más obvio: el de arriba.
    """
    if fnmatch.fnmatch(norm, pattern):
        return True
    if pattern.endswith("/**") and (norm == pattern[:-3] or norm.startswith(pattern[:-3] + "/")):
        return True
    if pattern.startswith("**/") and fnmatch.fnmatch(norm, pattern[3:]):
        return True
    return False


ALLOW, DENY, ASK = "allow", "deny", "ask"


@dataclass
class Decision:
    outcome: str
    reason: str = ""
    rule: str = ""

    @property
    def blocked(self) -> bool:
        return self.outcome == DENY


def decide_write(policy: Policy, workspace: Path, target: str, content: str = "") -> Decision:
    """Decide si una escritura se permite. Es el corazón del guardián.

    Se resuelve la ruta ANTES de compararla. Comparar la ruta tal como la escribió el agente es
    lo que hace que `verificacion/../verificacion/v1.py` y un enlace simbólico a `verificacion/`
    pasen por debajo del patrón. Se compara lo que el sistema de archivos va a tocar.
    """
    ws = workspace.resolve()
    raw = Path(target).expanduser()
    absolute = raw if raw.is_absolute() else (ws / raw)
    # `resolve()` sigue enlaces simbólicos: es justo lo que hace falta. Un enlace dentro del
    # espacio que apunta al juez es un ataque, no una comodidad.
    resolved = Path(os.path.realpath(absolute))

    try:
        rel = str(resolved.relative_to(ws))
    except ValueError:
        # Fuera del espacio. Se rechaza, salvo las raíces que el espacio declara suyas: la
        # memoria del agente y su cuaderno no son del proyecto y nunca van a estar dentro.
        externo = policy.external_allows(resolved)
        if externo:
            return _revisar_contenido(policy, content, donde=str(resolved),
                                      contexto=f"fuera del espacio, autorizado por «{externo}»")
        return Decision(DENY, rule="fuera-del-espacio",
                        reason=f"la escritura resuelve a {resolved}, fuera del espacio de "
                               f"trabajo {ws}. Una ruta relativa que sale del árbol es "
                               f"travesía de directorios, se haya pretendido o no. "
                               f"Si es un sitio propio del agente y debe poder escribirlo, "
                               f"decláralo en `external_write_allow`; no se abre por defecto.")

    # La excepción va PRIMERO: evaluada después nunca podría ganarle a lo protegido.
    libre = policy.is_writable(rel)
    if not libre:
        pattern = policy.is_protected(rel)
        if pattern:
            return Decision(DENY, rule=pattern,
                            reason=f"«{rel}» está protegida por «{pattern}». Es el estándar, el "
                                   f"juez, el insumo del cliente o la evidencia. Un agente que "
                                   f"edita lo que lo evalúa no está aprobando: está moviendo la "
                                   f"puerta. El cambio se propone, no se aplica.")

    secret_pat = policy.is_secret_path(rel)
    if secret_pat:
        return Decision(DENY, rule=secret_pat,
                        reason=f"«{rel}» coincide con «{secret_pat}»: es una ruta de credencial.")

    return _revisar_contenido(policy, content, donde=rel)


def _revisar_contenido(policy: Policy, content: str, *, donde: str,
                       contexto: str = "") -> Decision:
    """Lo último que se mira: si el TEXTO lleva un secreto.

    Se distingue prueba de indicio, y se responde distinto a cada una. Antes no: cualquier
    coincidencia rechazaba, y como la coincidencia más frecuente era «algo llamado `secret`
    recibe un valor», la regla bloqueaba justo el código que maneja secretos bien —
    `let secret = std::env::var("JWT_SECRET")?` entre otros 27 casos medidos en un espacio real.

    Una prueba rechaza. Un indicio lo decide una persona: eso es lo que se hace con una
    ambigüedad, en vez de resolverla siempre para el mismo lado.
    """
    from core.digest import classify

    if not (policy.block_secret_content and content):
        return Decision(ALLOW, reason=contexto)
    pruebas, indicios = classify(content)
    if pruebas:
        return Decision(DENY, rule="contenido-con-secreto",
                        reason=f"el contenido de «{donde}» contiene {', '.join(pruebas)}: eso "
                               f"tiene la forma de una credencial emitida, no de una referencia "
                               f"a ella. Lo que entra al árbol, sale. El control es que el dato "
                               f"no esté.")
    if indicios:
        return Decision(ASK, rule="posible-secreto-literal",
                        reason=f"en «{donde}» hay {', '.join(indicios)}. No tiene forma de "
                               f"credencial conocida, así que puede ser un ejemplo o una prueba "
                               f"— o puede ser real. No lo adivino: lo decide una persona.")
    return Decision(ALLOW, reason=contexto)


#: Órdenes cuyo trabajo es ejecutar OTRA orden. La regla tiene que mirar lo ENVUELTO: en
#: `xargs sudo rm` el token de cabeza es `xargs`, y `sudo:*` no casaba con nada.
_ENVOLTORIOS = {"env", "nohup", "time", "nice", "ionice", "xargs", "command", "builtin",
                "exec", "stdbuf", "timeout", "setsid", "sudo", "doas"}

#: Intérpretes que reciben la orden real como argumento de `-c`.
_INTERPRETES = {"sh", "bash", "zsh", "dash", "ksh", "fish"}

_ASIGNACION = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")


def _partir(command: str, *, tuberia: bool = True) -> list:
    """Parte la cadena por los separadores que están FUERA de comillas.

    Con `tuberia=False` corta sólo donde empieza una SENTENCIA nueva (`;`, `&&`, `||`, `&`,
    salto de línea) y deja las tuberías dentro. Hacen falta las dos vistas: hay reglas que
    describen una orden suelta (`rm -rf:*`) y reglas que describen precisamente la unión de dos
    por una tubería (`curl* | bash`). Cortar siempre por el `|` volvía inaplicables las segundas.

    Respetar las comillas no es cosmético. La primera versión partía a lo bruto, y entonces una
    BÚSQUEDA como `grep -rn "rm -rf" .` —que no ejecuta nada— se rechazaba por llevar el texto
    detrás de un separador imaginario. Se midió en el acto y de la peor manera: el parche que
    arreglaba esto no se pudo aplicar, porque su propio texto disparaba la regla. Un control que
    salta con el texto y no con la acción se desactiva en una semana, y entonces no protege de
    nada.
    """
    partes, actual = [], []
    simple = doble = False
    i, n = 0, len(command)
    while i < n:
        c = command[i]
        if c == "\\" and i + 1 < n:
            actual.append(c)
            actual.append(command[i + 1])
            i += 2
            continue
        if c == "'" and not doble:
            simple = not simple
        elif c == '"' and not simple:
            doble = not doble
        if not simple and not doble:
            if command.startswith("&&", i) or command.startswith("||", i):
                partes.append("".join(actual))
                actual = []
                i += 2
                continue
            if c in (";\n|&" if tuberia else ";\n&"):
                partes.append("".join(actual))
                actual = []
                i += 1
                continue
        actual.append(c)
        i += 1
    partes.append("".join(actual))
    return partes


def _sin_literales(command: str) -> str:
    """La cadena con el contenido de las comillas SIMPLES en blanco, conservando la longitud.

    Sirve para buscar sustituciones de orden sin confundir texto con ejecución.
    """
    out, simple = [], False
    i, n = 0, len(command)
    while i < n:
        c = command[i]
        if c == "\\\\" and i + 1 < n and not simple:
            out.append(c)
            out.append(command[i + 1])
            i += 2
            continue
        if c == "'":
            simple = not simple
            out.append(c)
        else:
            out.append(" " if simple else c)
        i += 1
    return "".join(out)


def _segmentos(command: str) -> list:
    """Cada orden que esta cadena va a ejecutar, no sólo la primera.

    `decide_command` normalizaba la cadena entera y la comparaba contra prefijos, así que
    decidía por el PRIMER token y nada más. Medido: `sudo lanzador` → deny, pero
    `echo hola; sudo lanzador` → allow, y `cd /tmp && git push --force` → allow. Las 16 reglas de
    rechazo se rodeaban anteponiendo cualquier cosa inofensiva.

    Esto NO es un analizador de shell y no pretende serlo: una ofuscación decidida (armar el
    nombre de la orden en una variable, o codificarla) lo atraviesa. Es una barandilla contra el
    resbalón, no una caja de arena contra un adversario. Lo que sí cubre es lo que de verdad
    pasa a diario: encadenar, envolver, sustituir e interpretar.
    """
    # Dos vistas: la sentencia con sus tuberías intactas, y cada orden suelta dentro de ella.
    sentencias = _partir(command, tuberia=False)
    pendientes = list(sentencias)
    for sent in sentencias:
        pendientes += _partir(sent)
    # Lo que va dentro de `$( … )` y de comillas invertidas también se ejecuta —salvo dentro de
    # comillas SIMPLES, donde el shell no expande nada y el texto es sólo texto. Sin esta
    # distinción, escribir `'$(algo)'` en un argumento se trataba como ejecutarlo.
    for a, b in re.findall(r"\$\(([^()]*)\)|`([^`]*)`", _sin_literales(command)):
        pendientes += _partir(a) + _partir(b)

    # La cadena ENTERA, además de sus trozos: hay reglas que describen precisamente la unión
    # —`curl* | bash`— y partir por el `|` las volvía inaplicables. Partir añade candidatos; no
    # puede quitar el que ya había.
    out: list = [" ".join(command.split())]
    for seg in pendientes:
        seg = " ".join(seg.split())
        if not seg:
            continue
        out.append(seg)
        tokens = seg.split()
        # Se pela envoltorio a envoltorio, y se mira DESPUÉS DE CADA CAPA. Pelarlos todos de
        # golpe y mirar sólo el fondo perdía la capa intermedia: de `xargs sudo rm` salía `rm`,
        # que no casa con nada, y la escalada del medio no la veía nadie.
        i = 0
        while i < len(tokens) and (tokens[i] in _ENVOLTORIOS or _ASIGNACION.match(tokens[i])):
            i += 1
            if i < len(tokens):
                out.append(" ".join(tokens[i:]))
        if i and i < len(tokens):
            tokens = tokens[i:]
        # `sh -c "…"`: la orden de verdad va dentro, y ahí sí hay que mirar.
        if len(tokens) >= 3 and tokens[0] in _INTERPRETES and "-c" in tokens[1:3]:
            dentro = seg.split("-c", 1)[1].strip().strip("'\"")
            out += [" ".join(x.split()) for x in _partir(dentro) if x.strip()]
    return out


def decide_command(policy: Policy, command: str) -> Decision:
    """Decide si una orden de consola se ejecuta, se pregunta o se rechaza.

    Se evalúan TODOS los segmentos de la cadena y gana el más restrictivo: un rechazo en
    cualquier posición rechaza la llamada entera, porque la herramienta ejecuta la cadena
    entera.
    """
    segmentos = _segmentos(command) or [" ".join(command.split())]
    peor_ask = None
    for cmd in segmentos:
        for pattern in policy.command_deny:
            if _matches_command(cmd, pattern):
                return Decision(DENY, rule=pattern,
                                reason=f"la orden coincide con la regla de rechazo «{pattern}»"
                                       f" (en «{cmd[:60]}»).")
        if peor_ask is None:
            for pattern in policy.command_ask:
                if _matches_command(cmd, pattern):
                    peor_ask = Decision(ASK, rule=pattern,
                                        reason=f"«{pattern}» sale del repositorio o cambia algo "
                                               f"remoto: lo decide una persona.")
                    break
    return peor_ask or Decision(ALLOW)


_GLOB_CHARS = re.compile(r"[*?\[]")


def _matches_command(cmd: str, pattern: str) -> bool:
    """Vocabulario de patrón de orden compartido con Claude Code: `prefijo:*` o glob.

    El prefijo puede llevar comodines (`aws *:*`). La primera versión hacía `startswith` con el
    prefijo literal, así que `aws *:*` no cubría `aws s3 ls` — una regla que parecía puesta y
    no lo estaba, que es el peor tipo de regla.
    """
    if pattern.endswith(":*"):
        prefix = pattern[:-2].strip()
        if _GLOB_CHARS.search(prefix):
            return fnmatch.fnmatch(cmd, prefix + "*") or fnmatch.fnmatch(cmd, prefix)
        if cmd == prefix or cmd.startswith(prefix + " "):
            return True
        # Más allá del espacio, lo que vale como continuación depende de QUÉ termina el prefijo,
        # y son dos casos que no se comportan igual:
        #
        #   nombre de programa  `mkfs` → `mkfs.ext4` SÍ (misma familia, mismo daño)
        #                       `dd`   → `ddev`      NO (otro programa que empieza igual)
        #   bandera corta       `rm -rf` → `rm -rfv` SÍ (las banderas cortas se agrupan)
        #
        # El `cmd.startswith(prefix)` suelto que había antes daba SÍ a los tres, así que `dd:*`
        # rechazaba `ddev up` y `ddgr python`. Un rechazo por parecido tipográfico enseña a
        # desconfiar del guardián, y un guardián del que se desconfía se rodea.
        if not cmd.startswith(prefix):
            return False
        siguiente = cmd[len(prefix)]
        if prefix.rsplit(" ", 1)[-1].startswith("-"):
            return True                       # agrupación de banderas: -rf ⊂ -rfv
        return not (siguiente.isalnum() or siguiente in "_-")
    return fnmatch.fnmatch(cmd, pattern)


# ── compilación ──────────────────────────────────────────────────────────────────────
def compile_for(policy: Policy, spec) -> dict:
    """Compila la política al runtime de `spec`. Delegado al adapter, que es quien sabe."""
    out = spec.compile_policy(policy)
    out.setdefault("supported", False)
    out.setdefault("artifacts", {})
    out.setdefault("unenforceable", [])
    out.setdefault("notes", [])
    return out
