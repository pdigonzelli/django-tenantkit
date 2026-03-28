# Installation

This document describes the current repository layout and the path toward installing the package in a standalone Django project.

## Status

The repository now uses a package-first layout:

- `src/multitenant` contains the reusable package
- `example/` contains the reference Django project
- `pyproject.toml` and `uv.lock` live at the repository root

## Current Development Setup

Use the repository root as the development entrypoint:

```bash
uv sync --dev
```

The example project then runs as a consumer of the installed local package.

```bash
uv run python example/manage.py test multitenant
```

## Planned Installation Modes

Once packaging and naming are finalized, the project should support installation with:

```bash
pip install <package-name>
uv add <package-name>
```

The final package name is still under review, so these commands are placeholders for the final public release workflow.

## Django Integration Overview

At a minimum, a Django project will need:

- the multitenancy app in `INSTALLED_APPS`
- tenant-aware middleware
- a database router
- tenant model and isolation strategy configuration

In the current repository layout, those pieces are demonstrated by the `example/` project while the package source itself lives in `src/multitenant`.

## Related Documents

- [Quickstart](./quickstart.md)
- [Concepts](./concepts.md)
- [Commands](./commands.md)
- [Example Project](./example.md)
