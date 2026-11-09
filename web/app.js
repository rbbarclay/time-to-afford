// Time to Afford: "your wages" mode.
// Privacy: the wage lives only in this page's memory. Nothing is stored (no cookies,
// localStorage, or URL parameters) and nothing is sent anywhere.
import {
  parseAmount, toHourly, computeResults, formatDuration, formatMoney, formatGasPrice,
} from "./calc.js";

const DEFAULT_METRO = "35620"; // New York-Newark-Jersey City (largest metro)
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

  // Radio buttons have no shared name (so nothing can be submitted); keep them exclusive by hand.
  for (const [id, other] of [["unit-hour", "unit-year"], ["unit-year", "unit-hour"]]) {
    $(id).addEventListener("change", () => { $(other).checked = !$(id).checked; render(); });
  }
  for (const id of ["metro", "rent-measure"]) $(id).addEventListener("change", render);
  $("wage").addEventListener("input", render);

  const s = data.sources;
  $("periods").textContent =
    `wages ${s.wage.reference_period}, rent ${s.rent.reference_period}, gas ${s.gas.reference_period}`;
  $("built").textContent = `Site data built ${data.built}.`;
  render();
}

function readWage() {
  const text = $("wage").value.trim();
  if (!text) return { hourly: null, error: null };
  const amount = parseAmount(text);
  if (amount == null) return { hourly: null, error: "Enter a positive number, like 25 or 52,000." };
  const unit = $("unit-year").checked ? "year" : "hour";
  return { hourly: toHourly(amount, unit), error: null };
}

function renderWageMessage(r, s) {
  const el = $("wage-used");
  const money = (v) => `${formatMoney(v, { cents: true })}/hr`;
  if (r.wage.source === "yours") {
    const median = r.wage.median != null ? ` This metro's median is ${money(r.wage.median)}.` : "";
    el.textContent = `Using your wage: ${money(r.wage.value)}.${median}`;
  } else if (r.wage.source === "median") {
    el.textContent = `Using this metro's median wage: ${money(r.wage.value)} ` +
      `(BLS OEWS, ${s.wage.reference_period}). Enter your wage above to use yours.`;
  } else {
    el.textContent = "No median wage is available for this metro. Enter your wage above.";
  }
}

function renderRent(r, s, rentMeasure) {
  const label = s.rent.measures[rentMeasure].toLowerCase();
  $("rent-label").textContent = `· ${label}`;
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
  $("rent-source").textContent = `Census ACS, ${s.rent.reference_period}`;
}

function renderGas(r, s) {
  const missing = r.gasGallon.cost == null;
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
  $("gas-source").textContent = `EIA, ${s.gas.reference_period}`;
}

function render() {
  const metro = metrosByCode.get($("metro").value);
  if (!metro) return;
  const rentMeasure = $("rent-measure").value;
  const { hourly, error } = readWage();

  $("wage-error").hidden = !error;
  $("wage-error").textContent = error ?? "";

  const r = computeResults(metro, { yourHourly: hourly, rentMeasure });
  renderWageMessage(r, data.sources);
  renderRent(r, data.sources, rentMeasure);
  renderGas(r, data.sources);
}

init();
