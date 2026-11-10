import { test } from "node:test";
import assert from "node:assert/strict";
import {
  parseAmount, toHourly, hoursFor, computeResults, formatDuration, formatMoney, formatGasPrice,
  HOURS_PER_YEAR, GAS_FILL_GALLONS,
} from "../calc.js";

const ok = (value, extra = {}) => ({ value, status: "ok", ...extra });
const seattle = {
  cbsa: "42660", name: "Seattle-Tacoma-Bellevue, WA",
  wage_median: ok(34.91),
  rent: { all_units: ok(2121, { moe: 25 }), one_bedroom: ok(1871, { moe: 31 }), two_bedroom: ok(2214, { moe: 35 }) },
  gas: ok(5.553),
};
const abilene = {
  cbsa: "10180", name: "Abilene, TX",
  wage_median: ok(21.32),
  rent: { all_units: ok(1230, { moe: 66 }), one_bedroom: { value: null, moe: null, status: "missing" }, two_bedroom: ok(1225, { moe: 82 }) },
  gas: { value: null, status: "not_covered" },
};

test("parseAmount accepts common formats and rejects junk", () => {
  assert.equal(parseAmount("32"), 32);
  assert.equal(parseAmount("$32.50"), 32.5);
  assert.equal(parseAmount(" 65,000 "), 65000);
  assert.equal(parseAmount(".5"), 0.5);
  for (const bad of ["", "abc", "-5", "0", "1.2.3", "12abc", null, undefined]) assert.equal(parseAmount(bad), null, String(bad));
});

test("toHourly converts annual pay at 2080 hours", () => {
  assert.equal(HOURS_PER_YEAR, 2080);
  assert.equal(toHourly(20.8, "hour"), 20.8);
  assert.equal(toHourly(62400, "year"), 30);
  assert.equal(toHourly(null, "year"), null);
});

test("hoursFor handles missing inputs", () => {
  assert.equal(hoursFor(100, 25), 4);
  assert.equal(hoursFor(null, 25), null);
  assert.equal(hoursFor(100, null), null);
  assert.equal(hoursFor(100, 0), null);
});

test("defaults to metro median wage when no wage entered", () => {
  const r = computeResults(seattle);
  assert.equal(r.wage.source, "median");
  assert.equal(r.wage.value, 34.91);
  assert.equal(r.rent.hours, 2121 / 34.91);
  assert.equal(r.rent.moe, 25);
  assert.equal(r.gasGallon.hours, 5.553 / 34.91);
  assert.equal(GAS_FILL_GALLONS, 15);
  assert.equal(r.gasFill.cost, 5.553 * 15);
  assert.equal(r.gasFill.hours, (5.553 * 15) / 34.91);
});

test("uses your wage when given, and the rent measure selected", () => {
  const r = computeResults(seattle, { yourHourly: 40, rentMeasure: "two_bedroom" });
  assert.equal(r.wage.source, "yours");
  assert.equal(r.wage.median, 34.91);
  assert.equal(r.rent.cost, 2214);
  assert.equal(r.rent.hours, 2214 / 40);
});

test("missing and not-covered values stay missing", () => {
  const r = computeResults(abilene, { rentMeasure: "one_bedroom" });
  assert.equal(r.rent.status, "missing");
  assert.equal(r.rent.hours, null);
  assert.equal(r.gasGallon.status, "not_covered");
  assert.equal(r.gasGallon.hours, null);
  assert.equal(r.gasFill.cost, null);
});

test("missing median wage with no user wage yields no hours", () => {
  const r = computeResults({ ...seattle, wage_median: { value: null, status: "missing" } });
  assert.equal(r.wage.source, "none");
  assert.equal(r.rent.hours, null);
});

test("formatters", () => {
  assert.equal(formatDuration(65.4167), "65.4 hours");
  assert.equal(formatDuration(1), "1.0 hours");
  assert.equal(formatDuration(0.159), "10 min");
  assert.equal(formatDuration(0.001), "1 min");
  assert.equal(formatDuration(null), "—");
  assert.equal(formatMoney(2121), "$2,121");
  assert.equal(formatMoney(83.295, { cents: true }), "$83.30");
  assert.equal(formatGasPrice(5.553), "$5.553");
  assert.equal(formatGasPrice(null), "—");
});

// ---------- mortgage scenario ----------
import { monthlyPayment, mortgageScenario, MORTGAGE_DEFAULTS } from "../calc.js";

const cents = (x) => Math.round(x * 100) / 100;

test("monthlyPayment matches known amortization examples", () => {
  assert.equal(cents(monthlyPayment(200000, 0.06, 30)), 1199.10); // textbook example
  assert.equal(cents(monthlyPayment(100000, 0.05, 30)), 536.82);
  assert.equal(cents(monthlyPayment(300000, 0.04, 15)), 2219.06);
});

test("monthlyPayment: zero rate and invalid inputs", () => {
  assert.equal(cents(monthlyPayment(240000, 0, 30)), 666.67);
  assert.equal(monthlyPayment(0, 0.06, 30), 0);
  for (const args of [[-1, 0.06, 30], [100000, -0.01, 30], [100000, 1, 30], [100000, 0.06, 0],
                      [NaN, 0.06, 30], [100000, null, 30], [100000, 0.06, undefined]]) {
    assert.equal(monthlyPayment(...args), null, JSON.stringify(args));
  }
});

test("mortgageScenario defaults: 20% down, 30 years, labeled scenario", () => {
  assert.deepEqual({ ...MORTGAGE_DEFAULTS }, { downPayment: 0.2, termYears: 30 });
  const s = mortgageScenario({ value: 250000, status: "ok" }, { value: 0.06, as_of: "2026-11-05" });
  assert.equal(s.tier, "scenario");
  assert.equal(s.loan, 200000);
  assert.equal(cents(s.value), 1199.10);
  assert.deepEqual(s.assumptions, { home_value: 250000, down_payment: 0.2, term_years: 30,
                                    annual_rate: 0.06, rate_as_of: "2026-11-05" });
  assert.deepEqual(s.excludes, ["property taxes", "homeowner's insurance"]);
});

test("mortgageScenario with user-edited down payment and term", () => {
  const s = mortgageScenario(375000, { value: 0.04 }, { downPayment: 0.2, termYears: 15 });
  assert.equal(cents(s.value), 2219.06);
  assert.equal(s.assumptions.rate_as_of, null);
  const zeroDown = mortgageScenario(200000, { value: 0.06 }, { downPayment: 0 });
  assert.equal(cents(zeroDown.value), 1199.10);
});

test("mortgageScenario returns null rather than guessing", () => {
  assert.equal(mortgageScenario({ value: null, status: "top_coded" }, { value: 0.06 }), null);
  assert.equal(mortgageScenario(250000, null), null); // no rate source available
  assert.equal(mortgageScenario(250000, { value: null }), null);
  assert.equal(mortgageScenario(250000, { value: 0.06 }, { downPayment: 1 }), null);
  assert.equal(mortgageScenario(250000, { value: 0.06 }, { downPayment: -0.1 }), null);
  assert.equal(mortgageScenario(250000, { value: 0.06 }, { termYears: 0 }), null);
});

test("scenario payment converts to hours like rent", () => {
  const s = mortgageScenario(250000, { value: 0.06 });
  assert.equal(cents(hoursFor(s.value, 29.53)), cents(1199.10 / 29.53));
});
