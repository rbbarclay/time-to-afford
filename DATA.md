# Data sources and terms

Only public or clearly licensed sources are used. Every value carries an as-of date, and missing data is shown as missing, never imputed.

## In use (v1)

### BLS Occupational Employment and Wage Statistics (OEWS): wages
- **Publisher:** U.S. Bureau of Labor Statistics
- **Used for:** hourly wages by metro area (MSA) and occupation
- **Timing:** annual, with a lag of about a year
- **Terms:** U.S. government data, generally in the public domain. Attribution is recommended.
- **Site:** https://www.bls.gov/oes/

### Census American Community Survey (ACS): rent
- **Publisher:** U.S. Census Bureau
- **Used for:** median monthly gross rent (contract rent plus utilities) by metro area: all units, 1 bedroom, 2 bedrooms
- **Table:** B25031 (median gross rent by bedrooms), 1-year estimates, with margins of error
- **Files:** table-based summary files, e.g. `https://www2.census.gov/programs-surveys/acs/summary_file/2025/table-based-SF/data/1YRData/acsdt1y2025-b25031.dat`, plus `.../documentation/Geos20251YR.txt` for area names. These need no API key. The Census API itself now requires a free key, so it isn't used.
- **Timing:** 1-year estimates for year N are published around September of year N+1
- **Special values:** negative codes (e.g. `-666666666`, sample too small) are treated as missing. `3501` means "$3,500 or more" and is marked as top-coded. Neither is imputed.
- **Terms:** U.S. government data, generally in the public domain. Attribution is recommended.
- **Site:** https://www.census.gov/programs-surveys/acs

### EIA gasoline prices: gas
- **Publisher:** U.S. Energy Information Administration
- **Used for:** retail price of regular gasoline (all formulations, taxes included), dollars per gallon, monthly average for the latest complete month
- **File:** `https://www.eia.gov/dnav/pet/xls/PET_PRI_GND_A_EPMR_PTE_DPGAL_M.xls`, sheet "Cities" (no key needed; the EIA API now requires a key, so it isn't used)
- **Coverage:** only 10 cities: Boston, Chicago, Cleveland, Denver, Houston, Los Angeles, Miami, New York City, San Francisco, Seattle. Each is mapped to its metro (CBSA) code. EIA's city sampling areas may not match metro boundaries exactly. All other metros are shown as missing. State and regional averages are not used to fill gaps.
- **Timing:** updated monthly. This is more recent than the wage and rent data (see PROJECT.md, Known data constraints).
- **Terms:** U.S. government data, generally in the public domain. Attribution is recommended.
- **Site:** https://www.eia.gov/petroleum/gasdiesel/

## Deferred

### Zillow
- Not used yet. Zillow's terms of use must be reviewed before any of its data is used.

## Not yet sourced
- **Groceries** and **dinner out:** no good metro-level public source has been found yet.
