# Roadmap

## Fase 0 - Estudio y definición

- estudiar Django con foco en:
  - middleware
  - auth
  - admin
  - ORM
  - routers de DB
- estudiar `django-tenants` y `django-tenant-schemas`
- cerrar RFC base
- cerrar ADRs iniciales

## Fase 1 - Bootstrap del proyecto

- inicializar estructura Python con `uv`
- preparar `pyproject.toml`
- definir layout del paquete
- definir estrategia de testing

## Fase 2 - Core conceptual

- `Tenant`
- `TenantContext`
- `TenantResolver`
- `CompositeTenantResolver`
- `TenantStrategy`

## Fase 3 - Activación y contexto

- contexto public
- contexto tenant
- cleanup seguro
- observabilidad base

## Fase 4 - Admin tenant-aware

- custom `AdminSite`
- login con tenant opcional
- resolver por sesión
- switch global -> tenant
- permisos y auditoría

## Fase 5 - Estrategias de aislamiento

### v1 recomendada

- `schema` con PostgreSQL-first
- `database` con alias explícito por tenant y router Django-friendly

## Fase 6 - Adapter REST

- primer adapter: DRF
- abstraer el core para futuros adapters

## Fase 7 - Hardening

- tests de seguridad
- tests de concurrencia
- métricas y logs
- documentación de operación

## Decisiones que quedan abiertas

- forma exacta del modelo de usuario global
- forma exacta del modelo de usuario local
- si conviene un user model único con separaciones fuertes o dos flujos explícitos
- packaging definitivo del framework
- contrato exacto del adapter REST inicial
