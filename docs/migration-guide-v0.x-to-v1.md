# Guía de Migración: v0.x a v1.0

Esta guía te ayuda a migrar desde la configuración antigua (`TENANTKIT_DUAL_APPS`) al nuevo sistema de clasificación por apps.

## Cambios Principales

| Antiguo (v0.x) | Nuevo (v1.0+) |
|----------------|---------------|
| `TENANTKIT_DUAL_APPS` | `TENANTKIT_BOTH_APPS` |
| Solo model decorators | App-level + model decorators |
| `DUAL_APPS` concepto confuso | `BOTH_APPS` concepto claro |

## Migración Paso a Paso

### Paso 1: Identificar Configuración Actual

Revisa tu `settings.py` actual:

```python
# Configuración antigua
TENANTKIT_DUAL_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
]
```

### Paso 2: Renombrar a BOTH_APPS

Simplemente renombra la configuración:

```python
# Nueva configuración
TENANTKIT_BOTH_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
]
```

### Paso 3: Verificar con el Comando de Check

```bash
python manage.py check_tenantkit_config
```

Deberías ver:
```
✓ All checks passed! No issues found.
```

Si aparece:
```
⚠ Deprecated Configuration
   TENANTKIT_DUAL_APPS is deprecated...
```

Revisa que hayas renombrado correctamente.

### Paso 4: Probar Migraciones

```bash
python manage.py showmigrations
```

Verifica que las migraciones se aplicarán donde corresponde:
- `auth` y `contenttypes` deben migrar en ambos contextos

### Paso 5: Ejecutar Pruebas

```bash
python manage.py test
```

Asegúrate de que todo sigue funcionando.

## Casos Especiales

### Caso A: Tenías Modelos con Decoradores

Si usabas `@shared_model` o `@tenant_model`, **no necesitas cambiar nada**.

Los decoradores siguen funcionando igual y tienen precedencia sobre la configuración por apps.

### Caso B: Quieres Migrar a App-Level Classification

Si tienes muchos modelos decorados y quieres simplificar:

**Antes:**
```python
# myapp/models.py
from tenantkit import tenant_model

@tenant_model
class Customer(models.Model):
    pass

@tenant_model
class Order(models.Model):
    pass

@tenant_model
class Invoice(models.Model):
    pass
```

**Después:**
```python
# settings.py
TENANTKIT_TENANT_APPS = [
    "myapp",  # Todos los modelos de myapp son tenant-scoped
]
```

```python
# myapp/models.py
# Puedes remover los decoradores si quieres
class Customer(models.Model):
    pass

class Order(models.Model):
    pass

class Invoice(models.Model):
    pass
```

### Caso C: App Mixta (Algunos Modelos Shared, Otros Tenant)

Para apps donde necesitas granularidad:

```python
# settings.py
TENANTKIT_MIXED_APPS = {
    "myapp": {
        "shared_models": ["GlobalConfig", "SystemSetting"],
        "tenant_models": ["CustomerData", "Transaction"],
    }
}
```

## Ejemplo Completo: sensorData

### Configuración Antigua

```python
# settings.py (v0.x)

TENANTKIT_DUAL_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
]
```

### Configuración Nueva

```python
# settings.py (v1.0+)

# Apps que existen en ambos contextos (shared y tenant)
TENANTKIT_BOTH_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
]

# Apps que solo existen en shared/default
TENANTKIT_SHARED_APPS = [
    "tenantkit",  # Framework
]

# Apps que solo existen en tenant contexts
TENANTKIT_TENANT_APPS = [
    # Tus apps de negocio aquí
]
```

## Troubleshooting

### "TENANTKIT_DUAL_APPS is deprecated"

**Problema:** Aún tienes la configuración antigua.

**Solución:** Renombra a `TENANTKIT_BOTH_APPS`.

### "Missing TenantRouter"

**Problema:** No has configurado el router.

**Solución:**
```python
DATABASE_ROUTERS = [
    "tenantkit.routers.TenantRouter",
]
```

### "Model X is not classified"

**Problema:** Modelos sin clasificación explícita.

**Solución:**
1. Añade la app a `TENANTKIT_TENANT_APPS` o `TENANTKIT_SHARED_APPS`
2. O usa `@tenant_model` / `@shared_model` en el modelo

### Migraciones no se aplican donde esperaba

**Problema:** Configuración de app scope incorrecta.

**Verificación:**
```bash
python manage.py list_tenant_models --type=tenant
python manage.py list_tenant_models --type=shared
python manage.py list_tenant_models --type=both
```

## Timeline de Deprecación

| Versión | Estado | Acción Requerida |
|---------|--------|------------------|
| v0.2.x | Deprecation warning | Renombrar a `BOTH_APPS` |
| v1.0.x | Deprecated | Migración recomendada |
| v2.0.0 | Removed | Migración obligatoria |

## Recursos

- [ADR 0006: App and Model Classification](../adr/0006-app-model-classification.md)
- [Guía de Configuración](./configuration-guide.md)
- [Auth y Admin](./auth-and-admin.md)

## Soporte

Si encuentras problemas durante la migración:

1. Ejecuta `python manage.py check_tenantkit_config --verbose`
2. Revisa `python manage.py list_tenant_models`
3. Consulta la documentación de troubleshooting
