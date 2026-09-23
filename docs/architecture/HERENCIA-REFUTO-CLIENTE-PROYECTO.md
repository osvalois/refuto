# Propuesta — `refuto → cliente → proyecto`

> Todo lo medido aquí es del 2026-09-23, contra el árbol de refuto y contra un espacio real
> con motor propio. Las citas llevan símbolo, no número de línea, para que no envejezcan.

## 0 · Por qué hoy no se hereda nada

No es que la herencia esté rota. **No existe.** Medido:

```sh
grep -rn "extends|parent_policy|overlay|base_manifest" core schemas gates refuto.py
→ ninguna coincidencia
```

Cada espacio declara su política, su manifiesto y su método **completos**, desde cero. Dos
espacios del mismo cliente repiten las mismas reglas y divergen en cuanto uno se toca. Eso es
lo que estás viendo.

Pero hay una pieza que **sí** existe y que nadie está usando.

## 1 · El dato que cambia el diagnóstico

Los dos vocabularios de estado son casi el mismo:

| | |
|---|---|
| refuto | `PASS` `FAIL` `BLOCKED` `NOT_EXECUTABLE` `NOT_APPLICABLE` |
| el motor propio del espacio | `PASS` `FAIL` `BLOCKED` `NOT_APPLICABLE` `UNKNOWN` + `BLOCKED_BY_PLATFORM`, `HARNESS_DEFECT` |

Cuatro de cinco coinciden **literalmente**. No son dos filosofías distintas: es la misma, con
dos implementaciones y un par de estados extra donde el motor especializado afina más.

Y el informe que ese motor emite ya tiene la forma que el puente de refuto espera:

```json
{"schema": "…:informe:v1",
 "etapas": [{"etapa": "AUDIT", "estado": "PASS", "satisface": true, …}]}
```

## 2 · El puente ya está construido

`gates/g_sdd.py` es exactamente esto, y su ADR lo dice desde el principio
([ADR-0007](../decisions/ADR-0007-puente-no-reescritura.md)): **envolver el verificador
externo, no reescribirlo**. El contrato vive en el manifiesto:

```json
"integrations": {
  "spec_core": {
    "runner":     ".harness/hz",
    "args":       ["run", "--sin-sellar", "--json"],
    "report":     "…",
    "gates_key":  "etapas",
    "status_map": {"PASS": "PASS", "FAIL": "FAIL", "BLOCKED": "BLOCKED",
                   "NOT_APPLICABLE": "NOT_APPLICABLE",
                   "UNKNOWN": "NOT_EXECUTABLE",
                   "BLOCKED_BY_PLATFORM": "BLOCKED",
                   "HARNESS_DEFECT": "NOT_EXECUTABLE"}
  }
}
```

El espacio con motor propio **declara `G-SDD` en su lista de puertas y no declara
`integrations`**. Por eso la puerta responde `NOT_APPLICABLE` — «no hay verificador externo
declarado» — y el veredicto del motor especializado nunca entra en refuto.

Las dos últimas correspondencias no son decorativas. `UNKNOWN` → `NOT_EXECUTABLE` conserva la
distinción entre «no lo sé» y «está mal»; `HARNESS_DEFECT` → `NOT_EXECUTABLE` dice que el
instrumento falló, que no es lo mismo que el sujeto. Aplanarlos a `BLOCKED` perdería justo lo
que este sistema existe para no perder.

### El único hueco real

El puente lee un **fichero** (`report`); el motor imprime el JSON por **stdout**. Se cierra
por cualquiera de los dos lados, y conviene elegir a conciencia:

| | coste | dónde se toca |
|---|---|---|
| el motor acepta `--informe <ruta>` | una opción | el espacio especializado |
| el puente acepta `report: "-"` = stdout | una rama | `gates/**`, **protegido**: lo aplica una persona |

La primera se puede hacer hoy y no toca nada protegido. La segunda es más general y sirve
para cualquier verificador futuro que sólo hable por stdout.

## 3 · Las tres capas, y qué pertenece a cada una

La regla para decidir dónde va algo: **si cambiarlo sólo afecta a un proyecto, es del
proyecto; si afecta a todos los de un cliente, es del cliente; si cambiarlo cambiaría el
significado de `PASS`, es de refuto.**

```
refuto              el vocabulario y el motor
  │                 estados · contrato Result · guardián · identidad · evidencia
  │                 las 13 puertas · el puente a verificadores externos
  ▼
cliente             lo que comparten sus proyectos
  │                 política base · roles · puertas exigidas · método
  │                 fronteras de datos · clases de obra
  ▼
proyecto            lo que sólo es suyo
                    su spec · su lock · su verificador especializado
                    lo que añade, nunca lo que relaja
```

**La restricción que hace que esto no degenere:** una capa hija puede **añadir** puertas y
**endurecer** reglas. No puede quitar una puerta que el padre exige ni ensanchar una ruta que
el padre protege. Sin esa asimetría, «heredar» acaba significando «heredo lo cómodo», y la
capa de cliente se convierte en el sitio donde se van a relajar los controles.

## 4 · Tres etapas, en orden de dependencia

### Etapa 1 · Herencia del veredicto — casi disponible hoy

El espacio especializado declara `integrations.spec_core`. Su motor sigue siendo el juez de su
dominio; refuto **traduce** ese veredicto a su vocabulario y lo integra en la corrida.

- Requiere: cerrar el hueco stdout↔fichero (§2).
- No requiere: ningún cambio en `core/`, ni en el motor especializado más allá de una opción.
- Qué **no** resuelve: sigue sin haber capa de cliente. Dos proyectos del mismo cliente
  siguen repitiendo su política entera.

### Etapa 2 · Herencia de declaración — `NOT_RUN`

`extends` funciona hoy para **políticas** (etapa 3). Para el **manifiesto** —heredar la lista
de puertas, los roles y el método— no está implementado: `NOT_RUN`.


```json
{ "schema": "harness.manifest/v1",
  "extends": "cliente:obra-publica/v1",
  "gates": ["+G-ATESTACION"] }
```

Lo que hace falta decidir, y es lo único difícil de esta etapa:

| pregunta | por qué no se puede posponer |
|---|---|
| ¿dónde vive la declaración del cliente? | `~/.config/harness/registry.json` ya nombra espacios y apunta a su política: es el sitio natural |
| ¿qué se acumula y qué se sustituye? | las puertas se acumulan; el método se sustituye entero — un método a medias no es un método |
| ¿qué pasa si el padre no está? | `NOT_EXECUTABLE`. **Nunca** los valores por omisión: un manifiesto que dice `extends` y corre sin el padre parece gobernado y no lo está |

Ese último punto ya tiene precedente medido en este repositorio: `Policy.from_dict` levanta
`PoliticaIlegible` cuando no reconoce **ninguna** clave, precisamente porque un documento de
otro programa producía la política de fábrica y el espacio parecía gobernado sin estarlo.

### Etapa 3 · Refinamiento de política — **IMPLEMENTADO**

`core/refinement.py`, expuesto como `refuto policy refine`. La invariante:

```
restricciones(hijo)  ⊇  restricciones(padre)
```

Cada campo de `Policy` declara su monotonía, y **ninguno puede quedarse sin declararla**: el
módulo no se importa si falta alguna. Un campo sin regla se heredaría como suponga quien lo
escribió, que es como no decidirlo.

| campo | regla | por qué |
|---|---|---|
| `protected_paths` `secret_read_deny` `command_deny` `command_ask` `network_rules` | **ACUMULA** | el hijo hereda todo y puede añadir; retirar es violación |
| `writable_paths` `external_write_allow` | **REDUCE** | abren agujeros en lo protegido: el hijo puede cerrarlos, nunca abrir otros |
| `block_secret_content` | **ENDURECE** | `true` del padre no se puede poner a `false` |
| `schema` `version` `default_modes` | **PROPIO** | metadatos y modo de interacción: no son restricciones |

Una corrección respecto a la primera versión de este documento: se dijo que `writable_paths`
**no se heredaría**. Es peor. Sin heredarlos, el hijo los declara desde cero y puede escribir
cualquiera — es decir, puede abrir un agujero que el padre no tenía. `REDUCE` conserva la
intención (nadie abre nada nuevo) y además propaga los cierres del padre.

**Lo que NO es:** no es `{**padre, **hijo}`. Un `merge` deja que el hijo sustituya cualquier
clave, y sustituir es relajar cuando la clave es una restricción. Medido: con un `merge`
ingenuo, **los 10 ataques de `tests/adversarial/test_monotonia.py` sobreviven**.

Y cuando el hijo intenta relajar, **no se aplica ninguna parte**. Una política a medias es
indistinguible de una política, y esa indistinguibilidad es el fallo.

## 5 · Qué probar antes de creerse cada etapa

Ninguna se puede dar por buena sin su prueba de falsación:

| etapa | la prueba que la sujeta |
|---|---|
| 1 | el veredicto del motor externo llega **tal cual**: si el motor dice `FAIL`, la corrida de refuto dice `FAIL` |
| 1 | un motor externo **ausente** da `NOT_EXECUTABLE`, nunca `NOT_APPLICABLE` — «no lo encontré» no es «no aplica» |
| 2 | un hijo que intenta **quitar** una puerta del padre es rechazado |
| 2 | `extends` a un padre inexistente da `NOT_EXECUTABLE`, no valores por omisión |
| 3 | un hijo que intenta **ensanchar** `protected_paths` del padre es rechazado |
| 3 | un `writable_paths` del padre **no** llega al hijo |

Las de «intenta relajar y es rechazado» son las importantes. Las otras comprueban que
funciona; éstas comprueban que **no se puede usar para lo que no es**.

## 6 · Lo que esta propuesta no afirma

- Que el motor especializado deba desaparecer. Su dominio —atestación, admisión de obra
  externa, clases— no está en refuto y no tiene por qué estarlo. ADR-0007 dice envolver, no
  absorber.
- Que las tres etapas sean necesarias. La 1 resuelve lo que preguntaste —que el veredicto se
  herede— y las otras dos resuelven la repetición entre proyectos de un mismo cliente. Son
  problemas distintos y se pueden decidir por separado.
- Que esté implementada. **Nada de las etapas 2 y 3 existe**: `extends` no está en ningún
  esquema ni en ningún módulo. Este documento es una propuesta, y mientras no haya pruebas
  ejecutadas su estado es `NOT_RUN`.

## 7 · `POLICY` ≠ `ENFORCEMENT` ≠ `ASSURANCE`

Tres cosas distintas que se confunden con facilidad, y confundirlas atribuye a refuto una
capacidad que no tiene.

| | qué es | quién lo hace aquí |
|---|---|---|
| **POLICY** | qué está permitido | `.harness/policy.json`, y su refinamiento |
| **ENFORCEMENT** | qué **impide físicamente** una acción prohibida | el guardián como `PreToolUse` del runtime, la protección de rama del servidor, el sandbox del sistema operativo |
| **ASSURANCE** | qué **demuestra** que el contrato se cumplió | las 13 puertas, la evidencia, la falsación |

El ejemplo que lo separa:

```
policy       un agente no modifica producción
enforcement  el sandbox o la autorización deniegan la operación
assurance    refuto comprueba la política, comprueba el enganche, y observa la denegación
```

**Refuto hace enforcement en un solo sitio y de forma limitada**: el guardián intercepta
`PreToolUse` del runtime que lo tenga enganchado. Eso no es un sandbox. Un agente que se
salte el runtime —o que corra sin el gancho— escribe igual. Lo que refuto sí puede demostrar
es que el gancho estaba puesto y que la denegación ocurrió, porque queda en el diario.

Medido en esta sesión: la protección de rama que sí sería enforcement de verdad **no está
disponible** (`HTTP 403`, requiere plan de pago), y lo que hay en su lugar es un gancho local
que se salta con `--no-verify`. Está declarado como tal en `docs/operations/DEVSECOPS.md`. Un
control que se presenta como barrera cuando es un recordatorio hace creer que hay defensa
donde hay costumbre.

## 8 · Preparación para agentes — conceptual, `NOT_RUN`

La cadena que refuto debe poder gobernar:

```
principal → delega → agente → pide capacidad → herramienta/acción → recurso → efecto → evidencia
```

Qué hay hoy de cada pieza, medido:

| pieza | estado |
|---|---|
| `Identity` | **parcial** — identidad tipada de ejecución (`ses_` `orq_` `ver_` `ctx_`), ADR-0012 |
| `Capability` | **parcial** — `core/capability.py` con 7 estados y catálogo |
| `Tool` / `Action` | **parcial** — el guardián decide por herramienta y patrón de argumentos |
| `Evidence` | **sí** — `Evidence` ya lleva `kind, summary, command, source, exit_code, stdout_digest, excerpt, redacted` |
| `Authority` / `Delegation` | **`NOT_RUN`** — no existe `parent_run_id` ni frontera de autoridad |
| `Agent` como principal gobernable | **`NOT_RUN`** |

**Lo que NO se construyó a propósito**, y es un criterio de parada, no una omisión:
orquestación de LLM, planificador, memoria de agente, runtime multi-agente. Eso pertenece a
las capas que *consumen* refuto. Refuto debe gobernarlas, no convertirse en ellas — y un
sustrato que empieza a planificar deja de poder juzgar con independencia lo que planifica.

## 9 · Límites actuales, declarados

| | estado | por qué |
|---|---|---|
| herencia de **manifiesto** (`extends` de puertas/roles/método) | `NOT_RUN` | sólo la política refina |
| resolución del padre **por nombre** contra el censo | `NOT_RUN` | exige decidir dónde vive la capa de cliente; hoy `extends` es una ruta |
| adaptador stdout del verificador externo | `BLOCKED` | vive en `gates/**`, protegido por política |
| `G-SDD`: integración declarada con ejecutor ausente | **inconsistencia** | devuelve `BLOCKED`; el contrato de estados dice `NOT_EXECUTABLE` («falta el ejecutor»). En `gates/**` |
| segunda máquina | `BLOCKED` | sólo existe una · `LIMITATION: single-host` |
