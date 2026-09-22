# -*- coding: utf-8 -*-
"""G-SECURITY · Inventario, secretos y dependencias, con las herramientas que HAY.

Umbral: **cero secretos en el árbol · inventario de dependencias generado · cero
vulnerabilidades críticas sin excepción declarada.**

La regla que ordena esta puerta
-------------------------------
Cuando falta la herramienta que haría una comprobación, el resultado es **`BLOCKED`**, no
`PASS`. Un pipeline de seguridad que sale en verde porque el escáner no estaba instalado es
peor que no tener pipeline: da una garantía falsa, y las garantías falsas se citan.

Lo que sí se hace siempre, aunque no haya nada instalado: el escaneo de secretos propio del
harness, que corre con biblioteca estándar y no depende de nadie.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from core.digest import redact
from core.model import BLOCKED, CRITICAL, Evidence, FAIL, Finding, HIGH, PASS, Result
from core.proc import TEXT_IO

GATE_ID = "G-SECURITY"
TITLE = "Seguridad: secretos, dependencias e inventario"
THRESHOLD = ("cero secretos en el árbol · SBOM generado · cero críticas sin excepción · "
             "herramienta ausente = BLOCKED, nunca PASS")

SKIP = {".git", "node_modules", "__pycache__", ".venv", "dist", "build", "target", ".harness"}
BINARY_EXT = {".png", ".jpg", ".jpeg", ".gif", ".pdf", ".zip", ".gz", ".woff", ".woff2",
              ".ico", ".mp4", ".pyc", ".so", ".dylib", ".jar", ".class"}
MAX_BYTES = 2_000_000


def run(ctx) -> Result:
    findings, observations, evidence = [], [], []
    blocked = False

    # 1 · Secretos. Siempre corre: no depende de nada instalado.
    scanned, hits = _scan_secrets(ctx.workspace)
    for rel, line_no, labels in hits:
        findings.append(Finding(rel, f"posible secreto ({', '.join(labels)}). "
                                     f"Lo que entra al árbol, sale: el control es que el dato "
                                     f"no esté, no que no se mande.", line_no))
    evidence.append(Evidence(kind="computation", summary="escaneo de secretos propio",
                             excerpt=f"{scanned} archivos recorridos · {len(hits)} hallazgos"))

    if shutil.which("gitleaks"):
        out = _run_json(["gitleaks", "detect", "--no-banner", "--report-format", "json",
                         "--report-path", "-", "-s", str(ctx.workspace)])
        if out["ok"]:
            n = len(out["data"] or [])
            observations.append(f"gitleaks: {n} hallazgos")
            for h in (out["data"] or [])[:10]:
                findings.append(Finding(h.get("File", "?"),
                                        f"gitleaks: {h.get('RuleID', 'regla desconocida')}",
                                        int(h.get("StartLine") or 0)))
        else:
            observations.append(f"gitleaks presente y no se pudo ejecutar: {out['error'][:120]}")
    else:
        observations.append("gitleaks NO está: el escaneo profundo de secretos no se ejecutó. "
                            "Sólo consta el escaneo propio de refuto, que es más superficial.")

    # 2 · Inventario de dependencias (SBOM).
    sbom_path = ctx.workspace / ".harness" / "evidence" / "sbom.json"
    if shutil.which("syft"):
        out = _run_json(["syft", "scan", f"dir:{ctx.workspace}", "-o", "syft-json"])
        if out["ok"] and out["data"]:
            from core.model import write_json
            write_json(sbom_path, out["data"])
            n = len(out["data"].get("artifacts") or [])
            evidence.append(Evidence(kind="command", summary=f"SBOM con {n} componentes",
                                     command="syft scan dir:. -o syft-json",
                                     source=str(sbom_path)))
            observations.append(f"SBOM generado: {n} componentes")
        else:
            blocked = True
            observations.append(f"syft presente y falló: {out['error'][:120]}")
    else:
        blocked = True
        observations.append(
            "syft NO está: no hay inventario de dependencias. Sin SBOM no se puede responder "
            "«¿qué contiene esto?» ante un CVE. → BLOCKED, no PASS. Instale con `brew install syft`.")

    # 3 · Vulnerabilidades.
    if shutil.which("trivy"):
        out = _run_json(["trivy", "fs", "--quiet", "--format", "json", "--severity",
                         "CRITICAL,HIGH", str(ctx.workspace)])
        if out["ok"]:
            crit = high = 0
            for res in (out["data"] or {}).get("Results", []):
                for v in res.get("Vulnerabilities") or []:
                    if v.get("Severity") == "CRITICAL":
                        crit += 1
                        findings.append(Finding(res.get("Target", "?"),
                                                f"CRÍTICA {v.get('VulnerabilityID')} en "
                                                f"{v.get('PkgName')}"))
                    else:
                        high += 1
            observations.append(f"trivy: {crit} críticas · {high} altas")
        else:
            observations.append(f"trivy presente y falló: {out['error'][:120]}")
    else:
        blocked = True
        observations.append("trivy NO está: no se escanearon vulnerabilidades conocidas. "
                            "→ BLOCKED. Instale con `brew install trivy`.")

    status = FAIL if findings else (BLOCKED if blocked else PASS)
    return Result(GATE_ID, TITLE, status, severity=CRITICAL if findings else HIGH,
                  threshold=THRESHOLD,
                  measure=f"{scanned} archivos recorridos · {len(findings)} hallazgos · "
                          f"herramientas: "
                          f"{', '.join(t for t in ('gitleaks','syft','trivy') if shutil.which(t)) or 'ninguna'}",
                  findings=findings, observations=observations, evidence=evidence)


def _scan_secrets(root: Path) -> tuple[int, list]:
    import os
    scanned, hits = 0, []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP]
        for name in filenames:
            p = Path(dirpath) / name
            if p.suffix.lower() in BINARY_EXT:
                continue
            try:
                if p.stat().st_size > MAX_BYTES:
                    continue
                text = p.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            scanned += 1
            for n, line in enumerate(text.splitlines(), 1):
                _, labels = redact(line)
                if labels:
                    hits.append((str(p.relative_to(root)), n, labels))
    return scanned, hits


def _run_json(argv: list, timeout: int = 300) -> dict:
    try:
        p = subprocess.run(argv, capture_output=True, **TEXT_IO, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as exc:
        return {"ok": False, "data": None, "error": str(exc)}
    if not (p.stdout or "").strip():
        return {"ok": p.returncode == 0, "data": None,
                "error": (p.stderr or "")[:300] or "sin salida"}
    try:
        return {"ok": True, "data": json.loads(p.stdout), "error": ""}
    except json.JSONDecodeError as exc:
        return {"ok": False, "data": None, "error": f"salida no era JSON: {exc}"}
