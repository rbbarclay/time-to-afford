# PROJECT.md

## Purpose

Show how many hours of work it takes to afford common expenses in each U.S. metro area.

## Current state

- Scaffolding in place: folder structure, docs, license.
- **Wage module done** (`pipeline/wages.py`). It writes `data/wages.json`: May 2025 OEWS, 393 MSAs (including Puerto Rico), with hourly median, hourly mean and employment for all occupations. Each value is `{value, status}`, where status is `ok`, `missing` or `top_coded`.
- **Rent module done** (`pipeline/rent.py`). It writes `data/rent.json`: ACS 2025 1-year table B25031, 393 metros (the same codes as wages), with median gross rent for all units, 1 bedroom and 2 bedrooms, each with a margin of error. Each value is `{value, moe, status}`.
- **Gas module done** (`pipeline/gas.py`). It writes `data/gas.json`: EIA monthly average price of regular gasoline for October 2026, for the 10 metros EIA covers. Each value is `{value, status}`.
- **Validation done for all 393 metros** (`pipeline/validate.py`). It checks structure, that the three files cover the same metros, and plausible ranges. It also compares values with figures published separately: BLS API v1 medians (393/393 match), Census table B25064 (393/393 match) and EIA's HTML table (10/10 match). It writes `data/validation_report.csv`: one row per metro with inputs, as-of dates, hours, and the measures that are missing. 10 metros have every measure; 383 lack only gas. One warning to review: Ponce, PR has a 1-bedroom rent of $299, below the $300 lower bound. The value comes straight from Census and is kept as is.
- Setup: `uv venv .venv && uv pip install -p .venv -r pipeline/requirements.txt`
- Run: `BLS_CONTACT=<email> .venv/bin/python pipeline/wages.py` (or `--file <oesmYYma.zip>`). `.venv/bin/python pipeline/rent.py` (or `--year`, `--file/--geos-file`); `.venv/bin/python pipeline/gas.py` (or `--file`); `.venv/bin/python pipeline/validate.py` (add `--refresh-references` to re-fetch the reference values; this uses 16 of the BLS API's 25 daily requests and needs `BLS_CONTACT`). Tests: `.venv/bin/pytest pipeline`

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
- **Gas:** EIA monthly retail price of regular gasoline for the **latest complete month**. This was chosen over an annual average that would match the wage and rent years, so prices feel current to users even though the periods don't line up. No fallback to state or regional prices.
- **Transparency:** the app must clearly list the limitations and constraints of every data source, including periods that don't match, coverage gaps, pre-tax wages and boundary differences.
- **Metro names:** ACS names keep accents (e.g. "Mayagüez") and OEWS names don't. Display names come from ACS, with the OEWS name as a fallback.
- **Local wage:** the **median** hourly wage is the default for hours calculations. The mean is stored but not the default.
- **Metro coverage:** the site shows all 393 metros. Any measure a metro lacks is clearly marked as missing; currently gas is missing for 383 metros.
- **BLS downloads:** the User-Agent is `time-to-afford/0.1 (contact: <email>)`. The email comes from `BLS_CONTACT` or `--contact` and is never committed. BLS rejects User-Agents that contain a URL.

## Feature order

1. **Your wages mode,** with a "use prices from this metro" selector
2. Comparison
3. Map
4. Occupation-based move scenario

## Known data constraints

- OEWS data lags about a year.
- EIA gas prices cover only 10 metros, and EIA's city areas may not match metro boundaries exactly.
- Periods don't match: wages are May 2025, rent is 2025 (ACS 1-year), gas is the latest month (currently October 2026). Comparing current gas prices with older wages overstates hours somewhat.
- No good metro-level sources exist yet for groceries or dinner out.
- v1 uses pre-tax wages only.

## To-do

- [x] Wage module (OEWS)
- [x] Rent module (ACS)
- [x] Gas module (EIA)
- [x] Validate metros end to end (expanded from about 10 to all 393)
- [ ] Front end: your wages mode (include a rent selector: all units by default, 1 bedroom, 2 bedrooms)
- [ ] Decide the gas quantity to convert into hours (e.g. one 15-gallon tank, or monthly fuel use)
- [ ] Methodology page, including a clear list of limitations and constraints for each source
- [ ] Choose hosting
