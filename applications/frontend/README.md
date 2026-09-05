# AIN dashboard - frontend

The dashboard front end. No business logic here: just visualization and
reusable components, in card-style layout.

Every view is rendered from what the backend sends. The frontend knows how to
draw a **line chart** or a **KPI card**; it does not know what "footfall" is.
Adding, removing or renaming a metric from the KPI catalogue is a backend
change and needs no code here.

## Scope

Five tabs, all declared by the backend:

| Tab | What it holds |
| --- | --- |
| Overview | A quick look across the branch, reusing cards from the other tabs |
| Customer intelligence | Live occupancy (total / indoor / outdoor on one card) · Footfall · Queue length · Queue wait time · Dwell time per table · Congestion count · Empty-restaurant count · Long-wait count |
| Employee monitoring | No-gloves count · No-hair-cover count · No-mask count |
| Cameras | Feed health and a tile per camera feed |
| Alerts | Every alert count, plus the rule builder |

Elements are declared once and referenced by id, so a KPI shown on Overview and
on its own tab is the same definition sharing one cache entry - the two tabs can
never disagree.

Each element is a **monitor** (tracks a value) or an **alert** (counts
occurrences and opens an instance log); the card badges which. Clicking a card
pops it out into a large dialog - same query, same numbers, more room for the
chart - and the header's expand button is the keyboard path to it. The renderer
supports every element type in the contract - gauge, donut, heatmap, table, bar
and stacked-bar views ship unused, ready for the next batch of KPIs.

## Stack

React 19 (compiler enabled) · TypeScript · Vite · Tailwind CSS v4 ·
TanStack Query · React Router · Recharts.

## Run it

```bash
npm install
VITE_API_MOCK=true npm run dev
```

`VITE_API_MOCK=true` serves every `/api` call from `src/mocks/`, a deterministic
transcription of the KPI catalogue, so the UI runs with no backend. Drop the
flag (see `.env.example`) and Vite proxies `/api` to `VITE_API_TARGET`.

```bash
npm run build       # type-check + production bundle
npm run typecheck
npm run lint
```

## The contract

`src/api/types.ts` is the single source of truth and the spec the backend has to
meet. Three endpoints:

| Endpoint | Returns |
| --- | --- |
| `GET /api/dashboard/config` | `DashboardConfig`: the filter list and the sections, each with its elements |
| `GET /api/elements/:id?<filters>` | `ElementResponse`: a payload shaped for the element's `type` |
| `GET /api/elements/:id/instances?<filters>` | `InstanceLog`: timestamp, camera and clip per occurrence |
| `GET /api/alerts/monitors?<filters>` | `AlertMonitor[]`: every monitor a rule can watch, each with its 30-day average and trend |
| `GET /api/alerts/rules?<filters>` | `AlertRule[]`: the saved rules |
| `POST /api/alerts/rules` | Creates a rule from `{ monitorId, comparator, threshold }` |
| `DELETE /api/alerts/rules/:id` | Removes one |

An `ElementDef` says what to draw and how it behaves:

```ts
{
  id: 'queue-length',
  title: 'Queue length',
  description: 'Customers waiting at the counter.',
  type: 'kpi',            // kpi | stat-group | gauge | line | bar | stacked-bar
                          // | histogram | donut | heatmap | alert | table
  kind: 'monitor',        // monitor | alert - drives the badge
  updates: 'realtime',    // sets the polling interval, nothing else
  span: 2,                // grid columns, 1-4
  cameras: ['03', '11'],  // chips in the card footer
  drilldown: 'instances', // adds the "view instances" action
}
```

Everything user-facing is authored server-side: titles, descriptions, formatted
values (`"3m 12s"`), deltas (`"+12%"` plus whether up is good news), and axis
labels. The frontend never formats a number, computes a percentage, or decides
that red means bad.

## Where things live

```
src/api/         contract types, fetch wrapper, TanStack Query hooks
src/components/ui/        card shell, chips, dialog, select, skeletons, palette
src/components/elements/  one view per element type + the type -> view switch
src/components/layout/    app shell, sidebar, section grid
src/features/filters/     URL-backed filter state and the filter bar
src/features/instances/   the instance-log drilldown
src/features/alerts/      the alert-rule builder and list
src/features/settings/    the settings dialog
src/pages/                RootLayout (fetches config) and SectionPage
src/mocks/                backend stand-in for VITE_API_MOCK=true
```

Three rules keep it that way:

- **`ElementBody` is the only place a type maps to a component.** A new element
  type is one `case` plus one view file.
- **Filters live in the URL** (`?branch=olaya&range=7d&lang=ar`), so a filtered
  view is shareable and survives a reload without a store.
- **The app has no state of its own.** There is not a single `useState`:
  server data lives in the query cache and everything else - which dialog is
  open, which day the calendar is showing, the half-filled alert form - is a
  search param. Alert rules are backend records: the UI POSTs a draft and
  re-reads the list, never keeping a copy.

  One consequence worth knowing: react-router resolves each `setSearchParams`
  against the current location instead of queueing it, so two writes in one
  handler would lose the first. `useUrlWriter` takes a patch object and writes
  the whole thing in one call - use it whenever a click changes more than one
  param.

## Filters and settings

Branch, venue type and date range slice every panel. The date range is a
calendar: quick presets for today / last 7 / last 30 days, and picking a day
sets it as the start date (value becomes an ISO date instead of a preset key).
The calendar draws from the backend's `today`, never the browser clock, so
rendering stays pure.

Language is a preference rather than a filter, so it sits in **Settings** at the
foot of the nav.

## Localisation

English and Arabic, with `dir="rtl"` applied to the document for Arabic.

Switching language re-fetches everything with `?lang=`, so **card content
changes too**, not just the chrome: titles, descriptions, stat labels, axis and
series labels, formatted durations (`4m 49s` / `4 د 49 ث`) and instance-log
rows all come back translated. The dictionary in `src/i18n/` covers UI chrome
only - about two dozen strings, plus the two fixed enums (severity and
monitor/alert) that are not backend text.

The mock backend localises the same way the real one must. Its generator seeds
on the filters *excluding* `lang`, so switching language re-labels a card
without moving its numbers.

## Container

`Dockerfile` builds the bundle and serves it from nginx, which proxies `/api/`
to the `backend` service. The repo workflow builds any `applications/*` folder
with a Dockerfile.
