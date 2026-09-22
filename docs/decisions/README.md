# Architecture Decision Records

| ADR | Decisión | Qué la haría cambiar |
|---|---|---|
| [0001](ADR-0001-protocolos-de-facto.md) | Adoptar MCP + ACP + `SKILL.md`, no inventar modelo canónico | que ACP se fragmente o lo retiren dos de los tres agentes que lo hablan |
| [0002](ADR-0002-solo-biblioteca-estandar.md) | Sólo biblioteca estándar de Python | necesitar criptografía de firma; sería dependencia opcional y su ausencia `BLOCKED` |
| [0003](ADR-0003-escalera-de-ejecutabilidad.md) | Cinco peldaños; `which` no es ninguno | que aparezca un handshake más barato que ACP `initialize` |
| [0004](ADR-0004-lock-antes-de-escribir.md) | Verificar antes de escribir; anclar por commit | nada razonable: la alternativa es una tautología |
| [0005](ADR-0005-cuatro-estados.md) | `PASS`/`FAIL`/`BLOCKED`/`NOT_EXECUTABLE` | ya está cambiando: faltan `NOT_RUN`, `INCONCLUSIVE` y `NOT_APPLICABLE`, que hoy se dicen todos con `BLOCKED` |
| [0006](ADR-0006-politica-unica-compilada.md) | Una política, N compilaciones, un guardián | que un runtime ofrezca aplicación de política verificable desde fuera |
| [0007](ADR-0007-puente-no-reescritura.md) | Envolver las puertas del verificador externo, no reescribirlas | que ese verificador deje de mantenerse, o que el contrato del puente pase a declararse en el manifiesto |
| [0008](ADR-0008-documentacion-generada.md) | Generar la matriz de compatibilidad | nada: una matriz escrita a mano miente en la dirección peligrosa |

Todos están fechados el 2026-08-27 salvo donde se diga otra cosa. Un ADR no caduca solo: si una
decisión ya no describe el código, lo que corresponde es una revisión fechada dentro del propio
ADR —como la que lleva el 0005—, no borrarla.
