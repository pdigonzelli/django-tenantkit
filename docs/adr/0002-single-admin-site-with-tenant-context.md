# ADR 0002 - Un solo `/admin/` con contexto global o tenant

## Estado

Aprobado

## Contexto

Se evaluó usar múltiples admin sites o separar completamente admin global y admin tenant.

## Decisión

Se usará un solo `/admin/` con dos modos:

- global
- tenant

El tenant activo para admin se manejará por sesión.

## Consecuencias

- UX más simple
- mayor necesidad de controlar permisos y visibilidad por contexto
- obliga a diseñar con cuidado el login y el switch de tenant
