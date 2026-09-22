# refuto

Una capa de gobierno para agentes de código, independiente del proveedor. No decide qué hace el
agente: decide **si lo que dice que hizo se puede demostrar**, y deja el rastro con el que
comprobarlo después.

Sólo biblioteca estándar. Python 3.10 o superior. Sin `pip install`.

---

## El problema

Un agente de código bajo presión de contexto hace lo que sea por terminar la tarea, y «editar la
verificación para que pase» es una forma perfectamente razonable de terminarla si nadie lo
impide. A eso se suma que los agentes cambian de nombre, de banderas y de precio cada trimestre,
y que cada uno expresa sus permisos en un vocabulario distinto.

`refuto` responde a las dos cosas con la misma pieza: **una política escrita una vez**, compilada
al dialecto de cada runtime y aplicada por **un único guardián** que todos los ganchos invocan; y
un contrato de estados donde «no pude comprobarlo» no acaba en verde.

La regla que ordena el resto: **un agente no puede ser juez de sí mismo.**

## Arranque en 60 segundos, en una máquina limpia

```bash
python3 --version            # hace falta 3.10 o superior
git clone <url-del-repositorio> refuto
cd refuto
python3 refuto.py doctor     # qué hay en esta máquina y qué funciona de verdad
python3 refuto.py selftest   # el juez se prueba a sí mismo
```

**Aviso para macOS:** `/usr/bin/python3` es **3.9.6** en macOS 15 y 26, y no sirve. Compruébelo
con `python3 --version` antes que nada; si sale `3.9.x`, instale 3.10+ (`brew install python@3.12`
u otro medio) y use ese intérprete. Con 3.9 algunos subcomandos arrancan y fallan más tarde, que
es el peor de los modos de fallar. Los detalles, en [`INSTALL.md`](INSTALL.md).

Después, sobre el espacio que quiera gobernar:

```bash
cd /ruta/al/espacio
python3 /ruta/a/refuto/refuto.py install   # política, vínculo, guardián y contexto
python3 /ruta/a/refuto/refuto.py verify    # ejecuta las puertas y emite evidencia
```

El resto de la documentación escribe `refuto verify` a secas. Para que eso sea un comando y no
una abreviatura, ponga `bin/` en el `PATH`; si no, escriba `python3 /ruta/a/refuto/refuto.py` en
su lugar. Ver [`INSTALL.md`](INSTALL.md).

## Las tres capas

**1 · Motor de sesión.** Lanzador, informe de sesión, **una política canónica** compilada al
gancho `PreToolUse` de cada runtime, y un diario de evidencia (`.harness/evidence/ledger.jsonl`,
sólo añadir, con procedencia). El informe de sesión llega al agente antes del primer turno: dónde
está, qué no puede tocar, y que lo aplica un programa fuera de su control.

**2 · Método por etapas.** El espacio declara su método en `.harness/pipeline.json` y `refuto` lo
**lee**; no lo impone. El método de referencia con el que se construyó esto tiene siete etapas
—`AUDIT → DESIGN → IMPLEMENT → TEST → E2E → DEPLOY → RUNTIME`— y una escala de evidencia
`E0…E4`. Un espacio que no declara método no recibe uno inventado: la sección simplemente no
aparece. Aparte, y sin relación con esa escala, el motor de ejecución de `refuto` tiene su propio
ciclo de **13 fases** con criterio de entrada y de salida (ver [`docs/lifecycle/`](docs/lifecycle/)).

**3 · Contrato de estados.** `PASS` · `FAIL` · `BLOCKED` · `NOT_RUN` · `INCONCLUSIVE` ·
`NOT_APPLICABLE`, y la regla de la que se derivan las demás: **un ámbito vacío nunca aprueba**.
Una comprobación que no encontró nada que comprobar no ha pasado.

> Estado medido del vocabulario, 2026-09-22 (E2, lectura de `core/model.py` y de `gates/*.py`): el
> motor implementa hoy **`PASS` `FAIL` `BLOCKED` `NOT_EXECUTABLE`**. `NOT_RUN`, `INCONCLUSIVE` y
> `NOT_APPLICABLE` son parte del contrato declarado y **todavía no** del tipo `Result`; varias
> puertas usan `BLOCKED` para decir «aquí no aplica» (`gates/g_sdd.py`). Es una divergencia
> conocida, no una capacidad. Ver [`docs/estado-del-proyecto.md`](docs/estado-del-proyecto.md).

## Qué hace, concretamente

**`which` no es prueba de nada.** Un agente pasa por cinco peldaños —`NOT_INSTALLED`,
`INSTALLED`, `STARTABLE`, `FUNCTIONAL`, `VERIFIED`— y `refuto` declara en cuál se detuvo y por
qué, incluida la firma del binario nativo (`VALID`, `UNSIGNED`, `INVALID`, `REVOKED`). Un caso
observado el 2026-08-27 en macOS arm64: un agente resolvía en el `PATH`, declaraba versión y
macOS lo mataba al arrancar porque su certificado estaba revocado. `command -v` decía que sí.

**Se le pregunta al agente qué sabe hacer, con un handshake local.** ACP `initialize` sobre stdio
para quien lo habla; `system/init` del flujo `stream-json` para Claude Code; `initialize` de MCP
para Codex. Ninguno llama a un modelo. Para Claude Code el sondeo **sí envía un prompt** (`-p hi`)
con tope `--max-budget-usd 0.05`: el coste no está medido y no se afirma que sea cero.

**Una política, N compilaciones, un guardián.** La regla se escribe una vez; cada adapter la
traduce a su vocabulario **y declara qué parte no puede aplicar**. El guardián resuelve la ruta
(`realpath`) antes de compararla, así que un enlace simbólico no la sortea. Qué runtimes lo tienen
enganchado de verdad, abajo.

**El lock ancla por commit, y se verifica antes de escribirse.** Nunca
`traer → reescribir el lock → comparar`, que es una tautología. Una etiqueta de git es mutable.

**Rol ≠ agente.** Un rol es una unidad de trabajo con contrato (22 en `roles/registry.json`); un
agente es un runtime que puede ejecutarlo. El router los empareja por capacidad y prefiere el
runtime donde la política sí se aplica.

## Qué runtime puede qué — y no es el mismo conjunto

Medido el 2026-09-22 sobre este árbol (E1/E2: lectura de código y `--help` del propio CLI; **no**
ejecución contra los agentes). Los cuatro verbos son independientes y confundirlos es el error que
esta tabla existe para impedir.

| Runtime | Sondeable (`probe`) | Sesión gobernada (`chat --agent`) | Guardián enganchable (`policy wire --agent`) | Dialecto de gancho (`core.guard --runtime`) |
|---|---|---|---|---|
| `claude` | sí | sí | **sí** | sí |
| `kiro` | sí | sí | **sí** | sí |
| `gemini` | sí | sí | **no** | sí |
| `opencode` | sí | sí | **no** | sí |
| `codex` | sí | no | **no** | no |
| `antigravity` | no (no hay adapter) | no | **sí** | sí |

Lecturas obligadas de esta tabla:

- **`gemini` y `opencode` no tienen guardián enganchable.** La política se compila a un
  artefacto (`.gemini/hooks/harness-guard.json`, `opencode.harness.json`) y `policy wire` no lo
  engancha; que el agente lea esa ruta no está verificado. Por eso **`chat` se niega a abrirlos**:
  una sesión con informe y contexto pero sin control preventivo no es una sesión gobernada, y
  llamarla así sería el aprobado vacuo de siempre. Si acepta ese riesgo a sabiendas, decláralo en
  el manifiesto (`agents.<runtime>.unguarded: true`) y la sesión abre con un aviso, no en silencio.
- **`codex` tiene adapter y compila política** (sandbox y aprobación, `adapters/codex.py`), pero
  no abre sesión con `chat` ni tiene gancho. Sus reglas de `command_deny` se listan para el
  operador; **no las aplica el agente**.
- **`antigravity` tiene gancho y dialecto, y no tiene adapter ni sonda**: no aparece en la matriz
  de compatibilidad ni en `chat --agent`.
- La capa que ningún agente puede tocar sigue siendo la tercera: **rama protegida y CI**.

## Qué está probado y a qué nivel (E0–E4)

`E0` dicho · `E1` documentado o leído en el código · `E2` reproducible con un comando · `E3`
probado por la suite automática · `E4` observado en ejecución, fechado.

| Afirmación | Nivel | Evidencia |
|---|---|---|
| La suite pasa entera | **E3** | `python3 refuto.py selftest` → **478/478, 1 omitida** (sólo Windows). 2026-09-22, macOS arm64 (Darwin 25.4.0), Python 3.14.6 y 3.12 |
| Reparto de la suite | **E2** | `grep -rc "def test_" tests/<suite>`: unit 366 · contract 19 · selftest 66 · adversarial 27 = 478. 2026-09-22 |
| 13 puertas · 22 roles · 13 fases · 5 adapters | **E2** | `gates/base.py::GATES`, `roles/registry.json`, `core.lifecycle.PHASES`, `adapters/registry.py`. 2026-09-22 |
| Sin dependencias de terceros | **E2** | `python3 scripts/check_stdlib_only.py` en local, 2026-09-22 |
| `Result` no se construye `PASS` con hallazgos | **E3** | `tests/contract/test_result_contract.py` |
| Un adapter sin política no puede devolver `unenforceable: []` | **E3** | `tests/contract/test_result_contract.py` |
| Los tres invariantes del lock | **E3** | `tests/adversarial/test_attacks.py` |
| El guardián bloquea la escritura sobre el juez, con Claude Code y con Kiro | **E4**, n=1 | 2026-08-27, macOS arm64, `claude 2.1.247` y `kiro 2.20.0`. Una ejecución. Ver [`docs/validation/informe.md`](docs/validation/informe.md) |
| Un agente real escribió una prueba que pasa, bajo puertas | **E4**, n=1 | 2026-08-27, `claude 2.1.247`, fase `TEST`. Ver [`docs/examples/end-to-end-run.md`](docs/examples/end-to-end-run.md) |

Y lo que **no** está probado, con su estado:

| Sujeto | Estado | Por qué |
|---|---|---|
| Ejecución en **Linux** | `NOT_RUN` | nunca se ha ejecutado la suite ahí |
| Ejecución en **Windows** | `NOT_RUN` | los arreglos de portabilidad existen y se midieron en una rama aislada; sobre este árbol no se han ejecutado. 1 prueba queda omitida en macOS por ser sólo de Windows |
| **Python 3.10**, el mínimo declarado | `NOT_RUN` | no hay intérprete 3.10 en la máquina donde se mide |
| **CI en GitHub Actions** | `NOT_RUN` | el flujo está escrito y **nunca ha corrido en verde** en el runner |
| `codex` en ejecución real | `NOT_RUN` | hay adapter y sonda; no hay ejecución observada conduciendo trabajo |
| `antigravity` en ejecución real | `NOT_RUN` | el dialecto se derivó de la documentación embebida en el binario 2.15.1 (leída el 2026-09-21); no se observó una decisión suya en vivo |
| `gemini` / `opencode` con guardián | `NOT_RUN` | no hay enganche que verificar |
| Ciclo completo de las 13 fases | `NOT_RUN` | se ejecutó `TEST` |

## Qué no es

No es un orquestador de prompts ni un marco de agentes. No sustituye a la revisión humana ni a la
rama protegida: los declara como la capa que el agente no puede tocar. Y no detecta inyección de
prompt por patrones — limita lo que el agente puede hacer si la obedece.

## Documentación

| | |
|---|---|
| [`INSTALL.md`](INSTALL.md) | instalar en una máquina limpia y comprobar que quedó bien |
| [`docs/estado-del-proyecto.md`](docs/estado-del-proyecto.md) | qué está probado, a qué nivel, y los riesgos abiertos |
| [`ARCHITECTURE.md`](ARCHITECTURE.md) | qué es núcleo, qué es adapter y por qué |
| [`OPERATIONS.md`](OPERATIONS.md) | gobernar un espacio, ejecutar, actualizar, diagnosticar |
| [`TROUBLESHOOTING.md`](TROUBLESHOOTING.md) | fallos observados, con su fecha, su causa y su arreglo |
| [`SECURITY.md`](SECURITY.md) | modelo de amenaza, pruebas adversariales y cómo reportar |
| [`MIGRATION.md`](MIGRATION.md) | adoptarlo sobre un conjunto de repositorios que ya funciona |
| [`SUPPORT_MATRIX.md`](SUPPORT_MATRIX.md) | salida de ejemplo de `refuto docs`, fechada |
| [`docs/lifecycle/`](docs/lifecycle/) | las 13 fases, con entrada, salida y revisión humana |
| [`docs/agents/`](docs/agents/) | los 22 roles, sus contratos y cómo se elige el runtime |
| [`docs/decisions/`](docs/decisions/) | 8 ADRs, cada uno con qué lo haría cambiar |
| [`docs/research/`](docs/research/) | investigación primaria, con fechas y versiones |
| [`CONTRIBUTING.md`](CONTRIBUTING.md) | cómo extenderlo sin romperlo |

## Idioma

La documentación y la prosa del código están en **español**. Los identificadores, las rutas, las
salidas de comando y el vocabulario técnico establecido (`PASS`, `commit`, `stdio`) van en
inglés. No hay traducción al inglés todavía.

## Nombres

El producto es `refuto`. «Harness» aparece como **nombre común** para el concepto de arnés de
gobierno, nunca como nombre del producto. Se conservan sin renombrar, porque son contrato con
espacios ya instalados: el directorio `.harness/`, las variables `HARNESS_*`, los identificadores
de esquema `harness.*/v1` y el prefijo `harness-guard` con el que el guardián firma sus mensajes.

## Estado

Versión en `VERSION`. **No hay ninguna etiqueta de git publicada todavía**, así que lo que un
`clone` obtenga puede no coincidir con lo que el `CHANGELOG` describe: compruebe `VERSION` en su
copia. Ver [`docs/estado-del-proyecto.md`](docs/estado-del-proyecto.md).
