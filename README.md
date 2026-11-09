# Time to Afford

How many hours of work does it take to afford common expenses (rent, gas, and later groceries and dining out) in different U.S. metro areas?

Time to Afford turns prices into hours of work. You can use your own wage, or typical local wages, and see how far that pay goes in each metro.

## Structure

```
pipeline/   Python scripts that fetch, clean, and validate source data, then write JSON
web/        Static front end that reads the JSON (all wage math runs in the browser)
data/       Pipeline output; data/raw/ holds downloads and is not committed
```

See [PROJECT.md](PROJECT.md) for current state, decisions, and to-do, and [DATA.md](DATA.md) for sources and terms.

## Data principles

- **Public or clearly licensed sources only.** Every source and its terms are listed in [DATA.md](DATA.md).
- **Every value carries an as-of date.** Values are never shown without the period they describe.
- **Missing data is shown as missing.** If a metro lacks a value, the site says so instead of filling it in.
- **No unlabeled estimates.** Every value has a tier:
  - **observed:** published directly for that place and period (e.g. a metro's median wage)
  - **estimated:** derived from a national or regional figure and a published adjustment factor (e.g. a national grocery price scaled by a metro price index)
  - **scenario:** calculated from stated or user-adjustable assumptions (e.g. a mortgage payment at a 20% down payment)

  Estimated and scenario values always carry their method and as-of date and are labeled as such. Scenario values never appear on the map. See [docs/plans/groceries-and-mortgage.md](docs/plans/groceries-and-mortgage.md).

## License

Code is released under the [MIT License](LICENSE). Source data is subject to each provider's terms (see [DATA.md](DATA.md)).
