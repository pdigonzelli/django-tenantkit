# Testing

This document describes the current testing entrypoints for the repository.

## Official Test Command

The current stable test command is:

```bash
uv sync --dev
uv run python example/manage.py test multitenant
```

## Integration Tests

Some integration tests require PostgreSQL to be available.

## Current Notes

- the example project is the current test harness
- the reusable package lives in `src/multitenant`
- Django's test runner is the current stable path
- the repository also contains integration-oriented test coverage for provisioning behavior

## Future Direction

As the package evolves further, tests will likely be split more clearly between:

- package tests
- integration tests
- example project validation

## Related Documents

- [Example Project](./example.md)
- [Provisioning](./provisioning.md)
