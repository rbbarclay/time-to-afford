// Time to Afford: "your wages" mode.
// Privacy: the wage and the mortgage inputs live only in this page's memory. Nothing is
// stored (no cookies, localStorage, or URL parameters) and nothing is sent anywhere.
import {
  parseAmount, toHourly, computeResults, formatDuration, formatMoney, formatGasPrice,
  ownerResults, groceryResults, basketScenario, parseRatePercent, mortgageScenario, MORTGAGE_DEFAULTS,
} from "./calc.js";
import { setTier, tierBadge, fillMethod } from "./ui.js";

const DEFAULT_METRO = "35620"; // New York-Newark-Jersey City (largest metro)
const OWNER_COST_TOP = "$4,000 or more";
const HOME_VALUE_TOP = "$2,000,000 or more";
const $ = (id) => document.getElementById(id);

let data = null;
let metrosByCode = new Map();

async function init() {
  try {
    const resp = await fetch("data/metros.json");
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    data = await resp.json();
  } catch (err) {
    $("wage-used").textContent = `Could not load data (${err.message}).`;
    return;
  }
  metrosByCode = new Map(data.metros.map((m) => [m.cbsa, m]));

  const metroSel = $("metro");
  metroSel.replaceChildren(...data.metros.map((m) => new Option(m.name, m.cbsa)));
  metroSel.value = metrosByCode.has(DEFAULT_METRO) ? DEFAULT_METRO : data.metros[0].cbsa;
  metroSel.disabled = false;

  const rentSel = $("rent-measure");
  const measures = data.sources.rent.measures;
  rentSel.replaceChildren(...Object.entries(measures).map(([k, label]) => new Option(label, k)));
  rentSel.value = data.sources.rent.default_measure;
  rentSel.disabled = false;

  resetMortgageInputs();
  for (const el of document.querySelectorAll(".tier[class*='tier-']")) setTier(el, el.className.match(/tier-(\w+)/)[1]);

  // Radio buttons have no shared name (so nothing can be submitted); keep them exclusive by hand.
  for (const [id, other] of [["unit-hour", "unit-year"], ["unit-year", "unit-hour"]]) {
    $(id).addEventListener("change", () => { $(other).checked = !$(id).checked; render(); });
  }
  for (const id of ["metro", "rent-measure", "mort-term"]) $(id).addEventListener("change", render);
  for (const id of ["wage", "mort-rate", "mort-down"]) $(id).addEventListener("input", render);
  $("mort-reset").addEventListener("click", () => { resetMortgageInputs(); render(); });

  const s = data.sources;
  const periods = [`wages ${s.wage.reference_period}`, `rent ${s.rent.reference_period}`,
    `gas ${s.gas.reference_period}`];
  if (s.owner) periods.push(`owner costs and home values ${s.owner.reference_period}`);
  if (s.grocery_estimates) periods.push(`groceries ${s.grocery_estimates.reference_period}`);
  $("periods").textContent = periods.join(", ");
  $("built").textContent = `Site data built ${data.built}.`;
  $("card-groceries").hidden = !data.basket;
  $("card-home").hidden = !s.owner;
  render();
}

function resetMortgageInputs() {
  $("mort-down").value = String(MORTGAGE_DEFAULTS.downPayment * 100);
  $("mort-term").value = String(MORTGAGE_DEFAULTS.termYears);
}

// ---------- shared pieces ----------

/** Fill the <details class="method"> with this id from the bundle's methods table. */
function renderMethod(id, keys) {
  fillMethod($(id), data.methods, keys);
}

function listItems(id, lines) {
  $(id).replaceChildren(...lines.map((t) => {
    const li = document.createElement("li");
    li.textContent = t;
    return li;
  }));
}

// ---------- wage, rent, gas ----------

function readWage() {
  const text = $("wage").value.trim();
  if (!text) return { hourly: null, error: null };
  const amount = parseAmount(text);
  if (amount == null) return { hourly: null, error: "Enter a positive number, like 25 or 52,000." };
  const unit = $("unit-year").checked ? "year" : "hour";
  return { hourly: toHourly(amount, unit), error: null };
}

function renderWageMessage(r, s, metro) {
  const el = $("wage-used");
  const money = (v) => `${formatMoney(v, { cents: true })}/hr`;
  if (r.wage.source === "yours") {
    const median = r.wage.median != null ? ` This metro's median is ${money(r.wage.median)}.` : "";
    el.replaceChildren(`Using your wage: ${money(r.wage.value)}.${median}`);
  } else if (r.wage.source === "median") {
    el.replaceChildren(`Using this metro's median wage: ${money(r.wage.value)} ` +
      `(BLS OEWS, ${s.wage.reference_period}). Enter your wage above to use yours. `, tierBadge(metro.wage_median.tier));
  } else {
    el.replaceChildren("No median wage is available for this metro. Enter your wage above.");
  }
  renderMethod("wage-method", [metro.wage_median.method]);
}

function renderRent(r, s, rentMeasure, metro) {
  const label = s.rent.measures[rentMeasure].toLowerCase();
  const field = metro.rent[rentMeasure] ?? {};
  $("rent-label").textContent = `· ${label}`;
  setTier($("rent-tier"), field.tier);
  const missing = r.rent.cost == null;
  $("card-rent").classList.toggle("is-missing", missing);
  $("rent-per").hidden = missing;
  if (missing) {
    const topCoded = r.rent.status === "top_coded";
    $("rent-hours").textContent = topCoded ? "Above $3,500" : "No data";
    $("rent-inputs").textContent = topCoded
      ? "Census reports this median only as “$3,500 or more”, so hours aren't calculated."
      : `Census has no ${label} rent estimate for this metro.`;
  } else {
    $("rent-hours").textContent = formatDuration(r.rent.hours);
    const moe = r.rent.moe != null ? ` ±${formatMoney(r.rent.moe)}` : "";
    $("rent-inputs").textContent = `Median gross rent ${formatMoney(r.rent.cost)}/month${moe} (includes utilities)`;
  }
  renderMethod("rent-method", [field.method]);
  $("rent-source").textContent = `Census ACS, ${s.rent.reference_period}`;
}

function renderGas(r, s, metro) {
  const missing = r.gasGallon.cost == null;
  setTier($("gas-tier"), metro.gas.tier);
  $("card-gas").classList.toggle("is-missing", missing);
  $("gas-fill-per").hidden = missing;
  $("gas-gallon-block").hidden = missing;
  if (missing) {
    $("gas-fill-hours").textContent = "No data";
    $("gas-gallon-hours").textContent = "";
    $("gas-inputs").textContent = r.gasGallon.status === "not_covered"
      ? "EIA publishes city gas prices for only 10 metros, and this isn't one of them."
      : "EIA has no gas price for this metro in the latest month.";
  } else {
    $("gas-fill-hours").textContent = formatDuration(r.gasFill.hours);
    $("gas-gallon-hours").textContent = formatDuration(r.gasGallon.hours);
    $("gas-inputs").textContent =
      `${formatGasPrice(r.gasGallon.cost)}/gallon · ${formatMoney(r.gasFill.cost, { cents: true })} for 15 gallons`;
  }
  renderMethod("gas-method", [metro.gas.method]);
  $("gas-source").textContent = `EIA, ${s.gas.reference_period}`;
}

// ---------- groceries ----------

function renderGroceries(metro, wage) {
  if (!data.basket) return;
  const s = data.sources;
  const items = groceryResults(metro, data.basket, wage);
  const notCovered = items.every((i) => i.status === "not_covered");
  $("card-groceries").classList.toggle("is-missing", notCovered);
  $("groc-note").hidden = !notCovered;
  $("groc-note").textContent = notCovered
    ? "No estimate: BEA publishes no price level (Regional Price Parity) for this metro, so local grocery prices can't be estimated."
    : "";
  $("groc-table-wrap").hidden = notCovered;
  $("basket").hidden = notCovered;

  $("groc-rows").replaceChildren(...items.map((i) => {
    const tr = document.createElement("tr");
    const name = document.createElement("th");
    name.scope = "row";
    name.textContent = `${i.label}`;
    const unit = document.createElement("span");
    unit.className = "hint";
    unit.textContent = ` per ${i.unit}`;
    name.append(unit);
    const cells = [
      i.price != null ? formatMoney(i.price, { cents: true }) : "No data",
      i.national != null ? formatMoney(i.national, { cents: true }) : "No data",
      formatDuration(i.hours),
    ].map((t) => { const td = document.createElement("td"); td.textContent = t; return td; });
    tr.append(name, ...cells);
    return tr;
  }));

  const rpp = metro.rpp_goods && metro.rpp_goods.status === "ok" ? metro.rpp_goods.value : null;
  renderMethod("groc-method", [items[0]?.method, metro.rpp_goods?.method]);
  if (rpp != null) {
    const body = $("groc-method").querySelector("div");
    const p = document.createElement("p");
    p.textContent = `This metro's all-goods price level: ${rpp.toFixed(1)} (U.S. = 100). ` +
      `The same method applies to every item; only the national price and BLS series differ.`;
    body.prepend(p);
  }

  const total = basketScenario(items, data.basket, { rppYear: s.grocery_estimates?.rpp_year });
  if (total) {
    $("basket-hours").textContent = formatDuration(wage == null ? null : total.value / wage);
    $("basket-per").textContent = `of work for one of each item above (${formatMoney(total.value, { cents: true })})`;
    const a = total.assumptions;
    listItems("basket-assumptions", [
      `One of each item: ${Object.values(a.quantities).join(", ")} (basket version ${a.basket_version})`,
      `Estimated local prices, from national prices for ${a.national_prices_as_of} and ${a.rpp_year} price levels`,
      "Not a full grocery budget; just these six items",
    ]);
  } else if (!notCovered) {
    $("basket-hours").textContent = "No total";
    $("basket-per").textContent = "At least one item has no price, so no total is shown.";
    listItems("basket-assumptions", []);
  }
  $("groc-source").textContent =
    `BLS Average Price Data, ${s.groceries.reference_period}; BEA Regional Price Parities, ${s.grocery_estimates.rpp_year}` +
    (s.usda_tfp ? `; USDA Thrifty Food Plan, ${s.usda_tfp.reference_period}` : "");
  renderTfp(wage);
}

/** National reference line: shown beside the groceries, never mixed into them. */
function renderTfp(wage) {
  const v = data.reference?.tfp_family_monthly;
  const show = v && v.status === "ok";
  $("tfp").hidden = !show;
  if (!show) return;
  const hours = wage == null ? "" : ` That's ${formatDuration(v.value / wage)} of work a month at ${formatMoney(wage, { cents: true })}/hr.`;
  $("tfp-text").textContent = `Family of four, U.S. average: ${formatMoney(v.value, { cents: true })} a month ` +
    `(${data.sources.usda_tfp.reference_period}).${hours}`;
  renderMethod("tfp-method", [v.method]);
}

// ---------- homeownership ----------

function readMortgageInputs() {
  const rateText = $("mort-rate").value.trim();
  const rate = rateText ? parseRatePercent(rateText) : null;
  const downText = $("mort-down").value.trim().replace(/%$/, "");
  const downPct = downText === "" ? null : Number(downText);
  const errors = [];
  if (rateText && rate == null) errors.push("Enter a rate between 0 and 30, like 6.5.");
  const downOk = downPct != null && Number.isFinite(downPct) && downPct >= 0 && downPct < 100;
  if (!downOk) errors.push("Enter a down payment from 0 to 99 percent.");
  return { rate, downPayment: downOk ? downPct / 100 : null, termYears: Number($("mort-term").value), errors };
}

function renderOwner(metro, wage) {
  const s = data.sources;
  if (!s.owner) return;
  const r = ownerResults(metro, wage);

  const costMissing = r.ownerCost.cost == null;
  $("own-per").hidden = costMissing;
  if (costMissing) {
    const top = r.ownerCost.status === "top_coded";
    $("own-hours").textContent = top ? "Above $4,000" : "No data";
    $("own-inputs").textContent = top
      ? `Census reports this median only as “${OWNER_COST_TOP}”, so hours aren't calculated.`
      : "Census has no owner-cost estimate for this metro.";
  } else {
    $("own-hours").textContent = formatDuration(r.ownerCost.hours);
    const moe = r.ownerCost.moe != null ? ` ±${formatMoney(r.ownerCost.moe)}` : "";
    $("own-inputs").textContent = `Median monthly costs for owners with a mortgage: ${formatMoney(r.ownerCost.cost)}${moe}. ` +
      "Includes the mortgage, property taxes, insurance, utilities, and fees.";
  }
  renderMethod("own-method", [metro.owner?.owner_cost_with_mortgage?.method, metro.owner?.home_value?.method]);

  // Scenario: principal and interest on the observed median home value.
  const home = r.homeValue;
  const homeText = home.value != null
    ? `${formatMoney(home.value)}${home.moe != null ? ` ±${formatMoney(home.moe)}` : ""}`
    : home.status === "top_coded" ? HOME_VALUE_TOP : "not available";
  $("mort-home").replaceChildren(`Median home value: ${homeText} `, tierBadge("observed"));

  const inp = readMortgageInputs();
  $("mort-error").hidden = inp.errors.length === 0;
  $("mort-error").textContent = inp.errors.join(" ");
  const scenario = inp.rate != null && inp.downPayment != null
    ? mortgageScenario(home.value, { value: inp.rate, as_of: null },
      { downPayment: inp.downPayment, termYears: inp.termYears })
    : null;
  if (scenario) {
    const a = scenario.assumptions;
    $("mort-hours").textContent = formatDuration(wage == null ? null : scenario.value / wage);
    $("mort-per").textContent = `of work per month for ${formatMoney(scenario.value)} principal and interest ` +
      `(${(a.annual_rate * 100).toFixed(2)}%, ${Math.round(a.down_payment * 100)}% down, ${a.term_years} years, ` +
      `loan ${formatMoney(scenario.loan)})`;
  } else {
    $("mort-hours").textContent = "—";
    $("mort-per").textContent = home.value == null
      ? "No payment shown: there's no median home value to use for this metro."
      : inp.rate == null ? "Enter an interest rate to see the monthly payment." : "";
  }
  $("own-source").textContent = `Census ACS, ${s.owner.reference_period}`;
}

// ---------- main ----------

function render() {
  const metro = metrosByCode.get($("metro").value);
  if (!metro) return;
  const rentMeasure = $("rent-measure").value;
  const { hourly, error } = readWage();

  $("wage-error").hidden = !error;
  $("wage-error").textContent = error ?? "";

  const r = computeResults(metro, { yourHourly: hourly, rentMeasure });
  renderWageMessage(r, data.sources, metro);
  renderRent(r, data.sources, rentMeasure, metro);
  renderGas(r, data.sources, metro);
  renderGroceries(metro, r.wage.value);
  renderOwner(metro, r.wage.value);
}

init();
