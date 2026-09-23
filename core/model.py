# -*- coding: utf-8 -*-
"""Contrato central de refuto. Todo lo demás depende de esto y de nada más.

Por qué sólo biblioteca estándar
--------------------------------
Se hereda la restricción de la cadena de verificación que inspiró a refuto: no puede depender de
una instalación que alguien tenga que recordar hacer. Un harness de gobierno cuyo `doctor`
necesita `pip install` no puede diagnosticar la máquina en la que aún no se instaló nada.
Ver ADR-0002.

Los cinco estados, y por qué son cinco
--------------------------------------
`NOT_EXECUTABLE` no es un aprobado disfrazado ni un fallo del código evaluado: es que la
comprobación no se pudo correr. `BLOCKED` es que la comprobación no se intentó porque una
dependencia declarada no está. Colapsarlos en dos estados es la forma en que una puerta deja de
ser una puerta: «no se pudo comprobar» empieza a leerse como «está bien».

`NOT_APPLICABLE` es el quinto, y se añadió porque faltaba justo donde más daño hacía. Había
puertas que, al no encontrar NADA que comprobar, devolvían `PASS` con una medida del tipo
«nada que verificar»: un aprobado de ámbito vacío. Un ámbito vacío no aprueba — no ha
demostrado nada. Tampoco está bloqueado (no falta ninguna dependencia: es que la puerta no
tiene sujeto en este espacio) ni es inejecutable. Por eso es un estado propio:

    PASS             se comprobó y cumple
    FAIL             se comprobó y no cumple
    BLOCKED          no se intentó: falta una dependencia declarada
    NOT_EXECUTABLE   se intentó y no se pudo correr
    NOT_APPLICABLE   se intentó y no hay sujeto que comprobar en este espacio

`NOT_APPLICABLE` **exige motivo**: `Result` rechaza construirse con ese estado y sin `measure`.
Sin esa regla vuelve a ser un aprobado cómodo con otro nombre.

Reglas duras, comprobadas por `tests/contract/test_result_contract.py`:
    - ninguna transición del sistema convierte NOT_EXECUTABLE, BLOCKED o NOT_APPLICABLE en PASS;
    - una corrida en la que TODAS las puertas son NOT_APPLICABLE no es integrable.
"""

from __future__ import annotations

import json
import os
import platform
import re
import subprocess
import sys
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from core.proc import TEXT_IO

VERSION = "0.2.0"
SCHEMA_VERSION = "harness.result/v1"

# ── estados ───────────────────────────────────────────────────────────────────────────
PASS = "PASS"
FAIL = "FAIL"
BLOCKED = "BLOCKED"
NOT_EXECUTABLE = "NOT_EXECUTABLE"
NOT_APPLICABLE = "NOT_APPLICABLE"
STATUSES = (PASS, FAIL, BLOCKED, NOT_EXECUTABLE, NOT_APPLICABLE)

#: Los cuatro estados que NO son un aprobado. Se declara como conjunto para que nadie tenga
#: que acordarse de cuáles eran, y para que el contrato lo pueda comprobar.
NON_PASSING = frozenset({FAIL, BLOCKED, NOT_EXECUTABLE, NOT_APPLICABLE})

#: Los que además IMPIDEN integrar. `NOT_APPLICABLE` no está: una puerta sin sujeto en este
#: espacio no puede retener un cambio. Lo que no puede hacer es contarse como aprobada, y de
#: eso se encarga `NON_PASSING` y el veredicto de `core.evidence.verdict_of`.
BLOCKING = frozenset({FAIL, BLOCKED, NOT_EXECUTABLE})

SYMBOL = {PASS: "✓", FAIL: "✗", BLOCKED: "⊘", NOT_EXECUTABLE: "!", NOT_APPLICABLE: "–"}

# ── severidad ─────────────────────────────────────────────────────────────────────────
CRITICAL, HIGH, MEDIUM, LOW, INFO = "CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"
SEVERITIES = (CRITICAL, HIGH, MEDIUM, LOW, INFO)

# ── nivel de verificación de una afirmación ──────────────────────────────────────────
# El vocabulario de la auditoría, ahora exigible por código.
VERIFIED = "VERIFIED"
PARTIALLY_VERIFIED = "PARTIALLY_VERIFIED"
NOT_VERIFIED = "NOT_VERIFIED"
# `NOT_APPLICABLE` se declara arriba, con los estados de puerta: es la misma palabra con el
# mismo significado en los dos vocabularios («no hay sujeto»), y tenerla dos veces invitaba a
# que una de las dos definiciones se moviera sin la otra.
VERIFICATION_LEVELS = (VERIFIED, PARTIALLY_VERIFIED, NOT_VERIFIED, BLOCKED, NOT_APPLICABLE)

# ── escalera de ejecutabilidad de un agente (H-01) ───────────────────────────────────
# Ordenada: cada peldaño implica los anteriores. `INSTALLED` es lo máximo que puede afirmar
# un `which`, y por eso `which` nunca es prueba suficiente.
NOT_INSTALLED = "NOT_INSTALLED"
INSTALLED = "INSTALLED"
STARTABLE = "STARTABLE"
FUNCTIONAL = "FUNCTIONAL"
AGENT_VERIFIED = "VERIFIED"
LADDER = (NOT_INSTALLED, INSTALLED, STARTABLE, FUNCTIONAL, AGENT_VERIFIED)


def rung(level: str) -> int:
    """Peldaño numérico, para comparar sin ordenar cadenas."""
    return LADDER.index(level) if level in LADDER else -1


# ── evidencia ────────────────────────────────────────────────────────────────────────
@dataclass
class Evidence:
    """Un hecho comprobable. Sin `command` o `source`, no es evidencia: es una afirmación.

    `redacted` marca que la salida pasó por el redactor de secretos antes de guardarse.
    """
    kind: str                       # command | file | probe | rpc | computation
    summary: str
    command: str = ""
    source: str = ""
    exit_code: int | None = None
    stdout_digest: str = ""
    excerpt: str = ""
    redacted: bool = False

    def to_dict(self) -> dict:
        return {k: v for k, v in asdict(self).items() if v not in ("", None, False)} | {
            "kind": self.kind, "summary": self.summary}


@dataclass
class Finding:
    """Un hallazgo dentro de un resultado. Lleva sitio, para poder ir a arreglarlo."""
    where: str
    message: str
    line: int = 0

    def as_text(self) -> str:
        return f"{self.where}:{self.line} — {self.message}" if self.line else f"{self.where} — {self.message}"


@dataclass
class Result:
    """Lo que devuelve toda puerta, toda sonda y toda validación de refuto.

    Un único contrato es lo que hace que el informe se componga solo y que añadir una puerta
    cueste un archivo en vez de tocar el emisor de evidencia.
    """
    id: str
    name: str
    status: str
    severity: str = MEDIUM
    threshold: str = ""
    measure: str = ""
    findings: list = field(default_factory=list)
    evidence: list = field(default_factory=list)
    observations: list = field(default_factory=list)
    provenance: dict = field(default_factory=dict)
    duration_ms: int = 0
    blocks: bool = True

    def __post_init__(self) -> None:
        if self.status not in STATUSES:
            raise ValueError(f"estado inválido {self.status!r}; permitidos: {STATUSES}")
        if self.severity not in SEVERITIES:
            raise ValueError(f"severidad inválida {self.severity!r}")
        # Invariante duro 1: `NOT_APPLICABLE` sin motivo escrito es un aprobado vacuo con otro
        # nombre. El método sólo admite «no aplica» cuando está DECLARADO: quién lo dice y por
        # qué. Aquí eso se traduce en que `measure` no puede venir vacío.
        if self.status == NOT_APPLICABLE and not (self.measure or "").strip():
            raise ValueError(
                f"{self.id}: NOT_APPLICABLE sin `measure`. «No aplica» sólo vale declarado "
                f"con motivo: escriba por qué esta puerta no tiene sujeto en este espacio.")
        # Invariante duro 2: un resultado con hallazgos NO puede aprobar.
        #
        # Se comprueba aquí y no en cada puerta porque en cada puerta se olvida. G-HUMAN
        # clasificaba sus problemas en dos cubos y devolvía PASS con un hallazgo dentro cuando
        # el problema no caía en ninguno. Lo encontró su propia prueba negativa; esta línea
        # convierte ese defecto en imposible para las trece puertas a la vez.
        if self.status == PASS and self.findings:
            raise ValueError(
                f"{self.id}: PASS con {len(self.findings)} hallazgos. Un resultado con "
                f"hallazgos no aprueba: o el hallazgo sobra, o el estado está mal. "
                f"Primero: {self.findings[0].as_text() if hasattr(self.findings[0], 'as_text') else self.findings[0]}")

    @property
    def passing(self) -> bool:
        return self.status == PASS

    def to_dict(self) -> dict:
        return {
            "schema": SCHEMA_VERSION,
            "id": self.id,
            "name": self.name,
            "status": self.status,
            "severity": self.severity,
            "threshold": self.threshold,
            "measure": self.measure,
            "findings": [f.as_text() for f in self.findings],
            "evidence": [e.to_dict() for e in self.evidence],
            "observations": list(self.observations),
            "provenance": self.provenance,
            "duration_ms": self.duration_ms,
            "blocks": self.blocks,
        }


def not_executable(gate_id: str, name: str, why: str, err: BaseException | None = None) -> Result:
    """Una comprobación que revienta no aprueba. Se declara no ejecutable, y bloquea."""
    detail = f"{why}: {type(err).__name__}: {err}" if err else why
    return Result(gate_id, name, NOT_EXECUTABLE, severity=HIGH,
                  measure=f"la verificación no se pudo ejecutar — {detail}")


def blocked(gate_id: str, name: str, why: str) -> Result:
    """La comprobación no se intentó porque una dependencia declarada no está disponible."""
    return Result(gate_id, name, BLOCKED, severity=HIGH,
                  measure=f"no se intentó — {why}")


def not_applicable(gate_id: str, name: str, why: str, *, severity: str = INFO) -> Result:
    """La comprobación se intentó y NO HAY SUJETO en este espacio.

    No es un aprobado: el motivo va en `measure` y el veredicto de la corrida lo cuenta aparte.
    Severidad `INFO` por omisión porque no retiene nada; lo que no hace es sumar a los verdes.
    """
    return Result(gate_id, name, NOT_APPLICABLE, severity=severity,
                  measure=f"no aplica en este espacio — {why}")


# ── procedencia ──────────────────────────────────────────────────────────────────────
def _git(*args: str, cwd: Path | None = None) -> str:
    try:
        p = subprocess.run(["git", *args], cwd=str(cwd) if cwd else None,
                           capture_output=True, **TEXT_IO, timeout=10)
        return p.stdout.strip() if p.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


# ── identidad de ejecución ───────────────────────────────────────────────────────────
#
# Cuatro entidades con ciclos de vida distintos, y hasta el 2026-09-22 las cuatro se
# identificaban con el mismo formato `run_<hex16>` salido de la misma función:
#
#     core/run.py:168        ejecución orquestada  →  .harness/state/<id>.json
#     core/session.py:879    sesión interactiva    →  eventos `session/*` del diario
#     core/runcontext.py     contexto construido   →  .harness/context/
#     refuto.py:888          verificación          →  .harness/evidence/<id>.json
#
# De seis enlaces posibles entre ellas existía **uno** (`Run.context_run_id`). El síntoma
# visible: `refuto status` decía «no hay ninguna ejecución registrada» justo después de un
# `verify` que había impreso la ruta de su evidencia. Ninguno de los dos mentía — leían
# familias distintas con el mismo nombre.
#
# Fusionarlas en un solo id sería peor: una sesión contiene N verificaciones, una
# verificación puede ocurrir sin sesión (CI), y un contexto se reconstruye sin ejecución.
# Forzar una identidad única obligaría a inventar una ejecución sintética cada vez que
# faltara, y una entidad inventada para cuadrar el modelo es el dato falso que este sistema
# persigue. Ver ADR-0012.
#
# El tipo va en el identificador, no en el directorio: el directorio es una propiedad del
# almacenamiento, no de la entidad, y un id suelto en un diario tiene que poder decir qué es.
KIND_SESSION = "ses"
KIND_ORCHESTRATION = "orq"
KIND_VERIFICATION = "ver"
KIND_CONTEXT = "ctx"
#: Lo que se emitía antes. Se sigue LEYENDO para siempre; no se emite más. Un diario
#: histórico tiene que seguir siendo legible por el código que lo lee.
KIND_LEGACY = "run"

KINDS = (KIND_SESSION, KIND_ORCHESTRATION, KIND_VERIFICATION, KIND_CONTEXT)
_ID = re.compile(r"^(ses|orq|ver|ctx|run)_([0-9a-f]{16})$")


def new_id(kind: str) -> str:
    """Un identificador tipado. `kind` debe ser uno de `KINDS`.

    `KIND_LEGACY` se rechaza a propósito: se lee, no se escribe. Permitir emitirlo dejaría
    la puerta abierta a seguir acuñando identidades sin tipo, que es el defecto que esto cierra.
    """
    if kind not in KINDS:
        raise ValueError(f"tipo de identidad desconocido {kind!r}; hay {KINDS}. "
                         f"`{KIND_LEGACY}` sólo se lee, no se emite.")
    return f"{kind}_{uuid.uuid4().hex[:16]}"


def kind_of(identifier: str) -> str:
    """El tipo que declara ese identificador, o cadena vacía si no reconoce la forma.

    Vacío significa «no lo reconozco», y NO se debe leer como «es legado»: un id con forma
    ajena puede venir de otro programa que reclame el mismo directorio. Confundir las dos
    cosas es cómo un documento de otro contrato acaba tratado como propio.
    """
    m = _ID.match(identifier or "")
    return m.group(1) if m else ""


def new_run_id() -> str:
    """LEGADO. Emite el formato sin tipo. Conservado sólo para no romper a un llamador
    externo que aún lo importe; dentro de refuto no lo usa nadie desde el 2026-09-22.
    Use `new_id(KIND_*)`."""
    return f"{KIND_LEGACY}_{uuid.uuid4().hex[:16]}"


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def provenance(workspace: Path, extra: dict | None = None) -> dict:
    """De qué máquina, qué commit y qué versiones sale esta evidencia.

    Sin esto un informe dice que algo pasó, pero no sobre qué. No es evidencia: es una captura.
    """
    dirty = _git("status", "--porcelain", cwd=workspace)
    base = {
        "harness_version": VERSION,
        "generated_at": now(),
        "workspace": str(workspace),
        "git_commit": _git("rev-parse", "HEAD", cwd=workspace),
        "git_branch": _git("rev-parse", "--abbrev-ref", "HEAD", cwd=workspace),
        "git_dirty": bool(dirty),
        "python": platform.python_version(),
        "platform": f"{platform.system().lower()}-{platform.release()}-{platform.machine()}",
        "hostname_digest": "",
    }
    # El nombre de la máquina identifica a una persona en un equipo pequeño; se guarda su
    # huella, que sirve igual para correlacionar corridas y no expone a nadie.
    import hashlib
    base["hostname_digest"] = hashlib.sha256(platform.node().encode()).hexdigest()[:16]
    if extra:
        base.update(extra)
    return base


def write_json(path: Path, payload: dict | list) -> None:
    """Escritura atómica: se escribe al lado y se renombra.

    Un informe a medias es peor que ninguno — se lee como completo.

    El salto de línea se fija a LF, y no es cosmética: sin fijarlo, Windows traduce cada salto
    a CRLF y el mismo documento produce dos huellas distintas según quién lo escribió. Todo
    este proyecto compara por huella —el lock, la evidencia, el manifiesto—, así que un byte de
    más convierte «idéntico» en «deriva» y hace fallar una puerta que no tenía nada que
    reprochar.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8", newline="\n")
    os.replace(tmp, path)
