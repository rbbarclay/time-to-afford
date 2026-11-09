// Fills methodology.html with periods, dates, and a worked example from the site data,
// so the page stays current whenever the data is rebuilt.
import { computeResults, formatDuration, formatMoney, formatGasPrice } from "./calc.js";

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
    el.textContent = s[el.dataset.period].reference_period;
  }
  for (const el of document.querySelectorAll("[data-count]")) el.textContent = data.metros.length;
  document.getElementById("built").textContent = data.built;
  document.getElementById("periods").textContent =
    `Wages are from ${s.wage.reference_period}, rent from ${s.rent.reference_period}, ` +
    `and gas from ${s.gas.reference_period}`;

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
  const title = document.createElement("strong");
  title.textContent = `Example: ${metro.name}`;
  document.getElementById("example").replaceChildren(title, ` ${parts.join(" ")}`);
}

init();
