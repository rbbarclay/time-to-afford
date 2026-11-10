# Data sources and terms

Only public or clearly licensed sources are used. Every value carries an as-of date. Missing data is shown as missing. Estimates are allowed only when labeled: each estimated or scenario value carries a tier (`observed`, `estimated`, `scenario`), a method string, and an as-of date (see [docs/plans/groceries-and-mortgage.md](docs/plans/groceries-and-mortgage.md)).

In the data files, each value carries `tier` and a `method` key; the file's `methods` table records each method's description, inputs (URL, table or series, column) and as-of date.

Each entry follows the checklist in section 10.8 of that plan. **"Checked"** means the URL, table or series ID, and terms were confirmed on the publisher's own site on the date shown. Anything that couldn't be confirmed is marked **UNVERIFIED** or **UNRESOLVED**.

## In use (v1)

### BLS Occupational Employment and Wage Statistics (OEWS): wages
- **Publisher:** U.S. Bureau of Labor Statistics
- **URL:** https://www.bls.gov/oes/ (data file: `https://www.bls.gov/oes/special-requests/oesm25ma.zip`)
- **Table / series:** `MSA_M2025_dl.xlsx` in the zip; occupation code `00-0000` (all occupations); field `H_MEDIAN` (hourly median). Cross-checked against BLS API series `OEUM{area}00000000000008`.
- **Geography:** metropolitan statistical areas (393, including 6 in Puerto Rico)
- **Cadence:** annual (May reference period), published about a year later
- **Terms checked 2026-11-09:** BLS copyright page (https://www.bls.gov/opub/copyright-information.htm): "everything that we publish ... is in the public domain, except for previously copyrighted photographs and illustrations. You are free to use our public domain material without specific permission, although we do ask that you cite the Bureau of Labor Statistics as the source."
- **Attribution text:** "Source: U.S. Bureau of Labor Statistics, OEWS"
- **As-of format in data files:** `as_of: "YYYY-05"`, `reference_period: "May YYYY"`

### Census American Community Survey (ACS): rent
- **Publisher:** U.S. Census Bureau
- **URL:** https://www.census.gov/programs-surveys/acs (data file: `https://www2.census.gov/programs-surveys/acs/summary_file/2025/table-based-SF/data/1YRData/acsdt1y2025-b25031.dat`, names from `.../documentation/Geos20251YR.txt`)
- **Table:** **B25031** (median gross rent by bedrooms; columns `E001` all units, `E003` 1 bedroom, `E004` 2 bedrooms, each with a margin of error). The plan (section 10.7) names B25064; the project uses B25031 because it has the bedroom breakdown. B25031 all units equals B25064 (median gross rent), which `pipeline/validate.py` uses as its cross-check.
- **Access:** table-based summary files, which need no key. The Census API now requires a key and isn't used.
- **Geography:** metropolitan statistical areas (all 393), 1-year estimates
- **Cadence:** annual; 1-year estimates for year N are published around September of year N+1
- **Special values:** negative codes (e.g. `-666666666`, sample too small) mean missing. `3501` means "$3,500 or more" (top-coded). Neither is filled in.
- **Terms checked 2026-11-09:** Census citation page (https://www.census.gov/about/policies/citation.html) asks users to cite the Census Bureau as the source of the original data. That page does not itself state "public domain"; Census data are U.S. government works (17 U.S.C. § 105).
- **Attribution text:** "Source: U.S. Census Bureau, American Community Survey"
- **As-of format in data files:** `as_of: "YYYY"`, `reference_period: "YYYY (ACS 1-year)"`

### EIA gasoline prices: gas
- **Publisher:** U.S. Energy Information Administration
- **URL:** https://www.eia.gov/petroleum/gasdiesel/ (data file: `https://www.eia.gov/dnav/pet/xls/PET_PRI_GND_A_EPMR_PTE_DPGAL_M.xls`, sheet "Cities"; cross-checked against https://www.eia.gov/dnav/pet/pet_pri_gnd_a_epmr_pte_dpgal_m.htm)
- **Series:** `EMM_EPMR_PTE_Y{city}_DPG` for 10 cities (mapping in `pipeline/gas.py`)
- **Geography:** only 10 cities: Boston, Chicago, Cleveland, Denver, Houston, Los Angeles, Miami, New York City, San Francisco, Seattle, each mapped to its metro code. EIA's city sampling areas may not match metro boundaries exactly. All other metros are shown as missing; state and regional averages are not used to fill gaps.
- **Cadence:** monthly (the site uses the latest complete month)
- **Terms:** U.S. government data, generally in the public domain; attribution recommended. **UNVERIFIED:** EIA's copyright and reuse page has not yet been checked against the publisher's site.
- **Attribution text:** "Source: U.S. Energy Information Administration"
- **As-of format in data files:** `as_of: "YYYY-MM"`, `reference_period: "Month YYYY (monthly average)"`

## Planned: groceries and mortgage

From [docs/plans/groceries-and-mortgage.md](docs/plans/groceries-and-mortgage.md), section 10. None of these are in the pipeline yet.

### Census ACS owner costs and home value: mortgage, observed (plan 10.1). In the pipeline as `pipeline/owner.py` (not yet on the site)
- **Publisher:** U.S. Census Bureau
- **URL:** same table-based summary files as rent, e.g. `https://www2.census.gov/programs-surveys/acs/summary_file/2025/table-based-SF/data/1YRData/acsdt1y2025-b25077.dat` and `...-b25088.dat`
- **Tables (checked 2026-11-09 against `ACS20251YR_Table_Shells.txt`):**
  - **B25077** median value (dollars), owner-occupied housing units: column `B25077_E001` (+ `M001`)
  - **B25088** median selected monthly owner costs by mortgage status: `B25088_E002` = housing units **with a mortgage** (+ `M002`). `E001` is all owners, `E003` is without a mortgage. Selected monthly owner costs include mortgage payments, real estate taxes, insurance, utilities, and fees, so the label must say so.
- **Access:** keyless summary files, the same as rent. The plan names the Census API, which now requires a key; not needed while the pipeline runs locally.
- **Geography:** metropolitan statistical areas. **2025 1-year:** both tables cover all 393 of our metros, with no missing values. **5-year:** the latest published is 2020–2024 (`acsdt5y2024-*`); 2021–2025 isn't out yet.
- **1-year vs 5-year:** the plan specifies 5-year estimates; the project uses **1-year 2025** (decided 2026-11-09; comparison in PROJECT.md). The 5-year data is a possible labeled fallback only if a future 1-year release drops metros.
- **Cross-check:** `B25097_E001` (median value, all owner-occupied units) equals `B25077_E001` for all 393 metros; `validate.py` checks this. Census publishes no second median for owner costs with a mortgage in the summary files (the Data Profile DP04 is API-only), so owner costs get structure and range checks only.
- **Special values:** `B25088_E002` = `4001` means "$4,000 or more" (top-coded) and is treated like rent's `3501`. In the 2025 1-year data this affects San Francisco (41860) and San Jose (41940). For `B25077`, `2000001` ("$2,000,000 or more") is handled as top-coded. That code follows ACS convention but isn't observed in the 2025 metro data, so it's **unverified** against a real file.
- **Cadence:** annual
- **Terms checked 2026-11-09:** as for ACS rent above (cite the Census Bureau).
- **Attribution text:** "Source: U.S. Census Bureau, American Community Survey"
- **As-of format in data files:** `as_of: "YYYY"`, `reference_period: "YYYY (ACS 1-year)"`

### Freddie Mac Primary Mortgage Market Survey (PMMS): mortgage rate, scenario input (plan 10.2)
- **Publisher:** Freddie Mac
- **URL:** https://www.freddiemac.com/pmms; history CSV `https://www.freddiemac.com/pmms/docs/PMMS_history.csv` (column `pmms30`, 30-year fixed, weekly, national); also `.../historicalweeklydata.xlsx`. Latest on 2026-11-09: 7.18% for the week of 2026-11-05.
- **Geography:** national only; metro rate differences aren't captured
- **Cadence:** weekly (Thursdays)
- **Terms checked 2026-11-09: UNRESOLVED. The two Freddie Mac statements conflict:**
  - PMMS page: "Information from this document may be used with proper attribution. Alteration of this document or its content is strictly prohibited."
  - Site Terms and Conditions (https://www.freddiemac.com/terms, last updated September 11, 2026): "You may not redistribute Data, publish Data, or commercially exploit Data or derived products/services without a separate written agreement or license from Freddie Mac." The terms also say dataset-specific terms, including attribution requirements, may be disclosed on the applicable website.
  - Freddie Mac's Content Use Permission page (https://www.freddiemac.com/terms/content-use) has a form to request permission to publish its content on a website.
  - **Don't publish PMMS values in the site data until this is resolved**, for example by written permission through that form.
- **Attribution text:** not specified by Freddie Mac. Proposed: "Source: Freddie Mac, Primary Mortgage Market Survey®". PMMS® is a Freddie Mac trademark.
- **As-of format (planned):** `as_of: "YYYY-MM-DD"` (survey week)

### BLS Average Price Data: groceries, observed national (plan 10.3)
- **Publisher:** U.S. Bureau of Labor Statistics
- **URL:** https://www.bls.gov/cpi/average-price-data.htm; series list `https://download.bls.gov/pub/time.series/ap/ap.series`; values via the BLS public API v1 (`https://api.bls.gov/publicAPI/v1/timeseries/data/`)
- **Series (checked 2026-11-09 against `ap.series` and the API; latest value September 2026):**

  | Item | Series ID | BLS title | Sep 2026 |
  |---|---|---|---|
  | Milk | `APU0000709112` | Milk, fresh, whole, fortified, per gal. (3.8 lit) | $4.106 |
  | Eggs | `APU0000708111` | Eggs, grade A, large, per doz. | $2.272 |
  | Bread | `APU0000702111` | Bread, white, pan, per lb. (453.6 gm) | $1.830 |
  | Ground beef | `APU0000703112` | Ground beef, 100% beef, per lb. (453.6 gm) | $6.792 |
  | Bananas | `APU0000711211` | Bananas, per lb. (453.6 gm) | $0.656 |
  | Coffee | `APU0000717311` | Coffee, 100%, ground roast, all sizes, per lb. (453.6 gm) | $9.332 |

- **Geography:** U.S. city average (area `0000`). **Regional series exist** for the four census regions (`0100` Northeast, `0200` Midwest, `0300` South, `0400` West), but coverage is uneven. Several stopped at October 2025 (Northeast and Midwest milk and eggs, all regional coffee), and there's no West series for eggs. **No metro-level series exist** for these six items.
- **Cadence:** monthly
- **Terms checked 2026-11-09:** as for OEWS above (public domain; cite BLS).
- **Attribution text:** "Source: U.S. Bureau of Labor Statistics, Average Price Data"
- **As-of format (planned):** `as_of: "YYYY-MM"`

### BEA Regional Price Parities (RPPs): grocery estimate adjustment (plan 10.4)
- **Publisher:** U.S. Bureau of Economic Analysis
- **URL:** https://www.bea.gov/data/prices-inflation/regional-price-parities-state-and-metro-area; data file `https://apps.bea.gov/regional/zip/MARPP.zip` (`MARPP_MSA_2008_2024.csv`)
- **Series (checked 2026-11-09):** table MARPP, line codes `1` All items, **`2` Goods**, `3` Services: Housing, `4` Services: Utilities, `5` Services: Other. **There is no food-specific line**, so grocery estimates must use the all-goods RPP and the method string must say so.
- **Geography:** metropolitan statistical areas. **387 of our 393 metros** match by code. **None of the 6 Puerto Rico metros have RPPs**, so they will show no data for grocery estimates.
- **Cadence:** annual. Latest year is 2024 (current release February 19, 2026); next release December 10, 2026.
- **Terms checked 2026-11-09:** BEA citation guidelines (https://www.bea.gov/help/guidelines-for-citing-bea): "Citations are appreciated and appropriate." That page doesn't state "public domain"; BEA data are U.S. government works (17 U.S.C. § 105).
- **Attribution text:** "Source: U.S. Bureau of Economic Analysis, Regional Price Parities"
- **As-of format (planned):** `year: YYYY` in `inputs`

### USDA Thrifty Food Plan: grocery reference line (plan 10.5)
- **Publisher:** USDA. The site now names it the **Food and Nutrition Administration** (the plan says Food and Nutrition Service); the Center for Nutrition Policy and Promotion (CNPP) sits under it. `fns.usda.gov` now redirects to `fna.usda.gov`.
- **URL:** https://www.fna.usda.gov/research/cnpp/usda-food-plans/cost-food-monthly-reports; monthly PDF, e.g. `https://www.fna.usda.gov/sites/default/files/resource-files/CostofFoodSep2026Thrifty.pdf`
- **Series (checked 2026-11-09):** "Official USDA Thrifty Food Plan: U.S. Average", weekly and monthly cost **by age-sex group**, plus a **reference family of four** (male and female 20–50, children 6–8 and 9–11). September 2026: $1,024.00 per month for the reference family. The plan says "by household type"; the report gives individuals and the one reference family.
- **Format:** PDF only (no CSV found), so the pipeline would need to parse a PDF.
- **Geography:** national (separate reports for Alaska and Hawaii)
- **Cadence:** monthly
- **Terms: UNVERIFIED.** USDA's policies page (https://www.usda.gov/policies-and-links) returned HTTP 403 to an automated request, and no reuse statement was found on the FNA pages checked. Expected to be a U.S. government work (17 U.S.C. § 105), but not confirmed on the publisher's site.
- **Attribution text:** "Source: USDA, Thrifty Food Plan cost of food report"
- **As-of format (planned):** `as_of: "YYYY-MM"`

## Deferred

### Zillow
- Not used yet. Zillow's terms of use must be reviewed before any of its data is used.

## Not yet sourced
- **Observed metro-level grocery prices** and **dinner out:** no public source found. Groceries are planned as national observed prices plus labeled metro estimates (above).
