# Repository conventions

## Python style and types

- Follow PEP 8 and PEP 257. Use the project's Ruff formatter and existing Python
  3.14 baseline rather than manually applying competing formatting rules.
- Use meaningful English names and simple, readable implementations. Keep changes
  focused; do not introduce abstractions solely to satisfy documentation or typing.
- Annotate public application function parameters and return values. Use modern
  syntax such as `str | None`, `list[str]` and `collections.abc.Iterator[Session]`.
  Avoid unnecessary `Any` and preserve API contracts and database schemas.

## Documentation and comments

- Write code documentation in English using triple double quotes and Google-style
  docstrings. Use imperative summaries for functions and descriptive summaries for
  modules and classes. End summaries with a period.
- Document public modules and classes where useful, and functions whose behavior
  is not immediately obvious. Explain non-obvious behavior and business rules;
  do not add boilerplate docstrings to trivial helpers or self-explanatory tests.
- Add `Args:`, `Returns:`, `Raises:` or `Yields:` only when useful. Separate the
  summary, description and sections with blank lines. Describe arguments without
  repeating type annotations. Document deliberate errors rather than every
  incidental exception from dependencies.
- Comments explain why, not obvious operations. Remove stale tutorial scaffolding,
  preserve security and transaction explanations, and keep documentation synchronized
  with implementation. Never invent behavior or business rules.
- Preserve the existing German README; English is required for code documentation.

## FastAPI and module boundaries

- Keep feature routers, table models and API schemas in their existing modules
  under `src/atelier_api/`. Register routers in `main.py`.
- Give endpoints meaningful OpenAPI summaries and accurate response models and
  error descriptions. Use endpoint docstrings for non-obvious behavior, including
  partial-update semantics. Do not repeat information already clear from schemas.
- Preserve route paths, status codes, response shapes, operation IDs and validation
  semantics when improving documentation. Schema descriptions may be improved.
- Share sessions through `atelier_api.database.SessionDep`. Keep business logic
  separate from HTTP handling when its complexity warrants a service.

## Database

- Document non-obvious constraints, security choices and transaction boundaries.
  Do not add comments for straightforward fields or relationships.
- Keep application and Alembic configuration consistent through the existing
  settings. Never include real credentials in documentation, responses or Git.
- Do not rewrite historical migration revisions for style changes. Ruff formatting
  excludes `alembic/versions/`; only docstring rules are exempted there, so existing
  non-documentation lint checks still apply.

## Tests

- Add or update tests when application behavior changes. Pure documentation edits
  normally need existing regression checks rather than tests mirroring the edits.
- Use descriptive names, deterministic data and independent tests. Avoid redundant
  test comments; explain isolation or other non-obvious fixture decisions.
- Restore FastAPI dependency overrides after tests. Use an isolated test database
  for database checks; do not run migrations or tests against production data.

## Required quality checks

Run from the repository root:

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy .
uv run pytest
```

`make lint`, `make format-check`, `make typecheck` and `make test` are equivalent.
`make format` applies formatting. Set `DATABASE_URL` to a migrated PostgreSQL test
database for pytest; the existing readiness test requires an actual connection.
Also verify application imports and OpenAPI generation after API documentation edits.

The repository checks application code, tests, scripts and migrations with
`mypy .`. Revision `66cdf18dbf11` has an explicitly authorized import-only fix:
`AutoString` is imported directly from `sqlmodel.sql.sqltypes` so mypy can resolve
it. Its revision ID, upgrade/downgrade operations and generated SQL are unchanged.
This is not permission to rewrite historical migrations for formatting or schema
changes. Do not suppress unrelated type errors.

Ruff extends the existing default lint selection with targeted docstring quality
and Google-section checks. Presence rules D100-D107 are intentionally not enabled:
useful documentation is required by these conventions, not boilerplate everywhere.
No broad `noqa` suppressions should be added. Report failed checks and distinguish
pre-existing issues from regressions.
