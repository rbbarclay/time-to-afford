# PROJECT.md

## Purpose

Show how many hours of work it takes to afford common expenses in each U.S. metro area.

## Current state

- Scaffolding in place: folder structure, docs, license.
- **Wage module done** (`pipeline/wages.py`). It writes `data/wages.json`: May 2025 OEWS, 393 MSAs (including Puerto Rico), with hourly median, hourly mean and employment for all occupations. Each value is `{value, status}`, where status is `ok`, `missing` or `top_coded`.
- **Rent module done** (`pipeline/rent.py`). It writes `data/rent.json`: ACS 2025 1-year table B25031, 393 metros (the same codes as wages), with median gross rent for all units, 1 bedroom and 2 bedrooms, each with a margin of error. Each value is `{value, moe, status}`.
- Setup: `uv venv .venv && uv pip install -p .venv -r pipeline/requirements.txt`
- Run: `BLS_CONTACT=<email> .venv/bin/python pipeline/wages.py` (or `--file <oesmYYma.zip>`). `.venv/bin/python pipeline/rent.py` (or `--year`, `--file/--geos-file`). Tests: `.venv/bin/pytest pipeline`

## Decisions

- **Architecture:** a static site. A Python pipeline writes JSON files that the site reads.
- **No database, user accounts, or runtime API** in v1.
- **v1 metrics:** wage (BLS OEWS), rent (Census ACS), gas (EIA). Groceries and dinner out come later.
- **License:** MIT for code. The repo is public.
- **Wage privacy:** wage math runs only in the browser. A user's wage is never put in URLs or stored on a server.
- **Map:** dots at metro centers, all the same size. Metros with no data get a hollow or gray dot. The legend shows the actual min and max values.
- **Tooltips** show the inputs used and their as-of dates.
- **Metro key:** 5-digit CBSA code, shared by OEWS and ACS. OEWS nonmetropolitan areas (area type 6) are excluded.
- **Wage scope:** all-occupations rows only for now. Per-occupation wages will be added when feature 4 needs them.
- **Rent:** ACS 1-year median gross rent (includes utilities), from the table-based summary files rather than the API, which needs a key. The front end defaults to **all units**, with a selector for 1 bedroom or 2 bedrooms. `rent.json` lists the options in `measures` and `default_measure`.
- **Metro names:** ACS names keep accents (e.g. "Mayagüez") and OEWS names don't. The front end should take display names from a single source.
- **BLS downloads:** the User-Agent is `time-to-afford/0.1 (contact: <email>)`. The email comes from `BLS_CONTACT` or `--contact` and is never committed. BLS rejects User-Agents that contain a URL.

## Feature order

1. **Your wages mode,** with a "use prices from this metro" selector
2. Comparison
3. Map
4. Occupation-based move scenario

## Known data constraints

- OEWS data lags about a year.
- EIA gas prices cover only about a dozen metros.
- No good metro-level sources exist yet for groceries or dinner out.
- v1 uses pre-tax wages only.

## To-do

- [x] Wage module (OEWS)
- [x] Rent module (ACS)
- [ ] Gas module (EIA)
- [ ] Validate about 10 metros end to end
- [ ] Front end: your wages mode (include a rent selector: all units by default, 1 bedroom, 2 bedrooms)
- [ ] Methodology page
- [ ] Choose hosting
