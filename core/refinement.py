# -*- coding: utf-8 -*-
"""Refinamiento de política: `refuto → cliente → proyecto`.

Qué NO es esto, y por qué importa decirlo primero
-------------------------------------------------
No es `{**padre, **hijo}`. Una superposición de diccionarios deja que el hijo **sustituya**
cualquier clave del padre, y sustituir es relajar cuando la clave es una restricción. Bajo esa
semántica, una capa de cliente se convierte en el sitio donde se van a aflojar los controles —
y peor, en silencio, porque un `merge` no tiene nada que reportar.

Aquí el hijo **refina**: puede endurecer y puede añadir. Cualquier intento de aflojar no se
aplica a medias ni se avisa: **se rechaza la política entera**. Una política parcialmente
aplicada es indistinguible de una política, y esa indistinguibilidad es el fallo.

La invariante, en una línea
---------------------------
    restricciones(hijo)  ⊇  restricciones(padre)

Cada campo declara de qué lado cae y por qué. Un campo que no esté en `REGLAS` **no se
hereda y no se acepta**: añadir una clave nueva a `Policy` sin decidir su monotonía dejaría un
agujero por omisión, y los agujeros por omisión son los que nadie revisa.

Identidad
---------
Dos políticas con el mismo texto pero distinto padre **no son la misma política**. El digest
efectivo encadena la identidad del padre, así que un cambio en el cliente cambia la identidad
del proyecto aunque el proyecto no se haya tocado. Eso es exactamente lo que se quiere poder
detectar: que el significado de un proyecto cambió sin que el proyecto cambiara.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

from core.policy import Policy, PoliticaIlegible

SCHEMA = "harness.refinement/v1"

# ── vocabulario de resultado ─────────────────────────────────────────────────────────
#
# Se reutilizan los estados del motor. No se inventan `NOT_DECLARED` ni `MISCONFIGURED`:
# `Result` ya obliga a que todo veredicto traiga su medida escrita, así que la distinción
# entre «no lo declaró», «lo declaró mal» y «no aplica» viaja en el motivo, que es donde se
# puede leer. Dos estados más partirían una dimensión ya expresada y romperían el
# `status_map` de cualquier consumidor externo.
from core.model import NOT_EXECUTABLE, PASS  # noqa: E402


@dataclass(frozen=True)
class Identidad:
    """Quién es una política, de forma verificable.

    `digest` es del documento canonicalizado; `efectivo` encadena al padre. Con sólo el
    primero, cambiar el cliente dejaría al proyecto con la misma identidad y otro
    significado — que es justo lo que hay que poder detectar.
    """

    nombre: str
    version: str
    digest: str
    efectivo: str = ""

    def to_dict(self) -> dict:
        return {"nombre": self.nombre, "version": self.version,
                "digest": self.digest, "efectivo": self.efectivo}


@dataclass
class Refinamiento:
    """El resultado de refinar. `status` es `PASS` o `NOT_EXECUTABLE`; nunca a medias."""

    status: str
    politica: Policy | None = None
    identidad: Identidad | None = None
    violaciones: list = field(default_factory=list)
    motivo: str = ""
    cadena: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"schema": SCHEMA, "status": self.status, "motivo": self.motivo,
                "identidad": self.identidad.to_dict() if self.identidad else None,
                "violaciones": list(self.violaciones),
                "cadena": [i.to_dict() for i in self.cadena]}


# ── monotonía, campo por campo ───────────────────────────────────────────────────────
#
# `ACUMULA`   conjunto: el hijo hereda todo lo del padre y puede añadir. Quitar es violación.
# `REDUCE`    conjunto: el hijo hereda y **sólo puede quitar**. Añadir es violación.
# `ENDURECE`  booleano: `True` del padre no se puede poner a `False`.
# `PROPIO`    no se hereda; el valor del hijo manda. Reservado a lo que no es una restricción.
ACUMULA, REDUCE, ENDURECE, PROPIO = "acumula", "reduce", "endurece", "propio"

REGLAS = {
    # Lo que protege. Más siempre se puede; menos, nunca.
    "protected_paths": ACUMULA,
    "secret_read_deny": ACUMULA,
    "command_deny": ACUMULA,
    # `command_ask` acumula por el mismo motivo: retirar una consulta convierte en automática
    # una decisión que alguien reservó a una persona.
    "command_ask": ACUMULA,
    "network_rules": ACUMULA,

    # Lo que ABRE un agujero en lo protegido. El hijo puede cerrar agujeros del padre, nunca
    # abrir otros: un agujero heredado en silencio a través de dos capas es indetectable en
    # revisión, y un agujero AÑADIDO por el hijo sería exactamente «relajar».
    "writable_paths": REDUCE,
    "external_write_allow": REDUCE,

    # Detectar secretos es una restricción: encenderla se puede, apagarla no.
    "block_secret_content": ENDURECE,

    # El modo por runtime no es una restricción de seguridad sino de interacción; el proyecto
    # lo decide. Se declara explícitamente para que no caiga aquí por omisión.
    "default_modes": PROPIO,

    # Metadatos. No son política y por eso el hijo los fija: `schema` identifica el contrato
    # del documento y `version` la revisión de quien lo escribe. Que estén aquí y no
    # ausentes es deliberado — la regla es «todo campo de `Policy` declara su monotonía», y
    # un metadato sin declarar haría fallar a cualquier hijo legítimo.
    "schema": PROPIO,
    "version": PROPIO,
}

#: Comprobado al importar: ningún campo de `Policy` puede quedarse sin regla. Si alguien
#: añade uno y olvida decidir cómo se hereda, esto revienta aquí — al importar el módulo, no
#: en producción con una política a medias. Es la misma idea que `check_wiring.py`: un
#: componente que existe y que nadie conectó es peor que no tenerlo.
_SIN_REGLA = sorted(set(Policy.__dataclass_fields__) - set(REGLAS))   # noqa: SLF001
if _SIN_REGLA:                                                        # pragma: no cover
    raise RuntimeError(
        f"campos de Policy sin regla de monotonía: {', '.join(_SIN_REGLA)}. "
        f"Decida en `REGLAS` si acumulan, reducen, endurecen o son propios: heredarlos por "
        f"omisión sería un agujero que nadie revisa.")


def _canonico(doc: dict) -> str:
    """El texto del que se saca el digest. Las claves de comentario (`_que_es`, `_medido`…)
    se descartan: una nota que cambia no cambia la política, y si contara, editar un
    comentario invalidaría la identidad de todos los proyectos que heredan."""
    limpio = {k: v for k, v in sorted(doc.items()) if not k.startswith("_")}
    return json.dumps(limpio, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest_de(doc: dict) -> str:
    return hashlib.sha256(_canonico(doc).encode("utf-8")).hexdigest()


def identidad_de(doc: dict, *, padre: Identidad | None = None) -> Identidad:
    d = digest_de(doc)
    base = f"{padre.efectivo}|{d}" if padre else d
    return Identidad(
        nombre=str(doc.get("name") or doc.get("nombre") or "sin-nombre"),
        version=str(doc.get("version", "")),
        digest=d,
        efectivo=hashlib.sha256(base.encode("utf-8")).hexdigest())


def _viola(campo: str, regla: str, padre, hijo) -> list:
    """Qué ha intentado hacer el hijo que no puede. Lista vacía = refina bien."""
    if regla == ENDURECE:
        if bool(padre) and not bool(hijo):
            return [f"`{campo}`: el padre lo exige (`true`) y el hijo lo apaga (`false`). "
                    f"Apagar una comprobación heredada es relajar."]
        return []
    p, h = set(padre or ()), set(hijo or ())
    if regla == ACUMULA:
        faltan = sorted(p - h)
        return [f"`{campo}`: el hijo retira {len(faltan)} entrada(s) del padre: "
                f"{', '.join(faltan[:5])}. Este campo sólo puede crecer."] if faltan else []
    if regla == REDUCE:
        sobran = sorted(h - p)
        return [f"`{campo}`: el hijo añade {len(sobran)} entrada(s) que el padre no tiene: "
                f"{', '.join(sobran[:5])}. Este campo abre agujeros en lo protegido y sólo "
                f"puede encogerse."] if sobran else []
    return []


def refinar(padre_doc: dict, hijo_doc: dict, *,
            padre_id: Identidad | None = None) -> Refinamiento:
    """Refina `hijo` sobre `padre`. `PASS` con la política efectiva, o `NOT_EXECUTABLE`.

    No devuelve nunca una política «casi refinada». Si el hijo intenta relajar algo, la
    operación entera se rechaza: aplicar la mitad de una política y seguir sería peor que no
    aplicarla, porque el espacio parecería gobernado.
    """
    try:
        padre = Policy.from_dict(padre_doc)
    except PoliticaIlegible as exc:
        return Refinamiento(NOT_EXECUTABLE,
                            motivo=f"la política padre no se pudo interpretar: {exc}")
    try:
        Policy.from_dict(hijo_doc)
    except PoliticaIlegible as exc:
        return Refinamiento(NOT_EXECUTABLE,
                            motivo=f"la política hija no se pudo interpretar: {exc}")

    desconocidas = [k for k in hijo_doc
                    if not k.startswith("_")
                    and k not in REGLAS
                    and k in Policy.__dataclass_fields__]       # noqa: SLF001
    if desconocidas:
        return Refinamiento(
            NOT_EXECUTABLE,
            motivo=f"el hijo declara campo(s) de política sin regla de monotonía: "
                   f"{', '.join(sorted(desconocidas))}. No se hereda lo que no se ha decidido "
                   f"cómo se hereda — un campo sin regla sería un agujero por omisión.")

    efectivo = dict(padre_doc)
    violaciones: list = []
    for campo, regla in REGLAS.items():
        if campo not in hijo_doc:
            continue
        violaciones += _viola(campo, regla, padre_doc.get(campo), hijo_doc.get(campo))
        if regla == ACUMULA:
            efectivo[campo] = sorted(set(padre_doc.get(campo) or ()) |
                                     set(hijo_doc.get(campo) or ()))
        elif regla == REDUCE:
            efectivo[campo] = sorted(set(padre_doc.get(campo) or ()) &
                                     set(hijo_doc.get(campo) or ()))
        else:
            efectivo[campo] = hijo_doc[campo]

    if violaciones:
        return Refinamiento(
            NOT_EXECUTABLE, violaciones=violaciones,
            motivo=f"la política hija intenta relajar la del padre en "
                   f"{len(violaciones)} punto(s). No se aplica ninguna parte: una política a "
                   f"medias es indistinguible de una política.")

    pid = padre_id or identidad_de(padre_doc)
    ident = identidad_de(hijo_doc, padre=pid)
    try:
        resultante = Policy.from_dict(efectivo)
    except PoliticaIlegible as exc:                              # pragma: no cover
        return Refinamiento(NOT_EXECUTABLE,
                            motivo=f"la política efectiva no se pudo construir: {exc}")
    del padre
    return Refinamiento(PASS, politica=resultante, identidad=ident,
                        cadena=[pid, ident],
                        motivo="el hijo refina al padre: no retira nada y no abre nada nuevo")


def resolver(workspace: Path, doc: dict, *, buscar) -> Refinamiento:
    """Resuelve `extends` y refina. `buscar(ref) -> dict | None` localiza al padre.

    Un padre ausente NO produce la política del hijo ni los valores de fábrica: produce
    `NOT_EXECUTABLE`. Un manifiesto que dice `extends` y corre sin su padre **parece**
    gobernado y no lo está — el mismo fallo que `Policy.from_dict` ya cierra cuando no
    reconoce ninguna clave de un documento ajeno.
    """
    ref = doc.get("extends")
    if not ref:
        return Refinamiento(PASS, politica=Policy.from_dict(doc),
                            identidad=identidad_de(doc), cadena=[identidad_de(doc)],
                            motivo="no declara `extends`: se aplica tal cual")
    if not isinstance(ref, str) or not ref.strip():
        return Refinamiento(NOT_EXECUTABLE,
                            motivo=f"`extends` presente pero no es una referencia legible: "
                                   f"{ref!r}")
    try:
        padre_doc = buscar(ref)
    except Exception as exc:                                     # noqa: BLE001
        return Refinamiento(NOT_EXECUTABLE,
                            motivo=f"no se pudo resolver el padre «{ref}»: "
                                   f"{type(exc).__name__}: {exc}")
    if padre_doc is None:
        return Refinamiento(
            NOT_EXECUTABLE,
            motivo=f"declara `extends: {ref}` y ese padre no se encontró. NO se aplican los "
                   f"valores por omisión: un espacio que dice heredar y corre sin su padre "
                   f"parece gobernado sin estarlo.")
    esperado = str(doc.get("extends_digest") or "")
    pid = identidad_de(padre_doc)
    if esperado and esperado != pid.digest:
        return Refinamiento(
            NOT_EXECUTABLE,
            motivo=f"el padre «{ref}» cambió: el hijo ancla `extends_digest` "
                   f"{esperado[:12]}… y hoy es {pid.digest[:12]}…. El significado del "
                   f"proyecto cambiaría sin que el proyecto se haya tocado.")
    return refinar(padre_doc, doc, padre_id=pid)
