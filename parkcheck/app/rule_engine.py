"""
Rule-based parking logic engine.

Priority chain (highest → lowest):
  1. FIRE_LANE       — absolute block, zero exemptions
  2. NO_STOPPING     — tow-away zone, zero exemptions
  3. BUS_ZONE        — transit zone, zero exemptions
  4. STREET_CLEANING — block (EV city exemptions surfaced as advisory warning)
  5. NO_PARKING      — block; ADA overrides *timed* (non-all-day) restrictions only
  6. DISABLED_ONLY   — block unless ADA/disabled permit
  7. LOADING_ZONE    — block unless actively loading/unloading
  8. PERMIT_ONLY     — block unless matching zone permit or ADA permit
  9. EV_CHARGING     — block unless vehicle is an EV
 10. TIMED_PARKING   — allow with duration cap; ADA removes the cap
 11. (default)       — CAN_PARK
"""
from __future__ import annotations

from datetime import datetime, time

from .models import (
    ParkingDecision,
    SlotStatus,
    TriggeredRule,
    VehicleContext,
    VehicleType,
)

ALL_DAYS     = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]
_WEEKDAY_MAP = {0: "MON", 1: "TUE", 2: "WED", 3: "THU", 4: "FRI", 5: "SAT", 6: "SUN"}

DISPLAY_START = 10   # 5:00 AM
DISPLAY_END   = 47   # 11:30 PM

_ABSOLUTE_BLOCKS = {"FIRE_LANE", "NO_STOPPING", "BUS_ZONE"}

_LABELS: dict[str, str] = {
    "FIRE_LANE":       "Fire lane — no stopping",
    "NO_STOPPING":     "Tow-away / no stopping zone",
    "BUS_ZONE":        "Bus stop / transit zone",
    "STREET_CLEANING": "Street cleaning in effect",
    "NO_PARKING":      "No parking",
    "DISABLED_ONLY":   "Disabled / handicap permit required",
    "LOADING_ZONE":    "Commercial loading zone",
    "PERMIT_ONLY":     "Residential / area permit required",
    "EV_CHARGING":     "Electric-vehicle charging only",
    "TIMED_PARKING":   "Time-limited parking",
    "FREE_PARKING":    "Free parking",
}


# ── Predicate helpers ────────────────────────────────────────────────────────

def _day_applies(rule: dict, day: str) -> bool:
    return True if rule.get("all_week") else day in rule.get("days", [])


def _time_in_range(start: str, end: str, t: time) -> bool:
    s, e = time.fromisoformat(start), time.fromisoformat(end)
    return (s <= t < e) if s <= e else (t >= s or t < e)


def _time_applies(rule: dict, t: time) -> bool:
    if rule.get("all_day"):
        return True
    if rule.get("start_time") and rule.get("end_time"):
        return _time_in_range(rule["start_time"], rule["end_time"], t)
    return True


def _vehicle_applies(rule: dict, vtype: VehicleType) -> bool:
    vt = rule.get("vehicle_type")
    return True if not vt else vtype.value.upper() in vt.upper()


def _fmt(t_str: str) -> str:
    h, m = map(int, t_str.split(":"))
    return f"{h % 12 or 12}:{m:02d} {'AM' if h < 12 else 'PM'}" if m else f"{h % 12 or 12} {'AM' if h < 12 else 'PM'}"


def _describe(rule: dict) -> str:
    rt, base = rule.get("restriction", ""), _LABELS.get(rule.get("restriction", ""), "")
    parts = [base or rt.replace("_", " ").title()]

    days = rule.get("days", [])
    if rule.get("all_week"):       parts.append("every day")
    elif days:                     parts.append("/".join(d.capitalize() for d in days))

    if rule.get("all_day"):        parts.append("all day")
    elif rule.get("start_time") and rule.get("end_time"):
        parts.append(f"{_fmt(rule['start_time'])}–{_fmt(rule['end_time'])}")

    dur = rule.get("duration_limit_minutes")
    if dur:
        h, m = divmod(dur, 60)
        parts.append(f"{h}h limit" if not m else (f"{h}h {m}m limit" if h else f"{m}m limit"))

    if rule.get("permit_type"):    parts.append(f"Permit {rule['permit_type']}")
    return " · ".join(parts)


# ── Core slot evaluator ──────────────────────────────────────────────────────

def _evaluate_slot(
    rules: list[dict],
    day:   str,
    t:     time,
    ctx:   VehicleContext,
) -> tuple[SlotStatus, list[TriggeredRule], int | None]:
    applicable = [
        r for r in rules
        if _day_applies(r, day) and _time_applies(r, t) and _vehicle_applies(r, ctx.vehicle_type)
    ]
    triggered:    list[TriggeredRule] = []
    max_duration: int | None          = None

    # 1–3: absolute blocks
    for r in applicable:
        rt = r.get("restriction", "")
        if rt in _ABSOLUTE_BLOCKS:
            triggered.append(TriggeredRule(rt, _describe(r), blocking=True))
            return SlotStatus.CANNOT_PARK, triggered, None

    # 4: street cleaning
    for r in applicable:
        if r.get("restriction") != "STREET_CLEANING":
            continue
        triggered.append(TriggeredRule("STREET_CLEANING", _describe(r), blocking=True))
        return SlotStatus.CANNOT_PARK, triggered, None

    # 5: no parking
    for r in applicable:
        if r.get("restriction") != "NO_PARKING":
            continue
        desc        = _describe(r)
        is_absolute = bool(r.get("all_day")) or not r.get("start_time")
        if ctx.has_disabled_permit and not is_absolute:
            triggered.append(TriggeredRule("NO_PARKING", desc, False,
                "ADA disabled permit exempts you from this time-limited restriction"))
        else:
            triggered.append(TriggeredRule("NO_PARKING", desc, blocking=True))
            return SlotStatus.CANNOT_PARK, triggered, None

    # 6: disabled only
    for r in applicable:
        if r.get("restriction") != "DISABLED_ONLY":
            continue
        if ctx.has_disabled_permit:
            triggered.append(TriggeredRule("DISABLED_ONLY", _describe(r), False,
                "You have a valid disabled/ADA permit"))
        else:
            triggered.append(TriggeredRule("DISABLED_ONLY", _describe(r), blocking=True))
            return SlotStatus.PERMIT_REQUIRED, triggered, None

    # 7: loading zone
    for r in applicable:
        if r.get("restriction") != "LOADING_ZONE":
            continue
        if ctx.is_loading_unloading:
            dur = r.get("duration_limit_minutes") or 30
            triggered.append(TriggeredRule("LOADING_ZONE", _describe(r), False,
                f"Loading/unloading permitted (max {dur} min)"))
            max_duration = min(max_duration, dur) if max_duration else dur
        else:
            triggered.append(TriggeredRule("LOADING_ZONE", _describe(r), blocking=True))
            return SlotStatus.CANNOT_PARK, triggered, None

    # 8: permit only
    for r in applicable:
        if r.get("restriction") != "PERMIT_ONLY":
            continue
        ptype      = (r.get("permit_type") or "").strip().upper()
        user_zone  = ctx.permit_zone.strip().upper()
        zone_match = ctx.has_residential_permit and (not ptype or ptype in user_zone or user_zone in ptype)

        if zone_match:
            triggered.append(TriggeredRule("PERMIT_ONLY", _describe(r), False, "Your permit matches this zone"))
        elif ctx.has_disabled_permit:
            triggered.append(TriggeredRule("PERMIT_ONLY", _describe(r), False,
                "ADA permit exempts from residential permit requirement"))
        else:
            triggered.append(TriggeredRule("PERMIT_ONLY", _describe(r), blocking=True))
            return SlotStatus.PERMIT_REQUIRED, triggered, None

    # 9: EV charging
    for r in applicable:
        if r.get("restriction") != "EV_CHARGING":
            continue
        if ctx.vehicle_type == VehicleType.EV:
            triggered.append(TriggeredRule("EV_CHARGING", _describe(r), False,
                "Your EV qualifies for this charging space"))
        else:
            triggered.append(TriggeredRule("EV_CHARGING", _describe(r), blocking=True))
            return SlotStatus.CANNOT_PARK, triggered, None

    # 10: timed parking
    status = SlotStatus.CAN_PARK
    for r in applicable:
        if r.get("restriction") != "TIMED_PARKING":
            continue
        dur = r.get("duration_limit_minutes")
        if ctx.has_disabled_permit:
            triggered.append(TriggeredRule("TIMED_PARKING", _describe(r), False,
                "ADA permit: no time limit applies to you"))
        else:
            triggered.append(TriggeredRule("TIMED_PARKING", _describe(r), blocking=False))
            status = SlotStatus.TIMED_PARK
            if dur:
                max_duration = min(max_duration, dur) if max_duration else dur

    return status, triggered, max_duration


# ── Helpers ──────────────────────────────────────────────────────────────────

def _next_change_at(
    rules:          list[dict],
    current_day:    str,
    current_slot:   int,
    current_status: SlotStatus,
    ctx:            VehicleContext,
) -> str | None:
    day_idx = ALL_DAYS.index(current_day)
    can_now = current_status in (SlotStatus.CAN_PARK, SlotStatus.TIMED_PARK)

    for delta in range(1, 49):
        abs_slot = current_slot + delta
        day      = ALL_DAYS[(day_idx + abs_slot // 48) % 7]
        slot     = abs_slot % 48
        h, m     = slot // 2, 30 if slot % 2 else 0
        status, _, _ = _evaluate_slot(rules, day, time(h, m), ctx)
        can_next = status in (SlotStatus.CAN_PARK, SlotStatus.TIMED_PARK)

        if can_now != can_next:
            ampm    = "AM" if h < 12 else "PM"
            min_str = f":{m:02d}" if m else ""
            return f"{h % 12 or 12}{min_str} {ampm}"

    return None


def _headline(decision: ParkingDecision, status: SlotStatus) -> str:
    if decision == ParkingDecision.PARK:
        return "YES, BUT TIME-LIMITED." if status == SlotStatus.TIMED_PARK else "YES, YOU CAN PARK HERE."
    return "PERMIT REQUIRED." if status == SlotStatus.PERMIT_REQUIRED else "NO, YOU CANNOT PARK HERE."


def _reason_and_warnings(
    decision:     ParkingDecision,
    triggered:    list[TriggeredRule],
    max_duration: int | None,
    next_change:  str | None,
    ctx:          VehicleContext,
) -> tuple[str, list[str]]:
    blocking   = [t for t in triggered if t.blocking]
    exemptions = [t for t in triggered if not t.blocking and t.exemption_applied]
    warnings:  list[str] = []

    if decision == ParkingDecision.DO_NOT_PARK:
        reason = f"{blocking[0].description}." if blocking else "A restriction prevents parking here."
        if next_change:
            reason += f" Restriction lifts at {next_change}."
    else:
        active = [t.exemption_applied or t.description for t in triggered if not t.blocking]
        reason = " · ".join(active) if active else "No restrictions apply at this time."
        if max_duration:
            h, m = divmod(max_duration, 60)
            dur = f"{h}h" if not m else (f"{h}h {m}m" if h else f"{m}m")
            warnings.append(f"Time limit: {dur}. Move before it expires to avoid a ticket.")
        if next_change:
            warnings.append(f"A restriction begins at {next_change} — plan to move before then.")

    if ctx.vehicle_type == VehicleType.EV:
        for t in triggered:
            if t.restriction == "STREET_CLEANING":
                warnings.append(
                    "Some cities (e.g. San Francisco) exempt EVs from street-cleaning "
                    "when actively charging. Check your local ordinance."
                )
                break

    for t in exemptions:
        if t.exemption_applied and "ADA" in t.exemption_applied:
            warnings.append(f"ADA exemption applied: {t.exemption_applied}.")
            break

    return reason, warnings


# ── Public API ────────────────────────────────────────────────────────────────

def generate_weekly_grid(
    rules: list[dict],
    ctx:   VehicleContext | None = None,
) -> dict[str, list[dict]]:
    if ctx is None:
        ctx = VehicleContext()
    grid: dict[str, list[dict]] = {}
    for day in ALL_DAYS:
        grid[day] = []
        for slot in range(DISPLAY_START, DISPLAY_END + 1):
            h, m = slot // 2, 30 if slot % 2 else 0
            status, _, _ = _evaluate_slot(rules, day, time(h, m), ctx)
            grid[day].append({"slot": slot, "time": f"{h:02d}:{m:02d}", "status": status.value})
    return grid


def get_current_verdict(rules: list[dict], ctx: VehicleContext | None = None) -> dict:
    if ctx is None:
        ctx = VehicleContext()

    now          = datetime.now()
    current_day  = _WEEKDAY_MAP[now.weekday()]
    current_slot = now.hour * 2 + (1 if now.minute >= 30 else 0)

    status, triggered, max_duration = _evaluate_slot(rules, current_day, now.time(), ctx)
    can_park    = status in (SlotStatus.CAN_PARK, SlotStatus.TIMED_PARK)
    decision    = ParkingDecision.PARK if can_park else ParkingDecision.DO_NOT_PARK
    next_change = _next_change_at(rules, current_day, current_slot, status, ctx)
    reason, warnings = _reason_and_warnings(decision, triggered, max_duration, next_change, ctx)

    return {
        "decision":             decision.value,
        "status":               status.value,
        "can_park":             can_park,
        "headline":             _headline(decision, status),
        "reason":               reason,
        "warnings":             warnings,
        "triggered_rules": [
            {"restriction": t.restriction, "description": t.description,
             "blocking": t.blocking, "exemption_applied": t.exemption_applied}
            for t in triggered
        ],
        "max_duration_minutes": max_duration,
        "next_change_at":       next_change,
        "current_day":          current_day,
        "current_time":         now.strftime("%I:%M %p").lstrip("0"),
        "current_day_full":     now.strftime("%A"),
        "current_slot":         current_slot,
        "day_index":            ALL_DAYS.index(current_day),
        "display_start_slot":   DISPLAY_START,
    }
