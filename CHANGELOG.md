# Registro de cambios

**Aviso sobre las versiones.** A fecha de **2026-09-22** este repositorio **no tiene ninguna
etiqueta de git publicada**. Los números de abajo describen trabajo real, no publicaciones: lo que
un `clone` obtenga puede no coincidir con lo que aquí se lee. Compruebe `VERSION` en su copia
antes de citar una versión.

Las cifras de este documento llevan comando, fecha y máquina, o no están. Donde una medición
histórica no las conservó, se dice.

---

## 0.4.1 — *sin publicar* · seis defectos que una revisión adversarial encontró en los controles

Todo lo de abajo salió de auditar la rama `assurance/protocolo-tres-caras` el **2026-09-25**
contra `69bcd6a`, con la suite en verde (748/748) y CI en verde sobre el commit exacto. Ninguno
lo detectó una prueba: los seis estaban **en los controles**, que es donde un defecto no tiene
quien lo mire.

El patrón se repite y conviene nombrarlo: un mecanismo se escribe bien, y **lo que decide si
funciona no se comprueba a sí mismo**. Una tabla que se consulta por orden y admite duplicados;
una atestación que enumera extensiones; una cadena de huellas que asume que nadie escribe a la
vez; un tier estático que afirma para siempre algo medido una vez.

**Arreglado**

- **`Ê` afirmaba «sé que no escribe» de tres intérpretes** (`core/effects.py`). `perl` estaba en
  `_ESCRITORES` **y** en `_OPACOS`, y la primera se consulta antes; con clase `en_sitio` y sin
  su bandera, `perl`, `awk` y `sed` salían como LECTURA con `opaco=False`. Como `core/grants.py`
  descarta una concesión `read-only` cuando la orden es opaca, el defecto **invertía su
  criterio**. Medido con la concesión del propio caso de uso del módulo (`sudo *`, `read-only`):

  ```
  sudo systemctl status nginx                        deny    ← lectura de diagnóstico
  sudo journalctl / dmesg / netstat / ss / strings   deny
  sudo perl -e 'unlink "gates/base.py"'              ALLOW   ← borra el juez, como root
  sudo awk 'BEGIN{print "" > "/etc/sudoers.d/x"}'    ALLOW
  ```

  Seis de ocho diagnósticos denegados y las tres escrituras como root permitidas. Ahora hay
  clase `en_sitio_opaco`: sin su bandera **no se derivó nada**, luego `opaco`. `ruff` y `gofmt`
  siguen en `en_sitio` porque formatean lo que se les nombra y no ejecutan programa del usuario.
  Y las tres tablas se comprueban **disjuntas al importar**: la causa raíz era el duplicado, no
  el caso. `tests/adversarial/test_efectos_interpretes.py` (6) — **7 fallos sin el arreglo**.
- **La cadena del diario se rompía con el uso normal** (`core/evidence.py`). `append_event` leía
  la cabeza y escribía sin serializar; el argumento de que `O_APPEND` bastaba es correcto sobre
  los BYTES y no dice nada de la CADENA. Con 12 guardianes concurrentes: **12 eventos escritos,
  cadena rota en la línea 3**, y el motivo emitido acusaba de manipulación — «falta, sobra o se
  movió algún evento» — lo que era concurrencia normal. Una alarma de integridad que salta con
  el uso normal se aprende a ignorar. Ahora leer la cabeza y escribir el eslabón van dentro del
  mismo `flock`, y `MECANISMO_DE_BLOQUEO` lo declara para poder afirmarlo. Medido después: 16
  procesos → 16 eventos, cadena íntegra. De paso, `cabeza()` leía el fichero **entero** en cada
  evento (O(n) en el camino caliente del guardián, sin techo); ahora lee desde el final.
  `tests/adversarial/test_ledger_concurrente.py` (5).
- **La atestación `I6'` no cubría lo que decide** (`core/trust.py`). `inventario_motor` recorría
  sólo `rglob("*.py")`: **73 ficheros, cero de datos**. `roles/registry.json` alimenta
  `capacidades_de()` y produce `DENY` en el guardián desde `da39715` — editarlo cambiaba
  veredictos sin que `deriva_del_motor()` lo notara. La huella se quedó atrás **en el mismo
  commit** que volvió relevante al registro. Ahora cubre `roles/`, `schemas/` y `policies/`
  (78 ficheros, 5 de datos), y la documentación sigue sin moverla.
  `tests/adversarial/test_huella_del_motor.py` (4).
- **Un fallo de auditoría no retenía nada en `claude`** (`core/guard.py`). Con el diario
  inescribible y una escritura que aprobaría: `claude` → `allow`, kiro/gemini/opencode →
  exit 2, `antigravity` → `ask`. Tres respuestas al mismo hecho, y la permisiva era la del
  runtime principal. `_emit_event` argumenta exactamente ese caso —«una aprobación sin registrar
  quedaba idéntica a una registrada»— y el arreglo estaba en `_main_antigravity` y no en
  `main()`. Ahora los dos dialectos estructurados responden `ask`: el trabajo no se pierde y lo
  decide quien puede arreglar el diario. `tests/adversarial/test_auditoria_interrumpida.py` (4).
- **Una concesión `read-only` concedía sin verificar** (`core/grants.py`). Con `efectos=None` la
  comprobación se saltaba entera, contra el principio que el propio módulo defiende: «no poder
  demostrar que no escribe no es haber demostrado que no escribe». Hoy `decide_command` siempre
  los pasa, así que el camino real estaba cubierto; una firma que concede por omisión sólo
  espera a que alguien la llame de otra forma. Dos pruebas existentes fijaban ese `fail-open` al
  omitir el dato; **se corrigieron las pruebas, no el criterio**.
- **`verify` indicaba una bandera que no acepta** (`core/report.py`). La puerta imprimía
  `… y N más (use --verbose)` y `refuto verify --verbose` sale con **64**: `--verbose` es global
  y va antes del subcomando. Ahora se imprime la orden entera.

**Añadido**

- **`scripts/check_mediciones.py`**, y CI lo ejecuta. Las cifras ESTRUCTURALES del README ya
  tenían vigilante (`check_wiring`, `check_citas`) y cuadraban las siete; las de CORRIDA no, y
  son las que se citan como `E3`/`E4`. Medido: la tabla declaraba **685 pruebas y 13 controles
  con fecha del propio día**, cuando eran 748 y 14 — el commit que las puso al día (`bf9f061`)
  fue seguido de cinco que añadieron 730 líneas de pruebas sin tocarla. No comprueba tiempos:
  dependen de la máquina, y un control que falla por motivos que no son el defecto se desactiva.
- **La deuda de `verify` se declara puerta a puerta** (`DEUDA_DECLARADA` en
  `scripts/preflight.py`). `verify` estaba en `INFORMA` con el motivo «deuda declarada del
  proyecto, no de este cambio»; el motivo era cierto —`git blame`: los 18 hallazgos de
  `G-SECURITY` vienen de `e28249c`, en `main`— y **nada lo comprobaba**. Un tier estático afirma
  para siempre algo medido una vez. Ahora `verify` es `BLOQUEA` y perdona sólo las ocho puertas
  con deuda escrita: una puerta nueva en rojo retiene el empujón. Verificado en los dos
  sentidos. Hoy ningún control usa `INFORMA`, y el módulo lo dice en vez de dejar un tier que
  parece en uso.
- **El control `datos-personales` cubre la norma que cita.** Comprobaba `/Users/…` y tres
  dominios de correo personal, y se reportaba con ese nombre; `AGENTS.md` prohíbe además correos
  corporativos, hosts internos y direcciones privadas. Un alcance declarado mayor que el medido
  es un `PASS` que afirma de más. Ampliado a correo de cualquier dominio (salvo los de ejemplo y
  los `noreply` de agentes), RFC 1918 y enlace-local, y sufijos internos. `.local` se dejó
  **fuera**, medido: con él, **47 coincidencias y cero hosts** — `settings.local.json` (44),
  `hooks.local.json` (2), `.env.local` (1). Sobre el árbol rastreado el resultado sigue siendo
  cero ficheros: ampliar no costó ninguna excepción.

**Propuesto, no aplicado** — `gates/**` está protegido por la propia política, así que lo aplica
una persona:

- **`G-SECURITY` aprueba con la herramienta caída**, y su `measure` afirma haberla usado.
  Ejecutado sobre un espacio limpio con `trivy` sin poder bajar su base: `status: PASS`,
  `measure: … herramientas: gitleaks, syft, trivy`, `obs: SBOM generado: 0 componentes`. Tres
  defectos: el umbral sólo distingue ausente de presente y no cubre *caída*; un SBOM de cero
  componentes aprueba contra «un ámbito vacío nunca aprueba»; y `measure` se construye con
  `shutil.which()` —por estar instalada, no por haber funcionado—, así que **la evidencia
  escrita afirma una cobertura que no hubo**. Que es olvido y no criterio lo demuestra el propio
  fichero: `syft` sí pone `blocked = True` al fallar, y las otras dos no. Parche verificado con
  `git apply --check` y ejecutado sobre una copia (`PASS` → `BLOCKED`):
  [`docs/remediation/g-security-aprueba-con-la-herramienta-caida.md`](docs/remediation/g-security-aprueba-con-la-herramienta-caida.md).

**Cerrado después, y es la otra mitad de la retractación.** Los tres arreglos de arriba que
tocan `scripts/preflight.py`, `core/report.py` y `scripts/check_mediciones.py` se entregaron
**verificados a mano y sin una sola prueba**. Es decir: el trabajo consistió en señalar
controles que nadie vigilaba y se entregó añadiendo controles que nadie vigilaba. Un guion de
verificación ejercitado sólo en el caso bueno no ha demostrado lo único que importa de él —que
**sabe decir que no**—, que es el mismo criterio que `scripts/mutate_probe.py` se aplica a sí
mismo con sus controles negativos `NC1`/`NC2`.

- **`tests/unit/test_preflight_criterio.py`** (15) fija los bordes que una corrida real no
  produce cuando uno quiere: puerta nueva en rojo, ámbito vacío, `NOT_APPLICABLE`, deuda ya
  saldada, y que toda entrada de `DEUDA_DECLARADA` traiga motivo y nombre una puerta que
  existe. Para poder probarlo sin pagar 40 s de puertas, el criterio se separó en
  `clasificar_puertas()`. Dos pruebas nuevas cazaron defectos reales durante su propia
  escritura: que `check_mediciones.py` no estaba rastreado por git —un control que no se publica
  no protege a quien clona— y que el fichero de casos disparaba el detector que prueba (resuelto
  partiendo los literales, como ya hace `tests/fixtures/__init__.py`, en vez de gastar la
  primera entrada de `_PERSONALES_PERMITIDOS`).
- **`tests/unit/test_next_ejecutable.py`** (5) comprueba que la orden que imprime una puerta la
  acepta el parser REAL de refuto, no que el texto sea uno concreto. `core.envelope.Siguiente`
  ya exigía esto del campo `do` —«una orden ejecutable, no una descripción»— y el texto que lee
  una persona no estaba cubierto por nada.
- **`tests/unit/test_check_mediciones.py`** (8), con el control negativo que faltaba: que el
  guion detecte una cifra falsa, y que una afirmación DESAPARECIDA no se dé por buena — el modo
  de fallo silencioso, donde «no hay problema» sería indistinguible de «ya no se comprueba
  nada».

**Y el hallazgo que quedaba en `E1` se midió, y era real** (`core/mcp_server.py`). El
`workspace` lo aporta el modelo y `refuto_verify` escribe. Medido sobre un directorio recién
creado, fuera de todo espacio gobernado:

```
.harness/evidence/ledger.jsonl · sbom.json · ver_edb734a4c5f14c66.json
```

No es destrucción ni exfiltración: es escritura **no solicitada fuera del espacio**, y la
doctrina del producto sobre eso ya estaba escrita en `external_write_allow` —fuera del espacio
sólo se escribe en raíces declaradas—. Esta superficie la rodeaba por no preguntarse cuál es el
espacio: el módulo declaraba «no escribe lo que gobierna» y decía *qué* no escribe, no *dónde*.
Ahora `_argv_de` exige que el destino sea la raíz desde la que se lanzó el servidor o un espacio
que ya tenga `.harness/`. Es el criterio más estrecho que no cierra ningún uso real —verificar
un directorio que nunca fue un espacio deja casi todas las puertas en `BLOCKED` y no informa de
nada— y se comprueba en `_argv_de`, por donde pasan las siete herramientas, para que no dependa
de que nadie añada mañana otra que escriba. `tests/adversarial/test_mcp_workspace.py` (8).

**Medido tras los cambios** — `804/804` pruebas (1 omitida, sólo Windows) y
`preflight PASS · 15 controles`, 2026-09-25, macOS arm64 (Darwin 25.4.0), Python 3.14.6. **No ha
pasado por CI**: la última corrida verde es sobre `69bcd6a`, anterior a todo esto.

---

## 0.4.0 — *sin publicar* · la política se hereda, y la evidencia dice cuál decidió

`VERSION` sigue en `0.3.0`: esto describe la rama `assurance/identidad-canonica-y-falsacion`,
no una publicación.

La capacidad nueva es una sola: **una política puede declarar `extends` y refinar a su padre**,
en la cadena `refuto → cliente → proyecto`. Lo demás son defectos encontrados al construirla y
al intentar falsarla — varios de ellos en los propios instrumentos de medida, que es de donde
salieron los peores.

**Añadido**

- **Refinamiento monotónico de política** (`core/refinement.py`), con la invariante
  `restricciones(hijo) ⊇ restricciones(padre)`. No es `{**padre, **hijo}`: un merge deja que el
  hijo SUSTITUYA cualquier clave, y sustituir es relajar cuando la clave es una restricción.
  Medido: con un merge ingenuo **los 10 ataques** de `tests/adversarial/test_monotonia.py`
  sobreviven; con `refinar()`, los 10 se rechazan. Las reglas: `ACUMULA` (unión —
  `protected_paths`, `secret_read_deny`, `command_deny`, `command_ask`, `network_rules`),
  `REDUCE` (sólo estrechar, por cobertura demostrada — `writable_paths`,
  `external_write_allow`), `ENDURECE`
  (`block_secret_content`), `MODO` (`default_modes`) y `PROPIO` (`schema`, `version`). Ningún
  campo de `Policy` puede quedarse sin regla: **el módulo no se importa si falta alguna**.
- **Identidad de política encadenada.** `efectivo = sha256(padre.efectivo + "|" + digest)`. Dos
  políticas con el mismo texto y distinto padre no son la misma política. Los comentarios
  (`_que_es`, `_medido`) se excluyen del digest: si contaran, editar una nota invalidaría la
  identidad de todos los que heredan y nadie volvería a escribir notas.
- **El diario cita la política que decidió.** Cada evento `policy/decision` lleva
  `policy_digest` con la identidad **efectiva**. Con herencia, «qué regla denegó» deja de bastar:
  la regla pudo venir del cliente, y el cliente pudo cambiar después.
- **Alta que nace heredando**: `refuto init --extends RUTA [--anchor]` escribe un hijo de cuatro
  claves (cinco con ancla) en vez de copiar la norma entera. `refuto policy base` emite la capa 1
  por la salida —no la escribe: su sitio es `policies/base.json`, que la política protege, y
  materializar la norma de la que cuelgan todos los clientes es acto de persona.
  `refuto policy refine [--json]` muestra la política efectiva y su identidad.
- **`schemas/policy.schema.json`**, el contrato de política publicado, con
  `tests/contract/test_policy_schema.py` que lo contrasta contra los documentos que el programa
  produce de verdad. Hacía falta porque `scripts/check_schemas.py` comprueba que un esquema cae
  en el subconjunto soportado y **no valida ni una instancia**: un contrato que nadie contrasta
  es documentación.
- **`examples/tres-capas/`**, estructura de referencia validada ejecutando el guardián real, con
  los dos controles que impiden cerrarla con un «deniega todo».
- **Identidad tipada de ejecución** (`core/model.py`): `new_id(kind)` y `kind_of(id)` sustituyen
  a cuatro acuñadores independientes de `run_<hex>`.
- **Sonda de mutación con testigo declarado** (`scripts/mutate_probe.py`): una mutación sólo
  cuenta como muerta si cayó **la prueba que se declaró que la vigilaba**. Estados `MUERTA`,
  `MUERTA_INCIDENTAL`, `MUERTA_ESTRUCTURAL`, `MUERTA_SIN_TESTIGO`, `VIVA`, más dos controles de
  calibración. Un «6/6 MUERTAS» anterior era hueco: dos morían por una prueba de fin de línea.
- **Centinela del árbol y comprobador de citas** (`scripts/tree_sentinel.py`,
  `scripts/check_citas.py`): 30 citas `fichero::símbolo` resuelven, y una escritura ajena al
  árbol durante una medición se detecta en vez de contaminarla.

**Añadido — un vocabulario, tres consumidores** (2026-09-24)

- **`harness.envelope/v1`** (`core/envelope.py`, `schemas/envelope.schema.json`, ADR-0015): el
  sobre que toda orden emite con `--json`. Lo que se unifica es el sobre —quién responde, con qué
  estado, sobre qué espacio, con qué procedencia y **qué toca después**—; la carga útil de cada
  orden viaja intacta bajo `payload` con su propio contrato. Medido antes de tocar nada: `--json`
  en **11 de 24** órdenes, **20** contratos `harness.*/vN` emitidos y **3** publicados, y ni un
  helper común de emisión — veinte `json.dumps` en línea, que es la razón estructural de que
  hubiera veinte formas.
- **El código de salida lo deriva el estado**, nunca se elige a mano. El defecto que cierra:
  `refuto context --json` devolvía **2** —«no se pudo comprobar»— con la salida completa y válida
  en stdout. Para una persona es invisible; en CI, `cmd && siguiente` no encadena nunca. La tabla
  es deliberadamente gruesa (seis estados, cuatro códigos) y el contrato lo dice: `status` es
  autoritativo, `exit` es para encadenar. `core.envelope` no se importa si un estado se queda sin
  código.
- **`next[]` es contrato, no cortesía.** Un estado que no aprueba **sin un solo `next` levanta
  `ValueError` en la orden que lo cometió**. Viene medido: un agente al que se denegó su
  directorio de entregables, sin que nada le dijera cuál usar, se llevó 9,2 GB a `/tmp`. Cada
  paso declara `why`, una orden `do` **ejecutable** y `who` ∈ `persona | maquina | agente`, donde
  `maquina` significa idempotente y sin decisión.
- **Con `--json`, stdout lleva sólo el sobre.** `main()` captura la salida humana y la reencamina
  a stderr. Así no hay cientos de guardas `if not opts.json:` —la que se olvide rompe el
  protocolo en silencio— y el texto no se pierde. Una orden aún sin migrar se comporta
  exactamente como antes: la migración es orden a orden.
- **Órdenes migradas**: `doctor`, `status`, `verify`, `probe`, `mcp`, `inventory`, `upgrade`. Las
  cuatro primeras y `upgrade` ganan además `--json`, que no tenían.
- **`payload_of(doc)`**, el puente de migración en una función: acepta el sobre y la forma suelta
  anterior, para poder migrar emisor y consumidor en commits distintos. Ya lo usan
  `scripts/gate_summary.py` y `scripts/check_probe_honesty.py`, que es lo que lee
  `.github/workflows/refuto.yml`.

**Añadido — el monitor de referencia gana un sujeto, y el privilegio se parametriza** (2026-09-25)

El control de acceso es una relación ternaria `(sujeto, objeto, operación)` y refuto decidía
sobre una binaria: el hecho normalizado tenía siete campos y ninguno era el sujeto. Consecuencia
matemática, no de implementación: **todo agente en todo rol tenía autoridad idéntica**.

- **El canal de lectura, que estaba sin mirar.** `secret_read_deny` se aplicaba en
  `decide_write` (escrituras) y en `adapters/claude.py` (capa del agente, sobre `Read`). El
  guardián engancha `Bash`, así que `cat .env` salía `allow` y `cp .env ~/.claude/…/memory/` —que
  **sobrevive a la sesión**— también. Y el dato ya estaba: `Efectos.lecturas` se poblaba y
  `decide_command` tenía tres referencias a `escrituras` y **cero** a `lecturas`. Ahora leer una
  credencial es `ask` —un `deny` duro se rodea con `python3 -c`, que es opaco, y entonces el canal
  deja de mirarse— y la **combinación** lectura-de-credencial + escritura-fuera-del-espacio es
  `deny`: no tiene lectura legítima, y que el destino esté en `external_write_allow` no lo cambia.
- **El sujeto** (`core/capabilities.py`). 22 roles declaraban 10 restricciones cuyos únicos
  consumidores las imprimían en el informe bajo «No puedes:». **Diez capacidades por veintidós
  roles, aplicadas por cero líneas de código.** Y peor, en la propia puerta: `G-ROLES` declara en
  su umbral «restricciones **aplicables**» y las contrastaba contra `KNOWN_CONSTRAINTS`, que es el
  diccionario de **prosa** del informe — «no sabe aplicar» significaba «no tengo una frase en
  español para describirla». Ahora se valida contra `capabilities.CONOCIDAS` = aplicadas ∪
  declaradas no observables **con motivo**; la tercera categoría ya no se puede expresar. Reparto:
  5 aplicadas, 5 no observables. Una de ellas, `destructive_requires_approval`, es no observable
  **porque sería una relajación**.
- **Elevación parametrizada** (`core/grants.py`). `command_deny` colapsaba cuatro dimensiones
  —privilegio, destrucción, alcance externo, integridad de suministro— en una lista plana con dos
  verdictos, así que `sudo cat /etc/shadow` y `sudo systemctl status` eran la misma regla. Una
  concesión declara `roles × hosts × commands × effects × expires × evidence`, se evalúa **antes**
  de `command_deny` —como `writable_paths` va antes de `protected_paths`— y `effects: read-only`
  se **verifica contra `Ê`**: si la orden escribe, o si es **opaca**, la concesión no aplica. Lo
  que impide que sea un agujero no es un campo que alguien deba comprobar: la concesión vive en
  `.harness/policy.json`, que la política protege, así que un agente no puede concederse
  privilegio a sí mismo.
- **El informe de sesión anuncia las concesiones vigentes** para ese rol en esa máquina. Sin eso
  el mecanismo existe y nadie lo usa: un agente que no sabe que tiene una concesión se comporta
  como si no la tuviera, y el camino declarado se queda sin usar mientras el atajo opaco sigue
  ahí. No se listan las caducadas ni las de otro host — prometer autoridad que no hay es lo peor
  que puede hacer un informe que se toma por cierto el resto de la sesión.
- **Dos reglas de monotonía nuevas**, porque `core/refinement.py` no se importa hasta que un campo
  declara la suya: `ACUMULA_MAPA` (unión clave a clave, para las capacidades — en negativo
  precisamente para que la unión sea la operación correcta) y `REDUCE_LISTA` (el hijo sólo retira
  registros enteros, por contenido canónico: comparar «anchura» entre concesiones exigiría decidir
  inclusión entre globs, que es lo que ADR-0014 evita).
- **`core.trust.RAIZ_NO_ACOTA`**, una excepción y sólo una. Con `REDUCE_LISTA` y la raíz del motor
  vacía, **ningún espacio podía declarar ninguna concesión nunca** — la misma trampa que ADR-0014
  documenta para `writable_paths`, escrita otra vez. La salida no es clasificar el campo como
  `PROPIO`, que dejaría a un proyecto aflojar lo que su cliente apretó: es reconocer que la raíz
  del motor **no es un cliente** y no puede enumerar las necesidades operativas de espacios que no
  conoce. Una prueba la fija en exactamente un campo para que no crezca en silencio, y la
  monotonía entre capas reales queda intacta.

Lo que **no** se afirma: `HARNESS_ROLE` es una variable de entorno, así que atenúa por rol
DECLARADO y no por principal criptográfico; `Ê` sigue incompleto (`tar`, `python3 -c`); la
contención de directorios es de un nivel (medido: 0,08 ms una lectura simple, 2,94 ms listando 43
entradas); y el entorno se sigue heredando entero, que es la Capa 4 y está propuesta sin código.
Diseño completo, alternativas descartadas y tradeoffs: ADR-0016.

**Corregido — nombres de producto y un inventario de credenciales en un repositorio público**
(2026-09-25)

Una retractación, y de las que importan. Al añadir `secret_env_deny` metí en la lista de fábrica
**once nombres concretos de servicios** —los proveedores de nube y de modelos más habituales— y,
en un comentario de `core/policy.py`, el inventario de qué credenciales había en la máquina donde
lo medí, **incluida una con el nombre de un cliente**. Se empujó a un repositorio público.

No se expuso ningún valor. Se expuso el **mapa**: de qué servicios hay credenciales y en qué
máquina. Para alguien hostil eso es casi tan útil, y en un producto de gobierno la asimetría es
inaceptable — el control estaría publicando parte de lo que existe para proteger. `AGENTS.md` ya
lo prohibía en prosa desde el principio.

- **La lista pasa a ser puramente estructural** (`*_KEY`, `*_TOKEN`, `*_SECRET`, `*_PASSWORD`…):
  13 patrones de forma en vez de 28 con nombres dentro. **No pierde cobertura**, comprobado uno a
  uno: los once nombres ya los cubría un patrón. Y gana — el enfoque estructural alcanza servicios
  que no existían al escribirlo, que es justo lo que una lista de marcas no puede hacer, porque
  envejece en cuanto alguien contrata un proveedor nuevo. Medido: `*_KEY` no añade **ni un** falso
  positivo sobre un entorno real de 70 variables.
- **Control nuevo en el preflight: `nombres-de-producto`.** La regla existía en prosa y no la
  comprobaba nada sobre el código — el control de datos personales miraba rutas y correos. Un
  control que depende de que quien escribe se acuerde no es un control. Busca
  `<MARCA>_…_<SUFIJO_DE_CREDENCIAL>` sobre el árbol rastreado, con cuatro ficheros declarados
  legítimos y su motivo (`core/provider.py` existe para reconocer esas variables; sin nombrarlas
  no hay nada que reconocer).
- **Por qué ese patrón y no «cualquier mención de una marca»:** la primera versión del control
  marcaba cualquier aparición y dio **28 ficheros** —`gemini` es un runtime soportado y se nombra
  en todas partes, con razón—. 28 hallazgos sobre 0 defectos es la definición de un control que
  se desactiva en una semana. Afinado al defecto que de verdad hubo: **5 ficheros, y uno era el
  mío**.
- Los ejemplos de comentarios y pruebas usan ahora una forma inventada (`MI_SERVICIO_API_KEY`),
  que es lo que `AGENTS.md` prescribe para todo lo demás.

**Lo que esto NO deshace:** los nombres están en el historial publicado de `f045aa4`. Reescribir
historia publicada exige `git push --force`, que la política de este espacio rechaza; queda como
decisión de una persona, con la alternativa de rotar lo que se nombró.

**Añadido — la credencial que vive en una variable, no en un fichero** (2026-09-25)

Medido en el entorno de una sesión gobernada real: **70 variables y 7 con forma de credencial**, todas legibles con un `printenv`. El fichero `.env` vigilado y el mismo secreto en
`$MI_SERVICIO_API_KEY`, libre.

- **`secret_env_deny`** (`ACUMULA`) compara el **nombre** de la variable, nunca el valor: mirar el
  valor de cada una para decidir si es un secreto obligaría a leer todos los secretos para
  protegerlos. Se consulta en el MISMO canal de lectura que las rutas, porque
  `printenv MI_SERVICIO_API_KEY` y `cat .env` son la misma pregunta por dos caminos.
- **La vía a granel, que es la fácil.** `env`, `printenv`, `set` no declaran ninguna lectura
  —`efectos("env").lecturas == set()`, no hay argumento que derivar— así que se enumeran. Sólo se
  pregunta si el entorno tiene de verdad alguna variable con forma de credencial: en una máquina
  limpia `env` es inofensivo y preguntarlo sería ruido. `env FOO=1 orden` no es un volcado. Y
  `env > /tmp/claude-x/todo` es `deny`: la redirección rompía la comprobación de «sólo banderas»
  y salía `allow`, que era el volcado del entorno entero a un fichero que la política abre.
- **La curación de la lista ES el trabajo.** Un sondeo con `SESSION|AUTH|KEY` marcaba
  `SSH_AUTH_SOCK` —la ruta de un socket, y quitarla rompe el agente de ssh—, `TERM_SESSION_ID` y
  `HARNESS_SESSION`, que es de refuto. Un detector que marca lo normal enseña a ignorarlo, y
  entonces deja de proteger de lo que sí.

**Corregido en ADR-0016 — una pieza que yo mismo propuse y NO es implementable** (2026-09-25)

El ADR proponía «`${secreto:NOMBRE}` resuelto en el punto de ejecución». No se puede hacer aquí, y
no por coste: el contrato del guardián es `{allow, deny, ask}` en los seis runtimes
(`core/guard.py:17-23`) y un gancho `PreToolUse` **no reescribe la orden**. refuto es un monitor
en el canal de órdenes, no un ejecutor, así que no hay punto donde sustituir. Fue un error de
frontera: describí una capacidad de un ejecutor en el documento de un monitor. Lo que sí controla
refuto es el entorno que ENTREGA —`core/session.py` lanza al agente con `env=`— y eso queda
propuesto, porque retirar una variable puede romper una sesión que la necesita y ese riesgo lo
decide quien opera el espacio.

**Añadido — `scripts/preflight.py`, un solo sitio donde consta qué hay que cumplir** (2026-09-25)

- **13 controles con el vocabulario de seis estados** y la regla que los ordena: **una
  herramienta ausente da `BLOCKED`, nunca `PASS`**. No es teoría — el 2026-09-24 se midió
  `G-SECURITY` aprobando con `trivy` caído. Emite el sobre `harness.envelope/v1` con `--json`,
  así que CI y un agente lo leen sin caso especial, y el código de salida lo deriva el estado.
- **`BLOQUEA` frente a `INFORMA`, y la diferencia se declara.** `refuto verify` está en
  `INFORMA` porque sus dos puertas en rojo son deuda del proyecto y no de un cambio concreto: un
  preflight que nace en rojo se desactiva con `--no-verify`, y entonces no protege de nada.
- **`--excepto CONTROL` declara lo que no cubrió** en vez de castigarlo. La primera versión tenía
  un `--rapido` que omitía la suite y devolvía `BLOCKED` a propósito; el instinto era correcto y
  la herramienta equivocada, porque en CI la suite la ejecuta otro trabajo y castigar la omisión
  obligaba a duplicar ~200 s o a no usar el guion en CI. Lo omitido viaja en `payload.skipped` y
  en un `next`.
- **Si falta una herramienta, el paso siguiente es INSTALARLA.** Decía «`ruff` no está en el
  PATH» y proponía `ruff check .` — la orden que acababa de fallar. Ahora propone
  `brew install ruff` con turno `persona`. Es la misma regla que el sobre aplica con `next`,
  aplicada al propio preflight.
- **El gancho `pre-push` lo ejecuta.** Antes hacía **una** cosa —impedir un empujón a `main`— y
  no comprobaba nada, así que «pasó el preflight» no significaba nada y lo primero que se caía
  era el runner, con el commit ya publicado. Se omite con `HARNESS_SIN_PREFLIGHT=1`, explícito
  por el mismo motivo que `--no-verify`.
- **Trabajo `calidad` en CI**, que ejecuta **el mismo guion** con `ruff`, `bandit`, `actionlint`
  y `gitleaks` de versión anclada. Nació porque `check_wiring.py` se puso en rojo al añadir el
  preflight —«un guion que existe y que CI no ejecuta es una comprobación que nadie corre»—, que
  es exactamente lo que esa puerta existe para hacer.
- **Corregido en el gancho una afirmación que dejó de ser cierta**: decía que la protección de
  rama no estaba disponible, con su medición de HTTP 403 del 2026-09-23. La medición sigue siendo
  cierta y ya no describe la situación — el repositorio pasó a público el 2026-09-25 y las reglas
  de rama sí están disponibles. Se declara, porque es mejor que el gancho: no se salta con
  `--no-verify`.

**Añadido — criterio de análisis estático, medido antes de elegirlo** (2026-09-25)

- **`ruff` en `pyproject.toml`**, con `select = ["F", "E9", "B904", "B905"]` y el motivo de cada
  exclusión. Medido sobre este árbol: `F,E9` → 0 · `F,E4,E7,E9` → 45 · `F,E,W` → **3.890**. Se
  elige el conjunto que está verde de verdad y señala defectos, no estilo: un criterio que nace
  con 3.890 hallazgos no se arregla, se desactiva. `E702` y `E741` quedan fuera porque el punto y
  coma y los nombres cortos son el estilo compacto deliberado de este código.
- **49 defectos reales corregidos** que ese criterio encontró: 39 importaciones sin usar, 6
  f-strings sin interpolación, 3 variables locales muertas, 1 redefinición. Más `B904` (perdía el
  encadenado de excepciones en `core/refinement.py`) y `B905` (un `zip` sin `strict` en
  `core/session.py`, donde las dos secuencias ya se habían comprobado del mismo largo).
- **`bandit` con seis supresiones declaradas, cada una con su motivo.** Sin ellas daba **70
  hallazgos y cero defectos reales**: 61 de la familia `subprocess` —que es literalmente el
  trabajo de refuto—, 5 de `B105` disparando sobre `PASS = "PASS"` y sobre los **nombres** de
  variables de entorno, y 2 de `B108` sobre `/tmp/claude-*/**`, que es un patrón de política. Con
  las supresiones queda en 0 y sirve para lo que venga después.
- **Endurecido el parseo de XML que recibe entrada ajena.** `bandit` señaló `B314` en
  `scripts/check_diagram_assurance.py`, que parsea ficheros del disco — y en CI esos ficheros
  llegan dentro de un PR, es decir entrada no confiable en un repositorio público.
  `xml.etree.ElementTree` no resuelve entidades externas (XXE no aplica) pero sí expande
  entidades internas, que agotan memoria con un fichero de pocos kilobytes. Se rechaza `DOCTYPE`
  y `ENTITY` **antes** de parsear: mirarlo después sería mirarlo después del daño. Los dos avisos
  del generador se declaran `# nosec` con su motivo — parsea lo que él mismo acaba de generar.
- **Comprobador de datos personales**, que aplica la regla de `AGENTS.md` al árbol rastreado. Era
  una regla escrita y sin nada que la comprobara, y el repositorio pasó a público. Su lista de
  excepciones está **vacía y medida**. La primera versión incluía `/home/…` y marcó dos ficheros
  de prueba cuyas rutas son `/home/persona/Documentos` — exactamente los marcadores genéricos que
  la regla **prescribe**; un detector que marca el cumplimiento de la norma enseña a ignorarlo.

**Añadido — `refuto mcp-serve`, refuto como servidor MCP stdio** (2026-09-25)

- **Siete herramientas de sólo lectura** (`core/mcp_server.py`): `refuto_doctor`,
  `refuto_status`, `refuto_verify`, `refuto_probe`, `refuto_mcp_check`, `refuto_inventory`,
  `refuto_upgrade_plan`. Cada una devuelve el sobre `harness.envelope/v1` en
  `structuredContent` y un resumen legible en `content`. No reimplementa nada: invoca
  `refuto.main(argv + ["--json"])`, así que si `verify` cambia su veredicto, esta boca lo dice
  al día siguiente sin tocar el archivo. Es el motivo de haber construido el sobre primero.
- **Tres cosas que esta superficie no hace, y son contrato probado**
  (`tests/adversarial/test_mcp_server.py`, 23 pruebas): no ejecuta órdenes arbitrarias —el
  `argv` sale de una tabla fija y el modelo sólo aporta una ruta y booleanos validados, sin
  concatenación de cadenas en ninguna parte—; no escribe lo que gobierna —ni `--apply`, ni
  `--force`, ni `wire`/`unwire`, ni `install`; `upgrade` se expone sólo como plan—; y no gasta
  dinero —`--deep` no se expone, porque el sondeo profundo envía un prompt de pago cuyo coste no
  está medido—. La última red comprueba el `argv` **completo**, no los argumentos de entrada: si
  alguien añade mañana una entrada con una bandera de escritura, se para ahí.
- **`isError` es del protocolo, no del veredicto.** Un `verify` que devuelve `FAIL` es una llamada
  que funcionó e informa de que el espacio no cumple; marcarla `isError` haría que el cliente la
  tratara como fallo del servidor y, según el cliente, la reintentara o la ocultara. El veredicto
  viaja en `structuredContent.status`, que tiene seis valores porque dos no bastan.
- **Habla las dos revisiones**: `server/discover` (2026-07-28, con `supportedVersions` y la
  identidad en `_meta`) y `initialize` (2025-06-18). La primera versión emitió
  `protocolVersions` y un `serverInfo` suelto: el cliente de refuto lo alcanzaba y listaba las
  siete herramientas, y devolvía `protocol_versions: []` y `server_info: {}` — un servidor que
  responde y del que no se puede afirmar qué revisión habla. Se corrigió contra
  `docs/research/mcp.md`. **El cliente propio de refuto lo interroga en la suite**, que es lo que
  convierte esa simetría en una prueba y no en una coincidencia.
- **No se cae por una línea ilegible.** Un servidor que muere ante el primer mensaje malo obliga
  al cliente a distinguir «se cerró» de «no entendió», y no puede: lo que ve es un descriptor
  cerrado. Se responde el error y se sigue escuchando.
- **stdout es sólo protocolo**, y el informe humano no se vuelca al log en cada llamada: 35
  líneas por invocación de `doctor` es ruido en un canal que los clientes MCP muestran como log
  del servidor. Se conserva y viaja **dentro del error** cuando la llamada falla, que es cuando
  es lo único que explica la causa.

**Corregido — la procedencia de toda la evidencia declaraba la versión equivocada** (2026-09-25)

`core/model.py` llevaba `VERSION = "0.2.0"` a fuego mientras el fichero `VERSION` decía `0.3.0`.
Dos fuentes para el mismo hecho, y la que se separó sin avisar era la que **firma toda la
evidencia**: `provenance()` la pone en `harness_version`. Comprobado en un artefacto real,
`.harness/evidence/ver_*.json` → `harness_version: 0.2.0` con el motor en `0.3.0`. Para un
producto cuya tesis es que la evidencia se puede falsar no es cosmético: es la cifra con la que
alguien reproduciría la medición, y apuntaba al sitio equivocado — y `refuto upgrade` ya leía el
fichero, de modo que la herramienta sabía la versión correcta y la escribía mal. Ahora se deriva
del fichero, con `importlib.metadata` como respaldo cuando va instalada como paquete, y
`desconocida` si no se puede leer: una procedencia que miente es peor que una que se declara
ausente, porque la segunda se nota. Fijado en `tests/contract/test_result_contract.py`.

**Corregido — `pip install .` ensuciaba el índice de git** (2026-09-25)

`.gitignore` sólo excluía `__pycache__/`, así que `build/` (936 KB) y `refuto.egg-info/` (28 KB)
quedaban listos para colarse en el siguiente commit de cualquiera que ejecutara `pip install .` o
`python -m build` — que `pyproject.toml` invita a hacer. Se descubrió midiendo justo eso.

**Corregido — códigos de salida que afirmaban lo que no constaba** (2026-09-24)

- **`refuto mcp` devolvía 1 con `NOT_APPLICABLE`**, es decir «algo está mal», para un espacio que
  legítimamente no declara MCP — mientras la propia puerta dice «no es un aprobado: es que la
  puerta no tiene sujeto aquí». Ahora lo proyecta la tabla.
- **`refuto verify` con cero puertas ejecutadas salía con 0.** Un ámbito vacío aprobando, que es
  lo que este programa existe para no hacer; la regla estaba escrita para las suites y no se
  aplicaba a la verificación. Igual en `refuto probe`, donde `all(...)` sobre una lista vacía
  daba `True` y la sonda salía con 0 sin haber medido nada.
- **`refuto upgrade` en seco salía con 0**, indistinguible de «al día». Ahora `BLOCKED` cuando
  queda trabajo.
- **`refuto status` con evidencia ilegible salía con 0.** Ahí `status` no informa de un estado:
  declara que no lo sabe. Ahora `INCONCLUSIVE`. En todo lo demás conserva `PASS`, porque cambiarlo
  rompería a quien encadena `refuto status && …`; lo pendiente viaja en `next`.
- **Tres instrucciones para el mismo hueco.** Ante un lock ausente, `doctor` decía
  `refuto init`, la puerta G-LOCK decía `refuto lock init` y el índice de la ayuda omitía `init`.
  Ahora el remedio sale de **una** tabla, que alimenta a la vez el texto humano y `next` — y por
  tanto no pueden divergir. Además dice de quién es el turno: anclar un origen inmutable es acto
  de persona, no una orden que se lance sola.

**Corregido — actualizar dejaba la mitad sin actualizar** (2026-09-24)

- **`upgrade --apply` sólo regeneraba el lanzador de Claude.** Un espacio cableado para
  Antigravity o para Kiro salía con punteros al motor viejo y el mensaje decía que se había
  actualizado. Ahora se regeneran todos los runtimes que el espacio tenga cableados.
- **La deriva de la norma no se medía, y la conclusión obvia era falsa.** `upgrade` no toca la
  política por diseño, de donde parecía seguirse que ninguna corrección de la norma base llega a
  un espacio instalado. **Falso en la mitad que importa**, medido: `Policy.load` compone toda
  política con la raíz del motor y `protected_paths` ACUMULA, así que una protección NUEVA se
  propaga sola, sin `upgrade` y aunque el fichero del espacio no la declare. Lo que no se propaga
  es la EXCEPCIÓN —`writable_paths` es `REDUCE` y manda la lista del hijo—, de modo que un espacio
  que declaró `.harness/memory/**` deja a sus repositorios hijos sin memoria de agente **y no se
  entera**: no es un agujero, es más estricto, y por eso ninguna puerta lo señalaba. Ahora
  `_deriva_de_norma` lo mide y `upgrade` lo nombra con su turno. Las dos mitades quedan fijadas
  por separado en `tests/selftest/test_propagacion_de_norma.py`; juntarlas en una sola afirmación
  es exactamente el error que se cometió al razonarlo sin medirlo.

**Corregido — lo que salió de auditar un espacio multi-repo real** (2026-09-24)

Los cinco defectos de abajo se midieron en un mismo espacio gobernado cuya raíz no es
repositorio y cuyos dos hijos sí. El síntoma de partida era «el arnés sólo deja trabajar en
`/tmp`»; ninguno de los cinco era eso, y los cinco eran reales.

- **Las protecciones sólo cubrían la RAÍZ.** `DEFAULT_PROTECTED` estaba anclado al primer nivel,
  así que en un espacio multi-repo el agente podía reescribir el guardián, la política y la
  evidencia de cada hijo:

      Write  .harness/bin/guard                     →  deny   («.harness/**»)
      Write  repo-hijo/.harness/bin/guard           →  ALLOW

  Ahora todas llevan `**/`, que cubre la raíz Y cualquier profundidad. No son patrones nuevos:
  es el alcance corregido de los que ya había. El dueño de ese espacio había parcheado la norma
  base a mano para tapar el agujero — que un espacio tenga que hacerlo significa que el agujero
  era de la norma base.
- **La excepción no acompañaba a la protección, y no se podía arreglar desde el espacio.**
  `protected_paths` ACUMULA y `writable_paths` REDUCE: cada protección que cubra más profundidad
  que su excepción produce una denegación colateral **irreparable**, porque añadir la excepción
  levanta `HerenciaIrresoluble` y un guardián que no carga deniega todo. Medido: los repositorios
  hijos quedaban sin memoria de agente. `DEFAULT_WRITABLE` pasa a `**/.harness/memory/**`, y las
  dos listas se mueven juntas por contrato (`tests/unit/test_policy.py`).
- **`REDUCE` comparaba cadenas, no cobertura** (`core/refinement.py`). Corregir la norma base
  dejaba ungobernable **todo espacio ya instalado**, porque el instalador escribía el valor
  anterior y pasaba a leerse como «el hijo añade una entrada que el padre no tiene». Ahora la
  inclusión se demuestra (`_cubre`): `X ⊂ **/X` es estrechar, y la dirección contraria sigue
  siendo violación. Ante la duda se responde «no cubre», que es el lado seguro. El efectivo pasa
  de la intersección a la lista del hijo — para toda política que ya cumplía, el mismo resultado.
- **El guardián rechazaba la prosa que MENCIONA una orden denegada.** `_segmentos` extraía
  órdenes de `$(…)` y de acentos invertidos sobre el cuerpo de un documento aquí, que el shell
  **no expande**. Un agente que documentaba en markdown la frontera de lo que NO había ejecutado
  se bloqueaba a sí mismo:

      cat > 00_AUTHORIZATION.md <<'EOF'
      `adb root`, fastboot, flashing, `dd`, escritura de particiones…
      EOF
                                  →  deny  («dd:*»)

  Medido también con `` `sudo` `` y con `` `rm -rf /` ``, que además salía como
  «fuera-del-espacio» porque `core.effects` leía el `/` del texto como destino real. Ya le había
  pasado a `_partir` con las comillas —lo cuenta su docstring— y se arregló sólo para comillas.
  Ahora `_sin_cuerpos_citados` descarta el cuerpo de `<<'EOF'` y `<<"EOF"`; `<<EOF` sin citar SÍ
  expande y se sigue analizando, y la línea del operador se conserva siempre, así que la
  redirección se sigue juzgando. Un control que salta con el TEXTO y no con la ACCIÓN se rodea:
  el rodeo medido fue dejar de usar el shell para escribir, y entonces el canal deja de mirarse.
- **Una política mínima legítima no cargaba.** `{"schema": "harness.policy/v1", "name": "x",
  "version": "1"}` —la forma natural de decir «acepto la norma base»— levantaba
  `PoliticaIlegible` hablando de «la política de OTRO programa» y enumerando cero campos ajenos,
  y el guardián denegaba todo. Incoherente con `{}`, que sí valía. Ahora un documento que declara
  NUESTRO esquema y ninguna clave ajena es una política mínima; con una sola clave ajena presente
  el control sigue cazando el caso real que lo motivó (nueve secciones de otro contrato).
- **Denegar sin nombrar la alternativa desvía en vez de proteger.** El mensaje único acusaba de
  «mover la puerta» también al agente que CREA un fichero nuevo dentro de un nombre reservado.
  Caso medido: un espacio cuyo entregable era un dossier llamado `evidence/` —la palabra que
  refuto reserva para el diario que lo juzga, contrato opuesto— se llevó 9,2 GB y 197 ficheros a
  `/tmp`, fuera de git y en un directorio que el sistema borra a los 3 días. Nunca intentó
  escribir dentro del espacio: no hubo denegación que lo empujara, sólo un nombre reservado y
  ninguna indicación de que renombrar era la salida. Ahora se distingue editar el juez de
  colisionar con su nombre, y el segundo mensaje dice qué hacer.

**Corregido**

- **La herencia no llegaba al guardián.** `refuto policy refine` resolvía `extends`;
  `Policy.load()` —lo que ejecuta el guardián— llamaba a `from_dict()` y no. Medido contra el
  guardián real: un proyecto que heredaba una orden denegada por su cliente obtenía
  `permissionDecision: "allow"`. La etiqueta «IMPLEMENTADO» en el documento de arquitectura era
  el defecto: cerraba el gate con documentación.
- **`ACUMULA` exigía repetición y detectaba mal.** La primera versión obligaba al hijo a repetir
  cada entrada del padre so pena de «retirarla» — justo la repetición que la herencia existe
  para eliminar. Con la unión **no hay sintaxis para retirar**: no se puede violar lo que no se
  puede decir, y eso es más fuerte que detectarlo.
- **`default_modes` estaba clasificado `PROPIO`** («no es seguridad sino interacción»). Falsado
  midiendo: `adapters/claude.py` lo compila a `permissions.defaultMode`, así que un hijo podía
  pasar de `ask` a `bypassPermissions`. Reclasificado a `MODO`. **No** está comprobado que
  `bypassPermissions` anule el gancho `PreToolUse`: eso es comportamiento de Claude Code y aquí
  está `NOT_RUN`.
- **`ENDURECE` se burlaba por omisión.** El padre no escribía `block_secret_content` (de fábrica
  `true`) y el hijo lo ponía a `false`: la cadena resolvía **sin violación** y la detección de
  secretos quedaba apagada. El refinamiento comparaba documentos crudos en vez de lo que el
  padre **aplica**.
- **`init --extends` resolvía la ruta relativa contra el directorio actual** y la guardaba
  relativa al directorio del hijo. Con `--workspace` —la forma de dar de alta un espacio ajeno,
  donde el directorio actual ni pertenece al árbol— la forma relativa fallaba siempre y sólo
  servía la absoluta, justo la que no sobrevive a mover ni clonar el árbol. Falló cerrado, pero
  su mensaje mandaba a materializar la capa base, que no era el problema. Medido el 2026-09-23.
- **La huella de ejecución era ciega al padre.** `core/run.py::fingerprint` digería sólo el
  fichero del hijo: el cliente podía cambiar entero y `compare_fingerprint` decía que el entorno
  seguía igual. **La reanudación afirmaba reproducibilidad sobre una política distinta.**
- **La identidad vivía en estado mutable de módulo.** Con dos espacios resueltos en el mismo
  proceso —lo que hace `refuto verify`— la segunda pisaba a la primera, y un evento podía citar
  la política de otro espacio.
- **La sonda medía bytecode rancio.** Python invalida un `.pyc` por `(mtime, tamaño)`; dos
  mutaciones del mismo tamaño en el mismo segundo servían el bytecode de la anterior, así que una
  mutación podía atribuirse a otra. Aislado con `PYTHONPYCACHEPREFIX`. Y un `finally` no corre
  tras un `SIGKILL`: ahora hay diario en disco con reparación al arrancar, que se disparó sobre
  un huérfano real.
- **El corredor ignoraba el tercer cubo.** `bad = failures + errors` omitía
  `unexpectedSuccesses`, que `wasSuccessful()` sí consulta: el día que se arreglaba un defecto
  marcado `@expectedFailure`, la corrida salía verde y esa prueba dejaba de comprobar nada.
- **`G-SECURITY` atribuía al espacio los hallazgos del repositorio padre** (`gitleaks detect`
  recorre el historial y asciende), **la captura del código de salida en CI nunca ocurría**
  (`set -uo pipefail` no desactiva `-e`) y **el control de cadena de suministro fallaba por un
  falso positivo suyo**.

**Medido** — `python3 refuto.py selftest` → **580/580, 1 omitida** (sólo Windows), 268 s.
2026-09-23, macOS arm64 (Darwin 25.4.0), Python 3.14.6. Eran 478 en `0.3.0`. Reparto: unit 409 ·
contract 26 · selftest 72 · adversarial 73, contado con `ast` sobre métodos de clase —
`grep -rc "def test_"` da 581 porque recoge uno que vive dentro de una cadena.
`scripts/check_stdlib_only.py`, `check_schemas.py`, `check_wiring.py` y `check_citas.py`
(30 citas) salen con `0`.

**Conocido, declarado y no cerrado**

- **`policy wire --repos` colapsa la tercera capa.** El guardián instalado fija `--workspace` al
  espacio que lo aloja y `core/guard.py` no asciende, así que el `policy.json` de un repositorio
  no se lee jamás. Correcto para dos capas; para tres falta que el guardián ascienda desde el
  directorio real. `FAIL`, medido el 2026-09-23.
- **No hay norma en disco.** La capa 1 vive como constantes en `core/policy.py`; mientras no
  exista `policies/base.json`, la cima de toda cadena real es el cliente y **nadie vigila lo que
  la cima retira**.
- **`extends` no comprueba dónde vive el padre.** Una ruta absoluta o un enlace simbólico
  resuelven a cualquier sitio del disco. Explotarlo exige escribir el `policy.json` del hijo, que
  está protegido: es defensa en profundidad, no una escalada. Declarado en
  `tests/adversarial/test_violaciones_refinamiento.py`, con una prueba que fija el comportamiento
  actual para que cerrarlo obligue a decidirlo a conciencia.
- Herencia de **manifiesto**, resolución del padre **por nombre** contra el censo, y segunda
  máquina: `NOT_RUN`. Cuatro puertas devuelven `BLOCKED` para ámbito vacío y `G-SDD` devuelve
  `BLOCKED` donde el contrato dice `NOT_EXECUTABLE`; viven en `gates/**`, protegido, así que
  están escritos como propuesta y esperan a una persona.

## 0.3.0 — 2026-09-22 · primera versión publicable, ahora `refuto`

Esta versión **no añade capacidad**: la separa de la máquina y del historial en que nació.
Todo lo anterior se desarrolló en privado; aquí empieza el historial público.

**Cambiado**

- **El producto se llama `refuto`.** El punto de entrada es `refuto.py` y el envoltorio
  `bin/refuto`. **No** cambian el directorio `.harness/` de cada espacio, las variables
  `HARNESS_*` ni los esquemas `harness.*/v1`: son formato de datos compartido con espacios ya
  instalados, y renombrarlos rompería sin mejorar nada.
- **Sexto runtime: Google Antigravity.** Dialecto propio del guardián (`core/antigravity.py`,
  contrato leído de la documentación embebida en su binario 2.15.1), cableado en
  `.agents/hooks.json` y el informe de sesión inyectado por `PreInvocation`, que es su
  equivalente del prompt de sistema. Motivo: el 2026-09-21 un agente de otro proveedor trabajó
  en un espacio gobernado sin ningún control, y no por carencia del producto, sino porque el
  cableado sólo cubría Claude Code y Kiro.

**Corregido — aprobados vacuos del propio motor** (cada uno con la prueba que falla antes)

- Una suite que ejecutaba **0 pruebas** salía con 0.
- `G-MCP` sin servidores devolvía `PASS`; ahora `NOT_APPLICABLE`, que no aprueba.
- `chat` abría sin guardián en 3 de 4 runtimes mientras la documentación afirmaba lo contrario;
  ahora bloquea, con excepción declarable.
- Los errores de uso de argparse salían con 2 y se confundían con «bloqueado»; ahora 64.
- Quinto estado `NOT_APPLICABLE` en el tipo `Result`, y **exige motivo**.

**Corregido — lo que ataba el producto a una máquina y a unos clientes**

- El aviso de sesión con privilegios mandaba reabrir con un lanzador privado inexistente fuera
  de la máquina del autor; ahora usa `HARNESS_SESSION`, que exporta el propio `refuto chat`.
- La puerta `G-SDD` ejecutaba un núcleo privado con sólo encontrar un fichero con ese nombre;
  ahora es una integración **declarada** y, sin declaración, `NOT_APPLICABLE` sin ejecutar nada.
- La búsqueda de especificaciones estaba escrita para la estructura de un espacio concreto;
  ahora es declarable, con esa convención como uno de los valores por omisión.
- El `.gitignore` que el producto genera ignoraba 2 rutas de estado local y ahora ignora 7. Por
  ese hueco llegaron a versionarse notas internas sobre un cliente en este mismo repositorio.

**Cerrado — deuda que se arrastraba como propuesta**

- Las 6 llamadas de `gates/**` que decodificaban con la codificación del sistema pasan por
  `core/proc.py`. Vivían en un parche (`docs/remediation/gates-portabilidad.patch`) porque en el
  espacio del autor `gates/**` está protegido y un agente no edita al juez que lo evalúa. El
  parche se retiró: al cambiar esos ficheros por otras razones, **había dejado de aplicar**, y un
  parche que no aplica es una promesa rota, no una deuda declarada.

**Añadido**

- `LICENSE` (Apache-2.0, texto canónico), `NOTICE`, `CODE_OF_CONDUCT.md`, `AI-DISCLOSURE.md`,
  `AGENTS.md` como fuente única de reglas para cualquier agente, `INSTALL.md`,
  `docs/estado-del-proyecto.md` y `pyproject.toml` sin dependencias.
- `experimental/`: diseño probado y **no conectado**, declarado como tal y verificado por
  `scripts/check_wiring.py`, que falla si algo vive ahí sin constar en su README.

**Medido** — `python3 refuto.py selftest` → **478/478, 1 omitida** (sólo Windows), 274 s,
2026-09-22, macOS arm64 (Darwin 25.4.0), Python 3.14.6. Reparto: unit 366 · contract 19 ·
selftest 66 · adversarial 27. `NOT_RUN`: Windows, Linux y Python 3.10.

### Incluido en 0.3.0 — el arranque dice lo que hace

**Corregido** (`core/session.py`; aplica a todo espacio que abra `refuto chat`)

- **El arranque se contradecía sobre el proveedor.** El aviso «esta sesión NO usará su
  suscripción» se emitía antes de decidir la limpieza y nunca se retractaba: con
  `--provider clean` salía junto a la línea verde que decía lo contrario. Ahora sólo se avisa si
  la redirección llega de verdad a la sesión. Lo mismo con una redirección **rota**
  (`ANTHROPIC_BASE_URL` sin esquema): el aviso «muere en el primer mensaje» salía aunque `auto` o
  `clean` la fueran a limpiar; ahora dice que está rota y que esta sesión la ignora.
- **Todas las sesiones se llamaban igual.** Con dos abiertas, el agente renombraba al azar. El
  nombre lleva ahora el espacio —`mi-espacio · sesión`, `mi-espacio · solution-architect`— y, con
  tarea, tres piezas: `mi-espacio · PROJ-12 · backend-engineer`.
- **Los árboles de trabajo contaban como especificaciones.** `*` de pathlib casa directorios
  ocultos y `*/*/` alcanzaba `.worktrees/<rama>/…`, así que un espacio con copias de trabajo
  anunciaba varias veces la misma especificación bajo nombres distintos. Siguen siendo candidatas
  cuando se pide una con `--spec`, porque una rama puede divergir y la guarda de ambigüedad debe
  verla.
- **`.harness/state/` entraba en git.** Las dos rutas de instalación escribían `.gitignore`
  distintos y ninguna corregía uno existente. `ensure_gitignore()` es la única vía, y abrir sesión
  la aplica: los espacios ya instalados convergen sin reinstalar. **Límite:** sólo corrige
  `.gitignore`; un `state/` ya versionado sigue versionado hasta
  `git rm -r --cached .harness/state`. **Límite mayor, abierto:** `ensure_gitignore` cubre
  `evidence/` y `state/` y **no** cubre `context/`, `memory/`, `backup/`, `bin/` ni
  `binding.json`, que quedan versionables por defecto.

**Añadido**

- **Aviso de sesiones concurrentes.** Si otra sesión gobernada está abierta sobre el mismo espacio
  (medido en la tabla de procesos, no en el diario), se dice con su pid: dos sesiones comparten
  árbol y lo que una mida la otra puede invalidarlo. La ruta se ancla al inicio de un argumento, y
  se excluye toda la ascendencia del proceso, no sólo el padre. Comprobado en macOS; en Linux,
  `NOT_RUN`.
- 10 pruebas de regresión, de las cuales 4 salen de intentar falsar las otras 6 y fallaban con el
  código previo.

**Estado de la suite en este punto** (`python3 refuto.py selftest`, 2026-09-22, macOS arm64
Darwin 25.4.0, Python 3.14.6 y 3.12): **478/478, 1 omitida** — la omitida sólo corre en Windows.
Reparto por suite (`grep -rc "def test_" tests/<suite>`): unit 366 · contract 19 · selftest 66 ·
adversarial 27.

### Incluido en 0.3.0 — portabilidad

`refuto` corría en macOS y en Linux. En Windows no fallaba a medias: **fallaba en la dirección
peligrosa**, dejando el espacio inoperante con un rastro de auditoría vacío.

**Lo que se midió, y dónde:** sobre la rama aislada de portabilidad, la suite pasó de **258/299**
a **326/326** en Windows. Al integrarla se ejecutó **en macOS**: las 27 pruebas de portabilidad
entran en el total. **En Linux y en Windows este árbol no se ha ejecutado nunca** (`NOT_RUN`): los
326/326 son de aquella rama, no de esto.

**Corregido**

- **`os.geteuid()` en el registro de cada decisión del guardián.** No existe en Windows: la
  excepción caía en el aviso de «auditoría interrumpida» y, como ese aviso hace salir con `2`,
  **toda** escritura quedaba bloqueada — también las que debían permitirse. El diario nunca
  llegaba a escribirse.
- **`os.killpg` y `signal.SIGKILL` al terminar la sonda.** Todo agente se declaraba
  `NOT_INSTALLED` con un `AttributeError` de por medio: un agente perfectamente instalado dado por
  ausente. Ahora el grupo se crea y se mata en el vocabulario de cada sistema
  (`setsid`/`killpg` · `CREATE_NEW_PROCESS_GROUP`/`taskkill /T`).
- **`subprocess(text=True)` decodificaba con la codificación del sistema.** En Windows, `cp1252`:
  la primera tilde de un mensaje del propio programa derribaba a quien lo leía. `G-POLICY` se caía
  leyendo el `stderr` del guardián, donde pone «AUDITORÍA».
- **`print()` de `✓`, `✗` y `⚠` sobre una consola `cp1252`.** `doctor` devolvía un `Traceback` en
  vez de un veredicto, y la respuesta estructurada del gancho moría antes de emitir el JSON.
- **El lanzador sólo existía como guion de `sh`,** y el gancho usaba `VAR=x orden`, que `cmd.exe`
  no ejecuta. Ahora se instalan los dos —`guard` y `guard.cmd`, con CRLF— y el gancho usa la
  sintaxis que ese sistema sabe ejecutar.
- **Los archivos generados heredaban el salto de línea del sistema.** Todo este proyecto compara
  por huella: un CRLF de más convertía «idéntico» en «deriva» y hacía fallar una puerta que no
  tenía nada que reprochar. Lo generado se escribe en LF; `guard.cmd` es la única excepción.
- **`core/trace.py` comparaba rutas con separadores nativos.** Con `tests\fixtures` no casaban las
  exclusiones, el juez indexaba sus propias fixtures y declaraba fantasmas los identificadores que
  ellas inventan a propósito: un `FAIL` en un proyecto impecable.
- **`scripts/check_wiring.py` declaraba desconectado el árbol entero** —81 falsos positivos— por la
  misma razón. Un verificador que grita tanto se aprende a ignorar.

**Añadido**

- `core/proc.py`: el único sitio del árbol que puede nombrar una primitiva POSIX. Donde el
  concepto no existe devuelve «no aplica» en vez de inventar un `0` que significaría «soy root».
- `tests/unit/test_portabilidad.py`: entre otras, un barrido que **falla si alguien vuelve a
  escribir `text=True` u `os.geteuid()` fuera de `core/proc.py`**.
- `.gitattributes`: el repositorio deja de depender del `core.autocrlf` de quien clona. Todo en
  LF, salvo `*.cmd` y `*.bat`, que exigen CRLF.
- **`bin/refuto` y `bin/refuto.cmd`: el comando que la documentación llevaba prometiendo.** La
  documentación escribía `refuto verify` y ese ejecutable no existía: la primera orden del manual
  respondía `command not found`. Los dos lanzadores se resuelven por su propia ubicación, así que
  funcionan invocados desde el espacio gobernado, que es donde se usan. Y llegó con modo `100644`,
  así que `./bin/refuto` respondía `permission denied`: lleva ahora el bit de ejecución, y dos
  pruebas lo comprueban.

**Retirado**

- **`docs/manual/`** entero: generaba un `.docx` con la marca personal del autor en los metadatos,
  sus capturas eran de un repositorio privado de cliente, y rehacer las figuras exigía un navegador
  externo —fuera de la regla de «sólo biblioteca estándar»—. Con él desaparece el `import docx`
  que hacía fallar `scripts/check_stdlib_only.py`: comprobado el 2026-09-22, ese guion devuelve
  ahora `✓ sólo biblioteca estándar`, `rc=0`.

## 0.2.2 — *sin publicar* · el agente sabe contra qué entorno trabaja

**No hay commit ni etiqueta de esta versión.** Lo que sigue describe el trabajo, no una entrega.

**Añadido**

- **`core/environments.py`** y `refuto environments|entornos show|check` — el espacio declara sus
  entornos en `.harness/environments.json`, y el informe de sesión abre diciendo **cuál es el de
  trabajo**, con sus dominios, máquinas, servicios, plano de datos, cómo se llega y qué trampas
  tiene. Va antes que el inventario de código: es el marco con el que se lee cualquier sondeo
  posterior.
- **Se declara, no se descubre.** Un descubridor que elija «los dominios de este proyecto» por
  heurística puede apuntar a producción creyendo que es desarrollo. El archivo está bajo
  `.harness/`, protegido: lo escribe una persona; el agente sólo lo lee. Un agente que puede
  reapuntarse solo a otro entorno puede reapuntarse a producción.
- **`check` vuelve a sondear** y compara con lo declarado, porque una declaración con una fecha
  dentro se pudre en silencio. Con `--write` actualiza el sondeo y la fecha.
- **Tabla de cómo se lee un sondeo** en el informe. `401` y `403` significan **vivo y exigiendo
  credenciales**; sólo `503`, `521` y «sin DNS» son una caída.

**Corregido**

- **El sondeo medía la protección de bots, no el servicio.** `urllib` sin `User-Agent` propio
  recibe **403 de un CDN en todo**, y el primer `check` devolvió 403 en todos los dominios de un
  espacio —frontend vivo y servicio caído por igual—. Detectado en el acto porque `curl` daba 200
  sobre el mismo dominio, en la misma máquina y el mismo segundo. Se manda un `User-Agent`, y
  `verificar()` **avisa cuando todos los dominios coinciden**: un instrumento que puede fallar
  entero tiene que decirlo antes de que alguien firme el resultado.

**Por qué existe esta versión.** Una sesión concluyó que «nada de esta plataforma está sirviendo»
tras sondear los dominios de **producción** dando por hecho que eran los del entorno de trabajo.
Desarrollo usaba otra familia entera de nombres, y **la lista correcta estaba publicada** en la
cabecera `content-security-policy` que sirve la propia aplicación. No se perdió una sonda: se
firmó un diagnóstico de plataforma completo sobre el entorno equivocado.

## 0.2.1 — *sin publicar* · el informe habla del proyecto, y la memoria vuelve

Revisión del arranque de sesión y de los guardas, medida sobre el diario de decisiones de un
espacio real y privado (`policy/decision`, ~14 900 decisiones en una semana). Las cifras que
siguen son de **ese corpus**: describen lo que se encontró, no una propiedad del producto.

**Añadido**

- **`core/knowledge.py`** — qué ES el espacio, no sólo qué está prohibido en él. Inventaría
  componentes y tecnología del sistema de archivos, lee el registro de capacidades si el espacio
  mantiene uno, y separa siempre lo **medido** de lo **declarado**. Detecta el `.git` como
  fichero, así que ve los árboles de trabajo, que ninguna medición anterior contaba.
- **Recuperación de memoria en el informe** (`_memoria`). `core.memory` sabía guardar notas desde
  0.2.0 y **nada las traía de vuelta**: una nota que nadie recupera es un fichero, no una memoria.
- **`Policy.writable_paths`** — excepciones evaluadas ANTES de lo protegido. `.harness/**`
  protegía la evidencia y arrastraba la memoria, cuyo contrato es el contrario. En el corpus
  medido, `.harness/memory/` **no existía** tras una semana de uso, porque toda escritura que lo
  habría creado se rechazaba.
- **`Policy.external_write_allow`** — las únicas raíces escribibles fuera del espacio, declaradas
  una a una: la memoria del propio agente y su cuaderno de sesión. Todo lo demás fuera del árbol
  sigue siendo travesía de directorios.
- **`digest.classify`** — separa **prueba** (la cadena tiene forma de credencial emitida) de
  **indicio** (algo llamado `secret` recibe un valor). La prueba rechaza; el indicio lo decide una
  persona.

**Corregido**

- **El informe ya no recorta en silencio.** `protected_paths[:12]` y `command_deny[:6]` escondían
  al agente la mitad de las reglas que debía respetar. En el corpus medido, los rechazos caían
  sobre reglas que el agente **no podía ver** tanto como sobre las visibles: la mitad de los
  choques los causaba el recorte.
- **El detector de secretos ya no castiga al código que hace lo correcto.** La regla anterior
  rechazaba cualquier coincidencia, y producía bloqueos sobre módulos de backend perfectamente
  sanos: `let secret = std::env::var("JWT_SECRET")?`, `secret: process.env.JWT_SECRET` y
  `password: ${VAULT_PASSWORD}` son las formas **buenas** de no tener el secreto en el árbol.
  Ninguno de los secretos reales del diario lo detectó esa regla: los cazaron los patrones de
  forma.
- **`_matches_command` ya no corta a media palabra.** `dd:*` rechazaba `ddev` y `ddgr`. La frontera
  distingue ahora nombre de programa (`mkfs` → `mkfs.ext4` sí, `dd` → `ddev` no) de bandera corta
  (`rm -rf` → `rm -rfv` sí, porque las banderas se agrupan).

**Cambio de contrato**

- Un literal sospechoso sin forma de credencial pasa de `deny` a **`ask`**. No es una vía de
  escape: en un runtime sin respuesta estructurada el guardián sigue saliendo con 2 y la escritura
  no ocurre. La invariante que se sostiene es «ningún secreto entra al árbol **sin que alguien lo
  decida**», que es la que importaba; «todo termina en `deny`» no lo era.
  `tests/adversarial/test_attacks.py` lo comprueba con `≠ ALLOW` además de con el estado exacto.

## 0.2.0 — 2026-08-27 · plataforma operativa

De «algo que verifica» a un sistema que descubre, decide, conduce y demuestra.

**Añadido**

- **Descubrimiento** (`refuto discover`) del entorno, el origen y el repositorio, con confianza
  declarada y umbrales fijos. Una carpeta con el nombre adecuado no es un origen: un origen es algo
  con manifiesto válido cuyas huellas coinciden con sus archivos.
- **Vínculo** (`refuto bind`): la ambigüedad se pregunta una vez y se escribe, anclada al
  **commit**, no a la ruta.
- **Grafo de capacidades** con siete estados. `BLOCKED` describe lo que está instalado y no sirve
  — que no es `MISSING` ni `INSTALLED` a secas.
- **Cálculo de herramientas** por stack y por fase: `REQUIRED` · `RECOMMENDED` · `OPTIONAL` ·
  `NOT_APPLICABLE`. Propone instalación oficial; **nunca instala**, y nunca propone `curl | sh`.
- **22 roles de ingeniería** con contrato (`roles/registry.json`), en 9 grupos.
- **Enrutado por capacidad** (`core/routing.py`): se elige runtime por lo que sabe hacer, y entre
  los que cumplen gana el que deja **menos restricciones sin aplicar**. Toda decisión explica por
  qué eligió y por qué descartó.
- **Contexto de ejecución** (`refuto context`): 10 archivos + `context-report.md`, con una sección
  de *lo que no se sabe*.
- **Memoria en cinco capas** (`refuto memory`), separada de la evidencia.
- **Ciclo de vida de 13 fases** con criterio de entrada y de salida.
- **Motor de ejecución** (`refuto plan|run|resume|status`), en seco salvo `--execute`, con guardia
  de reanudación que compara la huella del entorno.
- **Cinco puertas nuevas**: `G-TRACE`, `G-SECURITY`, `G-PR`, `G-HUMAN`, `G-ROLES`. Total: trece.
- **Revisión humana como artefacto**: quien revisa no puede ser quien generó.

**Corregido**

- `Result` **rechaza construirse** como `PASS` con hallazgos. Hace imposible en las trece puertas a
  la vez el defecto que tenía `G-HUMAN`.
- El router prefería el runtime donde la política **no** se aplica; ahora la aplicabilidad manda.
- El fallback reelegía al agente que acababa de fallar.
- El descubrimiento tardaba 96 s sobre 244 repositorios; ahora 0,8 s, en dos fases. (Medido una
  sola vez, en macOS arm64, el 2026-08-27; no se repitió.)
- Acotar la puntuación antes de ordenar empataba 251 candidatos en 1.00.
- El tracer indexaba las fixtures del propio verificador.
- La raíz de búsqueda por defecto era sólo el directorio actual, y el origen puede vivir **al
  lado** del repositorio.
- `G-PR` contaba sólo lo confirmado y decía «0 archivos cambiados».
- `G-HUMAN` exigía las cinco revisiones del ciclo tras ejecutar una sola fase.

## 0.1.0 — 2026-08-27 · remediación

- Escalera de ejecutabilidad de cinco peldaños (`H-01`).
- Integridad referencial de MCP con `server/discover` y caída a `initialize` (`H-02`).
- Política canónica, un guardián y enganche en la ruta del CLI (`H-03`).
- Lock anclado por commit inmutable, verificado antes de escribirse (`H-06`).
- Puerta de deriva de la flota (`H-07`) y contrato de skills (`H-08`).
- Ocho puertas, cuatro estados, evidencia con procedencia.
- 112 pruebas en cuatro suites, medidas ese día.
