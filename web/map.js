// Time to Afford: map of hours of work by metro.
// Privacy: the wage lives only in this page's memory. Nothing is stored (no cookies,
// localStorage, or URL parameters) and nothing is sent anywhere.
import {
  parseAmount, toHourly, formatDuration, formatMoney, formatGasPrice, GAS_FILL_GALLONS,
  mapMeasures, mapValues, quantileBreaks, groupOf,
} from "./calc.js";
import { setTier, tierBadge, fillMethod } from "./ui.js";

const SVG_NS = "http://www.w3.org/2000/svg";
const GROUPS = 5;
const DOT_MIN_PX = 3.5; // dot radius on screen, never smaller than this (7 px across)
const DOT_R = 4.5; // radius in map units at full width (about 8-9 px across)
const HIT_RADIUS_PX = 14; // pointer must be this close (screen pixels) to pick a dot
const $ = (id) => document.getElementById(id);

let data = null;
let basemap = null;
let measures = [];
let current = { values: [], breaks: null, measure: null };
let selected = null;

async function init() {
  try {
    const [d, b] = await Promise.all(["data/metros.json", "data/basemap.json"].map(async (u) => {
      const r = await fetch(u);
      if (!r.ok) throw new Error(`${u}: HTTP ${r.status}`);
      return r.json();
    }));
    data = d;
    basemap = b;
  } catch (err) {
    $("map-sub").textContent = `Could not load data (${err.message}).`;
    return;
  }

  measures = mapMeasures(data);
  const sel = $("measure");
  sel.replaceChildren(...measures.map((m) => new Option(m.label, m.key)));
  sel.value = `rent:${data.sources.rent.default_measure}`;
  sel.disabled = false;

  const metroSel = $("metro");
  metroSel.replaceChildren(new Option("Choose a metro…", ""), ...data.metros.map((m) => new Option(m.name, m.cbsa)));
  metroSel.disabled = false;

  drawBasemap();
  for (const [id, other] of [["unit-hour", "unit-year"], ["unit-year", "unit-hour"]]) {
    $(id).addEventListener("change", () => { $(other).checked = !$(id).checked; render(); });
  }
  sel.addEventListener("change", render);
  $("wage").addEventListener("input", render);
  metroSel.addEventListener("change", () => { select(metroSel.value || null); });
  $("toggle-table").addEventListener("click", () => {
    const show = $("table-wrap").hidden;
    $("table-wrap").hidden = !show;
    $("toggle-table").setAttribute("aria-expanded", String(show));
    $("toggle-table").textContent = show ? "Hide the table" : "View as a table";
  });

  const svg = $("map");
  new ResizeObserver(sizeDots).observe(svg);
  svg.addEventListener("pointermove", onHover);
  svg.addEventListener("pointerleave", () => { $("tip").hidden = true; });
  svg.addEventListener("click", (e) => {
    const hit = nearestDot(e);
    if (hit) { $("metro").value = hit.cbsa; select(hit.cbsa); }
  });
  $("built").textContent = `Site data built ${data.built}.`;
  render();
}

// ---------- drawing ----------

/** Keep dots at least DOT_MIN_PX on screen when the map is drawn small (phones). */
function dotRadius() {
  const ctm = $("map").getScreenCTM();
  return ctm && ctm.a > 0 ? Math.max(DOT_R, DOT_MIN_PX / ctm.a) : DOT_R;
}

function sizeDots() {
  const r = dotRadius();
  for (const c of $("dots").children) c.setAttribute("r", r);
  for (const c of $("selected-dot").children) c.setAttribute("r", r + 3);
}

/** Legend boundaries: one decimal for minutes, so close groups don't read "10 min – 10 min". */
function formatBoundary(hours) {
  return hours < 1 ? `${(hours * 60).toFixed(1)} min` : `${hours.toFixed(1)} hours`;
}

function el(tag, attrs = {}) {
  const node = document.createElementNS(SVG_NS, tag);
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
  return node;
}

function drawBasemap() {
  const svg = $("map");
  svg.setAttribute("viewBox", `0 0 ${basemap.width} ${basemap.height}`);
  $("states").replaceChildren(...basemap.states.map((s) => {
    const p = el("path", { d: s.d, class: "state" });
    const title = el("title");
    title.textContent = s.name;
    p.append(title);
    return p;
  }));
  $("insets").replaceChildren(...basemap.insets.flatMap((i) => {
    const [x, y, w, h] = i.box;
    const label = el("text", { x: x + 1, y: y - 3, class: "inset-label" });
    label.textContent = i.label;
    return [el("rect", { x, y, width: w, height: h, class: "inset-frame" }), label];
  }));
}

function readWage() {
  const text = $("wage").value.trim();
  if (!text) return { hourly: null, error: null };
  const amount = parseAmount(text);
  if (amount == null) return { hourly: null, error: "Enter a positive number, like 25 or 52,000." };
  return { hourly: toHourly(amount, $("unit-year").checked ? "year" : "hour"), error: null };
}

function render() {
  const { hourly, error } = readWage();
  $("wage-error").hidden = !error;
  $("wage-error").textContent = error ?? "";
  const measure = measures.find((m) => m.key === $("measure").value);
  const values = mapValues(data.metros, measure.key, { yourHourly: hourly });
  const breaks = quantileBreaks(values.map((v) => v.hours), GROUPS);
  current = { values, breaks, measure, hourly };

  $("measure-label").textContent = measure.label;
  setTier($("measure-tier"), measure.tier);
  $("map-sub").textContent = `Hours of work${measure.per ? ` ${measure.per}` : ""}, ` +
    (hourly != null ? `at your wage of ${formatMoney(hourly, { cents: true })}/hr in every metro.`
      : "at each metro's median wage.");

  // Hollow dots first, then groups light to dark, so darker dots draw on top.
  const order = [...values].sort((a, b) => (groupOf(a.hours, breaks) ?? -1) - (groupOf(b.hours, breaks) ?? -1));
  $("dots").replaceChildren(...order.filter((v) => v.xy).map((v) => {
    const g = groupOf(v.hours, breaks);
    return el("circle", { cx: v.xy[0], cy: v.xy[1], r: dotRadius(), class: g == null ? "dot dot-none" : `dot g${g}` });
  }));
  renderLegend(values, breaks);
  renderTable(values, measure);
  if (selected) select(selected); else $("selected-dot").replaceChildren();
}

function renderLegend(values, breaks) {
  const items = [];
  if (breaks) {
    const counts = Array(GROUPS).fill(0);
    for (const v of values) { const g = groupOf(v.hours, breaks); if (g != null) counts[g]++; }
    for (let g = 0; g < GROUPS; g++) {
      if (!counts[g]) continue;
      const lo = breaks[g];
      const hi = g === GROUPS - 1 ? breaks[GROUPS] : breaks[g + 1];
      items.push(legendItem(`g${g}`, `${formatBoundary(lo)} – ${formatBoundary(hi)}`, counts[g]));
    }
  }
  const none = {};
  for (const v of values) if (v.hours == null) none[noneReason(v)] = (none[noneReason(v)] ?? 0) + 1;
  for (const [reason, n] of Object.entries(none)) items.push(legendItem("dot-none", reason, n));
  $("legend").replaceChildren(...items);
}

function legendItem(cls, text, n) {
  const span = document.createElement("span");
  span.className = "legend-item";
  const svg = el("svg", { width: 12, height: 12, viewBox: "0 0 12 12", "aria-hidden": "true" });
  svg.append(el("circle", { cx: 6, cy: 6, r: 5, class: `dot ${cls}` }));
  const label = document.createElement("span");
  label.textContent = `${text} `;
  const count = document.createElement("span");
  count.className = "hint";
  count.textContent = `(${n})`;
  label.append(count);
  span.append(svg, label);
  return span;
}

// ---------- text for one metro ----------

function noneReason(v) {
  if (v.wage == null && v.cost != null) return "No median wage";
  switch (v.status) {
    case "not_covered": return "Not covered";
    case "top_coded": return "Top-coded";
    default: return "No data";
  }
}

function statusText(v, key) {
  if (v.wage == null && v.cost != null) return "No median wage for this metro. Enter your wage to see hours.";
  if (v.status === "not_covered") {
    if (key === "gas_fill") return "EIA publishes gas prices for only 10 metros, and this isn't one of them.";
    if (key.startsWith("grocery:")) return "No estimate: BEA publishes no price level for this metro.";
    return "The source doesn't cover this metro.";
  }
  if (v.status === "top_coded") {
    return key === "owner_cost" ? "Census reports this median only as “$4,000 or more”, so hours aren't calculated."
      : "Census reports this median only as “$3,500 or more”, so hours aren't calculated.";
  }
  return "The source has no value for this metro.";
}

function costText(v, key) {
  if (v.cost == null) return "";
  const moe = v.moe != null ? ` ±${formatMoney(v.moe)}` : "";
  if (key === "gas_fill") return `${formatMoney(v.cost, { cents: true })} for ${GAS_FILL_GALLONS} gallons (${formatGasPrice(v.cost / GAS_FILL_GALLONS)}/gallon)`;
  if (key.startsWith("grocery:")) return `${formatMoney(v.cost, { cents: true })} (estimated)`;
  return `${formatMoney(v.cost)}${moe}${key === "gas_fill" ? "" : " per month"}`;
}

function sourceText(key) {
  const s = data.sources;
  if (key.startsWith("rent:")) return `Census ACS, ${s.rent.reference_period}`;
  if (key === "gas_fill") return `EIA, ${s.gas.reference_period}`;
  if (key === "owner_cost") return `Census ACS, ${s.owner.reference_period}`;
  return `BLS Average Price Data, ${s.groceries.reference_period}; BEA Regional Price Parities, ${s.grocery_estimates.rpp_year}`;
}

// ---------- selection, hover, table ----------

function select(cbsa) {
  selected = cbsa;
  const v = cbsa && current.values.find((x) => x.cbsa === cbsa);
  $("detail").hidden = !v;
  $("selected-dot").replaceChildren();
  if (!v) return;
  const key = current.measure.key;
  if (v.xy) $("selected-dot").append(el("circle", { cx: v.xy[0], cy: v.xy[1], r: dotRadius() + 3, class: "dot-selected" }));

  $("d-name").replaceChildren(v.name, " ", tierBadge(v.tier ?? current.measure.tier));
  const has = v.hours != null;
  $("detail").classList.toggle("is-missing", !has);
  $("d-hours").textContent = has ? formatDuration(v.hours) : "No value";
  $("d-per").textContent = has ? `of work${current.measure.per ? ` ${current.measure.per}` : ""} · ${current.measure.label}` : current.measure.label;
  $("d-inputs").textContent = has ? costText(v, key) : statusText(v, key);
  $("d-wage").textContent = v.wage == null ? ""
    : `Wage used: ${formatMoney(v.wage, { cents: true })}/hr (${v.wageSource === "yours" ? "yours" : "metro median"})`;
  const g = groupOf(v.hours, current.breaks);
  const n = current.values.filter((x) => x.hours != null).length;
  const rank = has ? current.values.filter((x) => x.hours != null && x.hours < v.hours).length + 1 : null;
  $("d-group").textContent = g == null ? "" : `Group ${g + 1} of ${GROUPS} (1 = fewest hours). Rank ${rank} of ${n} metros with a value.`;
  fillMethod($("d-method"), data.methods, [v.method]);
  $("d-source").textContent = sourceText(key);
}

function nearestDot(event) {
  const svg = $("map");
  const ctm = svg.getScreenCTM();
  if (!ctm) return null;
  const pt = new DOMPoint(event.clientX, event.clientY).matrixTransform(ctm.inverse());
  const limit = HIT_RADIUS_PX / ctm.a; // screen pixels -> viewBox units
  let best = null;
  let bestD = limit;
  for (const v of current.values) {
    if (!v.xy) continue;
    const d = Math.hypot(v.xy[0] - pt.x, v.xy[1] - pt.y);
    if (d < bestD) { best = v; bestD = d; }
  }
  return best;
}

function onHover(event) {
  const tip = $("tip");
  const v = nearestDot(event);
  $("map").style.cursor = v ? "pointer" : "default";
  if (!v) { tip.hidden = true; return; }
  tip.replaceChildren();
  const name = document.createElement("strong");
  name.textContent = v.name;
  const line = document.createElement("span");
  line.textContent = v.hours != null ? `${formatDuration(v.hours)} · ${costText(v, current.measure.key)}` : noneReason(v);
  tip.append(name, line);
  const wrap = $("map-wrap").getBoundingClientRect();
  const x = event.clientX - wrap.left;
  const y = event.clientY - wrap.top;
  tip.hidden = false;
  const flip = x > wrap.width - tip.offsetWidth - 16;
  tip.style.left = `${flip ? x - tip.offsetWidth - 12 : x + 12}px`;
  tip.style.top = `${Math.max(0, y - tip.offsetHeight - 8)}px`;
}

function renderTable(values, measure) {
  const sorted = [...values].sort((a, b) =>
    (a.hours == null) - (b.hours == null) || (a.hours ?? 0) - (b.hours ?? 0) || a.name.localeCompare(b.name));
  $("table-caption").textContent = `${measure.label}: hours of work by metro, fewest first`;
  let rank = 0;
  $("table-rows").replaceChildren(...sorted.map((v) => {
    const tr = document.createElement("tr");
    const cells = [
      v.hours != null ? String(++rank) : "",
      v.name,
      v.hours != null ? formatDuration(v.hours) : noneReason(v),
      costText(v, measure.key),
    ].map((t, i) => {
      const c = document.createElement(i === 1 ? "th" : "td");
      if (i === 1) c.scope = "row";
      c.textContent = t;
      return c;
    });
    tr.append(...cells);
    return tr;
  }));
}

init();
