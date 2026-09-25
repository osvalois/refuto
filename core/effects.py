# -*- coding: utf-8 -*-
"""Modelo de EFECTOS de una orden de consola. Qué toca, no cómo se escribió.

Por qué existe
--------------
La política protege RUTAS. El guardián las aplicaba sólo cuando la herramienta declaraba una
ruta (`Write`, `Edit`), y decidía por la ORDEN cuando la herramienta era `Bash` — dos ramas
excluyentes en `core.guard.evaluate`. Medido el 2026-09-23 contra el guardián real, misma
ruta y misma política:

    Write  gates/base.py          →  deny
    Bash   echo x > gates/base.py →  allow, y el fichero se escribió

La política de rutas no se aplicaba al canal de órdenes. Este módulo existe para que la
decisión se tome sobre `Effects(orden)` y no sobre su sintaxis.

Lo que este módulo NO es, y conviene leerlo antes de confiar en él
------------------------------------------------------------------
`Effects` **no es computable**. Para cualquier máquina de Turing `M` y entrada `w`, la orden

    python3 -c 'if M(w) para: open("gates/base.py","w")'

escribe en el juez si y sólo si `M` para. Decidir el efecto decide la parada. Luego todo
analizador estático sobre órdenes es incorrecto (deja pasar) o incompleto (rechaza lo
inocuo), y un analizador correcto tendría que denegar `python3`, `make`, `npm` y cualquier
binario compilado — un control así se desactiva en una semana y entonces no protege de nada.

Por eso aquí se calcula `Ê`, una **sub-aproximación**: el conjunto de escrituras que se
pueden DEMOSTRAR desde la sintaxis.

    Ê(c) ⊆ Effects(c)

Lo que `Ê` afirma es sólido: si `Ê` dice que se escribe en `p`, se escribe en `p`. Lo que no
afirma es completitud: una orden opaca (`python3 -c …`, un binario propio) puede escribir
donde quiera y `Ê` devuelve `opaco=True` para que quien decida sepa que no sabe.

La garantía del producto NO descansa en este módulo. Descansa en `I6'` —«si el juez fue
modificado, ningún veredicto posterior es PASS»— que se sostiene con la atestación de
`core.trust`. Esto es reducción de superficie, y así se declara. Ver
`docs/assurance/FORMAL-MODEL.md` §6.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

READ, WRITE = "READ", "WRITE"

#: Programas cuyo efecto sobre el sistema de archivos se puede derivar de sus argumentos.
#: Cada entrada dice QUÉ posiciones de argumento se escriben. No se añade ninguno «por si
#: acaso»: uno mal modelado es peor que uno ausente, porque afirma saber lo que no sabe.
#:
#: `destino`  la ÚLTIMA ruta no-opción es el destino escrito  (cp, mv, install, ln)
#: `todas`    toda ruta no-opción se escribe                  (touch, mkdir, rm, chmod, …)
#: `en_sitio` toda ruta no-opción se escribe SÓLO si aparece la bandera indicada
_ESCRITORES = {
    "cp": ("destino", None), "mv": ("destino", None), "install": ("destino", None),
    "ln": ("destino", None), "rsync": ("destino", None),
    "touch": ("todas", None), "mkdir": ("todas", None), "rmdir": ("todas", None),
    "rm": ("todas", None), "truncate": ("todas", None), "shred": ("todas", None),
    "chmod": ("todas", None), "chown": ("todas", None), "chflags": ("todas", None),
    "tee": ("todas", None),
    "sed": ("en_sitio", "-i"), "perl": ("en_sitio", "-i"), "awk": ("en_sitio", "-i"),
    "gofmt": ("en_sitio", "-w"), "ruff": ("en_sitio", "--fix"),
}

#: Programas cuyo efecto sobre el árbol es NINGUNO: leen o hablan por la salida estándar.
#:
#: Existe para que `opaco` signifique algo. Sin esta lista, `ls -la` y `echo hola` salían
#: marcados «no sé qué hace», y una señal que se dispara con todo no informa de nada — el
#: mismo defecto que `core/policy.py::_partir` documenta para los patrones de texto.
#: Una escritura por redirección se detecta aparte, ANTES de mirar el programa, así que
#: `echo x > f` sigue viéndose como escritura aunque `echo` esté aquí.
_LECTORES = {
    "echo", "printf", "true", "false", "pwd", "date", "sleep", "seq", "yes",
    "ls", "cat", "head", "tail", "wc", "find", "grep", "rg", "egrep", "fgrep",
    "sort", "uniq", "cut", "tr", "file", "stat", "diff", "jq", "du", "df",
    "which", "type", "basename", "dirname", "realpath", "readlink",
    "cd", "pushd", "popd", "test", "printenv", "column", "comm", "join",
    "paste", "fold", "nl", "rev", "expand", "less", "more", "xxd", "base64",
    "shasum", "sha256sum", "md5", "md5sum", "cksum", "tree", "ps", "top",
    "lsof", "whoami", "id", "uname", "hostname", "sw_vers", "env",
}

#: Intérpretes y ejecutores: lo que hagan no se deriva de sus argumentos.
_OPACOS = {
    "python", "python2", "python3", "node", "deno", "bun", "ruby", "perl", "php",
    "sh", "bash", "zsh", "dash", "ksh", "fish", "make", "cmake", "ninja",
    "npm", "npx", "pnpm", "yarn", "pip", "pip3", "uv", "uvx", "cargo", "go",
    "mvn", "gradle", "ant", "dotnet", "java", "swift", "rustc", "gcc", "clang",
    "ansible", "terraform", "docker", "kubectl", "git",
}

#: Envoltorios que ejecutan OTRA orden CON SUS PROPIOS ARGUMENTOS. Se pelan antes de mirar
#: el programa.
#:
#: `xargs` **no** está aquí, y la ausencia es el arreglo de un agujero que encontró la
#: batería de falsación: `echo gates/base.py | xargs touch` escribía en el juez y el modelo
#: veía `touch` sin argumentos, porque las rutas de `xargs` llegan por la ENTRADA ESTÁNDAR.
#: Pelarlo como a los demás convertía una escritura demostrable en ninguna.
_ENVOLTORIOS = {"env", "nohup", "time", "nice", "ionice", "command", "builtin",
                "exec", "stdbuf", "timeout", "setsid", "sudo", "doas", "then", "do", "else"}

#: Los que reciben sus operandos por la entrada estándar. Lo que escriban no se deriva de
#: sus argumentos: se deriva de lo que les llegue por la tubería, que este módulo no ve.
_DESDE_STDIN = {"xargs", "parallel"}

_ASIGNACION = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
#: Sustitución de proceso y expansión: marcan opacidad.
_EXPANSION = re.compile(r"\$\(|`|\$\{[^}]*[?+=]|<\(|>\(")


@dataclass
class Efectos:
    """Lo que una orden hace sobre el sistema de archivos, hasta donde se puede demostrar."""

    escrituras: set = field(default_factory=set)
    lecturas: set = field(default_factory=set)
    #: `True` cuando la orden invoca algo cuyo efecto no se deriva de sus argumentos.
    #: No significa «peligrosa»: significa «no lo sé», que es distinto y hay que decirlo.
    opaco: bool = False
    #: Por qué es opaca, para poder explicarlo en el rastro.
    motivo_opaco: str = ""

    def __or__(self, otro: "Efectos") -> "Efectos":
        return Efectos(self.escrituras | otro.escrituras,
                       self.lecturas | otro.lecturas,
                       self.opaco or otro.opaco,
                       self.motivo_opaco or otro.motivo_opaco)


def _sin_comillas(texto: str) -> str:
    """El texto con el contenido de las comillas en blanco, conservando la longitud.

    Sirve para buscar redirecciones sin confundir un `>` citado con una redirección real:
    `echo "a > b"` no redirige a ninguna parte.
    """
    out, simple, doble = [], False, False
    i, n = 0, len(texto)
    while i < n:
        c = texto[i]
        if c == "\\" and i + 1 < n:
            out.append(" ")
            out.append(" ")
            i += 2
            continue
        if c == "'" and not doble:
            simple = not simple
            out.append(c)
        elif c == '"' and not simple:
            doble = not doble
            out.append(c)
        else:
            out.append(" " if (simple or doble) else c)
        i += 1
    return "".join(out)


def _destinos_de_redireccion(segmento: str) -> list:
    """Las rutas a las que este segmento redirige la salida.

    Se escribió primero con una expresión regular sobre el texto «sin comillas», y tenía un
    agujero que encontró la batería de falsación: `echo x > "gates/base.py"` y su variante
    con comilla simple **se colaban**, porque el destino iba entre comillas y el borrado de
    literales lo dejaba en blanco justo antes de leerlo. Citar una ruta es lo más normal del
    mundo —cualquier ruta con espacios lo exige— así que el agujero no era exótico.

    Ahora se recorre el segmento carácter a carácter llevando el estado de las comillas: el
    OPERADOR sólo cuenta si está fuera de comillas (`echo "a > b"` no redirige a ninguna
    parte), y el DESTINO se lee después respetándolas.
    """
    destinos, i, n = [], 0, len(segmento)
    simple = doble = False
    while i < n:
        c = segmento[i]
        if c == "\\" and i + 1 < n:
            i += 2
            continue
        if c == "'" and not doble:
            simple = not simple
        elif c == '"' and not simple:
            doble = not doble
        elif c == ">" and not simple and not doble:
            j = i + 1
            while j < n and segmento[j] in ">|":      # `>>`, `>|`
                j += 1
            while j < n and segmento[j] in " \t":
                j += 1
            # El destino, respetando las comillas que lo envuelvan.
            destino, cita = [], ""
            while j < n:
                ch = segmento[j]
                if cita:
                    if ch == cita:
                        cita = ""
                    else:
                        destino.append(ch)
                elif ch in "'\"":
                    cita = ch
                elif ch in " \t;&|<>()\n":
                    # Los paréntesis cierran el destino: en `(echo x > a.lock.json)` el
                    # cierre del subshell se pegaba al nombre y producía `a.lock.json)`,
                    # que ya no casa con `*.lock.json`. Sólo fallaban las rutas SIN barra
                    # —las de la raíz— porque un patrón `dir/**` seguía casando con el
                    # nombre sucio. Lo encontró el producto cartesiano, no el diseño.
                    break
                else:
                    destino.append(ch)
                j += 1
            ruta = "".join(destino)
            if ruta and ruta not in ("/dev/null", "/dev/stdout", "/dev/stderr"):
                destinos.append(ruta)
            i = j
            continue
        i += 1
    return destinos


def _tokens(segmento: str) -> list:
    """Los tokens del segmento, sin comillas envolventes."""
    bruto = segmento.split()
    return [t.strip("'\"") for t in bruto]


def _pelar(tokens: list) -> list:
    """Quita envoltorios y asignaciones de entorno de la cabeza."""
    i = 0
    while i < len(tokens) and (tokens[i] in _ENVOLTORIOS or _ASIGNACION.match(tokens[i])):
        i += 1
    return tokens[i:]


def _rutas(tokens: list) -> list:
    """Los argumentos que parecen rutas: los que no empiezan por guion."""
    return [t for t in tokens if t and not t.startswith("-")]


def _de_un_segmento(segmento: str) -> Efectos:
    """Efectos de UNA orden simple, ya separada de sus vecinas."""
    ef = Efectos()
    visible = _sin_comillas(segmento)

    # 1 · Redirecciones. Es el caso que el guardián no veía y el más común de todos.
    ef.escrituras.update(_destinos_de_redireccion(segmento))

    # 2 · Expansión dinámica: el nombre del fichero puede construirse en tiempo de ejecución.
    if _EXPANSION.search(visible):
        ef.opaco = True
        ef.motivo_opaco = "la orden construye parte de sí misma en tiempo de ejecución"

    tokens = _pelar(_tokens(segmento))
    if not tokens:
        return ef
    programa = tokens[0].rsplit("/", 1)[-1]
    resto = tokens[1:]

    # 3 · `xargs W`: las rutas le llegan por la tubería. Si `W` escribe, se escribe en algo
    # que este módulo no puede nombrar. Se declara opaco y NO se finge que no pasa nada.
    if programa in _DESDE_STDIN:
        envuelto = next((t.rsplit("/", 1)[-1] for t in resto if not t.startswith("-")), "")
        if envuelto in _ESCRITORES or envuelto in _OPACOS:
            ef.opaco = True
            ef.motivo_opaco = (f"«{programa} {envuelto}» recibe sus rutas por la entrada "
                               f"estándar: lo que escriba no se deriva de sus argumentos")
        elif envuelto:
            ef.lecturas.update(_rutas(resto))
        return ef

    # 4 · Programas con efecto derivable de sus argumentos.
    if programa in _ESCRITORES:
        clase, bandera = _ESCRITORES[programa]
        rutas = _rutas(resto)
        if clase == "destino" and len(rutas) >= 2:
            ef.escrituras.add(rutas[-1])
            ef.lecturas.update(rutas[:-1])
        elif clase == "destino" and len(rutas) == 1:
            ef.escrituras.add(rutas[0])
        elif clase == "todas":
            ef.escrituras.update(rutas)
        elif clase == "en_sitio":
            if any(t == bandera or t.startswith(bandera) for t in resto):
                # `sed -i` puede llevar sufijo de respaldo como argumento suelto; se marcan
                # todas las rutas como escritas, que es el lado conservador.
                ef.escrituras.update(rutas)
            else:
                ef.lecturas.update(rutas)
        return ef

    # 4 · Programas de sólo lectura: efecto conocido y vacío. No son opacos.
    if programa in _LECTORES:
        ef.lecturas.update(_rutas(resto))
        return ef

    # 5 · Opacos: no se deriva nada de sus argumentos. Se declara la ignorancia.
    if programa in _OPACOS:
        ef.opaco = True
        ef.motivo_opaco = f"«{programa}» ejecuta código que no se deriva de sus argumentos"
        return ef

    # 5 · Programa desconocido. Tampoco se sabe.
    if programa and not programa.startswith("-"):
        ef.opaco = True
        ef.motivo_opaco = f"«{programa}» no está modelado: su efecto no se puede derivar"
    return ef


def _segmentar(orden: str) -> list:
    """Cada orden simple que esta cadena va a ejecutar.

    Se reutiliza el partidor de `core.policy`, que ya respeta comillas — duplicarlo sería
    tener dos analizadores que divergen, que es el defecto que `core.policy` documenta.
    """
    from core.policy import _partir, _sin_cuerpos_citados, _sin_literales

    # El cuerpo de un documento aquí citado no se ejecuta, así que tampoco escribe. Sin esto, la
    # prosa `redirige con > /etc/passwd` dentro de un `<<'EOF'` se derivaba como una escritura
    # REAL a `/etc/passwd`, y la orden se denegaba por «fuera-del-espacio»: medido el 2026-09-24.
    # La línea del operador se conserva, así que la redirección de verdad (`cat > destino`) se
    # sigue viendo. Ver `core.policy._sin_cuerpos_citados`.
    orden = _sin_cuerpos_citados(orden)
    fuera = []
    for sentencia in _partir(orden, tuberia=False):
        fuera.append(sentencia)
        fuera += _partir(sentencia)
    # Lo que va dentro de `$( … )` y de comillas invertidas también se ejecuta.
    for a, b in re.findall(r"\$\(([^()]*)\)|`([^`]*)`", _sin_literales(orden)):
        fuera += _partir(a) + _partir(b)
    # `sh -c "…"`: la orden real va dentro.
    for seg in list(fuera):
        t = seg.split()
        if len(t) >= 3 and t[0].rsplit("/", 1)[-1] in {"sh", "bash", "zsh", "dash"} \
                and "-c" in t[1:3]:
            fuera += _partir(seg.split("-c", 1)[1].strip().strip("'\""))
    return [s for s in fuera if s.strip()]


def efectos(orden: str) -> Efectos:
    """`Ê(orden)`: las escrituras que se pueden DEMOSTRAR, y si queda algo sin demostrar.

    Sólido en lo que afirma —si dice que escribe en `p`, escribe en `p`— e incompleto por
    construcción: ver el encabezado del módulo.
    """
    total = Efectos()
    for seg in _segmentar(orden):
        total = total | _de_un_segmento(seg)
    return total
