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
| `CLOVA_STUDIO_API_KEY` | for `/draft`, `/ask`, `/rewrite`, `/agent/run`, the agent worker | HyperCLOVA X |
| `NCP_CSR_CLIENT_ID`, `NCP_CSR_CLIENT_SECRET` | for `/stt` | Speech recognition; also used by `/tts` when the TTS pair is unset |
| `NCP_TTS_CLIENT_ID`, `NCP_TTS_CLIENT_SECRET` | no | CLOVA Voice Premium for `/tts` when it runs on its own NAVER API app |
| `TTS_SPEAKER` | no | CLOVA Voice Premium speaker, default `vyuna` |
| `NCP_MAPS_CLIENT_ID`, `NCP_MAPS_CLIENT_SECRET` | for `/geocode`, `/staticmap` | Naver Maps |
| `INSTAGRAM_ACCESS_TOKEN`, `INSTAGRAM_USER_ID` | no | Instagram collector; a professional account the operator of this server owns |
| `NAVER_COMMERCE_CLIENT_ID`, `NAVER_COMMERCE_CLIENT_SECRET` | no | Smart Store collector, Naver Commerce API; ignored without the switch below |
| `NAVER_COMMERCE_SELF_OPERATED` | no | Exactly `true` states that the operator of this server owns that store; see [Collectors](#collectors) |

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

Revision `0005` adds `collector_sources`, `collector_runs`, and `collected_items`, and allows a `naver_blog`
channel. Downgrading drops collected items but keeps inquiries and orders already mapped from them.

Revision `0006_agent`은 비서 테이블 여섯 개를 추가하고 다른 테이블은 바꾸지 않습니다. 설정 행도 하나 넣으므로 새로 배포한 비서는 꺼진 채(`off`)로 시작합니다. 되돌리면 비서 테이블과 그 안의 기록을 지웁니다.

Revision `0007_connections`는 사장님이 저장한 공개 계정과 링크를 담는 `connections` 테이블을 추가합니다. 되돌리면 이 테이블과 저장한 값을 지웁니다.

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
| `POST /policy/extract`, `GET`/`POST /policy/versions`, `GET /policy/versions/{version}`, `POST /policy/notices` | K06: refund rules read from owner text, saved versions, and the notice per booking |
| `POST /cancellations/intake`, `/cancellations/quote`, `/cancellations/{bookingId}/decision`, `/cancellations/cases/{id}/draft`, `/approve`, `/undo`; `GET /cancellations/cases`; `DELETE /bookings/{id}/cancellation-cases` | K06: pasted message, fixed refund calculation, owner decision, reply draft, record removal |
| `GET /k06/cards?at`, `POST /bookings/{id}/attendance`, `/undo-attendance`, `GET /class-sessions/under-min`, `GET /class-sessions/{id}/refill`, `/k06`, `PUT .../plan`, `POST`/`DELETE .../waitlist`, `POST .../under-min-decision` | K06: late guests, freed seats, and under-filled classes |
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
| `GET /connections`, `PUT`/`DELETE /connections/{service}` | Public handles and https links the owner saved: `{items: [{service, value, state, updatedAt, revision}]}`; `PUT {value, expectedRevision}`, `DELETE {expectedRevision}`; `state` is `saved` or `none` and never means connected; revision `0` saves the first value; 409 stale revision, 422 wrong host or a value that looks like a secret, with Korean `detail` |
| `GET /collectors/status` | `{"sources": [{id, name, state, last_collected_at, collected_today, message}], "updated_at"}` for Instagram, Smart Store, blog, booking, and talk-talk; `state` is `collecting`, `idle`, `needs_connection`, or `error` |
| `GET /collectors/items?source&limit&offset` | Stored items, newest first, without their raw JSON |
| `POST /collectors/{source}/run` | Collect now; 409 while that source is already collecting |
| `PUT /collectors/{source}/config` | Owner-visible setup values, validated per source; unknown fields, including secrets, are 422 |
| `POST /draft`, `POST /ask`, `POST /rewrite`, `POST /stt`, `GET /geocode`, `GET /staticmap` | AI, speech, and map proxies |
| `GET /settings/class-costs`, `PUT /settings/class-costs/{classId}`, `PUT /settings/outreach-defaults` | K14: cost card per class title and the workshop's outreach rates |
| `POST /outreach/extract` | K14: `{text}` read once into fields, confidence, risk signals; never stored, contacts masked before the model call; a model failure answers 200 with `error: "extract_failed"` and rule-read fields |
| `POST /outreach/quotes`, `GET /outreach/quotes`, `GET /outreach/quotes/{id}`, `POST /outreach/quotes/{id}/recalculate`, `/verify-org`, `/sent`, `/outcome` | K14: quote arithmetic, verdict, reminder task, and recorded answer; no `expectedRevision` |
| `POST /agent/run` | `{question, history?, source: "chat" 또는 "voice", background?}`. 답, 단계, 제안을 반환합니다. `background: true`이면 `queued`로 바로 응답하고 작업 프로세스가 처리합니다 |
| `GET /agent/runs?limit` | 최근 실행 목록. `limit`은 1-100, 기본 20. 단계와 제안은 들어 있지 않습니다 |
| `GET /agent/runs/{id}` | 실행 하나의 진행 상황, 단계, 제안 |
| `GET /agent/proposals` | 승인을 기다리는 제안. 먼저 만료되는 순서입니다 |
| `POST /agent/proposals/{id}/approve` | `{expectedRevision, args?}`. 제안이 보낸 `expectedRevision`을 그대로 돌려보냅니다. `args`에는 송장번호처럼 승인하면서 적은 값을 넣습니다. 바뀌었거나 닫힌 제안은 409 |
| `POST /agent/proposals/{id}/dismiss` | 제안을 실행하지 않고 닫습니다 |
| `POST /agent/steps/{id}/undo` | 끝낸 단계를 되돌리고 `{step, summary}`를 반환합니다. 그 뒤 대상이 바뀌었으면 409 |
| `GET /agent/settings`, `PUT /agent/settings` | 방식, 먼저 챙기기, 도구별 방식, 하루 한도(1-50), 조용한 시간, 점검 간격(5-240분). `expectedRevision`이 필요하고 오래된 값은 409, 없는 도구나 읽기 도구는 422 |
| `GET /agent/memories`, `DELETE /agent/memories/{id}` | 기억 목록과 한 건 지우기(204) |
| `POST /agent/invoices/import?filename` | 본문은 CSV나 XLSX 파일 바이트. 읽은 행과 `readyCount`, `proposalCount`, `proposalId`를 반환하고 아무것도 등록하지 않습니다. 2 MiB를 넘으면 413, 읽지 못하는 파일은 422 |
| `POST /agent/invoices/{proposalId}/approve?filename&accept_format` | 같은 파일을 다시 받아 문제없는 행을 모두 등록하거나 하나도 등록하지 않습니다. `accept_format`에는 형식 경고를 확인한 행 번호를 쉼표로 적습니다. 파일이 다르면 409 |
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
answer says where to tap, because this route cannot change data. When the classifier
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
`/stt` and `/agent/invoices/` (413). Unexpected failures return a generic 500, database failures a generic
503, and provider failures a generic 502.

## 비서

`agent_run.py`가 모델에 도구를 주고 `agent_policy.py`가 호출마다 처리 여부를 정합니다. 모델은 이 결정을 바꾸지 못합니다. 모델에 보내는 글과 실행, 단계 기록에서는 손님 정보를 가립니다. 제안의 실행 값과 기억은 원문으로 저장합니다. 대기 중인 실행의 원문 요청은 실행이 끝나면 지웁니다.

| 결정 | 조건 |
| --- | --- |
| `auto` | 읽기이거나 대상, 근거, 확인 항목, 하루 한도를 모두 만족함 |
| `proposed` | 방식이 `ask`이거나 근거가 없음, 대상이 불확실함, 확인 항목에 걸림, 한도를 채움 |
| `clarify` | 맞는 대상이 없거나 여럿임 |
| `refused` | 방식이 `off`, 없는 도구, 잘못된 값, 또는 말하지 않은 내용을 기억하려 함 |

근거는 사장님의 현재 말과 설정된 택배사 어댑터의 결과입니다. 지금은 설정된 어댑터가 없습니다. 실행 한 번에 도구를 6번, 모델 시간을 45초까지 쓰고 모델 호출마다 1024토큰을 허용합니다. 실행은 한 번에 하나이며 다른 실행이 잠금을 쥐고 있으면 `/ask`와 같은 방식으로 답합니다. 모델이 아무것도 바꾸기 전에 실패해도 같습니다.

`agent_hcx.py`의 CLOVA Studio 도구 호출 형식은 가정입니다. TODO: 실제 모델로 확인합니다.

### 작업 프로세스 켜고 끄기

[deploy/roundup-agent.service](deploy/roundup-agent.service)는 `agent_worker.py`를 `gongbang` 사용자로 실행합니다. 포트를 열지 않고 로그는 journal로 보냅니다. 대기 중인 실행을 5초마다 확인하고 설정한 간격마다 규칙으로 할 일을 찾아 제안을 올립니다. 간격의 처음 값은 15분입니다. 찾은 일을 직접 처리하지는 않습니다. 한 번에 올리는 제안은 10건까지이고 하루에는 설정의 하루 한도까지 올립니다.

배포하면서 유닛을 설치하고 켭니다.

```sh
AGENT_WORKER=1 Server/deploy.sh
```

이 값 없이 배포하면 작업 프로세스를 건드리지 않습니다. 이미 켜져 있는 프로세스는 이전 릴리스 코드로 계속 돌기 때문에, 작업 프로세스를 쓴다면 배포할 때마다 이 값을 붙입니다.

서버에서 상태를 보거나 끄고 다시 켭니다.

```sh
systemctl status roundup-agent
journalctl -u roundup-agent -n 50
sudo systemctl disable --now roundup-agent
sudo systemctl enable --now roundup-agent
```

유닛을 끄면 먼저 올리는 제안과 `background` 실행이 멈추고 `queued` 실행은 다시 켤 때까지 기다립니다. `POST /agent/run`의 일반 실행은 계속됩니다. 비서 전체를 멈추려면 앱에서 "전부 멈추기"를 누르거나 `PUT /agent/settings`로 `mode`를 `off`로 바꿉니다.

한 번 점검하고 결과를 출력하려면 환경 변수를 넣고 실행합니다. 이 명령도 제안을 실제로 저장합니다.

```sh
uv run --frozen --no-dev python agent_worker.py --once
```

### 비서 테스트

`Server`에서 실행합니다. 테스트 DB 조건은 [tests/README.md](tests/README.md)를 봅니다.

```sh
ROUNDUP_TEST_DATABASE_URL=... ROUNDUP_TEST_DATABASE_SSLMODE=disable uv run pytest -q tests/test_agent_*.py
```

`test_agent_redteam.py`는 `tests/agent_corpora/redteam.json`의 공격과 헷갈리는 말을 실제 규칙과 실행 과정에 넣어 봅니다. 모델 평가는 업무 데이터를 바꾸지 않습니다. 평가용 스키마를 만들고 시드를 넣은 뒤 끝나면 지웁니다.

```sh
uv run python -m scripts.agent_eval --backend scripted
uv run python -m scripts.agent_eval --backend live --yes-call-model
```

두 명령 모두 스키마를 만들 수 있는 역할의 `DATABASE_URL`과 `DATABASE_SSLMODE`가 필요합니다. `live`는 유료 모델을 부르므로 `CLOVA_STUDIO_API_KEY`도 있어야 합니다.

- TODO: 비서 서버 테스트 수와 결과를 적습니다.
- TODO: 레드팀 결과를 적습니다.
- TODO: `scripted`와 `live` 평가 결과를 적습니다.

## Collectors

```sh
uv run --frozen --no-dev python -m collectors run --source all
```

Sources are `instagram`, `naver_smartstore`, `naver_blog`, `naver_booking`, `naver_talktalk`, and
`kakao_channel`. The last three have no pull API this server may use and always report `needs_connection`;
`collectors/manual.py` documents the path for each. The collector routes use snake_case keys.

* Every request carries the fixed User-Agent `GongdoriCollector/0.1`. Redirects are never followed.
* Every feed goes through `collectors/feed.py`, which reads the host's `robots.txt` first. The feed is not
  requested when the path is disallowed, or when `robots.txt` answers anything other than 200, 404, or 410.
  A refusal is `needs_connection`.
* `naver_blog` is off until the owner sets `{"blog_id", "enabled": true}`, and the robots check still decides.
  Research for this release found that Naver may disallow it and that its terms restrict automated access, so
  check both before turning it on.
* Instagram and Smart Store use only the official APIs with environment credentials. There is no login
  automation and no stored login session. Addresses, phone numbers, and payment means of orders are not stored.
* `naver_smartstore` runs only when `NAVER_COMMERCE_SELF_OPERATED` is exactly `true` and both credentials are
  set. Without the switch, credentials count as absent: the state is `needs_connection` and no request is made,
  the token call included. Set it only when the operator of this server is the owner of that store.
* Instagram is for an account the operator owns. Meta's
  [app review page](https://developers.facebook.com/documentation/instagram-platform/app-review.md) asks no review
  of an app that serves only such accounts, while its
  [webhook setup page](https://developers.facebook.com/documentation/instagram-platform/webhooks/setup.md) lists
  Advanced Access and a live app for Instagram Login webhooks. Run a trial with a tester account before relying
  on either. This adapter polls and receives no webhooks.
* Requests are spaced per source; connection failures, 429, and 5xx are tried three times with backoff; bodies
  are limited to 4 MiB; text is stored without markup. Runs record short error codes, never response text.

Why the Smart Store switch exists: Commerce API support answered on
[2026-03-04](https://github.com/commerce-api-naver/api-agency/discussions/809) that providing, transferring, or
entrusting an own-store application to a third party may breach the service terms. The answer of
[2026-11-09](https://github.com/commerce-api-naver/commerce-api/discussions/3967) says the same of a seller who puts
their own key into somebody else's program, because operation is then entrusted to that program. `type=SELF` is
only for a seller who builds and runs the integration for their own store, and an individual business has no other
route for now. 공도리 must not take another store owner's key. Its official route is to apply for a Commerce solution
or API agency, and only a domestic corporation can apply. Both answers were read in the project's research notes
on 2026-11-22; read them again before changing this rule.

Mapping: an inquiry, or an Instagram comment that asks something, becomes a waiting inquiry with an empty draft.
A store order becomes an order under a local order number. A collected row is updated only while its revision
is 0, so owner work is never overwritten. Seed inquiries and seed orders of a channel stay until the first real
row of that kind arrives for the channel; then seed rows with revision 0 are removed, and `seed.py` keeps them out.

Channel label: `GET /channels` shows the result of the source's last check, not of this moment. A run that collects
at least one item sets its channel to 연결됨. A run that finds setup missing or switched off, or is refused, sets it
to 아직 연결 안 됨; a temporary failure leaves it alone. Only the Instagram, Smart Store, and blog channels follow a
collector, so 네이버 예약 is never changed.

VPC deployment: the collectors run on the API server inside the NCP VPC and need outbound HTTPS only
(`graph.instagram.com`, `api.commerce.naver.com`, and a feed host if one is turned on). They open no port, so no
inbound rule changes. Install the timer once, by hand, after a release that contains it:

```sh
sudo install -m 644 /opt/gongbang/current/collectors.{service,timer} /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now collectors.timer
```

`deploy.sh` refreshes the two unit files only where the timer is installed, and otherwise leaves systemd alone.

For isolated database test details see [tests/README.md](tests/README.md).
