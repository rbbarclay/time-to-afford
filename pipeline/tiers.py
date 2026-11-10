"""Value tiers and method provenance shared by every pipeline module.

Policy (PROJECT.md, amended 2026-11-09): no unlabeled estimates. Every value
carries a tier and a method key; the method key points into the file's
top-level `methods` table, which holds the full description, every input
source, and the as-of date. Keeping the long text in one table (instead of on
each of ~2,000 values) keeps the data files compact.

    value:   {"value": 29.53, "status": "ok", "tier": "observed", "method": "oews_hourly_median"}
    methods: {"oews_hourly_median": {"description": "...", "inputs": [{...}], "as_of": "2025-05"}}

Scenario methods additionally carry an "assumptions" object.
"""

from __future__ import annotations

TIERS = ("observed", "estimated", "scenario")


def tag(value: dict, tier: str, method: str) -> dict:
    """Return `value` with tier and method added."""
    if tier not in TIERS:
        raise ValueError(f"unknown tier {tier!r}")
    return {**value, "tier": tier, "method": method}


def method_entry(description: str, inputs: list[dict], as_of: str, assumptions: dict | None = None) -> dict:
    entry = {"description": description, "inputs": inputs, "as_of": as_of}
    if assumptions is not None:
        entry["assumptions"] = assumptions
    return entry


def check_methods(label: str, methods: dict) -> list[str]:
    """Every method entry needs a description, at least one input, and an as-of date."""
    errors = []
    if not isinstance(methods, dict) or not methods:
        return [f"{label}: missing methods table"]
    for key, m in methods.items():
        if not isinstance(m, dict):
            errors.append(f"{label} method {key}: not an object")
            continue
        if not str(m.get("description", "")).strip():
            errors.append(f"{label} method {key}: missing description")
        if not isinstance(m.get("inputs"), list) or not m["inputs"]:
            errors.append(f"{label} method {key}: missing inputs")
        if not str(m.get("as_of", "")).strip():
            errors.append(f"{label} method {key}: missing as_of")
    return errors


def check_value(where: str, v: dict, methods: dict, allow_untagged_status: tuple[str, ...] = ()) -> list[str]:
    """A value must have a valid tier and a method key defined in `methods`.

    `allow_untagged_status` lists statuses that may omit tier/method, e.g.
    "not_covered" in the site bundle, where no source reported anything.
    """
    if v.get("status") in allow_untagged_status and "tier" not in v and "method" not in v:
        return []
    errors = []
    if v.get("tier") not in TIERS:
        errors.append(f"{where}: missing or invalid tier {v.get('tier')!r}")
    if not v.get("method"):
        errors.append(f"{where}: missing method")
    elif v["method"] not in methods:
        errors.append(f"{where}: method {v['method']!r} not defined in methods table")
    return errors
