# Backend requirements — AIN dashboard API

What `applications/frontend` needs to render. The frontend is a
renderer with no domain knowledge: it can draw a line chart or a KPI card, but
it does not know what "footfall" means, how a percentage is computed, or which
direction is good news. **Everything in this document is the backend's job.**

The authoritative types are [`applications/frontend/src/api/types.ts`](../frontend/src/api/types.ts).
This document explains them; where the two disagree, the TypeScript wins.
A complete reference implementation lives in `applications/backend` — it serves
this entire contract and can be diffed against.

---

## 1. Principles

These are requirements, not preferences. The frontend has no code to fall back
on if they are not met.

1. **The backend owns the layout.** Which tabs exist, which cards are on them,
   what each card is called and how much grid space it takes — all of it comes
   from `GET /dashboard/config`. Adding, removing or renaming a KPI must need no
   frontend change.
2. **The backend owns all user-facing text.** Titles, descriptions, axis labels,
   series names, status words. The frontend's own dictionary
   covers about two dozen chrome strings (Close, Retry, Settings) and nothing
   else.
3. **The backend owns all formatting.** Values arrive as display strings:
   `"42"`, `"4m 49s"`, `"+12%"`, `"—"`. The frontend never rounds, never
   converts units, never builds a duration, never formats a percentage.
4. **The backend owns all judgement.** Whether a number is good or bad
   (`sentiment`), whether a state is warning or critical (`severity`), what the
   threshold for "long wait" is. The frontend maps `severity` to a colour and
   stops there.
5. **The backend owns state.** The dashboard holds no client state of its own —
   no store, and not a single `useState`. Server data lives in a query cache;
   everything else (open dialog, selected filters, in-progress form) is a URL
   search param. Anything that must persist is a backend record.

---

## 2. Transport

| | |
| --- | --- |
| Base path | `/api` — nginx in the frontend image proxies `/api/` to `http://backend:8000/api/` |
| Content type | `application/json; charset=utf-8` |
| Methods used | `GET`, `POST`, `DELETE` |
| Auth | **Open question — see §8.** Nothing is sent today. |

### Errors

Any non-2xx makes the affected card show its own error state with a Retry
button; the rest of the dashboard keeps working. One failing element must never
fail the whole response.

- `GET /dashboard/config` failing blanks the app — treat it as the critical path.
- A single element endpoint failing degrades one card only.
- `204 No Content` is accepted for `DELETE`.
- An error body is not parsed; the status code is what matters. Return a JSON
  body anyway for logs and debugging.
- A payload that parses but is malformed — a `stat-group` whose trend series do
  not name its stats, a `camera-grid` feed with no status — is caught by a
  per-card error boundary
  and degrades that card alone. Do not rely on this; it is a backstop, not a
  contract.

### Timeouts and polling

The frontend polls per element according to its `updates` cadence:

| `updates` | Poll interval | Meaning |
| --- | --- | --- |
| `realtime` | 15s | Live value; the card shows a pulsing "Live" dot |
| `event` | 60s | Recomputed per detected event |
| `visit` | 120s | Recomputed per completed visit |
| `hourly` | 5min | Rolled up hourly |
| `daily` | 15min | Rolled up daily |
| `static` | never | Fetched once (reference data) |

This table is pinned by a test (`src/api/queries.test.ts`), so the intervals here
and the intervals the app actually uses cannot drift apart silently.

Element responses must be cheap enough to serve at these rates for every card on
a tab at once. If a KPI cannot sustain 15s, give it a slower cadence rather than
a slow response.

---

## 3. Global query parameters

Every data request carries the active filters. The frontend sends whatever
filter ids the config declared, plus `lang`, and does not interpret them.

| Param | Values | Notes |
| --- | --- | --- |
| `branch` | `olaya` \| `malaz` \| `all` | Whatever the config's option values are |
| `venue` | `cafe` \| `kitchen` \| `fnb` \| `drive-thru` \| `all` | Same |
| `range` | `today` \| `7d` \| `30d` \| `YYYY-MM-DD` | **An ISO date means "from that day to today".** The calendar writes it directly |
| `lang` | `en` \| `ar` | Selects the response language |

Params are sorted and sent identically on every call, so they are safe to use in
a cache key. Unknown params (`expanded`, `settings`, `calendar`, …) are UI state
and are **not** sent — ignore them if you see them.

---

## 4. Endpoints and payload shapes

The service publishes its own schema. Run it and read
[`/docs`](http://localhost:8000/docs), or fetch `/openapi.json`: every route,
every query parameter and every payload shape per element type is generated
from `ain_backend/models.py`, so it cannot drift from what the service returns.

`data` is discriminated by the element's `type`, and the frontend renders
exactly the types the config declares - no more.

---

## 5. Localization

`lang` is sent on **every** request, including element payloads and the alert
endpoints. The response must be fully localized:

- section and element titles and descriptions
- stat labels, series labels and axis titles
- formatted values, including durations — `"4m 49s"` in English,
  `"4 د 49 ث"` in Arabic
- camera labels, status words, alert headlines, `summary`, `createdLabel`

Arabic renders right-to-left; the frontend sets `dir="rtl"` on the document. No
special response handling is needed for direction — send Arabic text.

**Switching language must not change the numbers.** The user sees titles
re-render while values stay put. If your generator seeds on the request, exclude
`lang` from the seed.

---

## 6. Consistency requirements

1. **`type` in the element response must match `type` in the config** for that
   id. A mismatch renders the wrong component or nothing.
2. **The same id returns the same data** regardless of which section asked. The
   frontend caches by `(id, filters)` and shares that entry across tabs.
3. **`updatedAt` is the data's timestamp**, not the response's. It is what tells
   an operator how stale a card is.
4. **Numbers are numbers, strings are strings.** `points[].value` is numeric —
   the chart maths runs on it. `stats[].value` is a string — it is printed.
   Do not send `"44"` where a number is expected or `44` where a string is.
5. **Empty is not an error.** A section with no elements, a camera grid with no
   feeds, an instance log with none — all render their own empty state. Return
   the envelope with an empty array rather than a 404.

---

## 7. Reference implementation

`applications/backend` serves this entire contract. Running it is the fastest
way to see the expected shapes:

```bash
cd applications/backend && uv run uvicorn ain_backend.main:app --reload --port 8000
```

Every route, query parameter and payload shape is published at
[`/docs`](http://localhost:8000/docs). Alert rules are held in a process-local
dict, so a restart clears them; everything else is a pure function of the query
string.

---

## 8. Open questions

These need a decision before the backend is done. The frontend has no position
on them.

1. **Authentication.** Nothing is sent today — no header, no cookie handling, no
   401 flow, no login screen. If the API needs auth, that is a frontend change
   as well as a backend one.
2. **Multi-branch scoping.** `branch=all` is an option; whether an element rolls
   up across branches or returns per-branch series is undecided.
3. **Instance-log pagination.** `total` can exceed the returned list, but there
   is no "load more" control. Either cap the list and accept it, or say how many
   you will return.
4. **Alert-rule evaluation.** The frontend creates and lists rules; nothing
   defines what happens when one fires — no notification channel, no fired-alert
   feed, no acknowledge flow.
5. **Camera streaming.** `streamUrl` is in the contract but no player is wired
   up; the tiles show a placeholder. The stream format and auth model need
   deciding before that is built.
6. **Rule scoping.** Rules are created with the active filters in the query
   string. Whether a rule belongs to a branch, a venue type, or the account is
   not specified.
7. **Timezone.** `today` and all pre-formatted timestamps are assumed to be in
   the branch's local time. Confirm.
