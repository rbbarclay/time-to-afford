# PROJECT.md

## Purpose

Show how many hours of work it takes to afford common expenses in each U.S. metro area.

## Current state

- Scaffolding in place: folder structure, docs, license.
- **Wage module done** (`pipeline/wages.py`). It writes `data/wages.json`: May 2025 OEWS, 393 MSAs (including Puerto Rico), with hourly median, hourly mean and employment for all occupations. Each value is `{value, status}`, where status is `ok`, `missing` or `top_coded`.
- **Rent module done** (`pipeline/rent.py`). It writes `data/rent.json`: ACS 2025 1-year table B25031, 393 metros (the same codes as wages), with median gross rent for all units, 1 bedroom and 2 bedrooms, each with a margin of error. Each value is `{value, moe, status}`.
- **Gas module done** (`pipeline/gas.py`). It writes `data/gas.json`: EIA monthly average price of regular gasoline for October 2026, for the 10 metros EIA covers. Each value is `{value, status}`.
- **Validation done for all 393 metros** (`pipeline/validate.py`). It checks structure, that the three files cover the same metros, and plausible ranges. It also compares values with figures published separately: BLS API v1 medians (393/393 match), Census table B25064 (393/393 match) and EIA's HTML table (10/10 match). It writes `data/validation_report.csv`: one row per metro with inputs, as-of dates, hours, and the measures that are missing. 10 metros have every measure; 383 lack only gas. One warning to review: Ponce, PR has a 1-bedroom rent of $299, below the $300 lower bound. The value comes straight from Census and is kept as is.
- **Site data build done** (`pipeline/build.py`). It runs validation, then merges the three files into `web/data/metros.json` (393 metros sorted by name, about 115 KB) with source metadata. Gas for metros EIA doesn't cover has status `not_covered`, which is separate from `missing`.
- **Front end, your wages mode, done** (`web/index.html`, `app.js`, `calc.js`, `styles.css`). It has a metro picker (default New York), an optional wage (hourly or annual), and a rent-type selector. The rent card shows hours per month with inputs, margin of error and as-of date. The gas card shows hours for a 15-gallon fill-up and for 1 gallon. Missing, top-coded and not-covered values say so instead of showing a number. A short "Keep in mind" list links to the methodology page. Durations under an hour show as minutes. Local preview: `python3 -m http.server -d web` and open http://localhost:8000. JS tests: `cd web && node --test tests/`
- **Methodology page done** (`web/methodology.html`, `methodology.js`). It covers the calculation with a live worked example, a sources table, how missing data is handled, limitations grouped by source and across sources, privacy, and attribution. Periods, dates and metro count are read from `metros.json`, so they stay current when the data is rebuilt.
- **Hosting set up:** GitHub Pages at https://rbbarclay.github.io/time-to-afford/ via `.github/workflows/pages.yml`. On each push to `main` it runs the Python and JS tests, then publishes `web/` without the tests and `package.json`. The workflow doesn't run the data pipeline, so data updates are manual: run the pipeline locally, then commit and push.
- **Value tiers in place (plan build step 1, 2026-11-09).** Every value is `{value, status, tier, method}`, where `tier` is `observed`, `estimated` or `scenario` and `method` is a key into the file's top-level `methods` table. Each method entry has a description, its inputs (source URL, table or series, column) and an as-of date. All current values are `observed`. `validate.py` rejects values with a missing or invalid tier, an undefined method, or an incomplete method entry. `build.py` checks the finished bundle the same way; gas for metros EIA doesn't cover (`not_covered`) has no tier, since no source reported it. Data values are unchanged. `metros.json` grew from 115 KB to 189 KB raw, but from 16 KB to only 18 KB gzipped, which is what GitHub Pages serves. Modules run with `--file` now record the file's download date as `retrieved`.
- **Mortgage observed values done (plan build step 2, 2026-11-09)** (`pipeline/owner.py`). It writes `data/owner.json`: ACS 2025 1-year median home value (B25077) and median monthly owner costs with a mortgage (B25088, column 2), with margins of error, for all 393 metros. All values are tier `observed`. Owner costs are top-coded ($4,000+) for San Francisco and San Jose and stored as `top_coded`, not filled in. The method description says owner costs include taxes, insurance, utilities and fees. `validate.py` checks the owner data, and home value matches Census table B25097 for 393 of 393 metros. Census publishes no second median for owner costs in these files, so those get structure and range checks only. A 10-metro spot check against the raw Census rows matched. Not shown on the site yet (build step 6).
- **Mortgage scenario calculator done (plan build step 3, 2026-11-09)** in `web/calc.js`. `monthlyPayment()` is standard amortization. `mortgageScenario()` applies the defaults (20% down, 30-year term; both overridable) to a metro's ACS median home value and returns a `scenario`-tier result with its assumptions and `excludes: property taxes, homeowner's insurance`. It returns nothing, rather than guessing, if the home value is missing or top-coded, no rate is available, or the inputs are invalid. It's unit-tested against known examples: $200,000 at 6% over 30 years = $1,199.10/month; $100,000 at 5% over 30 years = $536.82; $300,000 at 4% over 15 years = $2,219.06. Calculation happens in the browser only, as the plan requires. **No rate is published yet**, because the Freddie Mac PMMS terms are unresolved, so nothing shows on the site.
- **National grocery basket done (plan build step 4 / phase G1, 2026-11-13)** (`pipeline/groceries.py`, `pipeline/config/basket.yml` v1). It writes `data/groceries.json` with the six BLS Average Price items, U.S. city average, October 2026, each tier `observed` with geography `US` and its own as-of month. Missing items stay missing. October 2026 prices: milk $4.101/gal, eggs $2.320/doz, bread $1.861/lb, ground beef $6.755/lb, bananas $0.655/lb, coffee $9.249/lb. `validate.py` cross-checks every item against the BLS `ap.data.3.Food` flat file, a separate publication from the API used to build the data: 6 of 6 match. Not on the site yet (step 6).
- **Planned: groceries and mortgage** ([docs/plans/groceries-and-mortgage.md](docs/plans/groceries-and-mortgage.md), accepted 2026-11-09). Sources were checked against publisher sites on 2026-11-09 and are recorded in DATA.md. Nothing is built yet.
- Setup: `uv venv .venv && uv pip install -p .venv -r pipeline/requirements.txt`
- Run: `BLS_CONTACT=<email> .venv/bin/python pipeline/wages.py` (or `--file <oesmYYma.zip>`). `.venv/bin/python pipeline/rent.py` (or `--year`, `--file/--geos-file`); `.venv/bin/python pipeline/gas.py` (or `--file`); `.venv/bin/python pipeline/owner.py` (or `--year`, `--value-file/--cost-file/--geos-file`); `BLS_CONTACT=<email> .venv/bin/python pipeline/groceries.py` (or `--file <ap.data.3.Food>`); `.venv/bin/python pipeline/build.py` (validates, then writes the site data); `.venv/bin/python pipeline/validate.py` (add `--refresh-references` to re-fetch all reference values, or `--refresh-references owner rent` etc. for only some; refreshing `wage` uses 16 of the BLS API's 25 daily requests and needs `BLS_CONTACT`). Tests: `.venv/bin/pytest pipeline`

## Decisions

- **Architecture:** a static site. A Python pipeline writes JSON files that the site reads.
- **No database, user accounts, or runtime API** in v1.
- **v1 metrics:** wage (BLS OEWS), rent (Census ACS), gas (EIA). Groceries and mortgage are planned (see below); dinner out comes later.
- **Data policy, amended 2026-11-09: "no imputed values" becomes "no unlabeled estimates."** Every value carries a tier: `observed` (published directly for that place and period), `estimated` (a national or regional figure scaled by a published adjustment factor), or `scenario` (calculated from stated or user-adjustable assumptions). Estimated and scenario values are allowed only with a tier, a method string, and an as-of date; the pipeline must reject values missing tier or method. Missing data is still shown as missing, never filled in. Scenario values never appear on the map; they show only in a detail panel beside their assumptions.
- **Mortgage (planned):** two figures, always labeled separately. Observed: ACS median monthly owner costs for owners with a mortgage (B25088), labeled as including taxes and insurance. Scenario: monthly principal and interest on the metro's ACS median home value (B25077). Defaults are a **20% down payment**, documented as an average assumption, and a **30-year term**; both are editable in the app (in-browser only) and reset to defaults. The rate is the national 30-year fixed average, so metro rate differences aren't captured.
- **ACS vintage for mortgage observed values (decided 2026-11-09): 1-year (2025)** for B25077 and B25088, matching rent. Compared against the 5-year (2020–2024) release:
  - **Coverage:** both cover all 393 metros with no missing values. The 5-year file's extra areas (about 540) are micropolitan areas, which have no OEWS wages, so they don't help.
  - **Margins of error:** the 5-year values are tighter. For owner costs with a mortgage, the typical metro is ±1.9% vs ±4.7%, and the worst ±6.2% vs ±30.4%. Show the margin of error beside each owner value, as the rent card does.
  - **Top-coding ($4,000+):** in the 1-year data, San Francisco and San Jose are top-coded; in the 5-year, only San Jose. Top-coded values are shown as "$4,000 or more", not replaced with the 5-year figure, which averages older and lower 2020–2024 costs.
  - **5-year as a fallback:** not used now, since there are no gaps. If a future 1-year release drops metros, the 5-year value may be used for those metros only, with its own method key and as-of date so it's labeled as a different period.
- **Property taxes and homeowner's insurance are excluded from v1** of the mortgage scenario. To be documented on the methodology page and added later as a separate, labeled line.
- **Tier data format (compact):** the plan's section 3 shows one flat record per value. The project instead keeps the per-metro layout and adds `tier` and a short `method` key to each value, with descriptions, inputs and as-of dates written once in a `methods` table. This holds the same information with far less repetition. Scenario methods add an `assumptions` object. Shared helpers are in `pipeline/tiers.py`.
- **Basket quantities (2026-11-13):** one of each item in BLS units (1 gallon milk, 1 dozen eggs, 1 lb each of bread, ground beef, bananas, coffee). This is a starting assumption, not a nutritional or spending-weighted basket. It lives in the versioned `basket.yml`; bump `version` on any change.
- **Grocery basket (planned, national phase):** milk, eggs, bread, ground beef, bananas, coffee, from BLS Average Price series (IDs in DATA.md), stored as observed national values. The USDA Thrifty Food Plan is a national reference line only. Metro estimates (later phase) scale national prices by BEA's **all-goods** RPP, since there's no food-specific line, and the method string says so. Groceries and dinner out stay out of any "total hours" figure until the basket is validated.
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
- **Front end:** plain HTML, CSS and JavaScript with no framework, build step or npm packages. Calculations live in `web/calc.js`, tested with Node's built-in test runner. The site loads one file, `web/data/metros.json`.
- **Before a wage is entered:** the page shows hours at the selected metro's median wage, clearly labeled. Entering your own wage (hourly, or annual ÷ 2,080) replaces it.
- **Gas display:** both hours for 1 gallon and hours for a 15-gallon fill-up. Both amounts are fixed for now.
- **Hosting:** GitHub Pages via a GitHub Actions workflow that publishes `web/`. A move to Vercel may come later, so `web/` stays plain static files with relative links and nothing specific to GitHub; only the deploy workflow would change.
- **Wage input safety:** the wage field has no `name` and isn't inside a `<form>`, so it can't be submitted or end up in a URL. Nothing is written to cookies or localStorage, and the page has no analytics.
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
- No public source gives observed metro-level grocery prices or dinner-out costs. Planned grocery metro values are estimates (national BLS price × BEA all-goods RPP).
- BEA RPPs cover 387 of 393 metros; the 6 Puerto Rico metros have none, so they'll show no grocery estimate. The latest RPP year is 2024, older than the other sources.
- BLS regional average-price series are uneven: several stopped at October 2025, and there's no West series for eggs. No metro-level series exist for the basket items.
- ACS owner costs with a mortgage are top-coded at $4,000+ (San Francisco and San Jose in 2025).
- v1 uses pre-tax wages only.
- ACS median gross rent covers all renters, including long-time tenants, so it is usually below current asking rents for new leases.

## To-do

- [x] Wage module (OEWS)
- [x] Rent module (ACS)
- [x] Gas module (EIA)
- [x] Validate metros end to end (expanded from about 10 to all 393)
- [x] Build the combined site data (`web/data/metros.json`)
- [x] Front end: your wages mode (with rent selector: all units by default, 1 bedroom, 2 bedrooms)
- [x] Decide the gas quantity (1 gallon and a 15-gallon fill-up, both fixed)
- [x] Methodology page, including a clear list of limitations and constraints for each source
- [x] Hosting: GitHub Pages workflow (Vercel possible later; only the workflow would change)
- [ ] Later: automate data refresh (e.g. monthly gas update)

### Groceries and mortgage (plan section 7 build order)
- [x] 1. Add `tier`, `method` and `inputs` to the data schema; make the validator enforce them. (Compact form: `method` key + `methods` table; see Decisions.)
- [x] 2. Mortgage observed values (ACS B25088 with a mortgage, B25077 home value), 1-year 2025, all 393 metros; 10-metro spot check against the Census table plus a B25097 cross-check of home value for all metros.
- [x] 3. Mortgage scenario calculator, unit-tested against known amortization examples (`web/calc.js`).
- [ ] 3b. Mortgage rate source for the scenario. **Blocked:** Freddie Mac PMMS terms are unresolved (DATA.md); get written permission or choose another source before any rate is published in the site data.
- [x] 4. National grocery basket (G1), with `pipeline/config/basket.yml`.
- [ ] 4b. USDA Thrifty Food Plan national reference line (part of G1 in the plan, deferred). Needs: USDA reuse terms verified (the policies page returns HTTP 403 to automated requests; don't work around it, so check it by hand in a browser) and a PDF reader, since the report is PDF only.
- [ ] 5. Metro grocery estimates (G2), checked against the national average for consistency.
- [ ] 6. Front end: tier badges, method tooltips, scenario panel.
- [ ] Methodology page: explain value tiers; state that property taxes and homeowner's insurance are excluded from the mortgage scenario; rewrite "never estimated or filled in" when the first estimated values ship (the live page is unchanged until then).
- [ ] Verify the terms still marked UNVERIFIED in DATA.md (EIA reuse page; USDA policies page).

## Open questions

- **Estimated grocery values on the map?** Still open. Proposed default: detail panel only for v1, so the map stays observed-only.
- **Basket total: which tier?** The items are observed, but a total depends on the chosen quantities, which are a stated assumption. Decide before step 6 whether a displayed total is labeled observed (sum of observed prices) or scenario (depends on assumptions). No total is stored yet.

## Future improvements

- **Cost map with a cost selector:** create a map color-coding the cost of living, letting people choose which cost to show (e.g. rent by type, or gas). This builds on feature 3 (Map) and follows the map decisions above: dots at metro centers, all the same size; no-data metros hollow or gray; a legend with the actual min and max. Colors show **hours of work**, not dollar cost. **Wage used:** by default, each metro's own median wage, which shows local affordability. If the user enters a wage, that wage is applied to every metro, which shows where their pay goes furthest. This matches the main page. The legend and tooltips must say which wage is in use.
