// Fills methodology.html with periods, dates, and a worked example from the site data,
// so the page stays current whenever the data is rebuilt.
import {
  computeResults, formatDuration, formatMoney, formatGasPrice, ownerResults, groceryResults,
} from "./calc.js";

const EXAMPLE_METRO = "35620"; // New York-Newark-Jersey City

async function init() {
  let data;
  try {
    const resp = await fetch("data/metros.json");
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    data = await resp.json();
  } catch (err) {
    document.getElementById("example").textContent = `Could not load data (${err.message}).`;
    return;
  }
  const s = data.sources;

  for (const el of document.querySelectorAll("[data-period]")) {
    el.textContent = s[el.dataset.period]?.reference_period ?? "—";
  }
  for (const id of ["rpp-year", "rpp-year-2"]) {
    document.getElementById(id).textContent = s.grocery_estimates?.rpp_year ?? "—";
  }
  for (const el of document.querySelectorAll("[data-count]")) el.textContent = data.metros.length;
  document.getElementById("built").textContent = data.built;
  document.getElementById("periods").textContent =
    `Wages are from ${s.wage.reference_period}, rent from ${s.rent.reference_period}, ` +
    `gas from ${s.gas.reference_period}, home values and owner costs from ${s.owner?.reference_period}, ` +
    `national grocery prices from ${s.groceries?.reference_period}, and BEA price levels from ` +
    `${s.grocery_estimates?.rpp_year}`;

  const metro = data.metros.find((m) => m.cbsa === EXAMPLE_METRO);
  if (!metro) return;
  const r = computeResults(metro);
  const wage = formatMoney(r.wage.value, { cents: true });
  const parts = [`at the median wage of ${wage}/hr.`];
  if (r.rent.cost != null) {
    parts.push(`Rent: ${formatMoney(r.rent.cost)} ÷ ${wage} = ${formatDuration(r.rent.hours)} per month.`);
  }
  if (r.gasGallon.cost != null) {
    parts.push(`Gas: ${formatGasPrice(r.gasGallon.cost)} ÷ ${wage} = ${formatDuration(r.gasGallon.hours)} per gallon; ` +
      `15 × ${formatGasPrice(r.gasGallon.cost)} = ${formatMoney(r.gasFill.cost, { cents: true })} ÷ ${wage} = ` +
      `${formatDuration(r.gasFill.hours)} per fill-up.`);
  }
  if (data.basket) {
    const milk = groceryResults(metro, data.basket, r.wage.value).find((i) => i.key === "milk");
    if (milk && milk.price != null) {
      const rpp = metro.rpp_goods.value;
      parts.push(`Milk (estimated): ${formatMoney(milk.national, { cents: true })} national × ${rpp.toFixed(1)} ÷ 100 = ` +
        `${formatMoney(milk.price, { cents: true })} ÷ ${wage} = ${formatDuration(milk.hours)} per gallon.`);
    }
  }
  const own = ownerResults(metro, r.wage.value);
  if (own.ownerCost.cost != null) {
    parts.push(`Owner costs: ${formatMoney(own.ownerCost.cost)} ÷ ${wage} = ${formatDuration(own.ownerCost.hours)} per month.`);
  }
  const title = document.createElement("strong");
  title.textContent = `Example: ${metro.name}`;
  document.getElementById("example").replaceChildren(title, ` ${parts.join(" ")}`);
}

init();
