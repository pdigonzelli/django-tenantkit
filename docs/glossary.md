# Glosario

## Tenant

Unidad lógica de aislamiento dentro del sistema.

## Shared / Public

Espacio global común a todo el sistema. Contiene control plane, configuración global y usuarios globales.

## Tenant-local

Espacio aislado donde viven los datos y usuarios propios de un tenant.

## Control plane

Capa global desde la que se gestionan tenants, configuración, auditoría y operación del sistema.

## Data plane

Capa donde viven y se operan los datos aislados del tenant.

## Isolation mode

Modo de aislamiento del tenant. En este proyecto puede ser:

- `schema`
- `database`

## Schema tenant

Tenant aislado mediante un schema separado dentro de una base.

## Database tenant

Tenant aislado mediante una base o conexión dedicada.

## Tenant context

Contexto de ejecución donde un tenant ya fue resuelto y activado.

## Public context

Contexto neutro/global sin tenant activo.

## Resolver

Componente que determina qué tenant corresponde a un request.

## Strategy

Implementación concreta de activación y aislamiento del tenant.

## Tenant-aware admin

Admin de Django adaptado para operar en modo global o en modo tenant.

## metadata

Campo JSON extensible por tenant. Se usa para información futura o no estructural.
No debe reemplazar campos clave del modelo.

## connection_alias

Alias de conexión de Django asociado a un tenant database. El framework lo autogenera y el router devuelve ese alias para que Django resuelva la conexión.

## connection_string

URL de conexión cifrada asociada a un tenant database. Se almacena cifrada y se descifra solo en runtime.

## provisioning_connection_string

URL admin cifrada asociada a un tenant database. Sirve para crear o verificar la DB física del tenant en su servidor destino.

## provisioning_mode

Modo de aprovisionamiento del tenant: `auto` o `manual`.
