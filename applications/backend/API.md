# Backend requirements — AIN dashboard API

What `applications/frontend` needs to render. The frontend is a
renderer with no domain knowledge: it can draw a line chart or a KPI card, but
it does not know what "footfall" means, how a percentage is computed, or which
direction is good news. **Everything in this document is the backend's job.**

The authoritative types are [`applications/frontend/src/api/types.ts`](../frontend/src/api/types.ts).
This document explains them; where the two disagree, the TypeScript wins.
A complete reference implementation lives in `applications/frontend/src/mocks/`
— it serves every endpoint below and can be diffed against.

---

## 1. Principles

These are requirements, not preferences. The frontend has no code to fall back
on if they are not met.

1. **The backend owns the layout.** Which tabs exist, which cards are on them,
   what each card is called and how much grid space it takes — all of it comes
   from `GET /dashboard/config`. Adding, removing or renaming a KPI must need no
   frontend change.
2. **The backend owns all user-facing text.** Titles, descriptions, axis labels,
   series names, status words, table headers. The frontend's own dictionary
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
| Auth | **Open question — see §9.** Nothing is sent today. |

### Errors

Any non-2xx makes the affected card show its own error state with a Retry
button; the rest of the dashboard keeps working. One failing element must never
fail the whole response.

- `GET /dashboard/config` failing blanks the app — treat it as the critical path.
- A single element endpoint failing degrades one card only.
- `204 No Content` is accepted for `DELETE`.
- An error body is not parsed; the status code is what matters. Return a JSON
  body anyway for logs and debugging.
- A payload that parses but is malformed — a `heatmap` whose rows do not match
  its labels, a `table` with no columns — is caught by a per-card error boundary
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

## 4. Endpoints

### 4.1 `GET /api/dashboard/config?lang=`

The whole navigation and layout. Called once per language, cached 5 minutes.

```jsonc
{
  "branchLabel": "Riyadh - Olaya",   // localized, shown under the app name
  "today": "2026-09-05",             // ISO date, the backend's today
  "filters": [ /* FilterDef[] */ ],
  "sections": [ /* SectionDef[] */ ]
}
```

**`today` is required.** The date picker is drawn from it, never from the
browser clock — that keeps rendering deterministic and makes the branch's
timezone authoritative rather than the viewer's.

**`FilterDef`**

```jsonc
{
  "id": "range",                     // the URL search-param key this filter owns
  "label": "Date range",             // localized
  "control": "date-range",           // "select" (default) | "date-range"
  "defaultValue": "today",
  "options": [ { "value": "7d", "label": "Last 7 days" } ]
}
```

`control: "date-range"` renders the presets as quick buttons plus a month
calendar; picking a day sends that ISO date as the filter's value. Days after
`today` are disabled.

**`SectionDef`** — one nav tab.

```jsonc
{
  "id": "customer",
  "title": "Customer intelligence",
  "description": "Information about the customers.",
  "view": "grid",                    // "grid" (default) | "alerts"
  "elements": [ /* ElementDef[] */ ]
}
```

`view: "alerts"` puts the alert-rule builder and the saved-rule list above the
card grid. Exactly one section should use it.

**`ElementDef`** — one card.

```jsonc
{
  "id": "queue-wait-time",           // stable; also the data endpoint's path segment
  "title": "Queue wait time",
  "description": "Time customers spent in queue.",
  "type": "kpi",                     // picks the renderer, see §5
  "kind": "monitor",                 // "monitor" | "alert" — badge, and alert-builder eligibility
  "updates": "event",                // polling cadence, §2
  "span": 2,                         // grid columns 1-4, default 1
  "cameras": ["03", "11"],           // chips in the footer
  "drilldown": "instances"           // adds the "view instances" action
}
```

Requirements:

- **`id` must be stable and globally unique.** It is the cache key and the data
  endpoint's path segment.
- **The same element may appear in more than one section** — Overview reuses
  cards from the other tabs. Return the *same* id, and both tabs share one cache
  entry and can never disagree. Do not mint `overview-queue-length`.
- **`kind: "monitor"`** makes the element eligible for the alert builder
  (§4.4). `kind: "alert"` marks it as a count of occurrences.
- `type` must be one the frontend renders (§5). An unknown type renders nothing.

### 4.2 `GET /api/elements/:id?<filters>`

The payload for one card, already shaped for its `type`.

```jsonc
{
  "elementId": "queue-wait-time",
  "updatedAt": "2026-09-05T11:04:00Z",  // when the DATA was computed, not the request
  "type": "kpi",                        // must match the config's type for this id
  "data": { /* shape per §5 */ }
}
```

### 4.3 `GET /api/elements/:id/instances?<filters>`

The drilldown behind any element with `drilldown: "instances"` — the catalog's
"click a card, get the occurrences and their clips".

```jsonc
{
  "elementId": "congestion-count",
  "title": "Congestion count",
  "total": 6,                        // total in range, may exceed instances.length
  "instances": [
    {
      "id": "congestion-count-0",
      "timestamp": "20:18",          // PRE-FORMATTED for display, branch-local
      "camera": "Camera 11",         // localized label, not a bare id
      "detail": "Occupancy passed 90% with a growing queue.",
      "severity": "critical",
      "clipUrl": "/api/clips/congestion-count/0.mp4",
      "thumbnailUrl": null
    }
  ]
}
```

- `total` is displayed separately from the list, so a truncated list is fine —
  but there is **no pagination UI today** (§9).
- `clipUrl` must be directly loadable by the browser with the session's
  credentials. It is rendered as a link.

### 4.4 `GET /api/alerts/monitors?<filters>`

Everything the alert builder can watch. Should be every element with
`kind: "monitor"` that carries a numeric value.

```jsonc
{
  "monitors": [
    {
      "id": "live-occupancy",
      "label": "Live occupancy",
      "unit": "people",
      "monthlyAverage": "46",        // PRE-FORMATTED, shown to the user
      "monthlyAverageValue": 46,     // numeric, prefills the threshold input
      "trend": {                     // last 30 days, drawn under the average
        "series": [{ "id": "value", "label": "Live occupancy", "colorIndex": 0 }],
        "points": [{ "x": "D-29", "value": 41 }]
      }
    }
  ]
}
```

**The 30-day average is a hard requirement** — the UI shows it while the user
picks a threshold, and prefills the input with `monthlyAverageValue` so the
default rule is "alert when it leaves normal". For a duration monitor,
`monthlyAverage` is a formatted duration (`"4m 12s"`) while
`monthlyAverageValue` is the number the threshold is compared in (minutes,
seconds — your choice, but be consistent with what the rule stores).

### 4.5 `GET /api/alerts/rules?<filters>`

```jsonc
{
  "rules": [
    {
      "id": "b1f2…",
      "monitorId": "live-occupancy",
      "monitorLabel": "Live occupancy",   // localized at read time
      "comparator": "above",
      "threshold": 46,
      "unit": "people",
      "summary": "Above 46",              // PRE-FORMATTED sentence, localized
      "createdLabel": "Created today"     // PRE-FORMATTED, localized
    }
  ]
}
```

**Rules must be stored language-neutrally and localized on read.** A rule
created in Arabic and read in English must come back in English — the frontend
verifies nothing and prints `monitorLabel`, `summary` and `createdLabel`.

### 4.6 `POST /api/alerts/rules?<filters>`

Body:

```jsonc
{ "monitorId": "live-occupancy", "comparator": "above", "threshold": 46 }
```

Returns the created `AlertRule` (§4.5 shape). The frontend then re-reads the
list — it does not merge the response into a local copy — so returning the
canonical record matters more than returning it fast.

Validation is the backend's: reject an unknown `monitorId` or a nonsensical
threshold with a 4xx. The form only enforces "a number, ≥ 0".

### 4.7 `DELETE /api/alerts/rules/:id`

`204` or the deleted record. The list is re-read afterwards.

### 4.8 Media

Referenced from payloads, fetched directly by the browser:

- `streamUrl` on a camera feed — a live stream for the tile. HLS (`.m3u8`) is
  assumed; **no player is wired up** (§9).
- `thumbnailUrl` on a camera feed or instance — a still image. When absent the
  tile draws a placeholder.
- `clipUrl` on an instance — the recorded clip for that occurrence.

---

## 5. Payload shape per element type

`data` is discriminated by `type`. The frontend renders exactly these.

### `kpi` — one headline number

```jsonc
{
  "value": "16",                     // string, pre-formatted
  "unit": "people",                  // optional, printed after the value
  "severity": "critical",            // colours the number
  "delta": {
    "label": "-30%",                 // pre-formatted
    "direction": "down",             // picks the ▲ ▼ ■ glyph
    "sentiment": "ok"                // colours the pill: is this direction good news?
  },
  "trend": { "series": [ … ], "points": [ … ] }   // optional in-card chart
}
```

`direction` and `sentiment` are separate on purpose: a falling alert count is
`direction: "down"`, `sentiment: "ok"`; a falling footfall is
`direction: "down"`, `sentiment: "warn"`. **Only the backend knows which.**

### `stat-group` — several related numbers on one card

```jsonc
{
  "stats": [
    { "id": "total",   "label": "Total",   "value": "44", "delta": { … } },
    { "id": "indoor",  "label": "Indoor",  "value": "29" },
    { "id": "outdoor", "label": "Outdoor", "value": "15" }
  ],
  "trend": {
    "series": [
      { "id": "total",   "label": "Total",   "colorIndex": 0 },
      { "id": "indoor",  "label": "Indoor",  "colorIndex": 1 },
      { "id": "outdoor", "label": "Outdoor", "colorIndex": 2 }
    ],
    "points": [{ "x": "08:00", "total": 44, "indoor": 29, "outdoor": 15 }]
  }
}
```

The first stat renders largest. Where the stats are parts of a whole (occupancy
total / indoor / outdoor), **the trend series must agree with the numbers** —
same ids, and the last point should match the headline values.

### `line` · `bar` · `stacked-bar` · `histogram` — one shape, four renderings

```jsonc
{
  "series": [{ "id": "value", "label": "Footfall", "colorIndex": 0 }],
  "points": [{ "x": "08:00", "value": 62 }],   // x is the pre-formatted axis label
  "xLabel": "Hour",                            // axis title — see below
  "yLabel": "Count",
  "unit": "people"
}
```

- Each `points[]` entry has `x` plus one key per series id.
- **`xLabel` and `yLabel` are required in practice.** Every chart draws both
  axes with titles; omitting them leaves an axis unlabeled.
- `stacked-bar` stacks all series; the others draw them side by side. A legend
  appears automatically when there is more than one series.
- `x` values are display strings the backend chooses: `"08:00"`, `"Mon"`,
  `"D-29"`, `"0-10"`. Their order in the array is the order drawn.

### `gauge` — a value in a range

```jsonc
{
  "value": 78, "min": 0, "max": 100, "unit": "%",
  "valueLabel": "78%",                 // pre-formatted, the big number
  "minLabel": "0%", "maxLabel": "100%",// pre-formatted range ends, both or neither
  "severity": "warn"
}
```

`value`, `min` and `max` are numbers because the arc maths runs on them.
`valueLabel`, `minLabel` and `maxLabel` are what gets printed — the frontend does
not format them, so an unlabeled range isn't drawn.

### `donut` — parts of a whole

```jsonc
{
  "slices": [{ "id": "male", "label": "Male", "value": 62, "colorIndex": 0 }],
  "centerLabel": "Total",
  "centerValue": "171"
}
```

### `heatmap` — a matrix

```jsonc
{
  "xLabels": ["08", "09"],
  "yLabels": ["Mon", "Tue"],
  "cells": [[12, 30], [8, null]],    // row-major, cells[y][x]; null = no data
  "unit": "people"
}
```

`cells.length` must equal `yLabels.length`, and each row's length must equal
`xLabels.length`.

### `alert` — a live state, not a count

```jsonc
{
  "severity": "critical",
  "headline": "Active now",
  "detail": "The till has been unmanned.",
  "meta": "since 14:02"              // pre-formatted
}
```

### `table`

```jsonc
{
  "columns": [{ "key": "camera", "label": "Camera", "align": "start" }],
  "rows": [{ "camera": "Camera 03", "zone": "Indoor entrance." }]
}
```

Row order is preserved exactly as sent. `align: "end"` right-aligns and
tabular-numbers a column. Missing keys render as `-`.

### `camera-grid`

```jsonc
{
  "feeds": [
    {
      "id": "03",
      "label": "Camera 03",          // localized
      "zone": "Indoor entrance and lobby / waiting area.",
      "status": "online",            // "online" | "offline"
      "statusLabel": "Online",       // localized
      "streamUrl": "/api/cameras/03/stream.m3u8",
      "thumbnailUrl": null
    }
  ]
}
```

`status` drives the colour; `statusLabel` is what is printed. Send both.

---

## 6. Localization

`lang` is sent on **every** request, including element payloads and the alert
endpoints. The response must be fully localized:

- section and element titles and descriptions
- stat labels, series labels, axis titles, table headers, slice labels
- formatted values, including durations — `"4m 49s"` in English,
  `"4 د 49 ث"` in Arabic
- camera labels, status words, alert headlines, `summary`, `createdLabel`

Arabic renders right-to-left; the frontend sets `dir="rtl"` on the document. No
special response handling is needed for direction — send Arabic text.

**Switching language must not change the numbers.** The user sees titles
re-render while values stay put. If your generator seeds on the request, exclude
`lang` from the seed.

---

## 7. Consistency requirements

1. **`type` in the element response must match `type` in the config** for that
   id. A mismatch renders the wrong component or nothing.
2. **The same id returns the same data** regardless of which section asked. The
   frontend caches by `(id, filters)` and shares that entry across tabs.
3. **`updatedAt` is the data's timestamp**, not the response's. It is what tells
   an operator how stale a card is.
4. **Numbers are numbers, strings are strings.** `points[].value` is numeric —
   the chart maths runs on it. `stats[].value` is a string — it is printed.
   Do not send `"44"` where a number is expected or `44` where a string is.
5. **Empty is not an error.** A section with no elements, a table with no rows,
   an instance log with none — all render their own empty state. Return the
   envelope with an empty array rather than a 404.

---

## 8. Reference implementation

`applications/frontend/src/mocks/` serves this entire contract in-browser when
`VITE_API_MOCK=true`:

| File | What it shows |
| --- | --- |
| `config.ts` | A full `DashboardConfig` — five sections, the element registry, localized filters |
| `payloads.ts` | A valid payload for **every** element type, in both languages |
| `alerts.ts` | The monitors, rules store, and the language-neutral-storage rule from §4.5 |
| `index.ts` | The routing table — every path and method the frontend calls |

Running the frontend against it is the fastest way to see the expected shapes:

```bash
cd applications/frontend && npm ci && VITE_API_MOCK=true npm run dev
```

---

## 9. Open questions

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
