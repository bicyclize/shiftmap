# shiftmap

**Which car trips could already be a bike — or a bike and a train?**

`shiftmap` answers that question from real mobile GPS traces and shows *where* the opportunity is, so a city knows which streets to put cycling infrastructure on first.

It reconstructs every trip as a **routed** path on the real road and rail networks (never a straight line between origin and destination), classifies each trip by the alternatives that could plausibly serve it, and renders the result in the browser.

- **bike** — origin→destination ≤ 5 km
- **bike + train + bike** — cycle to a station, train, cycle on
- **bike + train + foot** — cycle to a station, train, walk

## Live demo

**https://bicyclize.github.io/shiftmap/**

## How it runs

Entirely static — no backend, no build step. The browser parses the Parquet files with a vendored reader and does all filtering and rendering with MapLibre. Serve with any static file server:

```bash
python3 -m http.server 8765   # then open http://localhost:8765
```

## Data

One week of anonymised mobile GPS traces (May 2023, Budapest, ~440,000 trips), owned by Bicyclize.
The trip-level Parquet files live in this repo; the raw pings and the build databases do not (they
stay on the build machine under `data/` and `db/`). See `docs/platform.md` for the method and
`docs/Budapest transport analysis.md` for the analysis log.

## Build pipeline

`scripts/` holds the pipeline that produces the Parquet files from raw traces + OpenStreetMap + GTFS
turn-restriction data. It runs on macOS with `uv run --with duckdb …` and is documented, not turnkey.

## Honest framing

The tool reports **which trips could plausibly have been done** by bike or bike+train — never that they
*were*. It makes relative, spatial claims ("these corridors concentrate the opportunity"), not
city-wide volumes or mode-share estimates that a ~1% device panel cannot support.

The Mapbox access token in `style.json` is a public (`pk.`) token, scoped in the Mapbox dashboard.
