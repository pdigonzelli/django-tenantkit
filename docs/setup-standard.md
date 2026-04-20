# Guía de Configuración Estándar - TenantKit

Esta guía describe el orden correcto de configuración para TenantKit en proyectos Django. Seguir este orden es **crítico** para que la autenticación y el routing multitenancy funcionen correctamente.

---

## Resumen Rápido

Configuración mínima funcional:

```python
# settings.py

INSTALLED_APPS = [
    # Django core (auth PRIMERO)
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    
    # TenantKit DESPUÉS de auth
    "tenantkit",
    
    # Tus apps
    "myapp",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",  # ← ANTES
    "tenantkit.middleware.TenantMiddleware",                      # ← DESPUÉS
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
]

DATABASE_ROUTERS = ["tenantkit.routers.TenantRouter"]

TENANTKIT_BOTH_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
]
```

---

## 1. INSTALLED_APPS - Orden Correcto

El orden en `INSTALLED_APPS` es fundamental para el correcto funcionamiento de TenantKit:

```python
INSTALLED_APPS = [
    # 1. Django core (siempre primero)
    "django.contrib.admin",
    "django.contrib.auth",          # ← Auth debe registrarse antes
    "django.contrib.contenttypes",  # ← ContentTypes también
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    
    # 2. Third-party apps (opcional)
    "rest_framework",
    "rest_framework.authtoken",  # Si usás DRF
    "django_filters",
    
    # 3. TenantKit (después de auth y third-party)
    "tenantkit",                    # ← DESPUÉS de django.contrib.auth
    
    # 4. Tus apps de negocio
    "apps.telemetry",
    "apps.customers",
]
```

### ¿Por qué este orden?

| App | Posición | Razón |
|-----|----------|-------|
| `django.contrib.auth` | Antes de TenantKit | Los modelos User, Group, Permission deben registrarse primero en el schema `public` |
| `django.contrib.contenttypes` | Antes de TenantKit | ContentType es requerido por auth y debe estar disponible |
| `tenantkit` | Después de auth | TenantKit extiende y modifica comportamiento de auth. Si va primero, los modelos de auth no existen aún |

### ⚠️ Consecuencias de orden incorrecto

Si `tenantkit` está **antes** de `django.contrib.auth`:
- Los modelos User/Group/Permission no se encuentran en el schema correcto
- Las migraciones pueden fallar
- El login puede autenticar usuarios incorrectos o fallar silenciosamente
- Las relaciones de ForeignKey a User pueden romperse

---

## 2. MIDDLEWARE - Orden CRÍTICO

El orden del middleware es **absolutamente crítico** para la autenticación multitenancy:

```python
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    
    # AuthenticationMiddleware DEBE ir ANTES de TenantMiddleware
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    
    # TenantMiddleware DEBE ir DESPUÉS de AuthenticationMiddleware
    "tenantkit.middleware.TenantMiddleware",
    
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]
```

### ¿Por qué este orden?

```
Request → SecurityMiddleware → SessionMiddleware → CommonMiddleware
        → AuthenticationMiddleware  ← Autentica usuario en schema 'public'
        → TenantMiddleware            ← Cambia search_path al schema del tenant
        → ...resto del middleware
```

**Flujo correcto:**
1. `AuthenticationMiddleware` autentica al usuario consultando la tabla `auth_user` en el schema `public`
2. `TenantMiddleware` identifica el tenant del request y cambia el `search_path` al schema del tenant
3. Las consultas posteriores usan el schema del tenant para datos de negocio

### ⚠️ Consecuencias de orden incorrecto

Si `TenantMiddleware` está **antes** de `AuthenticationMiddleware`:

```
Request → TenantMiddleware (cambia a schema 'tenant_123')
        → AuthenticationMiddleware (busca usuario en 'tenant_123')
        → ERROR: auth_user no existe en schema del tenant!
```

**Problemas que causa:**
- Login falla (usuario no encontrado)
- Autentica usuario equivocado (si hay usuarios con mismo ID en diferentes schemas)
- Sesiones no funcionan correctamente
- Permisos y grupos no se resuelven bien

---

## 3. DATABASES - Engine y Routers

### Engine para Schema Isolation

Para usar el modo de aislamiento por schemas de PostgreSQL:

```python
DATABASES = {
    "default": {
        "ENGINE": "tenantkit.backends.postgresql",  # ← Engine especial
        "NAME": "mydb",
        "USER": "postgres",
        "PASSWORD": "postgres",
        "HOST": "localhost",
        "PORT": "5432",
    }
}
```

El engine `tenantkit.backends.postgresql` extiende el backend de PostgreSQL de Django para:
- Gestionar el `search_path` de schemas automáticamente
- Crear schemas de tenant dinámicamente
- Aislar consultas por tenant

### Database Router

```python
DATABASE_ROUTERS = ["tenantkit.routers.TenantRouter"]
```

El `TenantRouter` decide:
- Qué consultas van al schema `public` (modelos shared/both)
- Qué consultas van al schema del tenant actual (modelos tenant)
- En qué schema crear nuevas tablas durante migraciones

---

## 4. Configuración de TenantKit

### BOTH_APPS - Apps en ambos scopes

```python
TENANTKIT_BOTH_APPS = [
    "django.contrib.auth",          # Usuarios en public + tenants
    "django.contrib.contenttypes",  # ContentTypes en ambos
    "django.contrib.sessions",     # Sesiones en ambos (opcional)
    "django.contrib.admin",        # Admin logs en ambos (opcional)
]
```

Las apps en `BOTH_APPS` tienen sus tablas en:
- Schema `public` (usuarios globales, configuración)
- Cada schema de tenant (datos específicos si aplica)

### TENANT_APPS - Apps solo en tenants

```python
TENANTKIT_TENANT_APPS = [
    "apps.telemetry",
    "apps.customers",
    "apps.documents",
    "rest_framework.authtoken",  # Opcional: tokens por tenant
]
```

Las apps en `TENANT_APPS` solo existen en los schemas de tenant, nunca en `public`.

### SHARED_APPS - Apps solo en public

```python
TENANTKIT_SHARED_APPS = [
    "tenantkit",           # Framework models
    "apps.billing",        # Facturación global
    "apps.global_config",  # Configuración central
]
```

Las apps en `SHARED_APPS` solo existen en el schema `public`.

---

## 5. Ejemplo Completo - settings.py

```python
# settings.py - Configuración estándar recomendada

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# =============================================================================
# DJANGO CORE SETTINGS
# =============================================================================

INSTALLED_APPS = [
    # Django core (orden importante: auth antes que tenantkit)
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    
    # Third-party apps
    "rest_framework",
    "django_filters",
    
    # TenantKit (después de auth)
    "tenantkit",
    
    # Tus apps
    "apps.core",
    "apps.telemetry",
    "apps.customers",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",  # ← ANTES
    "tenantkit.middleware.TenantMiddleware",                      # ← DESPUÉS
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

# =============================================================================
# DATABASE
# =============================================================================

DATABASES = {
    "default": {
        "ENGINE": "tenantkit.backends.postgresql",
        "NAME": os.getenv("DB_NAME", "myapp"),
        "USER": os.getenv("DB_USER", "postgres"),
        "PASSWORD": os.getenv("DB_PASSWORD", "postgres"),
        "HOST": os.getenv("DB_HOST", "localhost"),
        "PORT": os.getenv("DB_PORT", "5432"),
    }
}

# Router para multitenancy
DATABASE_ROUTERS = ["tenantkit.routers.TenantRouter"]

# =============================================================================
# TENANTKIT CONFIGURATION
# =============================================================================

# Apps que existen en AMBOS scopes (public + cada tenant)
TENANTKIT_BOTH_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
]

# Apps que solo existen en el schema public
TENANTKIT_SHARED_APPS = [
    "tenantkit",
    "apps.core",  # Configuración global, planes, etc.
]

# Apps que solo existen en schemas de tenant
TENANTKIT_TENANT_APPS = [
    "apps.telemetry",
    "apps.customers",
]

# =============================================================================
# REST FRAMEWORK (opcional)
# =============================================================================

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
        "rest_framework.authentication.TokenAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
}

# =============================================================================
# OTHER SETTINGS
# =============================================================================

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True
STATIC_URL = "static/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
```

---

## 6. Checklist de Verificación

Después de configurar TenantKit, verifica cada punto:

### ✅ Checklist de Configuración

- [ ] `django.contrib.auth` está **antes** de `tenantkit` en `INSTALLED_APPS`
- [ ] `django.contrib.contenttypes` está **antes** de `tenantkit` en `INSTALLED_APPS`
- [ ] `AuthenticationMiddleware` está **antes** de `TenantMiddleware` en `MIDDLEWARE`
- [ ] `TenantMiddleware` está **después** de `AuthenticationMiddleware` en `MIDDLEWARE`
- [ ] `DATABASE_ROUTERS` incluye `"tenantkit.routers.TenantRouter"`
- [ ] `TENANTKIT_BOTH_APPS` incluye `"django.contrib.auth"` y `"django.contrib.contenttypes"`
- [ ] (Si usas schema isolation) `ENGINE` es `"tenantkit.backends.postgresql"`

### ✅ Comandos de Verificación

```bash
# 1. Verificar que Django no reporta errores
python manage.py check

# 2. Listar modelos clasificados
python manage.py list_tenant_models

# 3. Verificar migraciones
python manage.py showmigrations

# 4. Crear un tenant de prueba
python manage.py shell -c "
from tenantkit.models import Tenant
t = Tenant.objects.create(name='Test', schema_name='test_tenant')
print(f'Tenant creado: {t.schema_name}')
"

# 5. Verificar que el tenant tiene tablas correctas
python manage.py migrate_schemas --tenant=test_tenant
```

### ✅ Test de Autenticación

```python
# En shell de Django, verifica que la autenticación funciona:

from django.contrib.auth import authenticate
from tenantkit.models import Tenant
from tenantkit import set_current_tenant

# Crear tenant
 tenant = Tenant.objects.create(name="Test", schema_name="test_auth")

# Sin tenant context (debe funcionar para auth)
user = authenticate(username="admin", password="admin123")
print(f"Auth sin tenant: {user}")  # Debe funcionar

# Con tenant context
set_current_tenant(tenant)
user2 = authenticate(username="admin", password="admin123")
print(f"Auth con tenant: {user2}")  # Debe funcionar igual
```

---

## Solución de Problemas Comunes

### "No tenant context for tenant model X"

**Causa:** Consultando modelo tenant sin contexto de tenant.

**Solución:**
```python
from tenantkit import set_current_tenant
set_current_tenant(my_tenant)
# Ahora podés consultar modelos tenant
```

### Login falla después de configurar TenantKit

**Causa probable:** Orden incorrecto de middleware.

**Verificación:**
```python
# En settings.py, asegurate de que:
MIDDLEWARE = [
    ...
    "django.contrib.auth.middleware.AuthenticationMiddleware",  # ANTES
    "tenantkit.middleware.TenantMiddleware",                  # DESPUÉS
    ...
]
```

### "relation auth_user does not exist"

**Causa probable:** `django.contrib.auth` no está en `TENANTKIT_BOTH_APPS`.

**Solución:**
```python
TENANTKIT_BOTH_APPS = [
    "django.contrib.auth",  # ← Asegurate de incluirlo
    "django.contrib.contenttypes",
]
```

### Migraciones no se aplican en schemas de tenant

**Causa probable:** Apps no configuradas en `TENANTKIT_TENANT_APPS`.

**Verificación:**
```bash
python manage.py list_tenant_models --type=tenant
```

Si tu app no aparece, agregala:
```python
TENANTKIT_TENANT_APPS += ["myapp"]
```

---

## Referencias

- [Configuration Guide](./configuration-guide.md) - Guía detallada de configuración
- [Concepts](./concepts.md) - Conceptos de arquitectura multitenancy
- [Auth and Admin](./auth-and-admin.md) - Configuración de autenticación
- [Commands](./commands.md) - Comandos de gestión de tenants
- [Quickstart](./quickstart.md) - Guía de inicio rápido
