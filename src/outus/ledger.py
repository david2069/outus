"""The energy ledger: grid readings in, clock-aligned 5-minute intervals out.

Each device behind a meter (an inverter or battery gateway, say) reports the grid power
through its own connection, so the meter's power is the sum of their latest readings;
a device silent for ``FRESH_S`` is left out until it reports again.

State is a plain dict (JSON-safe) that the caller saves; nothing here does I/O.
"""
from __future__ import annotations

from typing import Any

SCHEMA_VERSION = 1
INTERVAL_S = 300          #: OUTUS ledger granularity
FRESH_S = 300             #: a reading older than this is stale
MAX_GAP_S = 3600          #: a longer gap between samples is not integrated


def new_state(meter_id: str, channel: str = "general") -> dict[str, Any]:
    return {"schema_version": SCHEMA_VERSION, "meter_id": meter_id, "channel": channel,
            "latest": {}, "last_ts": None, "open": None}


def _blank(start: int) -> dict[str, Any]:
    return {"start": start, "duration_s": INTERVAL_S, "quantity_in": 0.0, "quantity_out": 0.0,
            "peak_rate": 0.0, "seconds": 0.0}


def combined(state: dict, ts: float) -> float | None:
    """The meter's power now: the sum of fresh device readings (W), or None."""
    fresh = [w for t, w in state["latest"].values() if ts - t <= FRESH_S]
    return sum(fresh) if fresh else None


def add_reading(state: dict, device_id: str, ts: float, grid_w: float | None) -> list[dict]:
    """Record one device's grid power (W, + = import) at ``ts`` (UTC epoch seconds).

    Integrates the meter's power since the previous reading into the open interval and
    returns the intervals that closed (oldest first) as OUTUS usage intervals with
    ``start`` in epoch seconds.
    """
    if grid_w is not None:
        state["latest"][device_id] = (float(ts), float(grid_w))
    closed: list[dict] = []
    last = state["last_ts"]
    if last is not None and ts <= last:
        return closed
    power = combined(state, ts)
    if last is not None and power is not None and ts - last <= MAX_GAP_S:
        t = float(last)
        while t < ts:
            slot = int(t // INTERVAL_S * INTERVAL_S)
            cur = state["open"]
            if cur is None or cur["start"] != slot:
                if cur is not None:
                    closed.append(_finish(cur))
                cur = state["open"] = _blank(slot)
            seg_end = min(ts, slot + INTERVAL_S)
            sec = seg_end - t
            kwh = abs(power) * sec / 3_600_000.0
            if power >= 0:
                cur["quantity_in"] += kwh
            else:
                cur["quantity_out"] += kwh
            cur["seconds"] += sec
            t = seg_end
    elif state["open"] is not None and ts >= state["open"]["start"] + INTERVAL_S:
        closed.append(_finish(state["open"]))
        state["open"] = None
    state["last_ts"] = float(ts)
    return closed


def _finish(cur: dict) -> dict:
    out = {k: v for k, v in cur.items() if k != "seconds"}
    out["quantity_in"] = round(out["quantity_in"], 6)
    out["quantity_out"] = round(out["quantity_out"], 6)
    # Average import power over the interval, kW: the basis for any demand window.
    out["peak_rate"] = round(out["quantity_in"] * 3600.0 / INTERVAL_S, 4)
    if cur["seconds"] < INTERVAL_S * 0.9:
        out["source"] = "estimated"
    return out
