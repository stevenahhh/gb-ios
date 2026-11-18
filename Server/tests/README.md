# Backend tests

Run from `Server`: `uv run pytest -q`.

Without `ROUNDUP_TEST_DATABASE_URL`, PostgreSQL tests are explicitly skipped;
authentication, startup configuration, and request validation still run.

For real integration, provide `ROUNDUP_TEST_DATABASE_URL` through the environment
(never paste credentials into logs or command arguments), then run:

```sh
ROUNDUP_TEST_DATABASE_SSLMODE=disable uv run pytest -q -m postgres
```

The role needs CREATE SCHEMA permission. Each test creates a unique
`roundup_test_<uuid>` schema and uses SQLAlchemy schema translation for every
inquiry table operation, including initialization. Cleanup drops only that exact
schema. No public/business table is initialized or overwritten. Unreachable or
misconfigured supplied databases fail tests rather than skip them.

Coverage includes initial schema readiness, canonical seed shape, non-overwriting
initialization, durable edits through a fresh engine/pool, trimmed decisions,
blank approval rollback, blank rejection, stale/missing/repeated writes, and
competing edits/decisions through HTTP with independent DB sessions.

Async tests use AnyIO's asyncio backend because asyncpg requires it. HTTPX's
in-process ASGI transport exercises the real application and real PostgreSQL;
it does not call AI, Maps, CSR, or messaging services.
