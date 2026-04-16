# Auth y Admin

## Objetivo

Definir una arquitectura de autenticación y administración compatible con:

- superusuario global
- usuarios independientes por tenant
- un único `/admin/`
- activación de tenant vía sesión en admin
- soporte opcional para autenticación JWT tenant-aware

## Principio central

django-tenantkit usa una arquitectura de **usuarios independientes por tenant**.

- cada tenant tiene su propia tabla `auth_user`
- no existe sincronización entre tenants
- el mismo email puede existir en múltiples tenants
- la pertenencia es implícita: si el usuario existe en la DB del tenant, pertenece a ese tenant

El admin web no depende de headers para su navegación normal. En admin, el tenant activo se resuelve por **sesión**.

## Modelo de usuarios

### Usuarios globales

Viven en la base shared/default.

Responsabilidades:

- administración global del sistema
- gestión de tenants
- configuración global
- auditoría global
- entrada y cambio controlado a modo tenant

### Usuarios locales

Viven dentro de cada tenant.

Responsabilidades:

- administración local del tenant
- operación diaria sobre datos tenant-locales
- gestión interna del espacio del tenant

## DUAL_APPS

Para que los modelos de autenticación existan tanto en la base default como en las bases/schemas tenant, tenantkit soporta `TENANTKIT_DUAL_APPS`.

Configuración recomendada:

```python
TENANTKIT_DUAL_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
]
```

Esto permite que `auth_user` y sus dependencias se migren en todos los contextos necesarios.

## Login en `/admin/`

Un solo login con un campo opcional de tenant:

- `tenant`
- `username`
- `password`

### 1. Login global

Si `tenant` está vacío:

- autenticar en shared/default
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

### Modo tenant

- visible para superusuarios globales en tenant switch o para usuarios locales autenticados con tenant
- solo modelos del tenant activo

### Tenant switcher

El admin expone una vista de cambio de tenant en `/admin/tenant-switch/`.

- muestra un selector de tenants activos
- opción `Default / Global` para limpiar el tenant activo
- persiste en sesión:
  - `auth_scope`
  - `active_tenant_id`
- `default` significa “sin tenant activo”

## TenantSharedModel

`TenantSharedModel` es la base abstracta para modelos que pueden ser compartidos por todos los tenants o restringidos a una lista.

- `allowed_tenants` vacío: acceso para todos los tenants
- `allowed_tenants` con valores: acceso solo a esos tenants

En admin, este contrato se usa para filtrar resultados según el tenant activo.

## Helpers de autenticación tenant-aware

tenantkit incluye helpers opcionales en `tenantkit.auth`:

1. `TenantClaimsMixin`
2. `TenantTokenValidator`
3. `TenantJWTAuthentication`

Estos helpers son una **base agnóstica de backend**.

- ayudan a agregar `tenant_slug` al token
- validan que el claim del token coincida con el tenant actual
- permiten envolver un backend de autenticación DRF/JWT

### Importante

La **integración concreta** con una tecnología JWT específica queda diferida a una fase futura. Hoy tenantkit provee la base y los puntos de integración, no una implementación cerrada para un proveedor particular.

### Ejemplo de integración futura

```python
from tenantkit.auth import TenantClaimsMixin


class MyTokenSerializer(TenantClaimsMixin, SomeJWTSerializer):
    pass
```

```python
from tenantkit.auth import TenantJWTAuthentication


class MyProtectedView(APIView):
    authentication_classes = [TenantJWTAuthentication]
```

## Seguridad cross-tenant

Riesgo principal: usar un token emitido para Tenant A en Tenant B.

`TenantTokenValidator` existe para validar automáticamente que el `tenant_slug` del token coincida con el tenant resuelto en el request actual.

## Authentication backends

Este diseño permite más de un backend de autenticación.

Posibles roles:

- backend global
- backend tenant-aware para usuarios locales
- backend JWT integrado por proyecto

La elección concreta del proveedor o librería queda del lado del proyecto consumidor.

## Riesgos

- mezclar autenticación global y local sin contexto explícito
- permitir login tenant sin validar tenant
- dejar tenant pegado en sesión sin cleanup correcto
- permitir al admin navegar modelos tenant sin contexto válido
- asumir que tenantkit ya integra una librería JWT concreta cuando hoy solo provee la base

## Auditoría recomendada

Eventos mínimos:

- login global exitoso/fallido
- login tenant exitoso/fallido
- tenant switch
- salida de modo tenant
- acciones sensibles en admin
