# ADR 0004 - Superusuario global y usuarios locales por tenant

## Estado

Aprobado

## Contexto

El sistema necesita una capa global de operación y una capa local por tenant.

## Decisión

Habrá dos niveles de identidad:

- superusuarios/operadores globales en shared/public
- usuarios locales dentro del tenant

## Consecuencias

- separación fuerte entre control plane y data plane
- necesidad de diseñar cuidadosamente login tenant-aware
- necesidad probable de múltiples authentication backends
