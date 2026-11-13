// Shared DOM helpers for tier badges and method details. Built with DOM nodes, never HTML strings.

export const TIER_LABELS = {
  observed: ["Observed", "Published directly for this place and period"],
  estimated: ["Estimated", "A national figure adjusted by a published local price index"],
  scenario: ["Scenario", "Calculated from stated assumptions you can see (and some you can change)"],
};

export function setTier(el, tier) {
  const [label, title] = TIER_LABELS[tier] ?? ["", ""];
  el.className = tier ? `tier tier-${tier}` : "tier";
  el.textContent = label;
  el.title = title;
  el.hidden = !tier;
}

export function tierBadge(tier) {
  const el = document.createElement("span");
  setTier(el, tier);
  return el;
}

function describeInput(input) {
  const li = document.createElement("li");
  const parts = Object.entries(input).filter(([k]) => k !== "url" && k !== "source")
    .map(([k, v]) => `${k.replace(/_/g, " ")} ${v}`);
  li.append(`${input.source ?? "source"}${parts.length ? `: ${parts.join(", ")}` : ""}`);
  if (input.url) {
    const a = document.createElement("a");
    a.href = input.url;
    a.textContent = "link";
    a.rel = "noopener";
    li.append(" (", a, ")");
  }
  return li;
}

/** Fill a <details class="method"> (with a <div> body) from the bundle's methods table. Hidden if no keys resolve. */
export function fillMethod(details, methods, keys) {
  const body = details.querySelector("div");
  const found = [...new Set(keys.filter(Boolean))].map((k) => methods[k]).filter(Boolean);
  details.hidden = found.length === 0;
  body.replaceChildren(...found.map((m) => {
    const block = document.createElement("div");
    block.className = "method-entry";
    const desc = document.createElement("p");
    desc.textContent = m.description;
    const asOf = document.createElement("p");
    asOf.className = "hint";
    asOf.textContent = `As of ${m.as_of}`;
    const inputs = document.createElement("ul");
    inputs.append(...m.inputs.map(describeInput));
    block.append(desc, inputs, asOf);
    return block;
  }));
}

/** A new, empty <details class="method"> with the given summary text. */
export function methodDetails(summary = "How is this calculated?") {
  const d = document.createElement("details");
  d.className = "method";
  const s = document.createElement("summary");
  s.textContent = summary;
  d.append(s, document.createElement("div"));
  return d;
}
