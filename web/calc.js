// Pure calculation helpers for Time to Afford. No DOM access, no storage, no network.

export const HOURS_PER_YEAR = 2080; // 40 hours x 52 weeks
export const GAS_FILL_GALLONS = 15;

/** Parse user text like "$32", "65,000", " 18.5 " into a positive number, else null. */
export function parseAmount(text) {
  if (text == null) return null;
  const cleaned = String(text).replace(/[$,\s]/g, "");
  if (!/^\d*\.?\d+$/.test(cleaned)) return null;
  const n = Number(cleaned);
  return Number.isFinite(n) && n > 0 ? n : null;
}

/** Convert an amount to an hourly wage. unit: "hour" | "year". */
export function toHourly(amount, unit) {
  if (amount == null) return null;
  return unit === "year" ? amount / HOURS_PER_YEAR : amount;
}

/** Hours of work needed to pay `cost` at `wage` per hour, or null if either is unavailable. */
export function hoursFor(cost, wage) {
  if (cost == null || wage == null || wage <= 0) return null;
  return cost / wage;
}

const ok = (f) => (f && f.status === "ok" ? f.value : null);

/**
 * Compute everything the page shows for one metro.
 * yourHourly: the user's hourly wage, or null to fall back to the metro median.
 */
export function computeResults(metro, { yourHourly = null, rentMeasure = "all_units" } = {}) {
  const median = ok(metro.wage_median);
  const wage = yourHourly ?? median;
  const wageSource = yourHourly != null ? "yours" : median != null ? "median" : "none";

  const rentField = metro.rent[rentMeasure] ?? { value: null, status: "missing" };
  const rentCost = ok(rentField);
  const gasPrice = ok(metro.gas);
  const fillCost = gasPrice == null ? null : gasPrice * GAS_FILL_GALLONS;

  return {
    wage: { value: wage, source: wageSource, median },
    rent: { status: rentField.status, cost: rentCost, moe: rentField.moe ?? null, hours: hoursFor(rentCost, wage) },
    gasGallon: { status: metro.gas.status, cost: gasPrice, hours: hoursFor(gasPrice, wage) },
    gasFill: { status: metro.gas.status, cost: fillCost, gallons: GAS_FILL_GALLONS, hours: hoursFor(fillCost, wage) },
  };
}

/** "9 min" under an hour, otherwise "65.4 hours". */
export function formatDuration(hours) {
  if (hours == null) return "—";
  if (hours < 1) {
    const mins = Math.max(1, Math.round(hours * 60));
    return `${mins} min`;
  }
  return `${hours.toFixed(1)} hours`;
}

export function formatMoney(value, { cents = false } = {}) {
  if (value == null) return "—";
  return value.toLocaleString("en-US", {
    style: "currency", currency: "USD",
    minimumFractionDigits: cents ? 2 : 0, maximumFractionDigits: cents ? 2 : 0,
  });
}

/** Gas prices are published to 0.1 cent; keep three decimals. */
export function formatGasPrice(value) {
  return value == null ? "—" : `$${value.toFixed(3)}`;
}

// ---------- Mortgage scenario (tier "scenario") ----------
// Plan: docs/plans/groceries-and-mortgage.md, section 5B. Monthly principal and
// interest only: property taxes and homeowner's insurance are excluded in v1.
// Inputs the user edits (down payment, term) stay in this page's memory only.

export const MORTGAGE_DEFAULTS = Object.freeze({
  downPayment: 0.20, // share of home value; an average assumption, editable
  termYears: 30,
});

/**
 * Standard amortization: monthly payment on `principal` at `annualRate`
 * (e.g. 0.0718 for 7.18%) over `termYears`. Returns null for invalid inputs.
 */
export function monthlyPayment(principal, annualRate, termYears) {
  if (![principal, annualRate, termYears].every(Number.isFinite)) return null;
  if (principal < 0 || annualRate < 0 || annualRate >= 1 || termYears <= 0) return null;
  const n = Math.round(termYears * 12);
  if (n < 1) return null;
  const i = annualRate / 12;
  if (i === 0) return principal / n;
  return (principal * i) / (1 - Math.pow(1 + i, -n));
}

/**
 * Scenario payment for a metro's median home value.
 * homeValue: observed ACS median value (a {value, status, ...} field or a number).
 * rate: {value: annual rate as a fraction, as_of} from the rate source, or null if unavailable.
 * Returns null when any input is unavailable, so nothing is shown rather than guessed.
 */
export function mortgageScenario(homeValue, rate, {
  downPayment = MORTGAGE_DEFAULTS.downPayment,
  termYears = MORTGAGE_DEFAULTS.termYears,
} = {}) {
  const value = typeof homeValue === "number" ? homeValue : ok(homeValue);
  const annualRate = rate && Number.isFinite(rate.value) ? rate.value : null;
  if (value == null || annualRate == null) return null;
  if (!Number.isFinite(downPayment) || downPayment < 0 || downPayment >= 1) return null;
  const loan = value * (1 - downPayment);
  const payment = monthlyPayment(loan, annualRate, termYears);
  if (payment == null) return null;
  return {
    tier: "scenario",
    value: payment,
    loan,
    assumptions: {
      home_value: value,
      down_payment: downPayment,
      term_years: termYears,
      annual_rate: annualRate,
      rate_as_of: rate.as_of ?? null,
    },
    excludes: ["property taxes", "homeowner's insurance"],
  };
}

// ---------- Homeownership (observed) ----------

/** Observed ACS owner costs (with a mortgage) and median home value for a metro, with hours of work. */
export function ownerResults(metro, wage) {
  const field = (k) => (metro.owner && metro.owner[k]) || { value: null, status: "not_covered" };
  const cost = field("owner_cost_with_mortgage");
  const home = field("home_value");
  return {
    ownerCost: { status: cost.status, cost: ok(cost), moe: cost.moe ?? null, hours: hoursFor(ok(cost), wage) },
    homeValue: { status: home.status, value: ok(home), moe: home.moe ?? null },
  };
}

// ---------- Groceries (estimated items, scenario total) ----------

/**
 * Hours of work for each basket item at the metro's estimated price.
 * basket: the bundle's `basket` (labels, units, quantities, national prices).
 */
export function groceryResults(metro, basket, wage) {
  return Object.entries(basket.items).map(([key, item]) => {
    const field = (metro.groceries && metro.groceries[key]) || { value: null, status: "not_covered" };
    const price = ok(field);
    return {
      key, label: item.label, unit: item.unit, quantity: item.quantity,
      status: field.status, tier: field.tier ?? null, method: field.method ?? null,
      price, national: ok(item.national), hours: hoursFor(price, wage),
    };
  });
}

/**
 * Basket total for a metro: sum of quantity x estimated price. Tier "scenario",
 * because the total depends on the chosen quantities. Returns null if any item
 * is unavailable, so a partial basket is never shown as a total.
 */
export function basketScenario(items, basket, { rppYear = null } = {}) {
  if (!items.length || items.some((i) => i.price == null)) return null;
  const value = items.reduce((sum, i) => sum + i.price * i.quantity, 0);
  return {
    tier: "scenario",
    value,
    assumptions: {
      basket_version: basket.version,
      quantities: Object.fromEntries(items.map((i) => [i.key, `${i.quantity} ${i.unit}`])),
      national_prices_as_of: basket.as_of,
      rpp_year: rppYear,
      item_prices: "estimated (national BLS price x BEA all-goods RPP / 100)",
    },
  };
}

/** Parse a user-entered annual rate in percent ("6.25", "6.25%") into a fraction, else null. */
export function parseRatePercent(text) {
  if (text == null) return null;
  const cleaned = String(text).replace(/[%\s]/g, "");
  if (!/^\d*\.?\d+$/.test(cleaned)) return null;
  const pct = Number(cleaned);
  return Number.isFinite(pct) && pct > 0 && pct < 30 ? pct / 100 : null;
}
