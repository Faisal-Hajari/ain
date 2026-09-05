# AIN backend

the backend for the front end only data fetching and reading. everything that
feeds the database is running on other micro-services.

Right now every route answers with **deterministic dummy data** so the
dashboard can be built against the real response shapes. The catalogue in
`ain_backend/catalogue.py` is the transcription of the KPI & element
catalogue; `ain_backend/dummy.py` is the only module that invents values and
is the piece the real read models replace.

## Run it

```bash
uv run uvicorn ain_backend.main:app --reload --port 8000
```

Interactive schema: <http://localhost:8000/docs>.

```bash
uv run pytest
```

## Endpoints

| Route | Returns |
| --- | --- |
| `GET /health` | liveness, and which data source is behind the API |
| `GET /api/catalogue` | cameras, filter options and every section in one call |
| `GET /api/cameras` | the camera layout as installed at the branch |
| `GET /api/filters` | options for branch, venue type, date range, language |
| `GET /api/sections` | catalogue sections and the elements they group |
| `GET /api/sections/{section_id}` | one section |
| `GET /api/elements?section=&camera=` | catalogue entries, optionally narrowed |
| `GET /api/elements/{element_id}` | one catalogue entry |
| `GET /api/elements/{element_id}/data` | the payload drawn for that element |
| `GET /api/elements/{element_id}/instances` | instance log behind an alert card |
| `GET /api/alerts?limit=` | newest occurrences across every alerting element |
| `GET /api/employees` | derived timesheet for the rostered staff |

## Filters

Every data route takes the global filters as query parameters, and they stack:

```
?branch=riyadh-01&venue_type=cafe&range=7d&language=en
```

`range` is one of `today`, `yesterday`, `7d`, `30d`, or `custom` with
`start` and `end` ISO timestamps. An unknown range is a `400`.

Dummy values are seeded from the element, the filters and the window, so the
same request always answers the same numbers while changing a filter visibly
moves them.

## Payload shapes

`GET /api/elements/{id}/data` returns one `ElementData`. Which fields are
populated follows the element's `value_kind`:

| `value_kind` | populated | renders as |
| --- | --- | --- |
| `count` | `scalar` (window total) + `series` | KPI card with a trend line |
| `people` | `scalar` (latest) + `series` | live KPI card |
| `percent` | `scalar` + `series`, clamped to 0-100 | gauge |
| `duration` | `scalar` (window mean) + `series` | KPI card |
| `clock_time` | `text` (`HH:MM`) | first-seen / last-seen card |
| `distribution` | `buckets` + `scalar` (total) | bar, donut or histogram |

Elements with `has_instances` are clickable: their instance log carries a
timestamp, a camera id, a duration and `clip_url` / `thumbnail_url`. The clip
URLs are placeholders — no media is served yet.

`kitchen-operations` is served as an empty section: the catalogue does not
define its elements yet, and the front end should reserve the slot.
