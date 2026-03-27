# Auth y Admin

## Objetivo

Definir un modelo de autenticación y administración compatible con:

- superusuario global
- usuarios locales por tenant
- un único `/admin/`
- activación de tenant vía sesión

## Principio central

El admin web no debe depender de headers para su navegación normal.

Para el admin, el tenant activo se resuelve por **sesión**.

## Modelo de usuarios

### Usuarios globales

Viven en shared/public.

Responsabilidades:

- administración global del sistema
- gestión de tenants
- configuración global
- auditoría global
- entrada/switch controlado a un tenant

### Usuarios locales

Viven dentro del tenant.

Responsabilidades:

- administración local del tenant
- operación diaria sobre datos del tenant
- gestión interna del espacio tenant-local

## Login en `/admin/`

Un solo login con un campo opcional de tenant:

- `tenant`
- `username`
- `password`

## Flujos

### 1. Login global

Si `tenant` está vacío:

- autenticar en shared/public
- crear sesión global
- mostrar solo modelos globales

### 2. Login tenant

Si `tenant` está informado:

- resolver tenant
- activar contexto del tenant
- autenticar al usuario local dentro del tenant
- persistir en sesión:
  - `auth_scope = tenant`
  - `active_tenant_id`

## Switch de tenant para superusuario global

El superusuario global puede:

- iniciar en modo global
- seleccionar un tenant desde la UI del admin
- cambiar al modo tenant
- volver al modo global

Esto debe quedar auditado.

## SessionTenantResolver

Para requests del admin, el tenant se obtiene desde la sesión.

Datos esperados en sesión:

- `active_tenant_id`
- `auth_scope`

## Middleware del admin

Responsabilidades:

- leer tenant activo de sesión
- activar `SchemaStrategy` o `DatabaseStrategy`
- dejar el request en modo public si no hay tenant activo
- limpiar contexto al final del request

## Comportamiento del AdminSite

### Modo global

- visible para usuarios globales
- solo modelos shared/public
- no hay tenant activo

### Tenant switcher

El admin expone una vista de cambio de tenant en `/admin/tenant-switch/`.

- muestra un selector de tenants activos
- opción `Default / Global` para limpiar el tenant activo
- persiste en sesión:
  - `auth_scope`
  - `active_tenant_id`
- `default` significa "sin tenant activo"

## Operation errors

When a tenant operation fails in admin, the UI shows a friendly message.
The technical detail is kept in logs, while the user sees a plain-language explanation.

### Modo tenant

- visible para superusuarios globales en tenant switch o para usuarios locales autenticados con tenant
- solo modelos del tenant activo

## TenantSharedModel

`TenantSharedModel` es la base abstracta para modelos que pueden ser compartidos por todos los tenants o restringidos a una lista.

- `allowed_tenants` vacío: acceso para todos los tenants
- `allowed_tenants` con valores: acceso solo a esos tenants

En admin, este contrato se usa para filtrar resultados según el tenant activo.

## AdminSite y decisión de scope

El `AdminSite` decide qué modelos mostrar según el scope activo:

### Shared mode (default/global)
- Muestra modelos registrados con `SharedScopeModelAdmin`
- Incluye catálogo de tenants y configuración global
- No muestra modelos tenant-local

### Tenant mode
- Muestra modelos `TenantSharedModel` filtrados por `allowed_tenants`
- Si `allowed_tenants` está vacío, el modelo es visible (shared por defecto)
- Si tiene valores, solo visible para esos tenants
- El queryset se filtra automáticamente por el tenant activo en sesión

### Lógica de filtrado

```python
# En TenantSharedModelAdmin.get_queryset()
queryset.filter(
    Q(allowed_tenants__isnull=True) | Q(allowed_tenants=current_tenant)
).distinct()
```

Esto permite:
- Modelos globales para todos los tenants
- Modelos restringidos a una lista específica
- Un solo admin que adapta su vista según el contexto

## Base tenant-aware

La infraestructura base para admins tenant-aware vive en `multitenant.admin_base`.

Provee:

- resolución del tenant actual desde `request.tenant` o `contextvars`
- scoping automático de querysets por el campo `tenant`
- asignación automática del tenant al crear objetos nuevos
- una base `TenantAwareModelAdmin` reutilizable para futuros modelos tenant-locales

Regla:

- esta base no registra modelos concretos todavía; solo prepara el patrón

## Reglas de permisos

- un usuario local no debe ver modelos globales
- un usuario global no debe operar datos tenant sin contexto explícito
- sin tenant activo no deben exponerse modelos tenant

## Authentication backends

Para este diseño es esperable terminar con más de un backend de autenticación.

Posibles roles:

- backend global
- backend tenant-aware para usuarios locales

La decisión concreta de implementación se documentará mejor en la fase de diseño del auth subsystem.

## Riesgos

- mezclar autenticación global y local sin contexto explícito
- permitir login tenant sin validar tenant
- dejar tenant pegado en sesión sin cleanup correcto
- permitir al admin navegar modelos tenant sin contexto válido

## Auditoría recomendada

Eventos mínimos:

- login global exitoso/fallido
- login tenant exitoso/fallido
- tenant switch
- salida de modo tenant
- acciones sensibles en admin
