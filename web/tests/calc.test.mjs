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

import { ownerResults, groceryResults, basketScenario, parseRatePercent } from "../calc.js";

const basket = {
  version: 1, as_of: "2026-10",
  items: {
    milk: { label: "Milk, whole", unit: "gallon", quantity: 1, national: ok(4.101) },
    eggs: { label: "Eggs", unit: "dozen", quantity: 2, national: ok(2.32) },
  },
};
const est = (v, method) => ({ value: v, status: "ok", tier: "estimated", method });

test("ownerResults gives hours for owner costs and keeps top-coded/not-covered status", () => {
  const ny = { owner: { home_value: ok(691700, { moe: 5263 }), owner_cost_with_mortgage: ok(3441, { moe: 23 }) } };
  const r = ownerResults(ny, 37.4);
  assert.equal(r.ownerCost.cost, 3441);
  assert.equal(r.ownerCost.hours, 3441 / 37.4);
  assert.equal(r.homeValue.value, 691700);
  const sf = { owner: { home_value: ok(1152400), owner_cost_with_mortgage: { value: null, moe: null, status: "top_coded" } } };
  assert.equal(ownerResults(sf, 40).ownerCost.status, "top_coded");
  assert.equal(ownerResults(sf, 40).ownerCost.hours, null);
  assert.equal(ownerResults({}, 40).homeValue.status, "not_covered");
});

test("groceryResults uses the metro's estimated prices", () => {
  const metro = { groceries: { milk: est(4.522, "est_milk"), eggs: est(2.558, "est_eggs") } };
  const items = groceryResults(metro, basket, 22.61);
  assert.deepEqual(items.map((i) => i.key), ["milk", "eggs"]);
  assert.equal(items[0].price, 4.522);
  assert.equal(items[0].national, 4.101);
  assert.equal(items[0].tier, "estimated");
  assert.equal(items[0].hours, 4.522 / 22.61);
});

test("basketScenario is a scenario total of quantity x price, or null if any item is missing", () => {
  const metro = { groceries: { milk: est(4.5, "m"), eggs: est(2.5, "e") } };
  const s = basketScenario(groceryResults(metro, basket, 20), basket, { rppYear: 2024 });
  assert.equal(s.tier, "scenario");
  assert.equal(s.value, 4.5 + 2 * 2.5);
  assert.deepEqual(s.assumptions.quantities, { milk: "1 gallon", eggs: "2 dozen" });
  assert.equal(s.assumptions.national_prices_as_of, "2026-10");
  assert.equal(s.assumptions.rpp_year, 2024);
  const pr = { groceries: { milk: { value: null, status: "not_covered" }, eggs: { value: null, status: "not_covered" } } };
  assert.equal(basketScenario(groceryResults(pr, basket, 20), basket), null);
  const partial = { groceries: { milk: est(4.5, "m"), eggs: { value: null, status: "missing", tier: "estimated", method: "e" } } };
  assert.equal(basketScenario(groceryResults(partial, basket, 20), basket), null);
});

test("parseRatePercent accepts percents and rejects junk", () => {
  assert.equal(parseRatePercent("6.25"), 0.0625);
  assert.equal(parseRatePercent(" 7% "), 0.07);
  for (const bad of ["", "abc", "0", "-5", "45", null]) assert.equal(parseRatePercent(bad), null, String(bad));
});

test("mortgageScenario with a user-entered rate has no rate date", () => {
  const s = mortgageScenario(250000, { value: parseRatePercent("6"), as_of: null });
  assert.equal(s.value.toFixed(2), "1199.10");
  assert.equal(s.assumptions.rate_as_of, null);
});

import { compareMetros, hoursDiff } from "../calc.js";

const cmpBasket = { version: 1, as_of: "2026-10", items: { milk: { label: "Milk", unit: "gallon", quantity: 1, national: ok(4) } } };
const metroA = {
  cbsa: "A", name: "A", wage_median: ok(20, { tier: "observed", method: "w" }),
  rent: { all_units: ok(2000, { moe: 10, tier: "observed", method: "r" }) },
  gas: ok(4, { tier: "observed", method: "g" }),
  owner: { home_value: ok(400000, { method: "hv" }), owner_cost_with_mortgage: ok(3000, { method: "oc" }) },
  groceries: { milk: est(4.4, "em") }, rpp_goods: ok(110),
};
const metroB = {
  cbsa: "B", name: "B", wage_median: ok(25),
  rent: { all_units: ok(1500, { moe: 20 }) },
  gas: { value: null, status: "not_covered" },
  owner: { home_value: { value: null, status: "top_coded" }, owner_cost_with_mortgage: ok(2500) },
  groceries: { milk: { value: null, status: "not_covered" } }, rpp_goods: { value: null, status: "not_covered" },
};

test("hoursDiff is B minus A, with share of A", () => {
  assert.deepEqual(hoursDiff(100, 75), { hours: -25, pct: -0.25 });
  assert.equal(hoursDiff(null, 5), null);
  assert.equal(hoursDiff(5, null), null);
});

test("compareMetros uses each metro's median, or your wage for both", () => {
  const c = compareMetros(metroA, metroB, { basket: cmpBasket });
  assert.equal(c.wage.a.value, 20);
  assert.equal(c.wage.b.value, 25);
  assert.equal(c.wage.sameWage, false);
  const rent = c.rows.find((r) => r.key === "rent");
  assert.equal(rent.a.hours, 100);
  assert.equal(rent.b.hours, 60);
  assert.deepEqual(rent.diff, { hours: -40, pct: -0.4 });
  assert.equal(rent.a.tier, "observed");

  const mine = compareMetros(metroA, metroB, { yourHourly: 50, basket: cmpBasket });
  assert.equal(mine.wage.sameWage, true);
  assert.equal(mine.rows.find((r) => r.key === "rent").a.hours, 40);
  assert.equal(mine.rows.find((r) => r.key === "rent").b.hours, 30);
});

test("compareMetros keeps missing sides labeled and gives no difference", () => {
  const c = compareMetros(metroA, metroB, { basket: cmpBasket, mortgage: { rate: 0.06, downPayment: 0.2, termYears: 30 } });
  const row = (k) => c.rows.find((r) => r.key === k);
  assert.deepEqual(c.rows.map((r) => r.key), ["rent", "gas_fill", "basket", "owner_cost", "mortgage"]);
  assert.equal(row("gas_fill").a.cost, 60);
  assert.equal(row("gas_fill").b.status, "not_covered");
  assert.equal(row("gas_fill").diff, null);
  assert.equal(row("basket").a.cost, 4.4);
  assert.equal(row("basket").a.tier, "scenario");
  assert.equal(row("basket").b.status, "not_covered");
  assert.equal(row("mortgage").a.cost.toFixed(2), "1918.56");
  assert.equal(row("mortgage").b.status, "top_coded");
  assert.equal(c.items[0].a.price, 4.4);
  assert.equal(c.items[0].diff, null);
});

test("compareMetros mortgage needs a rate", () => {
  const c = compareMetros(metroA, metroA, { basket: cmpBasket });
  const m = c.rows.find((r) => r.key === "mortgage");
  assert.equal(m.a.status, "needs_input");
  assert.equal(m.a.cost, null);
});

import { mapMeasures, measureField, mapValues, quantileBreaks, groupOf } from "../calc.js";

test("mapMeasures: observed, estimated, and only the fixed-assumption basket scenario", () => {
  const data = { sources: { rent: { measures: { all_units: "All units" } }, owner: {} },
    basket: { version: 1, items: { milk: { label: "Milk, whole", unit: "gallon", quantity: 1 } } } };
  const keys = mapMeasures(data).map((m) => m.key);
  assert.deepEqual(keys, ["rent:all_units", "gas_fill", "owner_cost", "basket", "grocery:milk"]);
  const scenarios = mapMeasures(data).filter((m) => m.tier === "scenario");
  assert.deepEqual(scenarios.map((m) => m.key), ["basket"]); // never the mortgage payment
  assert.match(scenarios[0].assumptions, /one of each item \(1 gallon milk; basket version 1\)/);
  assert.equal(mapMeasures(data).find((m) => m.key === "grocery:milk").tier, "estimated");
});

test("measureField and mapValues use each median, or your wage everywhere", () => {
  assert.equal(measureField(metroA, "gas_fill").cost, 60);
  assert.equal(measureField(metroB, "gas_fill").status, "not_covered");
  assert.equal(measureField(metroA, "grocery:milk").tier, "estimated");
  assert.equal(measureField(metroB, "owner_cost").cost, 2500);
  assert.equal(measureField({ rent: {}, gas: { value: null, status: "not_covered" } }, "owner_cost").status, "not_covered");
  const v = mapValues([metroA, metroB], "rent:all_units");
  assert.deepEqual(v.map((x) => x.hours), [100, 60]);
  assert.equal(v[0].wageSource, "median");
  const mine = mapValues([metroA, metroB], "rent:all_units", { yourHourly: 50 });
  assert.deepEqual(mine.map((x) => x.hours), [40, 30]);
});

test("quantileBreaks gives min, equal-count boundaries, max; groupOf assigns groups", () => {
  const vals = Array.from({ length: 10 }, (_, i) => i + 1); // 1..10
  const b = quantileBreaks([...vals, null], 5);
  assert.deepEqual(b, [1, 3, 5, 7, 9, 10]);
  assert.deepEqual(vals.map((x) => groupOf(x, b)), [0, 0, 1, 1, 2, 2, 3, 3, 4, 4]);
  assert.equal(quantileBreaks([null], 5), null);
  assert.equal(groupOf(null, b), null);
  assert.deepEqual(quantileBreaks([7], 5), [7, 7, 7, 7, 7, 7]);
  assert.equal(groupOf(7, [7, 7, 7, 7, 7, 7]), 4);
});

test("basket on the map: total of estimated prices, scenario tier, not covered without RPP", () => {
  const a = measureField(metroA, "basket", cmpBasket);
  assert.equal(a.cost, 4.4);
  assert.equal(a.tier, "scenario");
  assert.equal(measureField(metroB, "basket", cmpBasket).status, "not_covered");
  assert.equal(measureField(metroA, "basket").status, "not_covered"); // no basket data at all
  const v = mapValues([metroA, metroB], "basket", { basket: cmpBasket, yourHourly: 22 });
  assert.deepEqual(v.map((x) => x.hours), [0.2, null]);
});

import { boundaryLabels } from "../calc.js";

test("boundaryLabels picks one unit and enough decimals to keep neighbors distinct", () => {
  assert.deepEqual(boundaryLabels([0.6483, 0.9717, 1.0333, 1.1, 1.1333, 1.4]),
    ["39 min", "58 min", "62 min", "66 min", "68 min", "84 min"]);
  assert.deepEqual(boundaryLabels([33.8, 47.5, 52.6, 59, 66, 94.1]),
    ["33.8 hours", "47.5 hours", "52.6 hours", "59.0 hours", "66.0 hours", "94.1 hours"]);
  assert.deepEqual(boundaryLabels([0.1, 0.16, 0.168, 0.17, 0.18, 0.2]).slice(1, 4), ["9.6 min", "10.1 min", "10.2 min"]);
  assert.deepEqual(boundaryLabels(null), []);
});
