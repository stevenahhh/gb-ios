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

Production is `gongbang-api-001` in the NCP `scnu` sub-account, at
`https://211.233.193.216`. nginx terminates TLS on 443 and proxies to `127.0.0.1:8000`.
The systemd unit [roundup-api.service](roundup-api.service) runs as `gongbang` from
`/opt/gongbang/current` and reads `/opt/gongbang/server.env`. Deploy with:

```sh
Server/deploy.sh
```

The script uses `~/.ssh/gongbang-prod`, uploads a new release, backs up `inquiries`,
migrates, seeds missing rows, switches `current`, restarts the service, and restores the
previous release if `/health/ready` fails. Interactive API docs are disabled.

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
| `CLOVA_STUDIO_API_KEY` | for `/draft`, `/ask`, `/rewrite` | HyperCLOVA X |
| `NCP_CSR_CLIENT_ID`, `NCP_CSR_CLIENT_SECRET` | for `/stt` | Speech recognition; also used by `/tts` when the TTS pair is unset |
| `NCP_TTS_CLIENT_ID`, `NCP_TTS_CLIENT_SECRET` | no | CLOVA Voice Premium for `/tts` when it runs on its own NAVER API app |
| `TTS_SPEAKER` | no | CLOVA Voice Premium speaker, default `vyuna` |
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

Revision `0003` permits rejected content drafts and recommendations. Deploying this
release applies `0003` through the existing `alembic upgrade head` deployment step;
readiness requires that revision. Downgrading to `0002` first maps rejected content
back to `draft` and rejected recommendations back to `open`, preserving their text.

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
| `GET /operations?month=YYYY-MM` or `?start=YYYY-MM-DD&end=YYYY-MM-DD` | Monthly or inclusive custom range (up to 366 days); custom comparisons use the immediately preceding equal-length range; month and range cannot be combined |
| `GET /bookings?status&q&session&limit&offset` | `status`: `all`, `confirmed`, `deposit_pending`; optional session ID filter |
| `GET /bookings/{id}` | Booking details, masked customer, deposit state, actions, and class completion revision |
| `POST /bookings` | `{sessionId, customerName, phone, partySize}` |
| `POST /bookings/{id}/confirm-deposit` | Deposit received |
| `POST /bookings/{id}/undo-deposit` | Return a confirmed booking with a deposit to deposit pending |
| `GET /class-sessions` | Future classes with free seats |
| `GET /class-sessions/{id}` | Class completion and active booking IDs in creation order |
| `POST /class-sessions/{id}/completion` | `{done, expectedRevision}` |
| `GET /orders?status&q&sort&limit&offset` | `status`: `all`, `paid`, `processing`; `sort`: `newest`, `oldest` |
| `POST /orders/{id}/confirm` | Accept an order and open its shipment |
| `POST /orders/{id}/undo-confirm` | Return to paid and remove the shipment only while it is still packing |
| `GET /shipments?status&q&sort&limit&offset` | `status`: `all`, `scheduled`, `in_transit`, `delivered`; `sort`: `soonest`, `latest` |
| `POST /shipments/{id}/pack`, `/invoice`, `/deliver` | Fulfilment steps; invoice takes `{carrier, trackingNumber}` |
| `POST /shipments/{id}/undo` | Reverse one fulfilment step; delivered undo also reopens the completed order |
| `POST /orders/confirm`, `/orders/undo-confirm`, `/shipments/pack`, `/shipments/deliver`, `/shipments/undo` | Batch steps with `{items: [{id, expectedRevision}]}` (1-50 rows); one transaction, so one refused row changes nothing (409); missing row 404; repeated row or bad input 422; returns `{items: [Card]}` in request order |
| `POST /shipments/invoice` | Batch invoices with `{carrier, items: [{id, expectedRevision, trackingNumber}]}`, same rules |
| Card actions | A `CardAction` may carry `target: {kind, id, revision}`; a processing order card uses it to carry its parcel's next step (`shipment-<order>`) |
| `GET /cards/{kind}/{id}` | One current card; kind is `order`, `shipment`, or `task` |
| `GET /channels?section&q&limit&offset` | `section`: `all`, `channels`, `inquiries`, `content` |
| `GET /content-drafts/{id}`, `POST /content-drafts/{id}/review` | Open a draft; approve `{body}` |
| `POST /tasks/{id}/completion` | `{done, expectedRevision}` |
| `POST /tasks/{id}/undo` | Reopen a completed task |
| `GET /assistant-drafts/{kind}/{id}` | Editable text, facts, decision state, and reopening availability; kind is `content` or `recommendation` |
| `PATCH /assistant-drafts/{kind}/{id}/draft` | Save nonblank pending text with `{draft, expectedRevision}` |
| `POST /assistant-drafts/{kind}/{id}/decision` | `{decision: "approve" or "reject", draft, expectedRevision}`; content decisions update linked recommendations atomically |
| `POST /assistant-drafts/{kind}/{id}/reopen` | Reopen decided text and linked recommendations with `{expectedRevision}` |
| `POST /recommendations/{id}/acknowledge`, `GET /opportunities` | Recommendation state and list |
| `GET /settings`, `PUT /workshop`, `PATCH /settings/{key}` | Profile and text settings; revision `0` creates the first profile |
| `GET /inquiries?limit&offset` | Array ordered by ID, default limit 200 |
| `PATCH /inquiries/{id}/draft`, `POST /inquiries/{id}/decision` | Existing inquiry contract |
| `POST /inquiries/{id}/undo-completion` | Return a completed reply to waiting with `{expectedRevision}`; the text stays |
| `GET /assistant/activities` | The assistant's work from the last seven days, newest first: reply drafts, post drafts, and missed pickups, each with the facts it used |
| `POST /draft`, `POST /ask`, `POST /rewrite`, `POST /stt`, `GET /geocode`, `GET /staticmap` | AI, speech, and map proxies |
| `POST /tts` | `{text}` (1-2000 characters) read aloud by CLOVA Voice Premium as `audio/mpeg`; markdown is stripped first |

`/ask` accepts `{question, history?}`, reads workshop facts from PostgreSQL, and returns
`{answer, items, intent}`, where `items` holds up to three cards the answer names and `intent`
names how the turn was read. `history`
is a list of `{role: "owner" | "assistant", text}` (at most 40 items, each text up to 2000
characters); only the newest 6 turns reach the model. A `context` field from older clients
is ignored. `turns.py` reads the newest owner turn first. A message that only praises,
thanks, acknowledges, or closes ("오 좋은데?", "고마워", "끝") gets a short fixed reply
with no items and no model call, unless it answers a question the assistant just asked. A
short change request ("좀 더 짧게", "다시 써줘") sends the previous answer to the model to
edit instead of starting over. A redo of "그거" with no earlier answer gets one fixed question
with three options. Every other turn goes through the intent gate in `intents.py`. One short
HyperCLOVA X call (3-second deadline, 100 tokens) runs while the facts load and returns
`{intent, confidence, reading}`. The intents are `lookup`, `write`, `edit`, `advise`, `act`, `react`,
`clarify`, and `out_of_scope`, and each adds its own instructions to the answer prompt. An `act`
answer says where to tap, because the assistant cannot change data. When the classifier
times out, fails, or returns malformed JSON, keywords pick `act`, `write`, or `lookup`.
Only `edit`, `advise`, and `react` keep earlier drafts in the context, so a new topic is never
answered from a stale draft. The server logs each choice as `ask_intent` with `intent`,
`intent_source` (`rules`, `model`, or `fallback`), and `confidence`. The owner's text
never appears in that log. `/draft` keeps `{customer, subject, question, facts}` and adds the workshop
profile and editable settings text from PostgreSQL. `/rewrite` accepts
`{kind: "content" | "recommendation" | "inquiry", title, text, instruction?}` and returns
`{draft}`. Prompts live in `prompts.py`. Every model answer is cleaned by `ai_output.py`.
An empty answer, or a reply that promises a booking, refund, payment, discount, amount, or
date missing from its facts, gets one corrective retry. If the retry fails too, the
endpoint returns 502.

Every state change takes `expectedRevision` and returns the updated object. Missing
rows are 404. A stale revision or an action the current state does not allow is 409;
invalid input is 422. Writes lock their row, and bookings lock the class so seats
cannot be oversold. Approving an inquiry or reviewing a draft sends nothing outside
this database.

Cards add nullable `undo`, `draft`, and `booking` fields; existing `action` codes
remain unchanged. `undo` is `{label, path}` and accepts POST `{expectedRevision}`
at that path. `draft` is `{kind, id, status, preview}`, with status `pending`,
`approved`, or `rejected`; linked recommendations target their content draft.
Booking facts are `{day, dayTitle, time, customer, people}`. Calendar agenda rows
add nullable `isDone` for class and task completion.

Today suggestions retain open recommendations and decisions from the last seven
days, while `openRecommendations` counts only open suggestions. Assistant draft
approval never publishes, applies, sends, or books anything. The legacy content
review and recommendation acknowledgement routes remain available.

## Production behavior

Logs are one JSON object per line on stdout, with an allow-list of fields: route
template, status, duration, request ID, and error type. Query strings, bodies, keys,
and SQL parameters are not logged; run uvicorn with `--no-access-log` because its
access log includes query strings. Request bodies are limited to 64 KiB, or 2 MiB on
`/stt` (413). Unexpected failures return a generic 500, database failures a generic
503, and provider failures a generic 502.

For isolated database test details see [tests/README.md](tests/README.md).
