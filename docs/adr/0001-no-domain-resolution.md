# ADR 0001 - No usar resolución por domain como estrategia principal

## Estado

Aprobado

## Contexto

Los frameworks clásicos de multitenancy en Django suelen resolver tenant por host/subdomain.

Para este proyecto, esa estrategia no es deseada como base principal.

## Decisión

La resolución primaria del tenant será por:

- header
- token claim
- sesión para admin

## Consecuencias

- mejor alineación con APIs y admin tenant-aware
- menos dependencia del routing DNS/http host
- necesidad de diseñar validaciones más fuertes entre identidad y tenant
