# -*- coding: utf-8 -*-
"""Diario de evidencia. JSON Lines, append-only, con procedencia.

Regla de dirección, y es la que separa evidencia de informe:

    evidencia estructurada  →  informe humano
    NUNCA al revés

Un informe HTML del que después se extraen datos es una captura con pretensiones. Lo que se
audita dentro de un año es el JSONL.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
from pathlib import Path

from core.model import now, provenance

LEDGER = "ledger.jsonl"

#: Con qué mecanismo se serializa `append_event`. Se expone para poder AFIRMARLO: una prueba
#: que dijera «la cadena aguanta la concurrencia» sin saber si hubo bloqueo estaría midiendo la
#: suerte del planificador.
try:                                                                  # pragma: no cover
    import fcntl as _fcntl
    MECANISMO_DE_BLOQUEO = "fcntl.flock"
except ImportError:                                                   # pragma: no cover
    _fcntl = None
    try:
        import msvcrt as _msvcrt
        MECANISMO_DE_BLOQUEO = "msvcrt.locking"
    except ImportError:
        _msvcrt = None
        MECANISMO_DE_BLOQUEO = ""
else:                                                                 # pragma: no cover
    _msvcrt = None


@contextlib.contextmanager
def _exclusivo(fh):
    """Bloqueo exclusivo sobre el diario mientras se lee la cabeza y se escribe el eslabón.

    Por qué hace falta, medido el 2026-09-25
    -----------------------------------------
    `append_event` leía la cabeza y escribía sin serializar, y el argumento de que eso bastaba
    —una escritura de menos de PIPE_BUF en modo `a` no se entrelaza— es correcto **sobre los
    bytes** y no dice nada **sobre la cadena**. Dos guardianes concurrentes leen la misma cabeza
    y emiten dos eventos con el mismo `prev`. Con 12 invocaciones simultáneas:

        eventos escritos : 12
        cadena ok        : False  (rota en la línea 3)
        motivo           : «falta, sobra o se movió algún evento entre medias»

    Es decir, el diario acusaba de MANIPULACIÓN lo que era concurrencia normal — y un agente de
    código invoca herramientas en paralelo de forma rutinaria. Una alarma de integridad que
    salta con el uso normal se aprende a ignorar, que es el mismo modo de muerte que este
    repositorio ya documentó en `core.policy._partir` (comillas) y en `dd:*` (`ddev`).

    Si no hay mecanismo de bloqueo se SIGUE escribiendo, sin bloquear. Perder el evento sería
    peor que perder la serialización, y el estado queda declarado en `MECANISMO_DE_BLOQUEO`
    para que nadie afirme una garantía que este proceso no tiene.
    """
    if _fcntl is not None:
        _fcntl.flock(fh.fileno(), _fcntl.LOCK_EX)
        try:
            yield True
        finally:
            _fcntl.flock(fh.fileno(), _fcntl.LOCK_UN)
        return
    if _msvcrt is not None:                                           # pragma: no cover
        fh.seek(0)
        try:
            _msvcrt.locking(fh.fileno(), _msvcrt.LK_LOCK, 1)
        except OSError:
            yield False       # no se pudo bloquear: se escribe igual y se declara
            return
        try:
            yield True
        finally:
            with contextlib.suppress(OSError):
                fh.seek(0)
                _msvcrt.locking(fh.fileno(), _msvcrt.LK_UNLCK, 1)
        return
    yield False                                                       # pragma: no cover


def ledger_path(workspace: Path) -> Path:
    return workspace / ".harness" / "evidence" / LEDGER


#: Semilla de la cadena de huellas. Un diario vacío tiene una cabeza definida, así que
#: «no hay eventos» y «me borraron los eventos» dejan de ser el mismo estado.
GENESIS = hashlib.sha256(b"harness.ledger/v1").hexdigest()


def _canonico(evento: dict) -> str:
    """El texto del que se saca la huella. Claves ordenadas y sin espacios: dos procesos
    distintos tienen que producir el mismo byte para el mismo evento."""
    return json.dumps({k: v for k, v in sorted(evento.items()) if k != "h"},
                      ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _eslabon(previo: str, evento: dict) -> str:
    return hashlib.sha256((previo + "\n" + _canonico(evento)).encode("utf-8")).hexdigest()


def _ultima_linea(fh) -> str:
    """La última línea no vacía, leyendo desde el FINAL. `fh` abierto en binario.

    La versión anterior hacía `read_text().splitlines()` del diario entero, y `append_event` la
    llama en cada evento: el guardián leía el fichero completo antes de cada decisión. Con 1.779
    eventos el coste es invisible; el diario es de sólo añadir, así que crece sin techo y el
    coste con él — en el camino caliente, que es donde un control lento se acaba desactivando.

    Se leen bloques desde el final hasta encontrar un salto de línea. El caso normal —la última
    línea mide unos cientos de bytes— se resuelve con UNA lectura de 4 KiB.
    """
    fh.seek(0, os.SEEK_END)
    fin = fh.tell()
    if fin == 0:
        return ""
    bloque, datos, pos = 4096, b"", fin
    while pos > 0:
        paso = min(bloque, pos)
        pos -= paso
        fh.seek(pos)
        datos = fh.read(paso) + datos
        lineas = [ln for ln in datos.split(b"\n") if ln.strip()]
        # Con más de una línea completa, la última ya está entera: sólo si `pos == 0` puede
        # la primera estar cortada, y entonces no hay más fichero que leer.
        if len(lineas) > 1 or pos == 0:
            return lineas[-1].decode("utf-8", "replace") if lineas else ""
    return ""


def cabeza(workspace: Path) -> str:
    """La huella del último evento del diario, o `GENESIS` si no hay ninguno.

    Leer la cabeza es barato y no exige recorrer la cadena: es el campo `h` de la última
    línea legible. Verificarla SÍ exige recorrerla, y para eso está `verificar_cadena`.
    """
    path = ledger_path(workspace)
    if not path.is_file():
        return GENESIS
    try:
        with path.open("rb") as fh:
            ultima = _ultima_linea(fh)
    except OSError:
        return GENESIS
    if not ultima:
        return GENESIS
    try:
        return str(json.loads(ultima).get("h") or GENESIS)
    except json.JSONDecodeError:
        return GENESIS


def append_event(workspace: Path, event: dict) -> None:
    """Añade un evento al diario, encadenado por huella. Append atómico: una línea, una
    escritura.

    En POSIX, una escritura de menos de PIPE_BUF a un descriptor abierto en modo `a` no se
    entrelaza con la de otro proceso. Por eso los eventos del guardián —que corre en procesos
    distintos y concurrentes— no se corrompen entre sí.

    La cadena, y qué compra
    -----------------------
        h₀ = H("harness.ledger/v1")
        hᵢ = H( hᵢ₋₁ ‖ canonical(eventoᵢ) )

    El diario era JSON Lines plano: sin huella, sin firma, sin encadenar. «Sólo añadir» era
    una propiedad de QUIEN ESCRIBE, no una propiedad frente a quien lee o edita. Medido el
    2026-09-23: purgar selectivamente las denegaciones dejaba un diario coherente, más corto
    y sin rastro de la purga.

    Con la cadena, borrar, reordenar o editar un evento rompe todos los eslabones
    posteriores. **Esto es tamper-EVIDENCIA, no tamper-proofing**: un adversario que reescriba
    la cadena ENTERA y todas sus copias publicadas produce un diario coherente. Lo que ya no
    puede es editar una línea y marcharse. Ver FORMAL-MODEL §3.5.

    Leer la cabeza y escribir el eslabón es UNA operación
    -----------------------------------------------------
    Las dos van dentro del mismo bloqueo exclusivo (`_exclusivo`). Separarlas es lo que hacía
    que dos guardianes concurrentes encadenaran los dos al mismo `prev` y produjeran un diario
    que `verificar_cadena` declaraba manipulado. La atomicidad de los BYTES no da atomicidad de
    la CADENA: son dos propiedades y sólo una se seguía de `O_APPEND`.
    """
    path = ledger_path(workspace)
    path.parent.mkdir(parents=True, exist_ok=True)
    # `a+` y no `a`: hace falta LEER la cabeza con el bloqueo ya tomado. Leerla antes de
    # abrir —como se hacía— deja la ventana entre la lectura y la escritura, que es justo la
    # carrera. Se abre en binario porque `_ultima_linea` busca desde el final.
    with path.open("a+b") as fh:
        with _exclusivo(fh):
            ultima = _ultima_linea(fh)
            previo = GENESIS
            if ultima:
                try:
                    previo = str(json.loads(ultima).get("h") or GENESIS)
                except json.JSONDecodeError:
                    previo = GENESIS
            record = {"ts": now(), **event, "prev": previo}
            record["h"] = _eslabon(previo, record)
            line = json.dumps(record, ensure_ascii=False) + "\n"
            fh.seek(0, os.SEEK_END)
            fh.write(line.encode("utf-8"))
            fh.flush()
            os.fsync(fh.fileno())


def verificar_cadena(workspace: Path, esperado: str = "") -> dict:
    """Recorre el diario y comprueba que cada eslabón cierra.

    `esperado` es un ANCLA PUBLICADA: una cabeza que alguien guardó fuera de este árbol
    (en el registro de CI, en un mensaje de commit, en otra máquina). Sirve para lo único
    que la cadena por sí sola NO puede detectar.

    El límite, dicho sin rodeos
    ---------------------------
    Cortar la COLA del diario deja una cadena que cierra: los eslabones que quedan siguen
    siendo consistentes entre sí. Medido mientras se escribía esto — purgar los eventos
    posteriores al veredicto daba `ok`. Dentro de un único fichero mutable eso no es
    detectable por construcción: no hay nada que diga cuántos eventos «debería» haber.
    Con `esperado` sí: si la huella publicada ya no está en la cadena, el diario se cortó
    por detrás de ella. Sin ancla publicada, la truncación de cola queda **NOT_PROVEN**.
    Obtenga una con `refuto evidence --anchor` y guárdela fuera del espacio.

    Devuelve `{"ok", "eventos", "rota_en", "motivo", "cabeza"}`. `ok=False` NO dice quién lo
    hizo ni por qué: dice que el diario de ahora no es el que se escribió.

    Un evento sin `prev`/`h` se cuenta como `legado`: los diarios escritos antes de que
    existiera la cadena siguen siendo legibles, y tratarlos como rotos convertiría toda
    instalación previa en sospechosa el día de la actualización — que es como se enseña a
    ignorar una alarma.
    """
    path = ledger_path(workspace)
    if not path.is_file():
        return {"ok": True, "eventos": 0, "legado": 0, "rota_en": -1, "motivo": "",
                "cabeza": GENESIS}
    previo, n, legado = GENESIS, 0, 0
    vistas: set = set()
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines()):
        if not line.strip():
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError as exc:
            return {"ok": False, "eventos": n, "legado": legado, "rota_en": i,
                    "motivo": f"la línea {i + 1} no es JSON legible: {exc}", "cabeza": previo}
        n += 1
        if "h" not in ev or "prev" not in ev:
            legado += 1
            continue
        if ev["prev"] != previo:
            return {"ok": False, "eventos": n, "legado": legado, "rota_en": i,
                    "motivo": f"la línea {i + 1} encadena a {str(ev['prev'])[:12]}… y el "
                              f"evento anterior es {previo[:12]}…: falta, sobra o se movió "
                              f"algún evento entre medias.", "cabeza": previo}
        huella = _eslabon(previo, ev)
        if ev["h"] != huella:
            return {"ok": False, "eventos": n, "legado": legado, "rota_en": i,
                    "motivo": f"la línea {i + 1} lleva huella {str(ev['h'])[:12]}… y su "
                              f"contenido produce {huella[:12]}…: el evento se editó "
                              f"después de escribirse.", "cabeza": previo}
        vistas.add(ev["h"])
        previo = ev["h"]
    if esperado and esperado != GENESIS and esperado not in vistas:
        return {"ok": False, "eventos": n, "legado": legado, "rota_en": -1,
                "motivo": f"el ancla publicada {esperado[:12]}… no está en la cadena: el "
                          f"diario se cortó por detrás de ella o se reescribió entero.",
                "cabeza": previo}
    return {"ok": True, "eventos": n, "legado": legado, "rota_en": -1, "motivo": "",
            "cabeza": previo}


def read_events(workspace: Path, kinds: list | None = None) -> list:
    path = ledger_path(workspace)
    if not path.is_file():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if kinds and ev.get("kind") not in kinds:
            continue
        out.append(ev)
    return out


def write_run(workspace: Path, run_id: str, results: list, extra: dict | None = None) -> Path:
    """Escribe el informe estructurado de una corrida y devuelve su ruta.

    El artefacto se COMPROMETE con tres cosas que no están dentro de él
    -------------------------------------------------------------------
    `engine_digest`  qué programa emitió este veredicto (`core.trust`). Si el juez cambia,
                     el veredicto de antes y el de ahora no los emitió el mismo programa, y
                     eso se puede afirmar sin tener que impedir la edición. Es `I6'`.
    `ledger_head`    la cabeza de la cadena del diario en el instante de escribir.
    `gates`          el estado de cada puerta, que también viaja al diario.

    El compromiso es lo que convierte la redundancia en detección. Medido el 2026-09-23:
    editando SÓLO el artefacto —conservando su `mtime`— `refuto status` pasaba de
    «NO INTEGRABLE · 2 en rojo» a «INTEGRABLE · 0 en rojo», y el diario conservaba intacto
    el veredicto verdadero sin que nadie los comparara. Los datos ya estaban; faltaba el
    cruce. Ahora lo hace `latest_verification`.
    """
    from core.model import write_json
    from core.trust import digest_motor

    estados = {r.id: r.status for r in results}
    # El evento va PRIMERO: si se escribiera después, un fallo entre las dos escrituras
    # dejaría un artefacto sin contraparte en el diario, y «no hay con qué comparar» es
    # indistinguible de «alguien borró la contraparte».
    append_event(workspace, {"kind": "run/complete", "run_id": run_id,
                             "verdict": verdict_of(results), "gates": estados})
    payload = {
        "schema": "harness.run/v1",
        "run_id": run_id,
        "provenance": provenance(workspace, extra),
        "verdict": verdict_of(results),
        "engine_digest": digest_motor(),
        "ledger_head": cabeza(workspace),
        "gates": [r.to_dict() for r in results],
    }
    path = workspace / ".harness" / "evidence" / f"{run_id}.json"
    write_json(path, payload)
    return path


def reconciliar(workspace: Path, doc: dict) -> dict:
    """¿Dice el diario lo mismo que este artefacto? Es la comprobación de `I4`.

    Tres veredictos, y los tres son distintos a propósito:

        `ok`            las dos fuentes coinciden y la cadena cierra
        `contradice`    las dos fuentes son legibles y NO coinciden  →  FAIL
        `indeterminado` no se pudo establecer la integridad          →  INCONCLUSIVE

    La tercera existe porque «no pude comprobarlo» no es «está mal» ni «está bien». Un
    artefacto de antes de que existiera la cadena cae aquí, y cae en un estado que no
    aprueba pero tampoco acusa.
    """
    run_id = doc.get("run_id", "")
    declarado = {g.get("id", ""): g.get("status", "") for g in doc.get("gates", [])}
    cadena = verificar_cadena(workspace)
    if not cadena["ok"]:
        return {"estado": "contradice", "motivo": f"la cadena del diario está rota: "
                                                  f"{cadena['motivo']}"}
    # Truncar el diario entero lo dejaba «coherente»: una cadena vacía cierra trivialmente,
    # que es la misma verdad vacua que este trabajo existe para cerrar — y la cometí aquí al
    # escribirlo. El artefacto se comprometió con la cabeza que había al emitirse, así que
    # esa huella TIENE que seguir estando: si desapareció, el diario se cortó por detrás.
    ancla = str(doc.get("ledger_head") or "")
    if ancla:
        huellas = {str(e.get("h") or "") for e in read_events(workspace)}
        if ancla != GENESIS and ancla not in huellas:
            return {"estado": "contradice",
                    "motivo": f"el artefacto se ancló a la cabeza {ancla[:12]}… del diario y "
                              f"esa huella ya no está en la cadena: el diario se truncó o se "
                              f"reescribió después de emitir el veredicto."}

    eventos = [e for e in read_events(workspace, ["run/complete"])
               if e.get("run_id") == run_id]
    if not eventos:
        return {"estado": "indeterminado",
                "motivo": f"el diario no registra ninguna corrida «{run_id}»: no hay con qué "
                          f"contrastar el artefacto. Puede ser un artefacto de otro espacio, "
                          f"o un diario truncado."}
    ev = eventos[-1]
    if ev.get("gates") != declarado:
        difs = [f"{k}: artefacto dice {declarado.get(k, '—')} y diario dice {v}"
                for k, v in (ev.get("gates") or {}).items() if declarado.get(k) != v]
        return {"estado": "contradice",
                "motivo": f"el artefacto y el diario discrepan en {len(difs)} puerta(s): "
                          f"{'; '.join(difs[:3])}. Dos registros de la misma corrida que no "
                          f"coinciden: uno de los dos se editó después."}
    if ev.get("verdict") != doc.get("verdict"):
        return {"estado": "contradice",
                "motivo": f"el artefacto declara «{doc.get('verdict')}» y el diario registró "
                          f"«{ev.get('verdict')}» para la misma corrida."}
    return {"estado": "ok", "motivo": f"artefacto y diario coinciden · {cadena['eventos']} "
                                      f"eventos encadenados"}


def latest_verification(workspace: Path) -> dict | None:
    """La última verificación registrada: `{run_id, verdict, gates, path, generated_at}`.

    Por qué existe
    --------------
    `refuto verify` escribía aquí e imprimía la ruta; `refuto status` leía
    `.harness/state/` (las ejecuciones orquestadas, `core/run.py`) y respondía **«no hay
    ninguna ejecución registrada»** justo después. Ninguno de los dos mentía: leían dos
    familias distintas que, hasta la identidad tipada, además se llamaban igual.

    La corrección NO es fusionarlas —una sesión contiene N verificaciones y una verificación
    puede ocurrir sin orquestación, en CI—, sino que quien informa del estado lea **las dos
    fuentes** y las nombre por separado. Ver ADR-0012.

    Devuelve `None` sólo cuando no hay ninguna. Un fichero ilegible NO se salta en silencio:
    se declara en `unreadable`, porque «no pude leerlo» y «no existe» son cosas distintas y
    confundirlas es el defecto que este módulo entero existe para impedir.
    """
    d = workspace / ".harness" / "evidence"
    if not d.is_dir():
        return None
    candidatos = [p for p in d.glob("*.json") if p.name != "sbom.json"]
    if not candidatos:
        return None
    unreadable = []
    mejor = None
    for p in sorted(candidatos, key=lambda x: x.stat().st_mtime, reverse=True):
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            unreadable.append({"path": str(p), "problem": f"{type(exc).__name__}: {exc}"})
            continue
        if doc.get("schema") != "harness.run/v1":
            continue
        integridad = reconciliar(workspace, doc)
        veredicto = doc.get("verdict", "")
        if integridad["estado"] != "ok":
            # El veredicto del artefacto deja de ser la autoridad en cuanto su integridad
            # no se sostiene. No se «corrige» el veredicto —no se sabe cuál era— : se
            # declara que no se puede afirmar. Un informe que sigue imprimiendo INTEGRABLE
            # mientras su respaldo no cuadra es exactamente la captura con pretensiones que
            # el encabezado de este módulo rechaza.
            veredicto = (f"NO INTEGRABLE — la evidencia no se sostiene: "
                         f"{integridad['motivo']}")
        mejor = {
            "run_id": doc.get("run_id", ""),
            "verdict": veredicto,
            "gates": {g.get("id", ""): g.get("status", "") for g in doc.get("gates", [])},
            "generated_at": (doc.get("provenance") or {}).get("generated_at", ""),
            "path": str(p),
            "unreadable": unreadable,
            "integrity": integridad,
        }
        break
    if mejor is None and unreadable:
        return {"run_id": "", "verdict": "", "gates": {}, "generated_at": "", "path": "",
                "unreadable": unreadable}
    return mejor


def verdict_of(results: list) -> str:
    """Un veredicto por corrida, con las mismas palabras que las puertas.

    El orden importa: un NOT_EXECUTABLE manda sobre un FAIL porque significa que ni siquiera
    se sabe cuántos fallos hay.

    `NOT_APPLICABLE` no impide integrar, pero **tampoco cuenta como aprobado**: una corrida en
    la que ninguna puerta encontró sujeto no es INTEGRABLE, es una corrida sin ámbito. Ésa es
    la diferencia que un `PASS` de cortesía borraba.
    """
    from core.model import (BLOCKED, FAIL, INCONCLUSIVE, NOT_APPLICABLE, NOT_EXECUTABLE,
                            PASS)

    # `PASS ⟹ Proof(PASS)`, aplicado por quien tiene autoridad de veredicto.
    #
    # Una puerta que aprueba sin declarar CUÁNTO miró no ha demostrado nada: «no encontré
    # nada» y «no miré nada» producen el mismo resultado y no son el mismo hecho. El
    # invariante no se puede exigir al construir `Result` —el registro de puertas vive en
    # `gates/`, que la política protege del propio sujeto— así que se exige aquí, que es
    # donde se decide si la corrida es integrable. Una puerta sin cobertura declarada NO
    # retiene el cambio por sí sola, pero tampoco suma a los verdes: cuenta como
    # `INCONCLUSIVE`. Ver FORMAL-MODEL §3.3 e `I1`.
    sin_prueba = [r.id for r in results
                  if r.status == PASS and getattr(r, "scope", None) is None]
    statuses = {r.status for r in results}
    if sin_prueba:
        statuses.discard(PASS)
        statuses.add(INCONCLUSIVE)
        if any(r.status == PASS and getattr(r, "scope", None) is not None
               for r in results):
            statuses.add(PASS)
    if NOT_EXECUTABLE in statuses:
        return "NO INTEGRABLE — hay verificaciones que no se pudieron ejecutar"
    if FAIL in statuses:
        return "NO INTEGRABLE — hay puertas en rojo"
    if BLOCKED in statuses:
        return "NO INTEGRABLE TODAVÍA — hay puertas que no se pudieron comprobar"
    # Después de los tres bloqueantes «duros»: un fallo real manda sobre un aprobado sin
    # justificar, porque el primero dice qué está mal y el segundo sólo dice que no se sabe.
    if INCONCLUSIVE in statuses:
        return (f"NO INTEGRABLE — {len(sin_prueba)} puerta(s) aprueban sin declarar qué "
                f"observaron: {', '.join(sin_prueba[:4])}. Un PASS sin cobertura no es una "
                f"demostración")
    if not statuses:
        return "SIN PUERTAS EJECUTADAS"
    if PASS not in statuses:
        n = sum(1 for r in results if r.status == NOT_APPLICABLE)
        return (f"SIN ÁMBITO — ninguna puerta encontró nada que comprobar "
                f"({n} no aplican). Eso no es un aprobado")
    if statuses <= {PASS, NOT_APPLICABLE}:
        n = sum(1 for r in results if r.status == NOT_APPLICABLE)
        return "INTEGRABLE" + (f" — {n} puertas sin sujeto en este espacio" if n else "")
    return "SIN PUERTAS EJECUTADAS"
