# Roundup inquiry persistence

Only PostgreSQL is supported. No SQLite, memory fallback, automatic demo reset,
startup seeding, booking creation, or message delivery occurs.

From this directory:

```sh
uv sync --group dev
# Supply DATABASE_URL and ROUNDUP_API_KEY privately in the environment.
export DATABASE_SSLMODE=disable
uv run init_db.py
uv run uvicorn main:app --host 127.0.0.1 --port 8000
uv run pytest -q
uv run ruff check database.py inquiries.py seed.py init_db.py tests
uv run basedpyright
```

`DATABASE_URL` accepts `postgresql://`, `postgres://`, or
`postgresql+asyncpg://`. Percent-encode credentials. Do not put `ssl` or `sslmode`
in the URL: select transport explicitly with `DATABASE_SSLMODE`:

| Mode | Behavior |
| --- | --- |
| `verify-full` (default) | Require TLS and verify CA and hostname |
| `require` | Require TLS without certificate/hostname verification |
| `disable` | Plain PostgreSQL transport; no database encryption claim |

`allow` and `prefer` are rejected, so there is no transport retry/fallback.
The parent verified that the current private NCP PostgreSQL endpoint requires
`disable`; this server does not change cloud configuration.
Missing/invalid database configuration fails application startup.
Database connection/statement errors return a generic 503 without URL,
credentials, SQL parameters, or database error text.

`init_db.py` is the explicit v1 schema initialization command: transactional
SQLAlchemy DDL creates `inquiries` if absent, followed by PostgreSQL
`ON CONFLICT (id) DO NOTHING` for the three canonical synthetic Core inquiries.
Existing drafts, statuses, revisions, and other rows remain untouched.
Run initialization once at a time. It does not alter an incompatible existing
table; future schema changes need an explicit versioned migration.
No table is created by server startup or HTTP requests.

All application routes retain `X-Roundup-Key` authentication against
`ROUNDUP_API_KEY`. Existing AI/Maps/CSR routes are retained.
`GET /health` remains liveness; use authenticated `GET /health/ready` for
database connectivity plus initialized-schema readiness (200 or 503).
Empty initialized tables are ready.

Inquiry API:

* `GET /inquiries` returns an array ordered by ID, including completed inquiries.
* `PATCH /inquiries/{id}/draft`: `{"draft":"...", "expectedRevision":0}`.
* `POST /inquiries/{id}/decision`:
  `{"decision":"approve","draft":"...", "expectedRevision":0}` (`reject` also valid).

Each object contains exactly `id`, `customer`, `subject`, `question`,
`facts` (string array), `draft`, `status` (`pending|approved|rejected`),
and `revision` (integer, initially 0).
Successful writes return the updated object and increment revision once.
Edits preserve whitespace and may be blank. Decisions trim whitespace;
blank approval is 422, blank rejection is valid.
Missing rows are 404. Completed rows or stale revisions are 409, including
repeated decisions. Clients should reload on 409. Revisions must be nonnegative
JSON integers (booleans and strings are rejected).

Each write holds a PostgreSQL row lock while checking pending state and revision.
The transaction commits before the HTTP response is sent; a failed validation
rolls back. Approval only updates the inquiry row. There is no booking or
message dispatch operation in this backend.

For isolated remote/tunnel verification see [tests/README.md](tests/README.md).
