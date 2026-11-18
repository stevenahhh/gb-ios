# Roundup API server

FastAPI serves every business screen of the iOS app from PostgreSQL. Only
PostgreSQL is supported: there is no SQLite, memory fallback, startup seeding, or
automatic reset. Counts, badges, percentages, and calendar markers are computed
from rows on each request.

## Requirements

* Python 3.12 or newer and [uv](https://docs.astral.sh/uv/).
* PostgreSQL 15 or newer (production runs 17). No extension is required.
* No other system package; `tzdata` is a Python dependency.

## Commands

Run from this directory, with the environment below supplied privately:

```sh
uv sync --frozen --no-dev        # production dependencies
uv run --frozen --no-dev alembic upgrade head
uv run --frozen --no-dev python seed.py   # optional, explicit, safe to repeat
uv run --frozen --no-dev uvicorn main:app --host 127.0.0.1 --port 8000 --no-access-log
```

Production is the `KOSA_경진대회_09` server at `https://223.130.130.1:8787`. Uvicorn serves TLS
directly with the certificate in `/opt/roundup`. The systemd unit
[roundup-api.service](roundup-api.service) runs from `/opt/roundup/current` and reads
`/opt/roundup/server.env` and the release `db.env`. Deploy with:

```sh
ROUNDUP_SSH_TARGET=user@223.130.130.1 Server/deploy.sh
```

The script uploads a new release, backs up `inquiries`, migrates, seeds missing rows,
switches `current`, restarts the service, and restores the previous release if
`/health/ready` fails. Interactive API docs are disabled.

Development checks:

```sh
uv sync --frozen --group dev
uv run ruff check .
uv run basedpyright
ROUNDUP_TEST_DATABASE_URL=... ROUNDUP_TEST_DATABASE_SSLMODE=disable uv run pytest -q
```

## Environment

See [.env.example](.env.example). Keep real values out of version control.

| Variable | Required | Purpose |
| --- | --- | --- |
| `DATABASE_URL` | yes | `postgresql://`, `postgres://`, or `postgresql+asyncpg://`; percent-encode credentials; no `ssl`/`sslmode` query |
| `DATABASE_SSLMODE` | no | `verify-full` (default), `require`, or `disable` |
| `DATABASE_SCHEMA` | no | Lowercase schema placed on the connection `search_path` |
| `ROUNDUP_API_KEY` | yes | Shared `X-Roundup-Key` value, compared in constant time |
| `ROUNDUP_LOG_LEVEL` | no | Application log level, default `INFO` |
| `CLOVA_STUDIO_API_KEY` | for `/draft`, `/ask` | HyperCLOVA X |
| `NCP_CSR_CLIENT_ID`, `NCP_CSR_CLIENT_SECRET` | for `/stt` | Speech recognition |
| `NCP_MAPS_CLIENT_ID`, `NCP_MAPS_CLIENT_SECRET` | for `/geocode`, `/staticmap` | Naver Maps |

`allow` and `prefer` SSL modes are rejected, so there is no transport fallback.
The current private NCP PostgreSQL endpoint requires `disable`.

## Migrations and seed

`alembic upgrade head` is the only schema path. Revision `0001` adopts the original
`inquiries` table as it stands, or creates it on an empty database, so a deployed
database needs no manual stamp. Revision `0002` adds the business tables, extends
`inquiries`, and removes the old sample suffix and sample rule from fields owners
cannot edit; drafts, decisions, and revisions are preserved. Migrations run in one
transaction under an advisory lock. Server startup never migrates.

`seed.py` inserts missing rows with `ON CONFLICT DO NOTHING` and links seeded
inquiries to their customers only while that link is empty. It never changes
existing data. Dates are relative to the first seeding day in Asia/Seoul; a later
run does not move them.

## API

Every route requires `X-Roundup-Key`, including `/health`. JSON uses camelCase.

| Route | Purpose |
| --- | --- |
| `GET /health`, `GET /health/ready` | Liveness; database plus exact migration version (200 or 503) |
| `GET /today` | Today tab, all segments |
| `GET /calendar?start&end` | Days with markers and agenda, inclusive, at most 62 days |
| `POST /calendar/events` | Add `{title, kind, detail, startsAt}`; `startsAt` needs a UTC offset |
| `GET /operations?month=YYYY-MM` | Attention counts, monthly summary, area totals |
| `GET /bookings?status&q&limit&offset` | `status`: `all`, `confirmed`, `deposit_pending` |
| `POST /bookings` | `{sessionId, customerName, phone, partySize}` |
| `POST /bookings/{id}/confirm-deposit` | Deposit received |
| `GET /class-sessions` | Future classes with free seats |
| `POST /class-sessions/{id}/completion` | `{done, expectedRevision}` |
| `GET /orders?status&q&sort&limit&offset` | `status`: `all`, `paid`, `processing`; `sort`: `newest`, `oldest` |
| `POST /orders/{id}/confirm` | Accept an order and open its shipment |
| `GET /shipments?status&q&sort&limit&offset` | `status`: `all`, `scheduled`, `in_transit`, `delivered`; `sort`: `soonest`, `latest` |
| `POST /shipments/{id}/pack`, `/invoice`, `/deliver` | Fulfilment steps; invoice takes `{carrier, trackingNumber}` |
| `GET /channels?section&q&limit&offset` | `section`: `all`, `channels`, `inquiries`, `content` |
| `GET /content-drafts/{id}`, `POST /content-drafts/{id}/review` | Open a draft; approve `{body}` |
| `POST /tasks/{id}/completion` | `{done, expectedRevision}` |
| `POST /recommendations/{id}/acknowledge`, `GET /opportunities` | Recommendation state and list |
| `GET /settings`, `PUT /workshop`, `PATCH /settings/{key}` | Profile and text settings; revision `0` creates the first profile |
| `GET /inquiries?limit&offset` | Array ordered by ID, default limit 200 |
| `PATCH /inquiries/{id}/draft`, `POST /inquiries/{id}/decision` | Existing inquiry contract |
| `POST /draft`, `POST /ask`, `POST /stt`, `GET /geocode`, `GET /staticmap` | AI, speech, and map proxies |

`/ask` accepts `{question}` and reads workshop facts from PostgreSQL. A `context`
field from older clients is ignored.

Every state change takes `expectedRevision` and returns the updated object. Missing
rows are 404. A stale revision or an action the current state does not allow is 409;
invalid input is 422. Writes lock their row, and bookings lock the class so seats
cannot be oversold. Approving an inquiry or reviewing a draft sends nothing outside
this database.

## Production behavior

Logs are one JSON object per line on stdout, with an allow-list of fields: route
template, status, duration, request ID, and error type. Query strings, bodies, keys,
and SQL parameters are not logged; run uvicorn with `--no-access-log` because its
access log includes query strings. Request bodies are limited to 64 KiB, or 2 MiB on
`/stt` (413). Unexpected failures return a generic 500, database failures a generic
503, and provider failures a generic 502.

For isolated database test details see [tests/README.md](tests/README.md).
