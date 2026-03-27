# Guía de estudio

## Objetivo

Tener una base sólida de Django antes de implementar el framework.

## Prioridades de estudio en Django

### 1. Admin

Estudiar:

- `AdminSite`
- `ModelAdmin`
- `has_permission`
- `get_queryset`
- custom login form
- templates del admin

### 2. Auth

Estudiar:

- `authenticate()`
- `login()`
- `logout()`
- `AUTHENTICATION_BACKENDS`
- custom authentication backends
- permisos
- sesiones

### 3. Middleware

Estudiar:

- orden de middlewares
- lifecycle request/response
- interacción con `request.session`
- interacción con `request.user`

### 4. ORM y DB layer

Estudiar:

- múltiples bases de datos
- routers
- managers y querysets
- transacciones

### 5. Requests y seguridad

Estudiar:

- headers
- CSRF
- sessions
- staff vs superuser

## Qué mirar en django-tenants

### Conceptos útiles

- separación entre `public` y `tenant apps`
- middleware de activación de tenant
- lifecycle de schema switching

### Qué no copiar automáticamente

- resolución por domain como estrategia central
- suposiciones PostgreSQL-only para todo el framework

## Preguntas para validar mientras estudiás

- ¿qué hook del admin conviene customizar primero?
- ¿cómo convive un custom login form con múltiples backends?
- ¿qué parte del auth debe vivir en shared y cuál en tenant?
- ¿cómo se garantiza cleanup de tenant context?
- ¿cómo se testea el admin tenant-aware?

## Orden recomendado de lectura

1. Django auth customization
2. Django admin customization
3. Django middleware
4. Django multi-db
5. django-tenants
6. django-tenant-schemas advanced usage
