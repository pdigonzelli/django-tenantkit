# ADR 0003 - El modo de aislamiento del tenant queda fijo al crearse

## Estado

Aprobado

## Contexto

Se evaluó permitir migrar un tenant entre `schema` y `database`.

## Decisión

El tenant define su `isolation_mode` al crearse y no podrá cambiarlo automáticamente como capacidad nativa del framework.

## Consecuencias

- simplifica operaciones, testing y soporte
- evita migraciones extremadamente complejas entre estrategias
- reduce ambigüedad en el diseño del core
