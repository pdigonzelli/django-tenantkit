# Guía de Configuración de TenantKit

Esta guía te ayuda a configurar tenantkit en tu proyecto Django paso a paso.

## Requisitos Previos

- Django 6.0+
- PostgreSQL (para schema isolation)
- Python 3.12+

## Instalación

```bash
pip install django-tenantkit-core
```

## Configuración Básica

### 1. Añadir a INSTALLED_APPS

```python
INSTALLED_APPS = [
    # TenantKit primero para que sus modelos estén disponibles
    "tenantkit",
    
    # Tus apps
    ...
    
    # Django contrib
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    ...
]
```

### 2. Configurar el Router

```python
DATABASE_ROUTERS = [
    "tenantkit.routers.TenantRouter",
]
```

### 3. Configurar Middleware

```python
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "tenantkit.middleware.TenantMiddleware",  # Después de SecurityMiddleware
    "django.contrib.sessions.middleware.SessionMiddleware",
    ...
]
```

### 4. Configurar Apps de Ambos Alcances

Esta es la configuración **mínima requerida** para que auth funcione:

```python
TENANTKIT_BOTH_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
]
```

## Casos de Uso Comunes

### Caso 1: SaaS con Datos Aislados por Tenant

Ideal para aplicaciones donde cada cliente tiene datos completamente separados.

```python
# settings.py

TENANTKIT_BOTH_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
]

TENANTKIT_SHARED_APPS = [
    "tenantkit",
    "myapp.billing",  # Facturación global (administración)
]

TENANTKIT_TENANT_APPS = [
    "myapp.customers",   # Datos de clientes por tenant
    "myapp.documents",   # Documentos por tenant
    "myapp.analytics",   # Analytics por tenant
]
```

### Caso 2: Plataforma con Configuración Global y Datos Tenant

Cuando necesitas configuración global compartida pero datos aislados.

```python
TENANTKIT_BOTH_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
]

TENANTKIT_SHARED_APPS = [
    "tenantkit",
    "myapp.config",      # Configuración global
    "myapp.plans",       # Planes y pricing
]

TENANTKIT_TENANT_APPS = [
    "myapp.projects",    # Proyectos por tenant
    "myapp.tasks",       # Tareas por tenant
]

# App mixta: algunos modelos globales, otros por tenant
TENANTKIT_MIXED_APPS = {
    "myapp.core": {
        "shared_models": ["Plan", "Feature"],
        "tenant_models": ["Subscription", "Usage"],
    }
}
```

### Caso 3: Multi-tenant con Schema Isolation

Para PostgreSQL con schemas separados por tenant.

```python
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": "myapp",
        "USER": "postgres",
        "PASSWORD": "postgres",
        "HOST": "localhost",
        "PORT": "5432",
    }
}

TENANTKIT_BOTH_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
]

# Todas las apps de negocio son tenant-scoped
TENANTKIT_TENANT_APPS = [
    "myapp.sensors",
    "myapp.readings",
    "myapp.alerts",
]
```

## Verificación de Configuración

### 1. Listar Modelos Clasificados

```bash
python manage.py list_tenant_models
```

Muestra:
- Shared models (📄)
- Tenant models (🏢)
- Both-scope models (🔁)
- Unclassified models (❓)

### 2. Verificar Configuración

```bash
python manage.py check
```

Detecta:
- Modelos no clasificados
- Configuraciones conflictivas
- Problemas de routing

### 3. Verificar Migraciones

```bash
python manage.py showmigrations
```

Asegúrate de que las migraciones se aplicarán donde corresponde.

## Solución de Problemas

### Problema: "No tenant context for tenant model X"

**Causa:** Estás consultando un modelo tenant sin contexto de tenant activo.

**Soluciones:**
1. Activa un tenant antes de la consulta:
   ```python
   from tenantkit import set_current_tenant
   set_current_tenant(my_tenant)
   ```

2. O marca el modelo como both-scope si debe funcionar sin tenant:
   ```python
   # settings.py
   TENANTKIT_BOTH_APPS += ["myapp"]
   ```

3. O usa `@shared_model` si el modelo debe ser global.

### Problema: Migraciones no se aplican en tenant

**Causa:** La app no está configurada para migrar en tenant DBs.

**Verificación:**
```bash
python manage.py list_tenant_models --type=tenant
```

Si tu modelo no aparece, revisa:
- ¿La app está en `TENANTKIT_TENANT_APPS`?
- ¿El modelo tiene `@tenant_model`?

### Problema: "Model X is not classified"

**Causa:** El modelo no tiene clasificación explícita.

**Solución:**
```python
from tenantkit import tenant_model

@tenant_model
class MyModel(models.Model):
    ...
```

O configura la app:
```python
TENANTKIT_TENANT_APPS += ["myapp"]
```

## Buenas Prácticas

1. **Sé explícito**: Configura todas tus apps de negocio en `SHARED_APPS` o `TENANT_APPS`

2. **Usa BOTH_APPS solo para framework**: `auth`, `contenttypes`, `sessions`

3. **Evita MIXED_APPS si puedes**: Mejor separar en apps distintas

4. **Verifica regularmente**:
   ```bash
   python manage.py list_tenant_models
   python manage.py check
   ```

5. **Documenta tu configuración**: Añade comentarios en settings.py explicando por qué cada app está en su categoría

## Ejemplo Completo

```python
# settings.py

INSTALLED_APPS = [
    "tenantkit",
    "myapp.global",
    "myapp.tenants",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
]

DATABASE_ROUTERS = [
    "tenantkit.routers.TenantRouter",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "tenantkit.middleware.TenantMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
]

# Configuración de TenantKit
TENANTKIT_BOTH_APPS = [
    "django.contrib.auth",        # Usuarios en shared y tenants
    "django.contrib.contenttypes",  # Content types en ambos
    "django.contrib.sessions",     # Sesiones en ambos
]

TENANTKIT_SHARED_APPS = [
    "tenantkit",        # Framework models
    "myapp.global",     # Configuración global
]

TENANTKIT_TENANT_APPS = [
    "myapp.tenants",    # Todo lo demás por tenant
]
```

## Referencias

- [ADR 0006: App and Model Classification](../adr/0006-app-model-classification.md)
- [Auth y Admin](./auth-and-admin.md)
- [Guía de Migración](./migration-guide-v0.x-to-v1.md)
