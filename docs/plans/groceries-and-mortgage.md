# Plan: Groceries and mortgage costs, with value tiers

Status: accepted, with one open question (section 8). Last updated: 2026-11-09.

## 1. Why this plan exists

The v1 data policy said “no imputed values.” Groceries can’t meet that policy, because no public source gives reliable prices by metro for individual items. Mortgage costs can meet it in part, but a calculated payment is a scenario, not an observed value. This plan adds a way to label values by how they were produced, so the app can show groceries and mortgage costs without mixing modeled numbers in with observed ones.

Amended decision: “No imputed values” becomes “no unlabeled estimates.” Estimated and scenario values are allowed only when they carry a tier, a method, and an as-of date. Observed values work as before.

## 2. Value tiers

Every value in the data files has one of three tiers:

| Tier | Meaning | Example | Map and UI treatment |
|---|---|---|---|
| observed | Published directly for that place and period | Metro median wage (OEWS), ACS median owner cost | Solid dot, normal label |
| estimated | Derived from a national or regional observation and a published adjustment factor | National milk price scaled by a metro price parity | Hatched or outlined dot, “Estimated” badge, method shown in tooltip |
| scenario | Calculated from user-adjustable or stated assumptions | Mortgage payment for a typical home at the current rate | Labeled “Scenario,” assumptions listed beside the value, never shown as a fact |

No-data state stays as it is: hollow or gray, never filled in.

Map rule: Observed and estimated values can share a metric’s color scale. Scenario values never appear on the map. They show only in the detail panel, where the user can see the assumptions.

## 3. Data file format

Each value in data/ includes:

```json
{
  "metro": "Denver-Aurora-Lakewood, CO",
  "metric": "milk_gallon",
  "value": 4.12,
  "unit": "usd",
  "tier": "estimated",
  "method": "National BLS average price for whole milk x BEA goods RPP for metro",
  "inputs": [
    {"source": "bls_apd", "series": "<series id>", "as_of": "2026-09"},
    {"source": "bea_rpp", "table": "<table id>", "year": 2024}
  ],
  "as_of": "2026-09"
}
```

Rules:

- tier and method are required. The pipeline fails validation if either is missing.
- inputs lists every source, so any estimate can be traced.
- Scenario values also include an assumptions object (for example down payment and term).

## 4. Groceries

**Phase G1: National basket (no metro data).**

- Define the basket in a versioned file, pipeline/config/basket.yml: milk, eggs, bread, ground beef, bananas, and coffee, using BLS Average Price series.
- Store the national values as observed with geography: "US".
- Show a national grocery panel. Don’t show metro values yet.
- Use the USDA Thrifty Food Plan monthly cost as a national reference line, not as the basket itself.

**Phase G2: Metro estimates.**

- Apply the BEA Regional Price Parity for the goods category to each national price. Confirm during implementation whether RPPs have a food-specific line. If not, this is an approximation, and the method string must say so.
- Tier: estimated.
- Show metros where the RPP exists, which covers all metros.

**Phase G3 (optional): Observed metro prices.**

- If a licensed or public source with metro-level prices becomes available, it replaces the estimate. The tier changes to observed.

Acceptance criteria for groceries:

- Each basket item has a national observed value and a stated as-of month.
- Every metro estimate shows its method in the tooltip.
- Groceries and dinner out are excluded from the “total hours” figure until the basket is validated.

## 5. Mortgage costs

Two figures, always labeled separately:

**A. Observed (tier observed):** ACS median monthly owner costs for owners with a mortgage, by metro. The table bundles mortgage, taxes, and insurance, so the label must say so.

**B. Scenario (tier scenario):** Monthly principal and interest for a typical home.

- Inputs:
  - Home value: ACS median home value for the metro (observed)
  - Down payment: 20% by default, an average assumption, editable in the app
  - Term: 30 years by default, editable
  - Rate: Freddie Mac Primary Mortgage Market Survey, 30-year fixed, national weekly average, with its as-of date shown
- Formula: standard amortization payment on the loan amount.
- Limitation: The rate is national, so the scenario doesn’t reflect metro-level rate differences.
- Taxes and homeowner’s insurance are excluded in v1. Document this choice in the methodology page. Add them later as a separate, labeled line.

Hours conversion: Mortgage payment ÷ hourly wage gives hours per month, the same as rent. The label names which payment was used.

Acceptance criteria for mortgage:

- Observed and scenario figures never share a single number or label.
- Scenario inputs are editable in the detail panel and reset to defaults.
- Scenario values do not appear on the map.

## 6. Privacy and the wage

- Mortgage and grocery inputs are computed in the browser, as with wage. Nothing user-entered goes into URLs or leaves the browser.
- If a user changes the down payment or term, the change lives only in the browser session.

## 7. Build order

1. Add tier, method, and inputs fields to the JSON schema. Update the pipeline validator to enforce them.
2. Add the mortgage observed value (ACS) for about 10 metros. Verify against the Census table.
3. Add the mortgage scenario calculator, with a unit test against a known amortization example.
4. Add the national grocery basket (G1).
5. Add metro grocery estimates (G2), and check them against the national average for consistency.
6. Update the front end: tier badges, method tooltips, and the scenario panel.

## 8. Open questions

- Estimated grocery values on the map? Still open. Proposed default: detail panel only for v1, so the map stays observed-only.

Resolved: the amended data rule (section 1), the 20% down payment, the 30-year term, taxes and insurance excluded in v1, and the six-item basket.

## 9. Documentation to update

- PROJECT.md: amended data policy, new metrics in the to-do list, the 20% down payment, the taxes and insurance exclusion, and the open question above
- DATA.md: sources from section 10
- README.md: a short note on value tiers

## 10. Data sources

Each source is recorded in DATA.md with its terms. Before committing, confirm every URL, series ID, and table ID against the publisher’s current page. Series and table IDs change between releases, and the values here are from memory.

### 10.1 Mortgage observed values

Census American Community Survey (ACS), 5-year estimates

- Publisher: U.S. Census Bureau
- Access: Census API (api.census.gov) or data.census.gov
- Tables to verify:
  - B25077: Median value (owner-occupied units)
  - B25088: Median selected monthly owner costs, for housing units with a mortgage
- Geography: Metropolitan statistical areas (MSAs)
- Cadence: Annual release, 5-year estimates. Store the margin of error with each value, since smaller areas have wider margins.
- Terms: U.S. government work, public domain. Cite the Census Bureau.
- Note: B25088 bundles mortgage, taxes, and insurance. The label must say so.

### 10.2 Mortgage scenario input

Freddie Mac Primary Mortgage Market Survey (PMMS)

- Publisher: Freddie Mac
- Access: freddiemac.com/pmms (weekly CSV or public page)
- Series: 30-year fixed-rate mortgage average, weekly, national
- Cadence: Weekly, released Thursdays
- Terms: Check Freddie Mac’s current terms of use before redistributing. Attribution is required. Record the terms in DATA.md as checked, with the date.
- Note: National rate only. Metro-level rate differences are not captured.

### 10.3 Grocery observed national prices

Bureau of Labor Statistics (BLS), Average Price Data

- Publisher: U.S. Bureau of Labor Statistics
- Access: bls.gov/cpi/average-price-data (also the BLS public data API, api.bls.gov)
- Items for v1 (confirm the series ID for each):
  - Milk, fresh, whole, per gallon
  - Eggs, grade A, large, per dozen
  - Bread, white, pan, per pound
  - Ground beef, 100% beef, per pound
  - Bananas, per pound
  - Coffee, 100% ground roast, per pound
- Geography: National. Confirm whether any regional series exist for these items.
- Cadence: Monthly
- Terms: U.S. government work, public domain.

### 10.4 Grocery estimate adjustment

Bureau of Economic Analysis (BEA), Regional Price Parities (RPPs)

- Publisher: U.S. Bureau of Economic Analysis
- Access: bea.gov, Regional Price Parities by state and metro area
- Series: Metro RPP for goods (services and rents available for reference)
- Cadence: Annual, with a lag of about two years
- Terms: U.S. government work, public domain.
- Note: If only an all-goods RPP is available, the method string must say so.

### 10.5 Grocery reference line

USDA Center for Nutrition Policy and Promotion, Thrifty Food Plan

- Publisher: USDA, Food and Nutrition Service
- Access: fns.usda.gov, Food Plans: Cost of Food reports
- Series: Monthly cost of the Thrifty Food Plan market basket, national, by household type
- Cadence: Monthly
- Terms: U.S. government work, public domain.
- Use: National reference line only. It isn’t the basket, and it isn’t a metro value.

### 10.6 Wage (existing, for reference)

BLS Occupational Employment and Wage Statistics (OEWS)

- Decided for v1. Record in DATA.md with the same verification step.

### 10.7 Rent (existing, for reference)

Census ACS, median gross rent (B25064)

- Decided for v1. Record alongside the owner-cost tables.

### 10.8 Source checklist for DATA.md

Each entry includes: publisher, URL, table or series ID, geography, cadence, terms checked (with date), attribution text, and the as-of format used in the data files.
