# RFC v0 - django-multitenant

## Estado

Draft

## Resumen

`django-multitenant` será un framework multitenant para Django con soporte híbrido para tenants por **schema** y por **database**, manteniendo una arquitectura nativa para Django y una separación explícita entre:

- **shared/public data**
- **tenant-local data**

El framework no usará resolución de tenant basada en domain como estrategia principal. En su lugar, priorizará:

- `header`
- `token claim`
- `session` para Django Admin

## Motivación

Los frameworks actuales del ecosistema Django suelen resolver uno de estos problemas, pero no ambos juntos:

- multitenancy por schema sobre PostgreSQL
- multitenancy por database
- integración razonable con admin y auth

Este proyecto apunta a una solución más pequeña y flexible, inspirada en Django y no en una plataforma completamente distinta.

## Objetivos

- soportar tenants `schema` y `database`
- permitir tablas shared/public y tablas tenant-local
- adaptar Django Admin para que sea tenant-aware
- soportar un **superusuario global** y **usuarios locales por tenant**
- diseñar un core desacoplado del framework REST
- mantener contratos claros para estrategias, resolvers y contexto

## No objetivos iniciales

- no resolver tenant por domain/subdomain como estrategia principal
- no soportar cambio de `database` a `schema` o viceversa después de crear el tenant
- no soportar todos los motores con capacidades idénticas
- no hacer una abstracción que esconda limitaciones reales del backend
- no acoplar el core a FastAPI o a un framework REST específico

## Modelo conceptual

### Shared/Public

Espacio donde viven entidades globales como:

- registro de tenants
- configuración global
- superusuarios globales
- auditoría global
- feature flags globales
- billing/control plane

### Tenant-local

Espacio donde viven entidades del tenant:

- usuarios locales
- permisos locales
- datos de negocio
- configuración interna

### TenantSharedModel

Base abstracta para modelos del dominio tenant que pueden ser:

- compartidos por todos los tenants, si `allowed_tenants` está vacío
- restringidos a una lista de tenants, si `allowed_tenants` tiene valores

Este contrato permite modelar SaaS con una sola abstracción de visibilidad por tenant.

## Tipos de aislamiento

### Schema tenant

- el tenant vive en un schema separado
- especialmente útil en motores con soporte fuerte de schemas, como PostgreSQL
- el switching debe ser explícito y seguro

### Database tenant

- el tenant vive en una base o conexión aislada
- es más portable entre motores
- aumenta complejidad operativa, pero mejora aislamiento
- el framework genera `connection_alias` automáticamente para que Django pueda resolver la conexión
- almacena la URL de conexión cifrada en `connection_string`
- puede almacenar una URL admin cifrada en `provisioning_connection_string` para crear/verificar la DB física

### Provisioning mode

- `auto`: el backend genera todos los campos estructurales
- `manual`: el operador envía los campos estructurales requeridos por el modo elegido

### metadata

`metadata` es un campo JSON extensible para información futura o variable.
No es autoritativo para las decisiones estructurales del framework.

### connection_string

URL de conexión cifrada para tenants database.

### provisioning_connection_string

URL admin cifrada para tenants database. Se usa para crear o verificar la DB física en el servidor destino.

### Zero-config rule

El framework genera automáticamente la configuración estructural del tenant a partir del `slug` y la estrategia seleccionada.

### Sandbox note

El bootstrap automático de conexiones no se ejecuta en el sandbox SQLite; está pensado para backends de base de datos reales.

### Zero-config status

El prototipo actual genera automáticamente `schema_name`, `connection_alias` y `connection_string` a partir del `slug`.

### API status

Existe una API nativa en `/api/tenants/` para crear, listar, obtener y borrar tenants.

## Decisión de diseño clave

El core será **agnóstico de estrategia**, pero no fingirá que todos los motores tienen las mismas capacidades.

Se seguirá la regla:

> **portable core, specialized backends**

## Resolución de tenant

### Estrategias soportadas

- `HeaderTenantResolver`
- `TokenTenantResolver`
- `SessionTenantResolver`

### Prioridad sugerida

#### API
1. token claim
2. header
3. validación cruzada si ambos están presentes

#### Admin
1. session

## Admin de Django

Se usará un solo `/admin/`, con dos modos de operación:

### Modo global

- login sin tenant seleccionado
- acceso solo a modelos shared/public
- orientado al superusuario global y operadores globales

### Modo tenant

- login con tenant seleccionado, o switch posterior desde modo global
- acceso a modelos tenant-local
- aplica contexto activo de tenant vía sesión

## Autenticación

### Global

- usuarios del sistema/plataforma
- viven en shared/public
- pueden operar en modo global
- pueden cambiar al contexto de un tenant con trazabilidad

### Tenant-local

- usuarios del tenant/organización
- viven dentro del espacio aislado del tenant
- deben autenticarse con tenant explícito

## Contratos base propuestos

- `TenantContext`
- `TenantResolver`
- `TenantStrategy`
- `TenantRegistry`
- `TenantActivationService`
- `TenantAuthService`
- `TenantSharedModel`

## Estado de implementación

Prototipo actual:

- `Tenant` con soft delete, auditoría y auto-generación de aislamiento
- `TenantMembership`, `TenantInvitation`, `TenantSetting`
- `TenantRouter`
- `TenantMiddleware`
- `SchemaStrategy`
- `DatabaseStrategy`
- auto-provision and registry management for database tenant aliases

## Regla sobre metadata

`metadata` es extensible pero no autoritativo. Los campos estructurales del contrato principal viven en campos explícitos.

## Observabilidad

Desde etapas tempranas se deben contemplar:

- logging estructurado con `tenant_id`, `scope`, `user_id`
- métricas tipo Prometheus

Métricas sugeridas:

- `tenant_resolution_total`
- `tenant_resolution_errors_total`
- `tenant_activation_total`
- `tenant_activation_errors_total`
- `admin_tenant_switch_total`
- `tenant_middleware_duration_seconds`

## Testing

### Unit tests

- resolución de tenant
- contexto activo
- validación de capacidades
- selección de estrategia
- login global y login tenant

### Integration tests

- request global vs request tenant
- admin global vs admin tenant
- switching schema/database
- aislamiento entre tenants

### Security tests

- spoofing de header
- conflicto entre token y header
- fuga de contexto entre requests
- acceso a modelos tenant sin contexto válido

## REST framework

El framework REST no debe definir el core.

Recomendación actual:

- **DRF como primer adapter**
- mantener el diseño listo para soportar Ninja en una fase posterior

## Referencias conceptuales

- Django 6 documentation sobre auth y admin
- `django-tenants` como referencia de separación entre `public` y `tenant-specific data`
- `django-tenant-schemas` como antecedente de estrategias alternativas por header/middleware
