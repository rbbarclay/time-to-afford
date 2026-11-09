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
