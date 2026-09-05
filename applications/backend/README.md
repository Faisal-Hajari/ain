# AIN backend

The read side of the AIN dashboard: layout, KPI payloads and alert rules.
Everything that feeds the database runs in other microservices.

Values are placeholders — deterministic, generated per request from the
element id and the active filters. `ain_backend/payloads.py` is the only
module that invents a number; replacing it with real read models leaves the
contract, the catalogue and the routes untouched.

The service implements `applications/frontend/src/api/types.ts`. The frontend
is a renderer with no domain knowledge, so this backend owns the layout, every
user-facing string, all formatting, and every judgement about whether a number
is good news.

## Run it

The service needs [uv](https://docs.astral.sh/uv/). From
`applications/backend`, start a reloading dev server on port 8000:

```bash
uv run uvicorn ain_backend.main:app --reload --port 8000
```

To run the contract tests:

```bash
uv run pytest
```

To browse the schema and try requests, open the
[API docs](http://localhost:8000/docs).

## Endpoints

The service exposes these routes:

| Route | Returns |
| --- | --- |
| `GET /health` | liveness, and which data source is behind the API |
| `GET /api/dashboard/config` | the whole navigation and layout, localised |
| `GET /api/elements/{id}` | one card's payload, shaped for its `type` |
| `GET /api/elements/{id}/instances` | the occurrences behind an alert card |
| `GET /api/alerts/monitors` | what a rule can watch, with 30-day averages |
| `GET /api/alerts/rules` | stored rules, localised at read time |
| `POST /api/alerts/rules` | creates a rule, returns the canonical record |
| `DELETE /api/alerts/rules/{id}` | `204`, whether or not it existed |

Query parameters on every data route: `branch`, `venue`, `range`, `lang`.
`range` is `today`, `7d`, `30d`, or an ISO date meaning "from that day to
today". Unknown parameters are ignored.

## Where things live

Each module owns one concern:

| Module | Owns |
| --- | --- |
| `models.py` | the wire contract; snake_case here, camelCase on the wire |
| `catalogue.py` | cameras, filters, elements, sections — the layout |
| `i18n.py` | every localised string that is not an element title |
| `formatting.py` | display strings and judgement (`severity`, `sentiment`) |
| `payloads.py` | the placeholder generator, one builder per element type |
| `alerts.py` | monitors, and the in-process rule dict |
| `main.py` | routes |

Adding a KPI is one `ElementSpec` in `catalogue.py` plus, if it needs a shape no
builder covers, a branch in `payloads.py`. No frontend change.

## Stateless, with one exception

Every read route is a pure function of the query string, so any replica can
answer any request and nothing needs sticky sessions.

Alert rules cannot be: the frontend keeps no copy, so a rule it POSTs has to
come back from the next `GET`. `alerts.RULES` is a process-local dict — it
does not survive a restart, and two replicas would disagree. The `TODO` at the
top of `alerts.py` marks it as the one thing a real deployment has to replace.

## Determinism

Payloads are seeded on `(element id, filters)`. The same request always answers
the same numbers, so cards do not flicker between polls and screenshots stay
comparable. `lang` is excluded from the seed: switching language re-labels a
card without moving a single value.

`updatedAt` is the data's timestamp, not the response's — it is floored to the
element's cadence, so a card polled every 15s reports a stamp that only moves
when the data would have.

## Decisions taken on the open questions

The requirements document leaves seven open. Where this backend had to pick:

- **Timezone** — `Asia/Riyadh`. `today`, `createdLabel` and every pre-formatted
  timestamp are branch-local (`catalogue.BRANCH_TIMEZONE`).
- **Instance pagination** — capped at 12 per element. `total` equals the list
  length, so nothing is silently dropped.
- **Multi-branch scoping** — `branch=all` re-seeds the generator; it does not
  roll up or split per branch.
- **Rule scoping** — the active `branch` and `venue` are stored on the rule but
  do not filter the list.
- **Auth** — none. No header is read, nothing is rejected.
- **Media** — `clipUrl`, `streamUrl` and `thumbnailUrl` are placeholders. The
  service serves no media, so those paths answer `404`; a click renders a
  broken link, not a broken page.
- **Alert-rule evaluation** — nothing fires. Rules are stored and listed only.

## Docker

To build the image and run it on port 8000:

```bash
docker build -t ain-backend:dev . && docker run --rm -p 8000:8000 ain-backend:dev
```

The repository root's `docker-compose.yml` runs this image alongside the
dashboard and the camera server, with CORS pointed at a local dashboard dev
server; `docker compose up --build` from the root brings the whole stack up.
The `build-images` workflow publishes the image on every push to `main`.
