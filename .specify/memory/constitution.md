<!--
Sync Impact Report
Version change: 1.0.0 → 1.1.1
Modified principles:
- Clarified "Aggressive Library Use" and dependency workflow so that dependencies are encouraged, never optional, and managed exclusively via `uv`.
Added sections:
- None
Removed sections:
- Reserved Principle Slots III–V
Templates requiring updates:
- None
Follow-up TODOs:
- None
-->

# nate_ntm Constitution


## 1. Core Principles

### 1.1 Aggressive Library Use

1. Minimizing dependency count is not a goal of this project.
2. Prefer a well-maintained third-party library over custom code whenever practical.
3. Dependencies must never be optional or "soft": if any code imports a library, that library must be declared as a dependency of the project.
4. Do not wrap imports in `try`/`except` or otherwise handle the case where an import might not exist; the environment is assumed to contain all declared dependencies.
5. During design and implementation, explicitly ask: "Is there a library I could use for this?"


### 1.2 Linux-First Execution Environment

The only supported runtime target is a Linux environment similar to the one used for development and CI. Tooling, paths, process control, and packaging may assume POSIX semantics and common Linux userland tools.

## 3. Development Workflow & Tooling


1. Prefer well-maintained third-party libraries and tools over custom re-implementations; dependencies are encouraged, not avoided.
2. Use `uv` as the sole tool for managing Python dependencies and the project virtual environment located at `./.venv`.
3. Add or update dependencies only via `uv add`; do not run `pip install` inside `.venv` or use any other method that bypasses `pyproject.toml` and `uv.lock`.
4. Treat `pyproject.toml` and `uv.lock` as the single sources of truth for the Python environment; recreating `.venv` must be possible via `uv sync` alone.
5. When evaluating alternative designs, prioritize maintainability, clarity, and correctness; dependency count is not a factor in this project.


## 4. Governance


This constitution guides how we plan, implement, and review work in this repository.

1. Every new feature plan must include a "Constitution Check" section that confirms alignment with the principles above or documents explicit exceptions.
2. Intentional exceptions (for example, custom re-implementation instead of a library, or non-Linux targets) must be justified in the plan and, where helpful, captured in the "Complexity Tracking" table.
3. Amendments to this constitution require a pull request that updates this file, revises any affected spec-kit templates, bumps the version, and updates the "Last Amended" date.


**Version**: 1.1.1 | **Ratified**: 2026-07-06 | **Last Amended**: 2026-07-06

