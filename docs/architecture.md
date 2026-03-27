# Arquitectura

## Principio general

La arquitectura del proyecto se apoya en cinco capas:

1. **Domain model**
2. **Tenant resolution**
3. **Tenant activation and isolation**
4. **Django integration**
5. **Adapters**

## 1. Domain model

Elementos principales:

- `Tenant`
- `TenantContext`
- `IsolationMode`
- `BackendCapabilities`

### Tenant

Responsabilidad:

- representar un tenant del sistema
- declarar cómo se aísla
- declarar qué backend y qué recursos usa

Campos conceptuales sugeridos:

- `id`
- `slug` o `code`
- `name`
- `is_active`
- `isolation_mode` = `schema | database`
- `backend_vendor`
- `schema_name` nullable
- `connection_alias` auto-generated for database tenants
- `connection_string` encrypted URL for database tenants
- `provisioning_connection_string` encrypted admin URL for database provisioning
- `provisioning_mode` = `auto | manual`
- `metadata` JSON extensible, no autoritativo

### metadata

Campo JSON flexible para información futura o variable por tenant.

### TenantSharedModel

Base abstracta para modelos del dominio tenant que pueden ser compartidos por todos los tenants o restringidos a una lista explícita.

- `allowed_tenants` vacío => compartido por todos los tenants
- `allowed_tenants` con valores => visible solo para esos tenants

Este contrato modela alcance de negocio sin usar metadata para decisiones estructurales.

### connection_string

URL de conexión cifrada para tenants database.

### provisioning_connection_string

URL de administración cifrada usada para crear o verificar la DB física del tenant en su servidor Postgres destino.
No es la URL de runtime de la aplicación.

### Zero-config rule

El framework genera `schema_name`, `connection_alias` y `connection_string` automáticamente según el `slug` y la estrategia elegida.

Para tenants `database`, la provisión física de la DB es opt-in y depende de `provisioning_connection_string`.

### Provisioning mode

`provisioning_mode` define si el backend autogenera los campos estructurales (`auto`) o si acepta valores explícitos (`manual`).

### Tenant provisioning workflow

Para tenants `database`, el flujo esperado es:

1. el tenant se guarda en `default`
2. el runtime usa `connection_string` como DSN final
3. si existe `provisioning_connection_string`, el framework intenta crear la DB física
4. si la DB existe, el flujo es idempotente
5. el alias se registra en Django para que el router pueda devolverlo

Regla clave:

- el router nunca inventa conexiones nuevas
- el provisioning vive fuera del router
- la fuente de verdad del catálogo de tenants es `default`

### Regla

No debe reemplazar campos estructurales del contrato principal.
Los datos críticos del framework deben vivir en campos explícitos del modelo.

### Shared vs tenant-scoped data

- `Shared/public` sigue siendo el plano global del catálogo y configuración.
- `TenantSharedModel` cubre entidades del dominio SaaS que pueden ser globales o restringidas por tenants.
- La visibilidad concreta depende del tenant activo y de `allowed_tenants`.

## 2. Tenant resolution

La resolución debe ser componible.

### Resolvers

- `HeaderTenantResolver`
- `TokenTenantResolver`
- `SessionTenantResolver`
- `CompositeTenantResolver`

### Reglas

- el admin usa sesión
- la API usa token y/o header
- si token y header se contradicen, debe rechazarse la operación

## 3. Tenant activation and isolation

El framework no debe mezclar resolución y activación.

### Componentes

- `TenantActivationService`
- `SchemaStrategy`
- `DatabaseStrategy`
- `PublicContext`
- `TenantContext`

### Flujo

1. request entra en contexto public
2. se resuelve tenant
3. se activa tenant si corresponde
4. se ejecuta la vista/model logic
5. se limpia el contexto al finalizar

## 4. Django integration

### Middleware

Middleware tenant-aware para:

- admin
- requests web
- APIs

### Admin

Un solo `/admin/` con dos estados:

- global
- tenant

### ORM y base de datos

Puntos de integración futuros:

- routers
- connection management
- migration orchestration

Regla actual:

- el registry de tenants vive en la base `default`
- el tenant `database` puede tener una DB física propia en otro servidor
- si `provisioning_connection_string` está presente, el framework intenta crear esa DB si no existe
- el router siempre devuelve un alias; no crea conexiones dinámicamente

## 5. Adapters

El core debe ser independiente del stack de exposición.

Adapters previstos:

- Django views tradicionales
- Django Admin
- DRF
- eventualmente Ninja

## Public vs Tenant data plane

### Public/shared plane

- tenant registry
- usuarios globales
- configuración global
- auditoría global

### Tenant data plane

- usuarios locales
- permisos locales
- datos de negocio

## Capabilities por backend

Cada backend deberá declarar capacidades reales.

Ejemplos:

- soporte de schema isolation
- soporte de database isolation
- soporte de switching en runtime
- soporte de objetos shared

Esto evita una falsa abstracción total.

## Seguridad

### Invariantes

- nunca dejar tenant activo filtrado entre requests
- nunca confiar en header sin validación
- nunca permitir acceso a modelos tenant sin tenant válido
- auditar operaciones del admin global sobre tenants

## Observabilidad

### Logging

Campos mínimos:

- `tenant_id`
- `tenant_mode`
- `scope`
- `user_id`
- `request_id`

### Metrics

- resolución de tenant
- activación de tenant
- errores de activación
- switches de admin
- duración del middleware tenant-aware
