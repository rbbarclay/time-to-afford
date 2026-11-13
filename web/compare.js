// Time to Afford: compare two metros.
// Privacy: the wage, metro choices and mortgage inputs live only in this page's memory. Nothing is
// stored (no cookies, localStorage, or URL parameters) and nothing is sent anywhere.
import {
  parseAmount, toHourly, formatDuration, formatMoney, formatGasPrice, parseRatePercent,
  compareMetros, MORTGAGE_DEFAULTS,
} from "./calc.js";
import { tierBadge, fillMethod, methodDetails } from "./ui.js";

const DEFAULT_A = "35620"; // New York-Newark-Jersey City
const DEFAULT_B = "26420"; // Houston-Pasadena-The Woodlands (also has EIA gas prices)
const $ = (id) => document.getElementById(id);

let data = null;
let metrosByCode = new Map();

async function init() {
  try {
    const resp = await fetch("data/metros.json");
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    data = await resp.json();
  } catch (err) {
    $("wage-note").textContent = `Could not load data (${err.message}).`;
    return;
  }
  metrosByCode = new Map(data.metros.map((m) => [m.cbsa, m]));
  for (const [id, code, fallback] of [["metro-a", DEFAULT_A, 0], ["metro-b", DEFAULT_B, 1]]) {
    const sel = $(id);
    sel.replaceChildren(...data.metros.map((m) => new Option(m.name, m.cbsa)));
    sel.value = metrosByCode.has(code) ? code : data.metros[fallback].cbsa;
    sel.disabled = false;
  }
  const rentSel = $("rent-measure");
  rentSel.replaceChildren(...Object.entries(data.sources.rent.measures).map(([k, label]) => new Option(label, k)));
  rentSel.value = data.sources.rent.default_measure;
  rentSel.disabled = false;
  resetMortgageInputs();

  for (const [id, other] of [["unit-hour", "unit-year"], ["unit-year", "unit-hour"]]) {
    $(id).addEventListener("change", () => { $(other).checked = !$(id).checked; render(); });
  }
  for (const id of ["metro-a", "metro-b", "rent-measure", "mort-term"]) $(id).addEventListener("change", render);
  for (const id of ["wage", "mort-rate", "mort-down"]) $(id).addEventListener("input", render);
  $("mort-reset").addEventListener("click", () => { resetMortgageInputs(); render(); });
  $("swap").addEventListener("click", () => {
    [$("metro-a").value, $("metro-b").value] = [$("metro-b").value, $("metro-a").value];
    render();
  });
  $("toggle-items").addEventListener("click", () => {
    const show = $("item-rows").hidden;
    $("item-rows").hidden = !show;
    $("toggle-items").setAttribute("aria-expanded", String(show));
    $("toggle-items").textContent = show ? "Hide the six grocery items" : "Show the six grocery items";
  });
  $("toggle-items").hidden = !data.basket;

  const s = data.sources;
  const periods = [`wages ${s.wage.reference_period}`, `rent ${s.rent.reference_period}`,
    `gas ${s.gas.reference_period}`];
  if (s.owner) periods.push(`owner costs and home values ${s.owner.reference_period}`);
  if (s.grocery_estimates) periods.push(`groceries ${s.grocery_estimates.reference_period}`);
  $("periods").textContent = periods.join(", ");
  $("built").textContent = `Site data built ${data.built}.`;
  render();
}

function resetMortgageInputs() {
  $("mort-down").value = String(MORTGAGE_DEFAULTS.downPayment * 100);
  $("mort-term").value = String(MORTGAGE_DEFAULTS.termYears);
}

/** "New York" from "New York-Newark-Jersey City, NY-NJ". */
export function shortName(name) {
  return name.split(/[-,]/)[0].trim();
}

function readInputs() {
  const errors = { wage: null, mortgage: [] };
  const wageText = $("wage").value.trim();
  let yourHourly = null;
  if (wageText) {
    const amount = parseAmount(wageText);
    if (amount == null) errors.wage = "Enter a positive number, like 25 or 52,000.";
    else yourHourly = toHourly(amount, $("unit-year").checked ? "year" : "hour");
  }
  const rateText = $("mort-rate").value.trim();
  const rate = rateText ? parseRatePercent(rateText) : null;
  if (rateText && rate == null) errors.mortgage.push("Enter a rate between 0 and 30, like 6.5.");
  const downText = $("mort-down").value.trim().replace(/%$/, "");
  const downPct = downText === "" ? NaN : Number(downText);
  const downOk = Number.isFinite(downPct) && downPct >= 0 && downPct < 100;
  if (!downOk) errors.mortgage.push("Enter a down payment from 0 to 99 percent.");
  const mortgage = rate != null && downOk
    ? { rate, downPayment: downPct / 100, termYears: Number($("mort-term").value) } : null;
  return { yourHourly, mortgage, errors };
}

// ---------- cell text ----------

const ROWS = {
  rent: { label: () => `Rent · ${data.sources.rent.measures[$("rent-measure").value].toLowerCase()}`, per: "per month" },
  gas_fill: { label: () => "Gas · 15-gallon fill-up", per: "" },
  basket: { label: () => "Groceries · six-item basket", per: "" },
  owner_cost: { label: () => "Owner costs with a mortgage", per: "per month" },
  mortgage: { label: () => "Mortgage payment (principal and interest)", per: "per month" },
};

function statusText(key, cell) {
  switch (cell.status) {
    case "not_covered":
      return key === "gas_fill" ? "Not covered (EIA has gas prices for 10 metros)"
        : key === "basket" ? "No estimate (no BEA price level)" : "Not covered";
    case "top_coded":
      return key === "rent" ? "Above $3,500" : key === "owner_cost" ? "Above $4,000"
        : key === "mortgage" ? "Home value $2,000,000 or more; no payment calculated" : "Top-coded";
    case "needs_input":
      return "Enter an interest rate above";
    default:
      return "No data";
  }
}

function costText(key, cell) {
  const moe = cell.moe != null ? ` ±${formatMoney(cell.moe)}` : "";
  switch (key) {
    case "gas_fill": return `${formatMoney(cell.cost, { cents: true })} (${formatGasPrice(cell.perGallon)}/gallon)`;
    case "basket": return formatMoney(cell.cost, { cents: true });
    case "mortgage": return `${formatMoney(cell.cost)} on a ${formatMoney(cell.homeValue.value)} home`;
    default: return `${formatMoney(cell.cost)}${moe}`;
  }
}

function valueCell(label, key, cell) {
  const td = document.createElement("td");
  td.dataset.label = label;
  if (cell.hours == null && cell.cost == null) {
    td.className = "is-missing";
    td.textContent = statusText(key, cell);
    return td;
  }
  const big = document.createElement("span");
  big.className = "cmp-hours";
  big.textContent = formatDuration(cell.hours);
  const cost = document.createElement("span");
  cost.className = "cmp-cost";
  cost.textContent = costText(key, cell) + (ROWS[key]?.per ? ` ${ROWS[key].per}` : "");
  td.append(big, cost);
  return td;
}

function diffCell(diff, nameB) {
  const td = document.createElement("td");
  td.dataset.label = "Difference";
  if (!diff) {
    td.className = "is-missing";
    td.textContent = "—";
    return td;
  }
  const abs = Math.abs(diff.hours);
  if (abs < 1 / 60) {
    td.textContent = "About the same";
    return td;
  }
  const whole = diff.pct != null ? Math.abs(Math.round(diff.pct * 100)) : null;
  const pct = whole == null ? "" : whole === 0 ? " (under 1%)" : ` (${diff.pct > 0 ? "+" : "−"}${whole}%)`;
  td.className = diff.hours > 0 ? "diff-more" : "diff-less";
  td.textContent = `${nameB}: ${formatDuration(abs)} ${diff.hours > 0 ? "more" : "fewer"}${pct}`;
  return td;
}

function labelCell(text, tier, methodKeys) {
  const th = document.createElement("th");
  th.scope = "row";
  th.append(text, " ");
  if (tier) th.append(tierBadge(tier));
  const details = methodDetails();
  fillMethod(details, data.methods, methodKeys);
  th.append(details);
  return th;
}

// ---------- render ----------

function renderWage(c, a, b, yourHourly) {
  const money = (v) => (v == null ? "no median available" : `${formatMoney(v, { cents: true })}/hr`);
  const [na, nb] = [shortName(a.name), shortName(b.name)];
  $("wage-note").textContent = yourHourly != null
    ? `Using your wage, ${money(yourHourly)}, in both metros. Medians: ${money(c.wage.a.median)} in ${na}, ` +
      `${money(c.wage.b.median)} in ${nb}.`
    : `No wage entered, so each column uses that metro's median wage: ${money(c.wage.a.value)} in ${na}, ` +
      `${money(c.wage.b.value)} in ${nb}. Enter your wage to use it for both.`;

  const tr = document.createElement("tr");
  tr.className = "wage-row-cmp";
  const tier = yourHourly != null ? null : "observed";
  tr.append(labelCell("Wage used", tier, yourHourly != null ? [] : [a.wage_median.method, b.wage_median.method]));
  for (const [label, w] of [[na, c.wage.a], [nb, c.wage.b]]) {
    const td = document.createElement("td");
    td.dataset.label = label;
    td.textContent = w.value == null ? "No median wage" : `${money(w.value)}${w.source === "yours" ? " (yours)" : ""}`;
    if (w.value == null) td.className = "is-missing";
    tr.append(td);
  }
  const d = document.createElement("td");
  d.dataset.label = "Difference";
  const wa = c.wage.a.value, wb = c.wage.b.value;
  if (yourHourly != null) d.textContent = "Same wage";
  else if (wa == null || wb == null) { d.textContent = "—"; d.className = "is-missing"; }
  else d.textContent = `${nb}: ${formatMoney(Math.abs(wb - wa), { cents: true })}/hr ${wb >= wa ? "more" : "less"}`;
  tr.append(d);
  return tr;
}

function render() {
  const a = metrosByCode.get($("metro-a").value);
  const b = metrosByCode.get($("metro-b").value);
  if (!a || !b) return;
  const { yourHourly, mortgage, errors } = readInputs();
  $("wage-error").hidden = !errors.wage;
  $("wage-error").textContent = errors.wage ?? "";
  $("mort-error").hidden = errors.mortgage.length === 0;
  $("mort-error").textContent = errors.mortgage.join(" ");

  const c = compareMetros(a, b, {
    yourHourly, rentMeasure: $("rent-measure").value, basket: data.basket ?? null,
    rppYear: data.sources.grocery_estimates?.rpp_year ?? null, mortgage,
  });
  const [na, nb] = [shortName(a.name), shortName(b.name)];
  $("head-a").textContent = a.name;
  $("head-b").textContent = b.name;

  const rows = [renderWage(c, a, b, yourHourly)];
  for (const row of c.rows) {
    const tr = document.createElement("tr");
    const tier = row.key === "basket" || row.key === "mortgage" ? "scenario" : (row.a.tier ?? row.b.tier);
    const keys = [row.a.method, row.b.method];
    if (row.key === "basket") keys.push(a.rpp_goods?.method, b.rpp_goods?.method);
    tr.append(labelCell(ROWS[row.key].label(), tier, keys),
      valueCell(na, row.key, row.a), valueCell(nb, row.key, row.b), diffCell(row.diff, nb));
    rows.push(tr);
  }
  $("rows").replaceChildren(...rows);

  const head = document.createElement("tr");
  head.className = "items-head";
  const headCell = document.createElement("th");
  headCell.colSpan = 4;
  headCell.scope = "colgroup";
  headCell.textContent = "Grocery basket items (estimated local prices)";
  head.append(headCell);
  $("item-rows").replaceChildren(head, ...c.items.map((it) => {
    const tr = document.createElement("tr");
    const th = document.createElement("th");
    th.scope = "row";
    th.append(`${it.label}, per ${it.unit} `, tierBadge("estimated"));
    const cell = (label, i) => {
      const td = document.createElement("td");
      td.dataset.label = label;
      if (i.price == null) { td.className = "is-missing"; td.textContent = i.status === "not_covered" ? "No estimate" : "No data"; return td; }
      const big = document.createElement("span");
      big.className = "cmp-hours";
      big.textContent = formatDuration(i.hours);
      const cost = document.createElement("span");
      cost.className = "cmp-cost";
      cost.textContent = formatMoney(i.price, { cents: true });
      td.append(big, cost);
      return td;
    };
    tr.append(th, cell(na, it.a), cell(nb, it.b), diffCell(it.diff, nb));
    return tr;
  }));
}

init();
