#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""refuto — plataforma de ingeniería para operar agentes de código.

  Dónde estoy
    refuto discover                entorno, núcleo SDD y repositorio, con confianza declarada
    refuto bind set|show|verify    ata este espacio a un núcleo y a un repositorio
    refuto doctor                  ¿qué hay en esta máquina y qué funciona de verdad?
    refuto probe [--deep]          escalera de ejecutabilidad de los agentes
    refuto inventory [--json]      inventario mecánico del conjunto de repositorios

  Qué voy a hacer
    refuto install                 deja el espacio operativo: política, vínculo, guardián
                                    y contexto que cualquier agente encuentra solo
    refuto init                    sólo la estructura mínima
    refuto context                 qué cree refuto que está pasando, y por qué
    refuto plan                    qué se ejecutaría, quién y con qué puertas
    refuto policy show|compile|wire|unwire|audit
    refuto lock plan|update|verify|show

  Hacerlo
    refuto work                    qué tiene pendiente, ya enrutado a su rol y su runtime
    refuto chat [--task N]         abre una sesión sobre esa tarea, con su rol y su spec
    refuto run [--execute]         conduce el ciclo; en seco salvo --execute
    refuto resume [<run-id>]       continúa, si el entorno no cambió
    refuto status                  dónde está el trabajo y qué espera a una persona

  Demostrarlo
    refuto verify [--gate G]       ejecuta las puertas y emite evidencia
    refuto mcp                     integridad referencial de la cadena MCP
    refuto evidence [--last N]     lee el diario estructurado
    refuto memory list|summary     memoria en capas; NO es evidencia
    refuto docs                    regenera la matriz de compatibilidad
    refuto selftest                el juez se prueba a sí mismo

Sólo biblioteca estándar. Se ejecuta con `python3 refuto.py` o `./refuto.py`.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from core import report as R                                             # noqa: E402
from core.context import Context                                         # noqa: E402
from core.evidence import read_events, verdict_of, write_run             # noqa: E402
from core.model import (                                                 # noqa: E402
    BLOCKED, FAIL, FUNCTIONAL, NOT_EXECUTABLE, PASS, new_run_id, now, rung, write_json,
)
from core.proc import TEXT_IO, force_utf8_io

REPO = Path(__file__).resolve().parent

# Códigos de salida. Tres, no dos: la diferencia entre «falló» y «no se pudo comprobar» es la
# razón de ser de refuto de gobierno, y desaparecería al colapsarlos.
EXIT_OK = 0
EXIT_FAIL = 1
EXIT_BLOCKED = 2
EXIT_USAGE = 64


def _ws(opts) -> Path:
    return Path(opts.workspace or os.getcwd()).resolve()


# ── doctor ───────────────────────────────────────────────────────────────────────────
def cmd_doctor(opts) -> int:
    from adapters.registry import all_specs
    from core.probe import probe_all

    ws = _ws(opts)
    print(R.bold(f"\nrefuto doctor · {ws}"))

    reports = probe_all(all_specs(), deep=opts.deep, workspace=ws)
    print(R.render_probes(reports))

    checks: list = []
    py = sys.version_info
    checks.append(("python", py >= (3, 10), f"{py.major}.{py.minor}.{py.micro} (mínimo 3.10)"))
    import shutil
    for tool, why in (("git", "procedencia y lock"), ("gh", "GitHub"), ("glab", "GitLab")):
        found = shutil.which(tool)
        checks.append((tool, bool(found), found or "no está en el PATH"))

    ctx = Context(workspace=ws)
    for label, path in (("manifiesto", ctx.manifest_path), ("lock", ctx.lock_path),
                        ("política", ctx.policy_path)):
        checks.append((label, path.is_file(), str(path) if path.is_file() else
                       f"falta — ejecute `refuto init`"))

    # El lanzador del guardián, y a quién pertenece lo que escribe.
    from core import launcher
    lz = launcher.check(ws)
    checks.append(("lanzador", lz["ok"], lz.get("reason") or lz.get("harness_home", "")))
    own = launcher.ownership_report(ws)
    if own["checked"]:
        checks.append(("propiedad", own["count"] == 0,
                       "todo pertenece a quien lo usa" if own["count"] == 0 else
                       f"{own['count']} archivos de .harness/ son de otro usuario — "
                       f"el rastro de auditoría se corta en silencio"))

    print(R.bold("  Entorno"))
    for name, ok, detail in checks:
        mark = R.paint("✓", "32") if ok else R.paint("✗", "31")
        print(f"    {mark} {name:<12} {R.dim(detail)}")
    print()

    from core import provider as prov
    # `ruta` y no `r`: la variable `r` la reusa el bucle de sondas más abajo, y el resumen
    # accionable leía `r.problems` sobre un ProbeReport. Reventaba en cuanto había un agente
    # roto — es decir, siempre que el diagnóstico servía para algo.
    ruta = prov.inspect()
    print(R.bold("  A dónde habla"))
    color = "32" if not ruta.overridden else ("31" if ruta.problems else "33")
    print(f"    {R.paint('●', color)} {ruta.provider}")
    for name, info in sorted(ruta.overrides.items()):
        print(R.dim(f"      {name} = {info['value']}  ({info['effect']})"))
    for problem in ruta.problems:
        print(R.paint(f"      ✗ {problem}", "31"))
    for w in ruta.warnings:
        print(R.paint(f"      ! {w}", "33"))
    if ruta.overrides:
        print(R.dim(f"      dónde buscarlo:  {prov.how_to_find(list(ruta.overrides))}"))
    print()

    functional = [r for r in reports if rung(r.level) >= rung(FUNCTIONAL)]
    broken = [r for r in reports if rung(r.level) < rung(FUNCTIONAL)]
    print(R.bold("  Resumen accionable"))
    if not functional:
        print(R.paint("    ✗ ningún agente alcanza FUNCTIONAL: este espacio no puede operar", "31"))
    for r in broken:
        action = _remedy(r)
        print(R.paint(f"    → {r.agent}: {action}", "33"))
    missing = [n for n, ok, _ in checks if not ok]
    if missing:
        print(R.paint(f"    → falta: {', '.join(missing)}", "33"))
    if ruta.problems:
        print(R.paint("    → enrutado roto: la sesión abrirá y fallará en el primer mensaje.", "31"))
        print(R.dim("       Abra limpio con: refuto chat --provider clean"))
    elif ruta.overridden:
        print(R.paint(f"    → sus sesiones van a «{ruta.provider}», no a su suscripción.", "33"))
    if own.get("count"):
        print(R.paint(f"    → propiedad: {own['fix']}", "33"))
        print(R.dim(f"       (secuela de una sesión con sudo; sin esto pierde su propio "
                    f"rastro de auditoría)"))
    if functional and not broken and not missing:
        print(R.paint("    ✓ nada que arreglar", "32"))
    print()
    return EXIT_OK if functional else EXIT_FAIL


def _remedy(rep) -> str:
    """Un diagnóstico sin acción concreta es una queja."""
    if rep.signature.get("verdict") == "REVOKED":
        return (f"certificado de firma REVOCADO → reinstale el agente "
                f"(p. ej. `npm i -g @openai/{rep.agent}@latest`) y vuelva a sondear")
    if rep.level == "NOT_INSTALLED":
        return f"no está instalado → instálelo o quítelo de `agents` en el manifiesto"
    if "sin respuesta" in rep.stopped_because or "colgado" in rep.stopped_because:
        return (f"arranca pero no responde al handshake → compruebe la sesión "
                f"(`{rep.agent} auth` / login) y los permisos del binario")
    return rep.stopped_because or "revise la sonda con `refuto probe --verbose`"


# ── probe ────────────────────────────────────────────────────────────────────────────
def cmd_probe(opts) -> int:
    from adapters.registry import ADAPTERS, all_specs
    from core.probe import probe_all

    ws = _ws(opts)
    specs = [ADAPTERS[a] for a in opts.agent] if opts.agent else all_specs()
    reports = probe_all(specs, deep=opts.deep, workspace=ws)
    if opts.json:
        print(json.dumps([r.to_dict() for r in reports], ensure_ascii=False, indent=2))
    else:
        print(R.render_probes(reports))
        if opts.verbose:
            for r in reports:
                print(f"  {R.bold(r.agent)}")
                for s in r.steps:
                    mark = "✓" if s["ok"] else "✗"
                    print(f"    {mark} {s['step']:<18} {R.dim(str(s['detail'])[:110])}")
                print()
    ok = all(rung(r.level) >= rung(FUNCTIONAL) for r in reports)
    return EXIT_OK if ok else EXIT_FAIL


# ── discover ────────────────────────────────────────────────────────────────────────
def cmd_discover(opts) -> int:
    from core.discovery import discover

    ws = _ws(opts)
    roots = [Path(r).expanduser() for r in opts.root] if opts.root else None
    result = discover(ws, roots=roots, deep=opts.deep)

    if opts.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return EXIT_OK

    env = result["environment"]
    print(R.bold(f"\nrefuto discover · {ws}"))
    print(R.dim(f"  {env['os']['system']} {env['os']['release']} {env['os']['machine']} · "
                f"Python {env['os']['python']}"
                + (f" · CI: {env['ci']['provider']}" if env['ci']['in_ci'] else "")))

    for title, block, what in (("Núcleo SDD", result["sdd_core"], "núcleo"),
                               ("Repositorio de trabajo", result["repository"], "repositorio")):
        print(f"\n  {R.bold(title)}")
        outcome = block["outcome"]
        if outcome == "AUTO":
            c = block["chosen"]
            print(R.paint(f"    ✓ {c['subject']}", "32"))
            print(R.dim(f"      confianza {c['confidence']} ({c['score']}) · "
                        f"{block.get('note') or c.get('decisive_reason') or ''}"))
            _print_details(c)
        elif outcome == "ASK":
            print(R.paint(f"    ? {block['question']}", "33"))
            for c in block["candidates"][:5]:
                mark = "→" if c is block["candidates"][0] else " "
                print(f"      {mark} {c['confidence']:<9} {c['score']:.2f}  {c['subject']}")
                print(R.dim(f"          {', '.join(s['signal'] for s in c['signals'][:4])}"))
        else:
            print(R.paint(f"    ✗ no se encontró ningún {what}", "31"))
            print(R.dim(f"      buscado en: {', '.join(block.get('searched', []))}"))
        if block.get("truncated"):
            print(R.dim(f"      {block['truncated']}"))

    present = [t for t in env["tools"] if t["present"]]
    print(f"\n  {R.bold('Herramientas')} · {len(present)}/{len(env['tools'])} presentes")
    by_cat: dict = {}
    for t in env["tools"]:
        by_cat.setdefault(t["category"] or "otros", []).append(t)
    for cat in sorted(by_cat):
        # El estado va en el TEXTO, no sólo en el color. `R.dim` se anula cuando la salida
        # no es una terminal (core/report.py:11), así que en cualquier tubería o registro de
        # CI una herramienta ausente se leía IDÉNTICA a una presente — y en la dirección
        # peligrosa: hacia «sí está». El prefijo `~` sobrevive al color.
        names = [(R.paint(t["name"], "32") if t["present"] else R.dim("~" + t["name"]))
                 for t in by_cat[cat]]
        print(f"    {cat:<10} {' '.join(names)}")

    # A dónde va a hablar el agente. Es lo único que la sonda no puede ver: `FUNCTIONAL` se
    # comprueba con un handshake local que no toca la red, así que un agente correctamente
    # instalado y mal enrutado sale en verde y muere en el primer mensaje.
    creds = [k for k, v in env["credential_presence"].items() if v]
    print(f"\n  {R.bold('Credenciales presentes')} {R.dim('(presencia, nunca contenido)')}")
    print(f"    {', '.join(creds) if creds else R.dim('ninguna detectada')}")
    print()
    return EXIT_OK if result["sdd_core"]["outcome"] != "NONE" else EXIT_BLOCKED


def _print_details(c: dict) -> None:
    for key, label in (("version", "versión"), ("commit", "commit"), ("branch", "rama"),
                       ("remote", "remoto"), ("integrity", "integridad"),
                       ("ecosystems", "stack"), ("agent_configs", "agentes")):
        val = c.get(key)
        if val:
            shown = ", ".join(val) if isinstance(val, list) else str(val)
            print(R.dim(f"      {label:<11} {shown[:88]}"))


# ── context ─────────────────────────────────────────────────────────────────────────
def cmd_context(opts) -> int:
    from core.runcontext import build as build_context, report

    ws = _ws(opts)
    roots = [Path(r).expanduser() for r in opts.root] if opts.root else None
    rc = build_context(ws, roots=roots, deep=opts.deep,
                       phases=opts.phase or None, prefer=opts.prefer or None)

    if opts.json:
        print(json.dumps(rc.summary(), ensure_ascii=False, indent=2))
    written = rc.write()
    md = ws / ".harness" / "context" / "context-report.md"
    text = report(rc)
    md.write_text(text, encoding="utf-8", newline="\n")

    if not opts.json:
        print(text)
        print(R.dim(f"  Contexto: {len(written)} archivos en .harness/context/"))
        print(R.dim(f"  Informe:  {md.relative_to(ws)}\n"))

    routing = rc.parts.get("constraints") or {}
    if routing.get("blocked_roles"):
        return EXIT_BLOCKED
    unresolved = [b for b in (rc.parts["sdd_core"], rc.parts["repository"])
                  if b.get("outcome") != "AUTO"]
    return EXIT_BLOCKED if unresolved else EXIT_OK


# ── environments ────────────────────────────────────────────────────────────────────
def cmd_environments(opts) -> int:
    """Contra qué se trabaja, y si sigue siendo verdad.

    `check` vuelve a sondear porque una declaración con una fecha dentro se pudre en silencio.
    Sin esto, el informe de sesión repetiría durante meses un «200» de un día cualquiera.
    """
    from core import environments as env

    ws = _ws(opts)
    if opts.action == "show":
        inv = env.leer(ws)
        if opts.json:
            print(json.dumps({"ruta": inv.ruta, "error": inv.error,
                              "medido_el": inv.medido_el,
                              "de_trabajo": inv.de_trabajo.nombre if inv.de_trabajo else None,
                              "entornos": [e.nombre for e in inv.entornos]},
                             ensure_ascii=False, indent=2))
            return EXIT_OK if inv.entornos and not inv.error else EXIT_BLOCKED
        if inv.error:
            print(R.dim(f"  {inv.ruta} ilegible: {inv.error}"))
            return EXIT_BLOCKED
        if not inv.entornos:
            print(R.dim(f"  Este espacio no declara entornos. Cree {env.ARCHIVO} para que "
                        f"cada sesión sepa contra qué trabaja."))
            return EXIT_BLOCKED
        print("\n".join(env.seccion(ws)))
        return EXIT_OK

    res = env.verificar(ws, escribir=opts.write)
    if not res["ok"]:
        print(R.dim(f"  {res['razon']}"))
        return EXIT_BLOCKED
    ancho = max((len(r["dominio"]) for r in res["resultados"]), default=10)
    for r in res["resultados"]:
        igual = r["antes"] == r["ahora"]
        print(f"  {r['entorno']:<12} {r['dominio']:<{ancho}}  {r['ahora']}"
              + ("" if igual else R.dim(f"   (era {r['antes']})")))
    if res.get("sospecha"):
        print(f"\n  ⚠ SONDEO NO FIABLE: {res['sospecha']}")
        return EXIT_BLOCKED
    if res["cambios"]:
        print(R.dim(f"\n  {len(res['cambios'])} cambio(s) respecto a lo declarado."))
    if res["escrito"]:
        print(R.dim(f"  Actualizado {env.ARCHIVO}."))
    elif res["cambios"]:
        print(R.dim("  Nada se ha escrito. Use --write para dejarlo registrado."))
    # Un cambio no es un fallo: es algo que una persona tiene que mirar.
    return EXIT_BLOCKED if res["cambios"] and not res["escrito"] else EXIT_OK


# ── memory ──────────────────────────────────────────────────────────────────────────
def cmd_memory(opts) -> int:
    from core.memory import LAYERS, Memory

    ws = _ws(opts)
    mem = Memory(ws)
    if opts.action == "list":
        notes = mem.search(opts.query or "", layers=opts.layer or None,
                           include_superseded=opts.all)
        if opts.json:
            print(json.dumps([n.to_dict() for n in notes], ensure_ascii=False, indent=2))
            return EXIT_OK
        for layer in (opts.layer or LAYERS):
            here = [n for n in notes if n.layer == layer]
            if not here:
                continue
            print(f"\n  {R.bold(layer)}")
            for n in here:
                tag = R.dim(" · SUSTITUIDA por " + n.superseded_by) if n.superseded_by else ""
                print(f"    {n.key:<38} {R.dim(n.updated_at[:10])}{tag}")
                if n.why:
                    print(R.dim(f"        porque: {n.why[:96]}"))
        print()
        return EXIT_OK
    if opts.action == "summary":
        s = mem.summary()
        print()
        for layer, info in s.items():
            ttl = "no caduca" if info["ttl_days"] is None else f"{info['ttl_days']} días"
            print(f"  {layer:<12} {info['count']:>3} notas · {info['superseded']} sustituidas "
                  f"· {ttl}")
        print()
        return EXIT_OK
    if opts.action == "remember":
        if not (opts.layer and opts.key and opts.body):
            print("uso: refuto memory remember --layer L --key K --body TEXTO [--why POR-QUÉ]",
                  file=sys.stderr)
            return EXIT_USAGE
        p = mem.remember(opts.layer[0], opts.key, opts.body, why=opts.why or "",
                         source=opts.source or "")
        print(f"  ✓ {p.relative_to(ws)}")
        return EXIT_OK
    if opts.action == "export":
        p = mem.export(ws / ".harness" / "evidence" / "memory-export.json")
        print(f"  ✓ {p.relative_to(ws)}")
        return EXIT_OK
    return EXIT_USAGE


# ── install ─────────────────────────────────────────────────────────────────────────
def cmd_install(opts) -> int:
    """Deja un espacio operativo de principio a fin, en un solo comando.

    Existe porque los pasos sueltos —`init`, `bind`, `policy wire`— dejaban un espacio a medias
    con facilidad: el control enganchado y sin contexto, o el contexto puesto y sin control. Un
    espacio a medias es peor que uno sin gobernar, porque parece gobernado.
    """
    from core import binding, context_files, launcher, wire
    from core.discovery import discover
    from core.policy import Policy

    ws = _ws(opts)
    pasos: list = []

    def paso(nombre: str, ok: bool, detalle: str = "") -> None:
        pasos.append((nombre, ok, detalle))
        mark = R.paint("✓", "32") if ok else R.paint("✗", "31")
        print(f"  {mark} {nombre:<26} {R.dim(detalle[:96])}")

    print(R.bold(f"\nrefuto install · {ws}\n"))

    # 1 · estructura y política
    ctx = Context(workspace=ws)
    try:
        ctx.harness_dir.mkdir(parents=True, exist_ok=True)
        ctx.evidence_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        paso("estructura", False, f"{exc}. Compruebe permisos: `refuto doctor`.")
        return EXIT_FAIL
    if not ctx.policy_path.exists() or opts.force:
        write_json(ctx.policy_path, Policy.default().to_dict())
    paso("política", ctx.policy_path.is_file(), str(ctx.policy_path.relative_to(ws)))

    if not ctx.manifest_path.exists() or opts.force:
        from gates.base import GATES
        write_json(ctx.manifest_path, {
            "schema": "harness.manifest/v1",
            "_que_es": "Lo que este espacio declara necesitar. La otra mitad del contrato es "
                       "harness.lock.json, que dice con qué se materializó realmente.",
            "harness": {"version": "0.2.0", "min_python": "3.10"},
            "workspace": {"name": ws.name, "profile": "standard"},
            "agents": {}, "gates": sorted(GATES),
            "skills": {"roots": [".claude/skills", ".kiro/skills"],
                       "require_name_matches_directory": True},
            "mcp": {"protocol_version": "2026-07-28"},
            "provider": {"expect": opts.provider_expect},
        })
    paso("manifiesto", ctx.manifest_path.is_file(), str(ctx.manifest_path.relative_to(ws)))

    from core.session import ensure_gitignore
    ensure_gitignore(ctx.harness_dir)

    # 2 · vínculo
    if opts.no_bind:
        paso("vínculo", True, "omitido (--no-bind)")
    else:
        disc = discover(ws, deep=opts.deep)
        # Un núcleo externo sólo se busca si ESTE espacio da señales de estar gobernado por
        # uno. Sin esto, `install` en un repositorio cualquiera encontraba los núcleos del
        # disco, los declaraba ambiguos y pedía decidir algo que no aplica — la forma más
        # rápida de enseñar a la gente a ignorar una pregunta de refuto.
        #
        # La señal de primera clase es la DECLARADA (`integrations.spec_core` del manifiesto,
        # la misma que gobierna G-SDD). Los marcadores del árbol se conservan detrás porque un
        # espacio recién clonado aún no tiene manifiesto, pero ya no son la única vía: antes,
        # la lista de marcadores era la única, y estaba escrita con los nombres de un
        # repositorio privado.
        from core.context import read_manifest
        declarado = bool((read_manifest(ws).get("integrations") or {}).get("spec_core")
                         or (read_manifest(ws).get("integrations") or {}).get("sdd_core"))
        gobernado_por_sdd = bool(opts.core) or declarado or any(
            (ws / m).exists() for m in (".kiro", "verification", "verificacion"))
        objetivos = [("repository", "repository", "el repositorio", "")]
        if gobernado_por_sdd:
            objetivos.insert(0, ("sdd_core", "sdd_core", "el núcleo SDD", opts.core))
        hechos = []
        for kind, key, what, choice in objetivos:
            cand, why = binding.decide(disc[key], choice=choice, what=what)
            if cand is not None:
                maker = binding.bind_core if kind == "sdd_core" else binding.bind_repo
                hechos.append(maker(cand, by=os.environ.get("USER", "")))
        if hechos:
            existing = binding.read(ws)
            merged = [binding.Binding(**{k: v for k, v in b.items()
                                         if k in binding.Binding.__dataclass_fields__})
                      for k2, b in existing.items() if k2 not in {x.kind for x in hechos}]
            binding.write(ws, merged + hechos)
        atados = ", ".join(h.kind for h in hechos) or "ninguno"
        # No encontrar núcleo NO es un fallo: hay espacios que no están gobernados por uno.
        # Lo que sí es un fallo es encontrar varios y no decidir. Confundir «no aplica» con
        # «falta» deja `install` en rojo permanente en la mitad de los repositorios.
        atado = {h.kind for h in hechos}
        pedidos = {k for k, _, _, _ in objetivos}
        ambiguos = [k for k in pedidos if k not in atado and disc[k].get("outcome") == "ASK"]
        ausentes = [k for k in pedidos if k not in atado and disc[k].get("outcome") == "NONE"]
        detalle = f"atado: {atados}"
        if not gobernado_por_sdd:
            detalle += " · sin núcleo SDD: este espacio no está gobernado por uno"
        if ausentes:
            detalle += f" · sin {', '.join(ausentes)} en el entorno (no aplica aquí)"
        if ambiguos:
            detalle += f" · AMBIGUO: {', '.join(ambiguos)} → `refuto bind set --core <ruta>`"
        paso("vínculo", not ambiguos, detalle)

    # 3 · qué runtimes hay aquí, para no enganchar lo que nadie usa
    detectados = _runtimes_relevantes(ws, opts.agent)
    paso("runtimes", bool(detectados), ", ".join(detectados) or "ninguno detectado")

    # 4 · lanzador y ganchos
    resultados = []
    if "kiro" in detectados and (ws / ".kiro" / "agents").is_dir():
        resultados += wire.wire_kiro_agents(ws, harness_root=REPO)
    if "claude" in detectados:
        resultados += wire.wire_claude(ws, harness_root=REPO)
    if "antigravity" in detectados:
        resultados += wire.wire_antigravity(ws, harness_root=REPO)
    if not resultados:
        launcher.install(ws, harness_home=REPO, runtime="claude")
    lz = launcher.check(ws)
    paso("guardián", lz["ok"], lz.get("reason") or
         f"{len([r for r in resultados if r.action in ('wired', 'upgraded')])} ganchos · "
         f"lanzador en .harness/bin/guard")

    # 5 · contexto persistente — lo que hace que `claude` a secas SEPA dónde está
    escritos = context_files.install(ws, runtimes=[r for r in detectados
                                                   if r in context_files.TARGETS],
                                     spec=opts.spec)
    paso("contexto", True, ", ".join(sorted({w.path for w in escritos})))

    launcher.restore_ownership(ws)

    # 6 · comprobación: se ejecuta el guardián de verdad
    prueba = _probar_guardian(ws)
    paso("prueba del guardián", prueba["ok"], prueba["detail"])

    print()
    fallos = [n for n, ok, _ in pasos if not ok]
    if fallos:
        print(R.paint(f"  Incompleto: {', '.join(fallos)}", "33"))
        print(R.dim("  Ejecute `refuto doctor` para el detalle.\n"))
        return EXIT_BLOCKED
    print(R.paint("  Espacio operativo.", "32"))
    print(R.dim("  Cualquier forma de abrir el agente aquí —`refuto chat`, `claude`, "
                "`sudo claude`,\n  o la aplicación de escritorio— encuentra el contexto y el "
                "guardián.\n"))
    return EXIT_OK


def _runtimes_relevantes(ws: Path, pedidos: list | None = None) -> list:
    """Qué runtimes importan aquí, por orden de autoridad.

        1. lo que se pide en la orden      `--agent claude`
        2. lo que el espacio DECLARA       `agents` del manifiesto
        3. lo que hay instalado            último recurso

    Sondear los cinco para usar uno costaba 13,6 s en cada `refuto work`. Un comando que tarda
    catorce segundos en decir qué tienes pendiente se deja de usar, y entonces no gobierna nada.
    """
    from adapters.registry import ADAPTERS
    if pedidos:
        return [a for a in pedidos if a in ADAPTERS]
    declarados = list((Context(workspace=ws).manifest or {}).get("agents") or {})
    if declarados:
        # Primero los requeridos: son los que el espacio dice que no puede faltar.
        req = [a for a in declarados
               if (Context(workspace=ws).manifest["agents"][a] or {}).get("required")]
        ordenados = list(dict.fromkeys(req + declarados))
        return [a for a in ordenados if a in ADAPTERS] or _runtimes_presentes(ws)
    return _runtimes_presentes(ws)


def _grafo(ws: Path, runtimes: list, *, deep: bool = False):
    """Grafo de capacidades sondeando SÓLO los runtimes que importan."""
    from adapters.registry import ADAPTERS
    from core.capability import build as build_caps
    from core.discovery import ToolFact, scan_environment
    from core.probe import probe_all

    # Sin versiones: para saber si una capacidad existe basta con que la herramienta esté.
    env = scan_environment(with_versions=False)
    known = set(ToolFact.__dataclass_fields__)                          # noqa: SLF001
    facts = [ToolFact(**{k: v for k, v in t.items() if k in known}) for t in env["tools"]]
    specs = [ADAPTERS[a] for a in dict.fromkeys(runtimes) if a in ADAPTERS]
    probes = probe_all(specs, deep=deep, workspace=ws)
    return build_caps(probes, ADAPTERS, facts), probes


def _runtimes_presentes(ws: Path) -> list:
    """Qué runtimes tienen sentido en ESTE espacio: los instalados, más los que ya dejaron huella."""
    import shutil
    out = []
    for name, binario, huella in (("claude", "claude", ".claude"),
                                  ("kiro", "kiro-cli", ".kiro"),
                                  ("gemini", "gemini", ".gemini"),
                                  ("opencode", "opencode", "opencode.json"),
                                  # Antigravity es un IDE: puede no dejar binario en el PATH.
                                  # Su huella es el directorio de personalización que él mismo lee.
                                  ("antigravity", "agy", ".agents")):
        if shutil.which(binario) or (ws / huella).exists():
            out.append(name)
    if "antigravity" not in out and _antigravity_instalado():
        out.append("antigravity")
    return out


def _antigravity_instalado() -> bool:
    """¿Hay un Antigravity en esta máquina, aunque no deje binario en el PATH?

    Se comprueban las rutas de instalación habituales por sistema. Un falso negativo aquí
    significa que el guardián NO se engancha para ese agente y que trabaja sin control: por eso
    se mira también el directorio de configuración que crea al abrirse.
    """
    import os
    from pathlib import Path as _P
    candidatas = [
        _P("/Applications/Antigravity.app"),
        _P.home() / "Applications" / "Antigravity.app",
        _P.home() / ".gemini" / "antigravity",
        _P(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Antigravity" if os.name == "nt" else None,
    ]
    return any(c.exists() for c in candidatas if c is not None)


def _probar_guardian(ws: Path) -> dict:
    """Ejecuta el lanzador contra una escritura que DEBE rechazar. Sin esto, «instalado» es
    una suposición."""
    from core import launcher
    guard = ws / launcher.BIN / launcher.NAME
    if not guard.is_file():
        return {"ok": False, "detail": "el lanzador no está"}
    payload = json.dumps({"tool_name": "Write",
                          "tool_input": {"file_path": ".harness/policy.json", "content": "{}"}})
    try:
        import subprocess
        p = subprocess.run([str(guard)], input=payload, capture_output=True, **TEXT_IO,
                           cwd="/", timeout=60,
                           env={"HARNESS_GUARD_RUNTIME": "claude",
                                "HOME": os.environ.get("HOME", "/tmp")})
    except (OSError, Exception) as exc:                                  # noqa: BLE001
        return {"ok": False, "detail": f"no se pudo ejecutar: {exc}"}
    try:
        d = json.loads(p.stdout or "{}")
        decision = d["hookSpecificOutput"]["permissionDecision"]
    except (ValueError, KeyError):
        return {"ok": p.returncode != 0,
                "detail": f"salida {p.returncode} · {(p.stderr or '')[:70]}"}
    return {"ok": decision == "deny",
            "detail": f"bloqueó una escritura sobre .harness/policy.json ({decision})"}


# ── bind ────────────────────────────────────────────────────────────────────────────
def cmd_bind(opts) -> int:
    from core import binding
    from core.discovery import discover

    ws = _ws(opts)
    roots = [Path(r).expanduser() for r in opts.root] if opts.root else None

    if opts.action == "show":
        bound = binding.read(ws)
        if not bound:
            print(R.dim("\n  este espacio no está vinculado. Ejecute `refuto bind set`.\n"))
            return EXIT_BLOCKED
        print()
        for kind, b in sorted(bound.items()):
            print(f"  {R.bold(kind)}")
            for k in ("path", "commit", "version", "remote", "bound_at", "bound_by"):
                if b.get(k):
                    print(f"    {k:<16} {b[k]}")
        print()
        return EXIT_OK

    disc = discover(ws, roots=roots, deep=opts.deep)

    if opts.action == "verify":
        out = binding.verify(ws, disc)
        if not out["bound"]:
            print(R.paint("\n  sin vínculo: no hay nada que verificar\n", "33"))
            return EXIT_BLOCKED
        print()
        for n in out["notes"]:
            print(R.dim(f"  i {n}"))
        for problem in out["problems"]:
            print(R.paint(f"  ✗ {problem}", "31"))
        if not out["problems"]:
            print(R.paint("  ✓ el vínculo sigue siendo válido", "32"))
        print()
        return EXIT_OK if not out["problems"] else EXIT_FAIL

    bindings, blocked = [], []
    for kind, key, what, choice in (("sdd_core", "sdd_core", "el núcleo SDD", opts.core),
                                    ("repository", "repository", "el repositorio", opts.repo)):
        cand, why = binding.decide(disc[key], choice=choice, what=what)
        if cand is None:
            blocked.append((kind, why, disc[key]))
            continue
        maker = binding.bind_core if kind == "sdd_core" else binding.bind_repo
        b = maker(cand, by=opts.by or os.environ.get("USER", ""))
        bindings.append(b)
        print(R.paint(f"  ✓ {kind}: {b.path}", "32"))
        print(R.dim(f"      {why}"))
        if b.commit:
            print(R.dim(f"      anclado al commit {b.commit[:12]}"))

    for kind, why, block_doc in blocked:
        print(R.paint(f"\n  ? {kind}: {why}", "33"))
        for c in block_doc.get("candidates", [])[:6]:
            print(f"      {c['confidence']:<9} {c['score']:.2f}  {c['subject']}")
            extra = " · ".join(str(x) for x in (c.get("version"), c.get("integrity"),
                                                c.get("branch")) if x)
            if extra:
                print(R.dim(f"          {extra}"))
        flag = "--core" if kind == "sdd_core" else "--repo"
        print(R.dim(f"      elija con: refuto bind set {flag} <ruta>"))

    if bindings:
        existing = binding.read(ws)
        merged = [binding.Binding(**{k: v for k, v in b.items()
                                     if k in binding.Binding.__dataclass_fields__})
                  for kind, b in existing.items()
                  if kind not in {x.kind for x in bindings}] + bindings
        path = binding.write(ws, merged)
        print(f"\n  escrito {path.relative_to(ws)}")
    print()
    return EXIT_BLOCKED if blocked else EXIT_OK


# ── init ─────────────────────────────────────────────────────────────────────────────
def cmd_init(opts) -> int:
    from core.policy import Policy

    ws = _ws(opts)
    ctx = Context(workspace=ws)
    ctx.harness_dir.mkdir(parents=True, exist_ok=True)
    ctx.evidence_dir.mkdir(parents=True, exist_ok=True)

    created = []
    if not ctx.policy_path.exists() or opts.force:
        write_json(ctx.policy_path, Policy.default().to_dict())
        created.append(ctx.policy_path)
    if not ctx.manifest_path.exists() or opts.force:
        from gates.base import GATES
        write_json(ctx.manifest_path, {
            "schema": "harness.manifest/v1",
            "_que_es": "Lo que este espacio declara necesitar. La otra mitad del contrato es "
                       "harness.lock.json, que dice con qué se materializó realmente.",
            "harness": {"version": "0.1.0", "min_python": "3.10"},
            "workspace": {"name": ws.name, "profile": "standard"},
            "agents": {},
            "gates": sorted(GATES),
            "skills": {"roots": [".claude/skills", ".kiro/skills"],
                       "require_name_matches_directory": True},
            "mcp": {"protocol_version": "2026-07-28"},
        })
        created.append(ctx.manifest_path)

    from core.session import ensure_gitignore
    if ensure_gitignore(ctx.harness_dir):
        created.append(ctx.harness_dir / ".gitignore")

    for p in created:
        print(f"  ✓ {p.relative_to(ws)}")
    if not created:
        print("  nada que crear (use --force para reescribir)")
    print(f"\n  Siguiente: {R.bold('refuto doctor')} y luego {R.bold('refuto verify')}\n")
    return EXIT_OK


# ── verify ───────────────────────────────────────────────────────────────────────────
def _version_motor() -> str:
    v = REPO / "VERSION"
    return v.read_text(encoding="utf-8").strip() if v.is_file() else ""


def _cambios_entre(desde: str, hasta: str) -> list:
    """Las entradas del CHANGELOG entre dos versiones. Vacía si no se puede leer.

    Actualizar sin poder leer qué cambia es firmar en blanco. Si el CHANGELOG no está o no se
    entiende, se dice — no se calla y se actualiza igual.
    """
    ch = REPO / "CHANGELOG.md"
    if not ch.is_file():
        return []
    lineas, dentro, out = ch.read_text(encoding="utf-8").splitlines(), False, []
    for l in lineas:
        m = re.match(r"^##\s*\[?v?([0-9]+\.[0-9]+\.[0-9]+)", l)
        if m:
            v = m.group(1)
            if v == hasta:
                dentro = True
                out.append(l.strip())
                continue
            if v == desde:
                break
            if dentro:
                out.append(l.strip())
            continue
        if dentro and l.strip():
            out.append("  " + l.strip())
    return out[:40]


def cmd_upgrade(opts) -> int:
    """Lleva un espacio a la versión del motor que hay en disco.

    Por qué existe
    --------------
    El motor detectaba deriva del núcleo SDD (`core/binding.py`, con el commit como ancla) y
    deriva de agentes y skills duplicados (`core/inventory.py`, la puerta H-07). Medía la
    deriva de todo menos la suya: el 2026-09-17 había cuatro espacios gobernados declarando
    0.1.0 y 0.2.0 contra un motor 0.2.2, y ningún camino para ponerlos al día que no fuera
    editar el manifiesto a mano.

    Qué hace, y qué NO hace
    -----------------------
    Actualiza la versión declarada y REGENERA el lanzador del guardián, que es lo que de
    verdad ata el espacio a una ubicación del motor. No toca la política: si un espacio la
    extendió, esa extensión es una decisión de una persona y no se pisa. Y no actualiza un
    espacio cuya política el motor no entiende: actualizar a ciegas lo que no se sabe leer es
    la forma más limpia de romper algo en silencio.
    """
    ws = _ws(opts)
    manifiesto = ws / ".harness" / "harness.manifest.json"
    motor = _version_motor()

    if not manifiesto.is_file():
        print(f"\n  {R.paint('✗', '31')} no hay {manifiesto.relative_to(ws)}: "
              f"este espacio no está inicializado.")
        print(R.dim(f"      python3 {REPO}/refuto.py --workspace {ws} install\n"))
        return EXIT_FAIL

    doc = json.loads(manifiesto.read_text(encoding="utf-8"))
    declarada = (doc.get("harness") or {}).get("version") or ""

    print(f"\n  {R.bold(str(ws))}")
    print(f"    declara  {declarada or '(nada)'}")
    print(f"    motor    {motor}")

    if declarada == motor:
        print(f"\n  {R.paint('✓', '32')} al día. Nada que hacer.\n")
        return EXIT_OK

    # Una política que el motor no entiende invalida la actualización: no se sabe qué se
    # estaría preservando.
    from core.policy import PoliticaIlegible, Policy
    pf = ws / ".harness" / "policy.json"
    if pf.is_file():
        try:
            Policy.load(pf)
        except PoliticaIlegible as exc:
            print(f"\n  {R.paint('✗', '31')} BLOQUEADO: {exc}")
            print(R.dim("      Se arregla la política antes de actualizar, no después.\n"))
            return EXIT_FAIL

    cambios = _cambios_entre(declarada, motor)
    if cambios:
        print(f"\n  {R.bold('Qué cambia')}")
        for l in cambios[:18]:
            print(R.dim(f"      {l}"))
    else:
        print(R.dim("\n      (el CHANGELOG no declara entradas entre esas versiones)"))

    if not opts.apply:
        print(f"\n  {R.paint('·', '33')} en seco. Añada --apply para actualizar.\n")
        return EXIT_OK

    copia = manifiesto.with_name(manifiesto.name + f".antes-de-{declarada or 'nada'}")
    copia.write_bytes(manifiesto.read_bytes())   # copia exacta, byte a byte

    doc.setdefault("harness", {})["version"] = motor
    doc.setdefault("_actualizaciones", []).append(
        {"desde": declarada, "hasta": motor, "cuando": now(), "por": os.environ.get("USER", "")})
    write_json(manifiesto, doc)

    # El lanzador del guardián graba la ruta del motor a fuego; regenerarlo es la mitad útil
    # de actualizar.
    from core import wire
    resultados = wire.wire_claude(ws, harness_root=REPO)
    print(f"\n  {R.paint('✓', '32')} {declarada or '(nada)'} → {motor}")
    print(R.dim(f"      copia previa: {copia.name}"))
    for r in resultados:
        print(R.dim(f"      {r.action:<9} {r.path}"))
    print()
    return EXIT_OK


def cmd_verify(opts) -> int:
    from gates.base import GATES, run_all

    ws = _ws(opts)
    ctx = Context(workspace=ws, run_id=new_run_id(), deep=opts.deep, offline=opts.offline)
    declared = (ctx.manifest or {}).get("gates")
    only = opts.gate or (declared if declared else None)
    unknown = [g for g in (only or []) if g not in GATES]
    if unknown:
        print(R.paint(f"puertas desconocidas: {', '.join(unknown)}", "31"), file=sys.stderr)
        return EXIT_USAGE

    results = run_all(ctx, only=only)
    verdict = verdict_of(results)
    if opts.json:
        print(json.dumps({"run_id": ctx.run_id, "verdict": verdict,
                          "gates": [r.to_dict() for r in results]},
                         ensure_ascii=False, indent=2))
    else:
        print(R.render(results, verdict, verbose=opts.verbose))
    path = write_run(ws, ctx.run_id, results)
    if not opts.json:
        print(f"  Evidencia: {path.relative_to(ws)}\n")

    statuses = {r.status for r in results}
    if statuses & {FAIL, NOT_EXECUTABLE}:
        return EXIT_FAIL
    if BLOCKED in statuses:
        return EXIT_BLOCKED
    # Ninguna puerta encontró sujeto. No salió mal, pero tampoco demostró nada: salir con 0
    # aquí sería exactamente el aprobado vacuo que `NOT_APPLICABLE` existe para hacer visible.
    if statuses and PASS not in statuses:
        return EXIT_BLOCKED
    return EXIT_OK


# ── policy ───────────────────────────────────────────────────────────────────────────
def cmd_policy(opts) -> int:
    from adapters.registry import ADAPTERS, all_specs
    from core.policy import Policy, compile_for

    ws = _ws(opts)
    ctx = Context(workspace=ws)
    policy = Policy.from_dict(ctx.policy_doc) if ctx.policy_doc else Policy.default()

    if opts.action == "show":
        print(json.dumps(policy.to_dict(), ensure_ascii=False, indent=2))
        return EXIT_OK

    if opts.action == "prune":
        from core import hygiene
        objetivos = [ws / ".claude" / "settings.local.json", ws / ".claude" / "settings.json"]
        vistos = 0
        for fichero in objetivos:
            if not fichero.is_file():
                continue
            vistos += 1
            res = hygiene.podar(fichero, dry_run=not opts.apply)
            cabeza = "PODARÍA" if res["dry_run"] else "PODADO"
            print(f"\n  {R.bold(str(fichero.relative_to(ws)))}")
            print(f"    {res['total']} reglas · {cabeza} {res['retiradas']} · "
                  f"quedan {res['conservadas']}")
            for motivo, n in sorted(res["por_motivo"].items(), key=lambda kv: -kv[1]):
                print(R.dim(f"      {n:5}  {motivo}"))
            for motivo, ejemplos in res["ejemplos"].items():
                for e in ejemplos:
                    print(R.dim(f"           · {e[:110]}"))
            if res["copia"]:
                print(f"    copia previa: {res['copia']}")
        if not vistos:
            print("\n  no hay ningún settings de Claude Code en este espacio.")
            return EXIT_FAIL
        if not opts.apply:
            print(R.dim("\n  Nada se ha escrito. Añada --apply para podar de verdad.\n"))
        else:
            print()
        return EXIT_OK

    if opts.action in ("wire", "unwire", "audit"):
        from core import wire
        if opts.action == "audit":
            rep = wire.audit(ws)
            print(f"\n  Kiro · guardián en la ruta del CLI: "
                  f"{rep['wired']}/{rep['agents']} agentes")
            for name, state in sorted(rep["detail"].items()):
                mark = R.paint("✓", "32") if state == "enganchado" else R.paint("✗", "31")
                print(f"    {mark} {name:<34} {state}")
            cl = wire.audit_claude(ws)
            mark = R.paint("✓", "32") if cl["wired"] else R.paint("✗", "31")
            print(f"\n  Claude Code · {mark} {cl['reason']}")
            ag = wire.audit_antigravity(ws)
            ag_usado = (ws / ".agents").is_dir()
            mark = (R.paint("✓", "32") if ag["wired"]
                    else R.paint("✗", "31") if ag_usado else R.dim("·"))
            print(f"  Antigravity · {mark} {ag['reason']}"
                  + ("" if ag_usado else R.dim("  (sin .agents/: no se exige)")))
            print()
            ok_kiro = (not rep["agents"]) or rep["wired"] == rep["agents"]
            ok_ag = ag["wired"] or not ag_usado
            return EXIT_OK if ok_kiro and cl["wired"] and ok_ag else EXIT_FAIL
        if opts.action == "unwire":
            results = wire.unwire(ws)
        else:
            targets = opts.agent or ["kiro", "claude"]
            results = []
            if "kiro" in targets:
                results += wire.wire_kiro_agents(ws, harness_root=REPO, dry_run=opts.dry_run)
            if "claude" in targets:
                enganchar = (wire.wire_claude_repos if getattr(opts, "repos", False)
                             else wire.wire_claude)
                results += enganchar(ws, harness_root=REPO, dry_run=opts.dry_run)
            if "antigravity" in targets:
                results += wire.wire_antigravity(ws, harness_root=REPO, dry_run=opts.dry_run)
        for r in results:
            print(f"    {r.action:<9} {r.path} {R.dim(r.detail)}")
        print()
        return EXIT_OK

    specs = [ADAPTERS[a] for a in opts.agent] if opts.agent else all_specs()
    exit_code = EXIT_OK
    for spec in specs:
        out = compile_for(policy, spec)
        head = R.paint("✓", "32") if out["supported"] else R.paint("·", "33")
        print(f"\n  {head} {R.bold(spec.name)}")
        for gap in out["unenforceable"]:
            print(R.paint(f"      NO APLICA: {gap}", "33"))
        for note in out["notes"]:
            print(R.dim(f"      i {note}"))
        for rel, content in sorted(out["artifacts"].items()):
            target = ws / rel
            if opts.action == "compile":
                target.parent.mkdir(parents=True, exist_ok=True)
                # Artefacto generado: LF, como todo lo demás que escribe refuto. Se me
                # escapó en el barrido inicial y lo encontró un `compile` real.
                target.write_text(content, encoding="utf-8", newline="\n")
                print(f"      escrito {rel}")
            else:
                print(f"      generaría {rel} ({len(content)} bytes)")
    print()
    return exit_code


# ── lock ─────────────────────────────────────────────────────────────────────────────
def cmd_lock(opts) -> int:
    from core.lock import build_source_lock, plan_update, resolve_ref, verify, write_lock

    ws = _ws(opts)
    ctx = Context(workspace=ws)

    if opts.action == "show":
        print(json.dumps(ctx.lock or {}, ensure_ascii=False, indent=2))
        return EXIT_OK

    if opts.action == "verify":
        result = verify(ws, ctx.lock, check_remote=not opts.offline)
        print(R.render([result], verdict_of([result]), verbose=True))
        return EXIT_OK if result.status == PASS else (
            EXIT_BLOCKED if result.status == BLOCKED else EXIT_FAIL)

    sources = (ctx.manifest or {}).get("sources") or {}
    if not sources:
        print(R.paint("  el manifiesto no declara `sources`: no hay nada que anclar", "33"))
        return EXIT_BLOCKED

    existing = ctx.lock or {}
    new_entries = {}
    for name, decl in sorted(sources.items()):
        if opts.source and name not in opts.source:
            continue
        sha, err = resolve_ref(decl["uri"], decl["ref"])
        if err:
            print(R.paint(f"  ✗ {name}: {err}", "31"))
            return EXIT_FAIL
        dests = [m["to"] for m in (decl.get("materialize") or [])]
        entry = build_source_lock(name, decl["uri"], decl["ref"], sha, ws, dests)
        plan = plan_update(existing, entry)
        print(f"\n  {R.bold(name)}  {plan['commit_from'][:12] or '—'} → {plan['commit_to'][:12]}")
        for key, colour in (("added", "32"), ("changed", "33"), ("removed", "31")):
            for rel in plan[key][:20]:
                print(R.paint(f"      {key[:7]:<7} {rel}", colour))
        print(R.dim(f"      sin cambios: {plan['unchanged']}"))
        new_entries[name] = entry

    if opts.action == "plan":
        print(R.dim("\n  plan solamente; no se escribió nada. Use `refuto lock update` "
                    "para fijarlo.\n"))
        return EXIT_OK

    merged = {}
    from core.lock import SourceLock
    for name, entry in (existing.get("sources") or {}).items():
        merged[name] = SourceLock(name=name, **{k: v for k, v in entry.items()
                                                if k in SourceLock.__dataclass_fields__})
    merged.update(new_entries)
    write_lock(ctx.lock_path, merged)
    print(f"\n  ✓ lock escrito en {ctx.lock_path.relative_to(ws)}\n")
    return EXIT_OK


# ── mcp ──────────────────────────────────────────────────────────────────────────────
def cmd_mcp(opts) -> int:
    ws = _ws(opts)
    ctx = Context(workspace=ws, offline=opts.offline)
    from gates.base import run_gate
    result = run_gate("G-MCP", ctx)
    print(R.render([result], verdict_of([result]), verbose=True))
    return EXIT_OK if result.status == PASS else (
        EXIT_BLOCKED if result.status == BLOCKED else EXIT_FAIL)


# ── inventory ────────────────────────────────────────────────────────────────────────
def cmd_inventory(opts) -> int:
    from core.inventory import build, render_text
    ws = _ws(opts)
    inv = build(ws, depth=opts.depth)
    out_dir = REPO / "artifacts"
    if opts.json:
        print(json.dumps(inv, ensure_ascii=False, indent=2))
    else:
        print(render_text(inv))
    if opts.save:
        write_json(out_dir / "inventory.json", inv)
        (out_dir / "inventory.md").write_text(render_text(inv, markdown=True),
                                              encoding="utf-8", newline="\n")
        print(R.dim(f"\n  guardado en {out_dir}/inventory.json y .md\n"))
    return EXIT_OK


# ── evidence ─────────────────────────────────────────────────────────────────────────
def cmd_evidence(opts) -> int:
    ws = _ws(opts)
    events = read_events(ws, kinds=opts.kind or None)
    tail = events[-opts.last:] if opts.last else events
    if opts.json:
        print(json.dumps(tail, ensure_ascii=False, indent=2))
        return EXIT_OK
    if not tail:
        print(R.dim("  el diario está vacío"))
        return EXIT_OK
    for ev in tail:
        print(f"  {R.dim(ev.get('ts',''))} {ev.get('kind',''):<18} "
              f"{ev.get('outcome') or ev.get('verdict') or ''} "
              f"{R.dim(str(ev.get('target') or ev.get('run_id') or '')[:70])}")
    print()
    return EXIT_OK


# ── docs ────────────────────────────────────────────────────────────────────────────
def cmd_docs(opts) -> int:
    from adapters.registry import ADAPTERS, all_specs
    from core.docs import build_matrix, write_docs
    from core.probe import probe_all

    ws = _ws(opts)
    reports = probe_all(all_specs(), deep=opts.deep, workspace=ws)
    matrix = build_matrix(reports, ADAPTERS)
    written = write_docs(Path(opts.out) if opts.out else REPO, matrix)
    for p in written:
        print(f"  ✓ {p}")
    unknown = sum(1 for f in matrix["features"].values()
                  for c in f["by_agent"].values() if c["value"] in ("?", "BLOQUEADO"))
    total = sum(len(f["by_agent"]) for f in matrix["features"].values())
    print(f"\n  {total - unknown}/{total} casillas verificadas · {unknown} declaradas "
          f"sin verificar. Se dicen; no se rellenan.\n")
    return EXIT_OK


# ── selftest ─────────────────────────────────────────────────────────────────────────
def cmd_selftest(opts) -> int:
    from tests.runner import run_suites
    return run_suites(only=opts.suite, verbose=opts.verbose)


# ── chat ────────────────────────────────────────────────────────────────────────────
def cmd_chat(opts) -> int:
    from core.session import launch, plan as plan_session

    ws = _ws(opts)
    sp = plan_session(ws, runtime=opts.agent, role_id=opts.role, spec=opts.spec,
                      model=opts.model, resume=opts.resume, extra=opts.pass_through,
                      provider=opts.provider, task=opts.task, repo=opts.repo)

    print(R.bold(f"\nSesión gobernada · {sp.runtime} · {ws}"))

    for w in sp.warnings:
        print(R.paint(f"  ! {w}", "33"))
    if sp.blockers:
        print()
        for b in sp.blockers:
            print(R.paint(f"  ✗ {b}", "31"))
        print(R.dim("\n  No se abre la sesión. Un modo interactivo que apaga el guardián no es "
                    "un modo:\n  es una puerta trasera con nombre amable.\n"))
        return EXIT_FAIL

    destino = (sp.routing or {}).get("provider", "?")
    SUSCRIPCION = "suscripción de Anthropic"
    if sp.clean_provider:
        # `--provider clean` limpia SIEMPRE; que hubiera algo que limpiar es otra cosa. Decir
        # «se ignoró la redirección a «suscripción de Anthropic»» cuando no había ninguna
        # redirección enseña a desconfiar de la línea entera, justo la que hay que creerse.
        detalle = f" (se ignoró la redirección a «{destino}»)" if destino not in (
            SUSCRIPCION, "?", "") else ""
        print(R.paint(f"  proveedor          {SUSCRIPCION}{detalle}", "32"))
    elif (sp.routing or {}).get("overrides"):
        print(R.paint(f"  proveedor          {destino}", "33"))
    if sp.brief_path:
        print(R.dim(f"  informe de sesión  {sp.brief_path.relative_to(ws)} "
                    f"({len(sp.brief.splitlines())} líneas)"))
    print(R.dim(f"  orden              {' '.join(sp.argv[:6])}…"))

    if opts.dry_run:
        print(R.dim("\n  (simulación: no se abre nada)\n"))
        print(sp.brief)
        return EXIT_OK

    print(R.dim(f"  diario             .harness/evidence/ledger.jsonl\n"))
    return launch(sp)


# ── work ────────────────────────────────────────────────────────────────────────────
def _clasificar(ws, *, repo: str = "", limit: int = 40):
    """Trabajo pendiente, ya enrutado. Devuelve (pares, error)."""
    from core.classify import classify
    from core.forge import my_tasks, repo_of
    from core.roles import load as load_roles

    destino = repo or repo_of(ws)
    tareas, err = my_tasks(repo=destino, limit=limit)
    if err:
        return [], err
    manifiesto = Context(workspace=ws).manifest or {}
    aliases = (manifiesto.get("classification") or {}).get("aliases") or {}
    disponibles = set(load_roles())
    return [(t, classify(t, roles_disponibles=disponibles, aliases=aliases))
            for t in tareas], ""


def cmd_work(opts) -> int:
    from core.forge import available, review_requests
    from core.policy import Policy
    from core.routing import route
    from adapters.registry import ADAPTERS

    ws = _ws(opts)
    forjas = available()
    if not any(f["ok"] for f in forjas.values()):
        print(R.paint("\n  Ninguna forja consultable:", "33"))
        for name, f in sorted(forjas.items()):
            print(R.dim(f"    {name}: {f['reason']}"))
        print()
        return EXIT_BLOCKED

    pares, err = _clasificar(ws, repo=opts.repo, limit=opts.limit)
    if err:
        print(R.paint(f"\n  no se pudo consultar la forja: {err}\n", "31"), file=sys.stderr)
        return EXIT_FAIL

    if opts.json:
        print(json.dumps([{"task": t.to_dict(), "classification": c.to_dict()}
                          for t, c in pares], ensure_ascii=False, indent=2))
        return EXIT_OK

    print(R.bold(f"\nTrabajo pendiente · {opts.repo or 'todas sus asignaciones'}"))
    if not pares:
        print(R.dim("  nada asignado\n"))
        return EXIT_OK

    # El runtime se resuelve una vez, y sólo se sondea el que importa aquí.
    runtimes = _runtimes_relevantes(ws, opts.agent)
    graph, _ = _grafo(ws, runtimes)
    pf = ws / ".harness" / "policy.json"
    policy = Policy.load(pf) if pf.is_file() else Policy.default()
    print(R.dim(f"  runtime: {', '.join(runtimes)}"))

    for t, c in pares:
        cabecera = R.bold(f"  {t.key or '#' + str(t.number)}")
        print(f"\n{cabecera}  {t.title[:66]}")
        print(R.dim(f"       {t.repo}#{t.number} · {t.url}"))
        for campo in ("Tipo", "Tipo / Gate", "Épica", "Horas", "Estado spec", "Ejecutor"):
            if t.fields.get(campo):
                print(R.dim(f"       {campo:<12} {t.fields[campo][:60]}"))
        if t.spec_path:
            existe = (ws / t.spec_path).is_file()
            marca = R.paint("✓", "32") if existe else R.paint("✗", "33")
            print(R.dim(f"       spec         {marca} {t.spec_path}"
                        + ("" if existe else "  (no está en este espacio)")))
        color = {"CIERTO": "32", "PROBABLE": "33"}.get(c.confidence, "33")
        print(f"       {R.paint('roles', color)}        "
              f"{', '.join(c.roles) or '—'}  "
              f"{R.dim(f'[{c.confidence} · {c.source} · evidencia {c.evidence}]')}")
        for s in c.signals[:2]:
            print(R.dim(f"                    {s[:96]}"))
        if c.primary:
            d = route(c.primary, graph, ADAPTERS, policy=policy)
            estado = {"READY": "32", "DEGRADED": "33", "BLOCKED": "31"}[d.status]
            print(f"       runtime      {R.paint(d.chosen or '—', estado)} "
                  f"{R.dim(f'[{d.status}]')}")
            if d.human_review:
                print(R.dim(f"       revisión     {d.human_review}"))
            print(R.dim(f"       abrir con    refuto chat --task {t.number}"
                        + (f" --repo {t.repo}" if opts.repo or not _es_local(ws, t) else "")))
        if c.question:
            print(R.paint(f"       ? {c.question}", "33"))

    revisiones, _ = review_requests()
    if revisiones:
        print(f"\n  {R.bold('Revisiones que le han pedido')}")
        for r in revisiones:
            print(f"    {r.repo}#{r.number}  {r.title[:60]}")
    print()
    return EXIT_OK


def _es_local(ws, task) -> bool:
    from core.forge import repo_of
    return repo_of(ws) == task.repo


# ── plan / run / resume / status ────────────────────────────────────────────────────
def _render_run(run, *, verbose: bool = False) -> None:
    from core.run import BLOCKED_, DONE, FAILED, PENDING, SKIPPED
    colour = {DONE: "32", PENDING: "2", SKIPPED: "2", FAILED: "31", BLOCKED_: "33"}
    mark = {DONE: "✓", PENDING: "·", SKIPPED: "·", FAILED: "✗", BLOCKED_: "⊘"}
    phase = None
    for s in run.steps:
        if s.phase != phase:
            phase = s.phase
            print(f"\n  {R.bold(phase)}")
        tag = R.paint(f"{mark[s.status]} {s.status:<8}", colour[s.status])
        print(f"    {tag} {s.role or '(sin rol)':<24} {R.dim(s.runtime or '—')}")
        if s.reason and (verbose or s.status in (FAILED, BLOCKED_)):
            print(R.dim(f"        {s.reason[:150]}"))
        if s.gates:
            gs = " ".join(f"{g}:{v}" for g, v in sorted(s.gates.items()))
            print(R.dim(f"        puertas  {gs}"))
        if s.human_review:
            print(R.dim(f"        revisión {s.human_review}"))
        if s.cost_usd:
            print(R.dim(f"        coste    ${s.cost_usd:.4f}"))
    print()


def cmd_plan(opts) -> int:
    from core.run import plan as plan_run
    ws = _ws(opts)
    run, _ = plan_run(ws, goal=opts.goal, phases=opts.phase or None,
                      prefer=opts.prefer or None)
    if opts.json:
        print(json.dumps(run.to_dict(), ensure_ascii=False, indent=2))
        return EXIT_OK
    print(R.bold(f"\nPlan · {run.run_id}") + (f"  «{run.goal}»" if run.goal else ""))
    _render_run(run, verbose=opts.verbose)
    blocked = [s for s in run.steps if s.status == "BLOCKED"]
    if blocked:
        print(R.paint(f"  {len(blocked)} pasos bloqueados: no se puede ejecutar el ciclo "
                      f"completo tal como está.", "33"))
        print()
    if opts.save:
        p = run.save()
        print(R.dim(f"  guardado en {p.relative_to(ws)}\n"))
    return EXIT_BLOCKED if blocked else EXIT_OK


def _prompt_of(role, workspace, goal: str = ""):
    """Texto de la tarea de un rol. Deriva del contrato, no de un prompt escrito a mano.

    Refuto gobierna el proceso; no escribe el método. Lo que se le dice al agente sale de
    lo que el rol declara, así que cambiar el contrato cambia la instrucción — y no pueden
    divergir.
    """
    from core.roles import KNOWN_CONSTRAINTS
    lines = [f"Actúa como {role.id}.", ""]
    if goal:
        lines += [f"**El encargo:** {goal}", ""]
    lines += [f"**Tu papel en él.** {role.purpose}", ""]
    if role.input_contract:
        lines += [f"**Consumes:** {', '.join(role.input_contract)}", ""]
    lines += [f"**Debes producir:** {', '.join(role.output_contract)}.",
              "Sin esos artefactos la fase NO ha terminado, digas lo que digas.",
              "Trabaja sobre los archivos del repositorio actual; no describas lo que harías.",
              ""]
    if role.constraints:
        lines += ["**No puedes:**"]
        lines += [f"- {KNOWN_CONSTRAINTS.get(c, c)}" for c in role.constraints]
        lines += ["", "Estas restricciones las aplica un guardián fuera de tu control: "
                      "intentar saltarlas produce un bloqueo registrado, no un atajo.", ""]
    if role.quality_gates:
        lines += [f"**Al terminar se ejecutan:** {', '.join(role.quality_gates)}.", ""]
    if role.human_review:
        lines += [f"**Requiere {role.human_review}**: tu salida no cierra la fase por sí sola.",
                  ""]
    if role.notes:
        lines += [f"_{role.notes}_", ""]
    return "\n".join(lines)


def cmd_run(opts) -> int:
    from core.evidence import write_run
    from core.run import execute_step, finish, plan as plan_run

    ws = _ws(opts)
    run, ctxobj = plan_run(ws, goal=opts.goal, phases=opts.phase or None,
                           prefer=opts.prefer or None)
    dry = not opts.execute
    if dry:
        print(R.paint("\n  MODO SIMULACIÓN: no se invocará a ningún agente. "
                      "Use --execute para gastar créditos.", "33"))
    print(R.bold(f"\nEjecución · {run.run_id}") + (f"  «{run.goal}»" if run.goal else ""))
    run.save()
    for step in run.steps:
        execute_step(run, step, ctxobj, dry_run=dry, budget_usd=opts.budget,
                     prompt_of=lambda r, w: _prompt_of(r, w, run.goal))
        run.save()
    finish(run)
    _render_run(run, verbose=opts.verbose)
    total = sum(s.cost_usd or 0 for s in run.steps)
    print(f"  estado: {R.bold(run.status)}"
          + (f" · coste total ${total:.4f}" if total else ""))
    print(R.dim(f"  estado guardado en {run.path().relative_to(ws)}\n"))
    return {"DONE": EXIT_OK, "BLOCKED": EXIT_BLOCKED}.get(run.status, EXIT_FAIL)


def cmd_resume(opts) -> int:
    from core.run import execute_step, finish, latest, load, resumable, plan as plan_run

    ws = _ws(opts)
    run = load(ws, opts.run_id) if opts.run_id else latest(ws)
    if run is None:
        print(R.paint("  no hay ninguna ejecución que reanudar", "31"), file=sys.stderr)
        return EXIT_USAGE

    check = resumable(run)
    print(R.bold(f"\nReanudar · {run.run_id}"))
    if check["drift"]:
        print(R.paint("\n  El entorno cambió desde que se dejó:", "31"))
        for d in check["drift"]:
            print(R.paint(f"    ✗ {d}", "31"))
        print(R.dim("\n  Reanudar aquí produciría evidencia que dice una cosa sobre un árbol "
                    "que ya es otra.\n  Use --force sólo si sabe exactamente por qué.\n"))
        if not opts.force:
            return EXIT_FAIL
    if not check["pending"]:
        print(R.dim("\n  no queda ningún paso pendiente\n"))
        return EXIT_OK
    print(R.dim(f"  {len(check['pending'])} pasos pendientes: "
                f"{', '.join(check['pending'][:6])}\n"))

    _, ctxobj = plan_run(ws, goal=run.goal, phases=run.phases)
    dry = not opts.execute
    for step in run.steps:
        if step.status in ("PENDING", "FAILED", "BLOCKED"):
            execute_step(run, step, ctxobj, dry_run=dry, budget_usd=opts.budget,
                         prompt_of=lambda r, w: _prompt_of(r, w, run.goal))
            run.save()
    finish(run)
    _render_run(run, verbose=opts.verbose)
    return {"DONE": EXIT_OK, "BLOCKED": EXIT_BLOCKED}.get(run.status, EXIT_FAIL)


def cmd_status(opts) -> int:
    from core import humanreview as HR
    from core.run import latest, resumable

    ws = _ws(opts)
    run = latest(ws)
    print(R.bold(f"\nEstado · {ws}"))
    if run is None:
        print(R.dim("  no hay ninguna ejecución registrada\n"))
    else:
        check = resumable(run)
        print(f"  última ejecución  {run.run_id} · {R.bold(run.status)} · {run.started_at[:19]}")
        print(f"  pasos pendientes  {len(check['pending'])}")
        for d in check["drift"]:
            print(R.paint(f"    ✗ {d}", "31"))
    pend = HR.pending(ws)
    print(f"  revisiones humanas pendientes: {len(pend)}")
    for p, r in pend[:8]:
        print(R.dim(f"    {r.kind:<24} {r.subject}"))
    from core.memory import Memory
    print(f"  memoria: " + " · ".join(f"{k}={v['count']}"
                                      for k, v in Memory(ws).summary().items()))
    print()
    return EXIT_OK


# ── argumentos ───────────────────────────────────────────────────────────────────────
class UsageParser(argparse.ArgumentParser):
    """Un error de uso sale con `EXIT_USAGE`, no con el 2 de argparse.

    argparse sale con **2** ante `unrecognized arguments` o un subcomando ausente. Pero 2 es
    el código que este programa reserva para BLOCKED —«se ejecutó y algo no se pudo
    comprobar»—, así que una orden mal escrita y una puerta bloqueada eran indistinguibles
    para quien sólo ve el código de salida: un guion de CI que trata el 2 como «revísalo a
    mano» daba por bloqueada una corrida que nunca llegó a ejecutarse.

    `refuto selftest --suite zzz --verbose` es el caso exacto: `--verbose` es opción del
    parser raíz, así salía 2 y parecía un bloqueo. Ahora sale 64, que es lo que dice
    `sysexits.h` para EX_USAGE y lo que ya usaba el resto del programa.

    `--help` y `--version` siguen saliendo con 0: `exit()` sólo se fuerza cuando el código
    que argparse quiere usar es el 2 de un error de uso.
    """

    def error(self, message: str) -> None:            # noqa: D401  (contrato de argparse)
        self.print_usage(sys.stderr)
        self.exit(EXIT_USAGE, f"{self.prog}: error: {message}\n")


def build_parser() -> argparse.ArgumentParser:
    p = UsageParser(prog="refuto", description=__doc__,
                    formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--workspace", default="", help="espacio de trabajo (por defecto, el actual)")
    p.add_argument("--verbose", action="store_true")
    sub = p.add_subparsers(dest="command", required=True)

    d = sub.add_parser("doctor", help="qué hay en esta máquina y qué funciona de verdad")
    d.add_argument("--deep", action="store_true", help="incluye VERIFIED (gasta créditos)")
    d.set_defaults(func=cmd_doctor)

    pr = sub.add_parser("probe", help="escalera de ejecutabilidad de los agentes")
    pr.add_argument("--agent", action="append", default=[])
    pr.add_argument("--deep", action="store_true")
    pr.add_argument("--json", action="store_true")
    pr.set_defaults(func=cmd_probe)

    di = sub.add_parser("discover", help="qué hay alrededor: entorno, núcleo SDD y repositorio")
    di.add_argument("--root", action="append", default=[],
                    help="dónde buscar (repetible). Por defecto: el directorio actual")
    di.add_argument("--deep", action="store_true",
                    help="amplía la búsqueda a los directorios habituales de $HOME")
    di.add_argument("--json", action="store_true")
    di.set_defaults(func=cmd_discover)

    co = sub.add_parser("context", help="qué cree refuto que está pasando, y por qué")
    co.add_argument("--root", action="append", default=[])
    co.add_argument("--deep", action="store_true")
    co.add_argument("--phase", action="append", default=[])
    co.add_argument("--prefer", action="append", default=[],
                    help="runtime preferido (repetible), si cumple las capacidades")
    co.add_argument("--json", action="store_true")
    co.set_defaults(func=cmd_context)

    en = sub.add_parser("environments", aliases=["entornos"],
                        help="contra qué entorno se trabaja, y si sigue respondiendo")
    en.add_argument("action", nargs="?", default="show", choices=["show", "check"])
    en.add_argument("--write", action="store_true",
                    help="con `check`, actualiza el sondeo y la fecha en el archivo")
    en.add_argument("--json", action="store_true")
    en.set_defaults(func=cmd_environments)

    me = sub.add_parser("memory", help="memoria en capas; no es evidencia")
    me.add_argument("action", choices=["list", "summary", "remember", "export"])
    me.add_argument("--layer", action="append", default=[])
    me.add_argument("--key", default="")
    me.add_argument("--body", default="")
    me.add_argument("--why", default="")
    me.add_argument("--source", default="")
    me.add_argument("--query", default="")
    me.add_argument("--all", action="store_true")
    me.add_argument("--json", action="store_true")
    me.set_defaults(func=cmd_memory)

    ins = sub.add_parser("install", help="deja este espacio operativo de principio a fin")
    ins.add_argument("--agent", action="append", default=[],
                     help="runtimes a enganchar; por defecto, los presentes")
    ins.add_argument("--core", default="", help="ruta del núcleo SDD, si hay ambigüedad")
    ins.add_argument("--spec", default="", help="especificación activa, si hay varias")
    ins.add_argument("--provider-expect", default="subscription",
                     choices=["subscription", "api-key", "bedrock", "vertex", "foundry",
                              "custom"],
                     help="a qué proveedor debe hablar el agente aquí")
    ins.add_argument("--no-bind", action="store_true")
    ins.add_argument("--deep", action="store_true")
    ins.add_argument("--force", action="store_true")
    ins.set_defaults(func=cmd_install)

    b = sub.add_parser("bind", help="ata este espacio a un núcleo y a un repositorio")
    b.add_argument("action", choices=["set", "show", "verify"])
    b.add_argument("--core", default="", help="ruta del núcleo SDD, si hay ambigüedad")
    b.add_argument("--repo", default="", help="ruta del repositorio, si hay ambigüedad")
    b.add_argument("--root", action="append", default=[])
    b.add_argument("--deep", action="store_true")
    b.add_argument("--by", default="")
    b.set_defaults(func=cmd_bind)

    i = sub.add_parser("init", help="crea .harness/ en este espacio")
    i.add_argument("--force", action="store_true")
    i.set_defaults(func=cmd_init)

    up = sub.add_parser("upgrade", aliases=["actualizar"],
                       help="lleva este espacio a la versión del motor en disco")
    up.add_argument("--apply", action="store_true",
                    help="escribe. Sin esto muestra qué cambiaría y no toca nada.")
    up.set_defaults(func=cmd_upgrade)

    v = sub.add_parser("verify", help="ejecuta las puertas y emite evidencia")
    v.add_argument("--gate", action="append", default=[])
    v.add_argument("--deep", action="store_true")
    v.add_argument("--offline", action="store_true", help="no consulta orígenes remotos")
    v.add_argument("--json", action="store_true")
    v.set_defaults(func=cmd_verify)

    po = sub.add_parser("policy", help="compila la política canónica a cada runtime; `prune` retira reglas de permiso podridas")
    po.add_argument("action",
                    choices=["show", "plan", "compile", "wire", "unwire", "audit", "prune"])
    po.add_argument("--agent", action="append", default=[])
    po.add_argument("--dry-run", action="store_true")
    po.add_argument("--repos", action="store_true",
                    help="con `wire`: engancha tambien cada repositorio del espacio, todos al "
                         "MISMO guardian. Una politica, un guardian, N punteros.")
    po.add_argument("--apply", action="store_true",
                    help="sólo para `prune`: escribe. Sin esto mide y no toca nada.")
    po.set_defaults(func=cmd_policy)

    lo = sub.add_parser("lock", help="ancla el origen por commit inmutable")
    lo.add_argument("action", choices=["show", "verify", "plan", "update", "init"])
    lo.add_argument("--source", action="append", default=[])
    lo.add_argument("--offline", action="store_true")
    lo.set_defaults(func=cmd_lock)

    m = sub.add_parser("mcp", help="integridad referencial de la cadena MCP")
    m.add_argument("--offline", action="store_true")
    m.set_defaults(func=cmd_mcp)

    inv = sub.add_parser("inventory", help="inventario mecánico del conjunto de repositorios")
    inv.add_argument("--depth", type=int, default=3)
    inv.add_argument("--json", action="store_true")
    inv.add_argument("--save", action="store_true")
    inv.set_defaults(func=cmd_inventory)

    e = sub.add_parser("evidence", help="lee el diario estructurado")
    e.add_argument("--last", type=int, default=20)
    e.add_argument("--kind", action="append", default=[])
    e.add_argument("--json", action="store_true")
    e.set_defaults(func=cmd_evidence)

    dc = sub.add_parser("docs", help="genera la matriz de compatibilidad desde la máquina")
    dc.add_argument("--out", default="", help="directorio de salida (por defecto, el del repo)")
    dc.add_argument("--deep", action="store_true")
    dc.set_defaults(func=cmd_docs)

    ch = sub.add_parser("chat", help="abre una sesión interactiva con las protecciones puestas")
    ch.add_argument("--agent", default="claude",
                    choices=["claude", "kiro", "gemini", "opencode"])
    ch.add_argument("--role", default="", help="rol del registro; carga su contrato en la sesión")
    ch.add_argument("--spec", default="", help="especificación activa, si hay varias")
    ch.add_argument("--task", default="", help="número de issue: carga su contexto y su rol")
    ch.add_argument("--repo", default="", help="owner/name de la issue, si no es la de aquí")
    ch.add_argument("--model", default="")
    ch.add_argument("--resume", action="store_true", help="continúa la conversación anterior")
    ch.add_argument("--provider", default="auto", choices=["auto", "clean", "inherit"],
                    help="auto: limpia la redirección si está rota · clean: siempre limpia · "
                         "inherit: respeta el entorno tal cual")
    ch.add_argument("--dry-run", action="store_true",
                    help="enseña el informe y la orden, sin abrir nada")
    ch.add_argument("pass_through", nargs="*", default=[],
                    help="argumentos que se pasan tal cual al agente")
    ch.set_defaults(func=cmd_chat)

    wk = sub.add_parser("work", help="qué tiene pendiente, ya enrutado a su rol y su runtime")
    wk.add_argument("--repo", default="", help="owner/name; por defecto, el de este espacio")
    wk.add_argument("--agent", action="append", default=[],
                    help="runtime a considerar; por defecto, el que declara el manifiesto")
    wk.add_argument("--limit", type=int, default=40)
    wk.add_argument("--json", action="store_true")
    wk.set_defaults(func=cmd_work)

    pl = sub.add_parser("plan", help="qué se ejecutaría, quién y con qué puertas")
    pl.add_argument("--goal", default="")
    pl.add_argument("--phase", action="append", default=[])
    pl.add_argument("--prefer", action="append", default=[])
    pl.add_argument("--save", action="store_true")
    pl.add_argument("--json", action="store_true")
    pl.set_defaults(func=cmd_plan)

    ru = sub.add_parser("run", help="conduce el ciclo; en seco salvo --execute")
    ru.add_argument("--goal", default="")
    ru.add_argument("--phase", action="append", default=[])
    ru.add_argument("--prefer", action="append", default=[])
    ru.add_argument("--execute", action="store_true", help="invoca agentes de verdad")
    ru.add_argument("--budget", type=float, default=0.25, help="tope por paso, en USD")
    ru.set_defaults(func=cmd_run)

    re_ = sub.add_parser("resume", help="continúa una ejecución, si el entorno no cambió")
    re_.add_argument("run_id", nargs="?", default="")
    re_.add_argument("--execute", action="store_true")
    re_.add_argument("--budget", type=float, default=0.25)
    re_.add_argument("--force", action="store_true")
    re_.set_defaults(func=cmd_resume)

    st = sub.add_parser("status", help="dónde está el trabajo y qué espera a una persona")
    st.set_defaults(func=cmd_status)

    s = sub.add_parser("selftest", help="el juez se prueba a sí mismo")
    s.add_argument("--suite", action="append", default=[])
    s.set_defaults(func=cmd_selftest)
    return p


def main(argv: list | None = None) -> int:
    # Antes de imprimir nada: los informes llevan ✓, ✗ y rayas largas. En una consola cp1252
    # eso no era una tabla fea, era un `UnicodeEncodeError` que se llevaba el comando entero
    # —`doctor` incluido— con un Traceback en vez de un veredicto.
    force_utf8_io()

    opts = build_parser().parse_args(argv)
    try:
        return opts.func(opts)
    except KeyboardInterrupt:
        print("\n  interrumpido", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
