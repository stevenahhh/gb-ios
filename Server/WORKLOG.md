# 2026-11-18 inquiry persistence implementation

> Superseded: `init_db.py` no longer exists. Apply the schema with
> `uv run alembic upgrade head` and insert optional initial data with
> `uv run python seed.py`. See [README.md](README.md). The `init_db.py` commands
> below only record what was run on this date.

Scope: only this `Server` directory. Core sample/model/store/test files were read
without edits. No Git operation, deployment, browser, cloud configuration, SSH
connection, Keychain retrieval, or remote initialization was performed.

Implemented PostgreSQL-only persistence with SQLAlchemy async/asyncpg, typed
request/response models, authenticated routes, transaction row locks, atomic
revision checks, pending-only writes, and schema readiness. The explicit
`uv run init_db.py` command creates v1 schema and inserts missing canonical
synthetic IDs without overwriting existing rows. Initialization is not an
automatic schema-upgrade system.

Primary documentation consulted through Context7: SQLAlchemy async engine,
transactions, row locking, and PostgreSQL `on_conflict_do_nothing`.
Official FastAPI lifespan documentation and asyncpg connection/TLS documentation
were fetched directly. No new outgoing provider calls were introduced.

## QA evidence

Using an owned temporary environment inside Server with package/compiler/test
caches redirected there:

* `uv sync --group dev --no-install-project`: exit 0.
* `uv run ruff check database.py inquiries.py seed.py init_db.py tests`:
  exit 0, all checks passed under the configured ALL rules.
* `uv run basedpyright`: exit 0, 0 errors, 0 warnings.
* `uv run pytest -q`: exit 0, 19 passed, 17 skipped, no warnings.
* `env -u DATABASE_URL uv run init_db.py`: expected exit 1 with only the
  generic initialization failure message. No table was created.
* Authentication mutation: temporarily removing the application auth dependency
  caused all eight missing/wrong-key HTTP cases to fail (503/422 instead of 401).
  The mutation test command exited 1 as expected. Auth source was restored to its
  recorded SHA-256 baseline. The initial mutation also exposed asyncpg's string
  `verify-full` dependence on `~/.postgresql/root.crt`; the default now passes
  `ssl=True`, requiring TLS with system CA/hostname verification instead.
* Skips are exclusively the PostgreSQL tests because
  `ROUNDUP_TEST_DATABASE_URL` was not supplied. No SQLite substitute was used.

An earlier whole-directory lint run found two pre-existing long lines in the
existing `/ask` route. Those unrelated statements were preserved; the documented
lint command covers the new implementation and tests. Existing main.py was
imported and its routes exercised by the local contract tests.

The parent reported successful PostgreSQL 17.11 DDL/DML access and a server
without SSL support. This is parent-supplied evidence, not a run of this backend.
Use `DATABASE_SSLMODE=disable` for that endpoint and
`ROUNDUP_TEST_DATABASE_SSLMODE=disable` for its isolated test connection.
No database encryption is claimed.

Remote execution, concurrency, actual durable commits, DDL initialization, and
PostgreSQL test mutation checks remain unexercised locally. Run:

```sh
# Supply ROUNDUP_TEST_DATABASE_URL privately first.
ROUNDUP_TEST_DATABASE_SSLMODE=disable uv run pytest -q -m postgres
```

Each database test creates and drops only its own UUID schema. The role needs
CREATE SCHEMA permission; application/public tables are not initialized.

## Code review

Single responsibilities: database resource/schema ownership; inquiry protocol;
canonical seed; explicit initialization; boundary tests; database integration
tests. New implementation modules are 32-88 nonblank, noncomment lines, and the
largest test module is 181. No file exceeds the size ceiling.

Inputs are parsed by Pydantic at the HTTP boundary; IDs are branded; decision
variants use exhaustive matching; no Any annotations, casts, ignored type errors,
or speculative null guards were introduced. A shared lock helper serves both
write routes. No production function has more than three parameters; decision
test cases use a frozen value object.

Each successful write increments once, and function-scoped session teardown
commits before the response is sent. Missing/stale/completed checks precede
decision validation. Failed approval rolls back. Approval touches only the
inquiry row; no booking or dispatch integration exists.

Tests target public behavior with real PostgreSQL sessions where a database is
needed, without mocks or test-only production seams. Database regression and
mutation proofs require the supplied test URL. No business-data deletion,
post-delete verification code, negative-form flags, or new logging framework was
introduced. Secret-bearing errors are replaced with generic boundary failures.
