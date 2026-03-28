# Concepts

This document defines the main concepts used throughout the project.

## Repository Layout

The repository currently separates:

- `src/multitenant`: the reusable package source
- `example/`: the reference Django project used for integration and validation

## Tenant

A tenant is the logical unit of isolation in the system.

## Shared / Public

The shared or public plane contains global system data such as tenant registry, global administration, and shared configuration.

## Tenant-Scoped Data

Tenant-scoped data belongs to an isolated tenant context.

## Isolation Modes

The framework currently supports two main isolation modes:

- `schema`: one database, multiple PostgreSQL schemas
- `database`: one database per tenant

## Provisioning Modes

Provisioning may be:

- `auto`
- `manual`

## Control Plane and Data Plane

- **Control plane**: tenant registry, global administration, shared metadata
- **Data plane**: tenant-local business data and tenant runtime context

## Tenant Resolution

Tenant resolution determines which tenant should be active for the current request or operation.

## Tenant Activation

Tenant activation applies the chosen isolation strategy and makes tenant context available to the runtime.

## Related Documents

- [Architecture](./architecture.md)
- [Provisioning](./provisioning.md)
- [Example Project](./example.md)
