"""Billing setup steps, in the model's order: site → meter → plan → tariffs.

One source for every place an application tells the user what is missing, so all of
them say the same thing.
"""
from __future__ import annotations

import datetime as dt

from .billing import plan_in_force

STEPS = (
    ("site", "Site", "Add your site"),
    ("meter", "Meter", "Add your meter"),
    ("plan", "Plan", "Add your retailer plan on the meter"),
    ("tariffs", "Tariffs", "Add the plan's tariffs"),
)


def steps(sites: list[dict], meters: list[dict], plans: list[dict], meter_id: str | None,
          today: dt.date) -> list[dict]:
    """Each step with ``done`` and, while missing, what to do. ``plans`` are that meter's plans."""
    meter = next((m for m in meters if m.get("id") == meter_id), None)
    plan = plan_in_force(plans, today) if meter else None
    done = {
        "site": bool(sites),
        "meter": meter is not None,
        "plan": plan is not None,
        "tariffs": bool(plan and plan.get("tariffs")),
    }
    out, blocked = [], False
    for key, label, todo in STEPS:
        step = {"key": key, "label": label, "done": done[key]}
        if not done[key]:
            step["todo"] = todo
            step["blocked"] = blocked          # an earlier step is missing
            blocked = True
        if key == "meter" and meter:
            step["detail"] = meter.get("name")
        if key == "plan" and plan:
            step["detail"] = plan.get("name")
        out.append(step)
    return out


def complete(steps_: list[dict]) -> bool:
    return all(s["done"] for s in steps_)
