# -*- coding: utf-8 -*-
"""El guardián. Un solo programa; todos los ganchos de todos los runtimes lo invocan.

    python3 -m core.guard --runtime {kiro|claude|gemini|opencode|antigravity} --stdin

Lee por la entrada estándar la carga del gancho —que tiene forma distinta en cada runtime—, la
normaliza, aplica la política canónica y responde en el dialecto que ese runtime entiende.

Por qué un solo programa
------------------------
Porque la alternativa comprobada fue tener la regla escrita en dos vocabularios y aplicada en
uno (H-03). Traducir la CARGA es un problema de veinte líneas por runtime; traducir la REGLA es
un problema que diverge. Se traduce la carga.

Cómo responde cada runtime, verificado en su documentación instalada:

    claude    JSON en stdout con `hookSpecificOutput.permissionDecision` ∈ {allow, deny, ask}
              y salida 0. Salida 2 también bloquea, con stderr al modelo.
    kiro      salida ≠ 0 bloquea; stderr explica.
    gemini    salida ≠ 0 bloquea; stderr explica.
    antigravity  JSON en stdout `{"decision": allow|deny|ask, "reason"}`, salida 0 siempre
              (el código de salida no está documentado: ver core/antigravity.py).
    otros     salida ≠ 0 bloquea.

Cuando el dialecto exacto de un runtime NO consta verificado, se usa el mecanismo universal
—salida distinta de cero— y se registra en el evento que la respuesta fue genérica. Nunca se
inventa un campo.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from core.policy import (ALLOW, ASK, DENY, Decision, PoliticaIlegible, Policy,
                         decide_command, decide_write)
from core.proc import euid, force_utf8_io

#: Cómo se llama, en cada runtime, el campo que trae la ruta y el contenido.
_SHAPES = {
    "claude": {
        "tool": ("tool_name",),
        "path": ("tool_input.file_path", "tool_input.path", "tool_input.notebook_path"),
        "content": ("tool_input.content", "tool_input.new_string", "tool_input.new_source"),
        "command": ("tool_input.command",),
        "cwd": ("cwd",),
        "structured": True,
    },
    "kiro": {
        "tool": ("tool_name", "toolName", "name"),
        "path": ("tool_input.path", "toolInput.path", "input.path", "path", "arguments.path"),
        "content": ("tool_input.content", "toolInput.content", "input.content", "content",
                    "arguments.content", "tool_input.file_text", "arguments.file_text"),
        "command": ("tool_input.command", "toolInput.command", "input.command", "command"),
        "cwd": ("cwd", "workspace"),
        "structured": False,
    },
    "gemini": {
        "tool": ("tool_name", "toolName", "name"),
        "path": ("tool_input.file_path", "tool_input.absolute_path", "args.file_path",
                 "args.absolute_path", "path"),
        "content": ("tool_input.content", "args.content", "args.new_string", "content"),
        "command": ("tool_input.command", "args.command", "command"),
        "cwd": ("cwd",),
        "structured": False,
    },
    "opencode": {
        "tool": ("tool", "tool_name", "name"),
        "path": ("args.filePath", "args.path", "path"),
        "content": ("args.content", "args.newString", "content"),
        "command": ("args.command", "command"),
        "cwd": ("cwd",),
        "structured": False,
    },
}


def _dig(doc: dict, dotted: str):
    node = doc
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def _first(doc: dict, keys) -> str:
    for key in keys:
        value = _dig(doc, key)
        if isinstance(value, str) and value:
            return value
    return ""


def normalize(runtime: str, payload: dict) -> dict:
    """Carga del gancho → hecho canónico. Sin esto, cada runtime traería su propia política."""
    shape = _SHAPES.get(runtime, _SHAPES["kiro"])
    return {
        "runtime": runtime,
        "tool": _first(payload, shape["tool"]),
        "path": _first(payload, shape["path"]),
        "content": _first(payload, shape["content"]),
        "command": _first(payload, shape["command"]),
        "cwd": _first(payload, shape["cwd"]),
        "structured_reply": shape["structured"],
    }


def evaluate(policy: Policy, workspace: Path, fact: dict):
    """Aplica la política al hecho normalizado. Una escritura, una orden, o nada que decidir."""
    if fact["command"]:
        return decide_command(policy, fact["command"]), "command"
    if fact["path"]:
        return decide_write(policy, workspace, fact["path"], fact["content"]), "write"
    from core.policy import Decision
    return Decision(ALLOW, reason="la carga del gancho no trae ruta ni orden que evaluar"), "none"


def _emit_event(workspace: Path, fact: dict, decision, kind: str) -> str:
    """Toda decisión del guardián deja rastro. Un control sin rastro no se puede auditar.

    Si no se puede escribir el evento, el guardián NO se cae —bloquear una escritura legítima
    porque el diario está lleno sería peor que perder una línea— pero **tampoco se calla**.

    La primera versión imprimía a stderr y seguía. En una decisión `allow` con respuesta
    estructurada, stderr no llega a ninguna parte: una aprobación sin registrar quedaba idéntica
    a una registrada. Un rastro que se corta en silencio es peor que no tenerlo, porque nadie lo
    echa en falta. Ahora el fallo viaja **dentro de la propia decisión**.

    Devuelve un aviso para adjuntar a la respuesta, o cadena vacía.
    """
    try:
        from core.evidence import append_event
        append_event(workspace, {
            "kind": "policy/decision",
            "runtime": fact["runtime"],
            "tool": fact["tool"],
            "operation": kind,
            "target": fact["path"] or fact["command"],
            "outcome": decision.outcome,
            "rule": decision.rule,
            "reason": decision.reason,
            "euid": euid(),
            "sudo_user": os.environ.get("SUDO_USER", ""),
        })
    except Exception as exc:                                            # noqa: BLE001
        aviso = (f"AUDITORÍA INTERRUMPIDA: esta decisión no se pudo registrar en "
                 f"{workspace}/.harness/evidence/ledger.jsonl ({type(exc).__name__}: {exc}). "
                 f"Causa habitual: el diario quedó en manos de root tras una sesión con sudo. "
                 f"Arréglelo con: sudo chown -R $USER .harness")
        print(f"harness-guard: {aviso}", file=sys.stderr)
        return aviso
    return ""


def main(argv: list | None = None) -> int:
    # Lo PRIMERO, antes de que nada pueda imprimir: la decisión viaja por stdout y los motivos
    # por stderr. En una consola cp1252, un solo carácter del propio mensaje derriba el proceso
    # antes de emitir el JSON, y un gancho que no emite nada no es un gancho que permite: es un
    # gancho que el runtime interpreta como le parece.
    force_utf8_io()

    # `harness-guard` y no `refuto-guard`: es el nombre con el que este programa aparece EN LOS
    # GANCHOS ya instalados (`core.wire.MARK`) y en los mensajes que el runtime muestra cuando
    # bloquea. Es parte del formato de datos compartido con los espacios existentes, igual que
    # `.harness/` y `HARNESS_*`, no del nombre comercial del producto.
    parser = argparse.ArgumentParser(prog="harness-guard", add_help=True)
    parser.add_argument("--runtime", default="kiro", choices=sorted(set(_SHAPES) | {"antigravity"}))
    parser.add_argument("--stdin", action="store_true",
                        help="lee la carga del gancho por la entrada estándar")
    parser.add_argument("--workspace", default="")
    parser.add_argument("--path", default="", help="modo directo, para pruebas")
    parser.add_argument("--content", default="")
    parser.add_argument("--command", default="")
    opts = parser.parse_args(argv)

    raw = ""
    if opts.stdin and not sys.stdin.isatty():
        raw = sys.stdin.read()
    payload: dict = {}
    if opts.runtime == "antigravity":
        return _main_antigravity(opts, raw)
    if raw.strip():
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            # Una carga que no es JSON no se puede evaluar. NO se deja pasar: un guardián que
            # aprueba lo que no entiende no es un guardián.
            print("harness-guard: la carga del gancho no es JSON válido; se bloquea por "
                  "principio de precaución.", file=sys.stderr)
            return 2

    fact = normalize(opts.runtime, payload)
    if opts.path:
        fact["path"] = opts.path
    if opts.content:
        fact["content"] = opts.content
    if opts.command:
        fact["command"] = opts.command

    workspace = Path(opts.workspace or fact["cwd"] or os.getcwd()).resolve()
    policy_file = workspace / ".harness" / "policy.json"
    try:
        policy = Policy.load(policy_file) if policy_file.is_file() else Policy.default()
    except PoliticaIlegible as exc:
        # BLOCKED no aprueba. Un guardián que no entiende su política está en el mismo estado
        # que un guardián que no se encuentra: no puede afirmar nada, luego no deja pasar.
        policy = None
        decision = Decision(DENY, f"política ilegible en {policy_file}: {exc}")

    if policy is None:
        _emit_event(workspace, fact, decision, "policy/illegible")
        if fact["structured_reply"]:
            print(json.dumps({"hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": decision.reason}}, ensure_ascii=False))
            return 0
        print(decision.reason, file=sys.stderr)
        return 2

    decision, kind = evaluate(policy, workspace, fact)
    aviso = _emit_event(workspace, fact, decision, kind)

    # Si esto corre como root bajo sudo, se devuelve `.harness/` a quien invocó. Sin ello, una
    # sola sesión con sudo deja a la persona sin poder escribir su propio rastro.
    try:
        from core.launcher import restore_ownership
        restore_ownership(workspace)
    except Exception:                                                   # noqa: BLE001
        pass

    if fact["structured_reply"]:
        mapping = {ALLOW: "allow", DENY: "deny", ASK: "ask"}
        motivo = decision.reason or "política de refuto"
        if aviso:
            motivo = f"{motivo}\n\n⚠ {aviso}"
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": mapping[decision.outcome],
                "permissionDecisionReason": motivo,
            }
        }, ensure_ascii=False))
        return 0

    if decision.outcome == DENY:
        print(f"harness-guard: BLOQUEADO — {decision.reason}", file=sys.stderr)
        return 2
    if decision.outcome == ASK:
        print(f"harness-guard: REQUIERE APROBACIÓN — {decision.reason}", file=sys.stderr)
        return 2
    # Éxito silencioso: un guardián que habla cuando todo va bien se aprende a ignorar.
    # La excepción es el fallo de auditoría, que no es «todo bien».
    return 2 if aviso else 0


_ORDEN_DECISION = {ALLOW: 0, ASK: 1, DENY: 2}


def _main_antigravity(opts, raw: str) -> int:
    """Antigravity: la decisión SIEMPRE viaja en stdout, con salida 0.

    Su documentación no dice qué hace con un gancho que sale con código distinto de cero; un
    guardián no puede apoyar un bloqueo en un comportamiento no documentado. Por eso aquí no
    hay `return 2`: hay un `deny` explícito.
    """
    from core import antigravity as ag

    try:
        payload = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        print(ag.responder("deny", "harness-guard: la carga del gancho no es JSON válido; "
                                   "se bloquea por principio de precaución."))
        return 0
    if not isinstance(payload, dict):
        print(ag.responder("deny", "harness-guard: carga de gancho con forma desconocida."))
        return 0

    workspace = Path(opts.workspace or ag.espacio(payload) or os.getcwd()).resolve()
    if ag.es_pre_invocacion(payload):
        print(ag.pre_invocacion(workspace, payload))
        return 0

    ag.registrar_sesion(workspace, "antigravity", str(payload.get("conversationId") or ""))
    herramienta, facts = ag.hechos(payload)
    if not facts:
        print(ag.responder("allow", f"{herramienta or 'herramienta'}: nada que refuto "
                                    f"deba decidir (lectura o sin ruta ni orden)"))
        return 0

    policy_file = workspace / ".harness" / "policy.json"
    try:
        policy = Policy.load(policy_file) if policy_file.is_file() else Policy.default()
    except PoliticaIlegible as exc:
        decision = Decision(DENY, f"política ilegible en {policy_file}: {exc}")
        _emit_event(workspace, facts[0], decision, "policy/illegible")
        print(ag.responder("deny", decision.reason))
        return 0

    peor, motivos, avisos = ALLOW, [], []
    for fact in facts:
        decision, kind = evaluate(policy, workspace, fact)
        aviso = _emit_event(workspace, fact, decision, kind)
        if aviso:
            avisos.append(aviso)
        if _ORDEN_DECISION[decision.outcome] > _ORDEN_DECISION[peor]:
            peor = decision.outcome
        if decision.outcome != ALLOW:
            motivos.append(f"{fact['path'] or fact['command']}: {decision.reason}")
    try:
        from core.launcher import restore_ownership
        restore_ownership(workspace)
    except Exception:                                                   # noqa: BLE001
        pass

    nombre = {ALLOW: "allow", DENY: "deny", ASK: "ask"}[peor]
    motivo = "; ".join(motivos) or "política de refuto"
    if avisos:
        # Un fallo de auditoría no es «todo bien»: con decisión allow se convierte en ask.
        motivo += "\n\n⚠ " + " ".join(avisos)
        if nombre == "allow":
            nombre = "ask"
    print(ag.responder(nombre, f"harness-guard: {motivo}"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
