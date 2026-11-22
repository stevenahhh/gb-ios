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
`roundup_test_<uuid>` schema, selects it with `DATABASE_SCHEMA`, runs the real Alembic
migrations there, and drops only that schema. No public or business table is touched.
Unreachable or misconfigured supplied databases fail tests rather than skip them.

The request clock is fixed through a FastAPI dependency override so date-derived
numbers are deterministic. HTTPX's in-process ASGI transport exercises the real
application and PostgreSQL. Only the outbound HyperCLOVA call is replaced, in the
test that inspects the prompt built from database rows.

`test_collectors.py` runs collectors against a scripted HTTP transport with hand-written fixtures, including
the robots.txt refusal. `test_collector_runs.py` runs storage, mapping, and the API on PostgreSQL the same way.
No collector test may reach a real host.

`test_carry_overs.py` covers putting left-over work into today's list, taking it back, and the day it ends.

`test_undo.py` covers revision-checked reversals, state restoration, and shared
attention totals. `test_drafts.py` covers local edits, decisions, linked
recommendations, and reopening. `test_details.py` covers the additive screen
contracts and custom operation periods. Migration tests exercise both directions
of revision `0003`, including preserving rejected text on downgrade; API-key
contract tests cover the new routes without a database.
