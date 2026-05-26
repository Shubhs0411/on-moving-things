"""
Rule-based parking logic engine.

Priority chain (highest → lowest):
  1. FIRE_LANE       – absolute block, no exemptions
  2. NO_STOPPING     – absolute block (tow-away), no exemptions
  3. BUS_ZONE        – absolute block
  4. STREET_CLEANING – block (EV exemption is city-specific; we warn but still block)
  5. NO_PARKING      – block; ADA permit overrides *timed* (non-all-day) restrictions
  6. DISABLED_ONLY   – block unless ADA permit
  7. LOADING_ZONE    – block unless actively loading/unloading
  8. PERMIT_ONLY     – block unless matching permit or ADA permit
  9. EV_CHARGING     – block unless EV
 10. TIMED_PARKING   – allow with duration limit; ADA removes the limit
 11. FREE_PARKING    – always allow (default when no rule fires)
"""
from __future__ import annotations

from datetime import datetime, time

from .models import (
    ParkingDecision,
    ParkingResult,
    SlotStatus,
    TriggeredRule,
    VehicleContext,
    VehicleType,
)

ALL_DAYS      = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]
_WEEKDAY_MAP  = {0: "MON", 1: "TUE", 2: "WED", 3: "THU", 4: "FRI", 5: "SAT", 6: "SUN"}

DISPLAY_START = 10   # 5:00 AM  (slot = hour*2 + (1 if min>=30 else 0))
DISPLAY_END   = 47   # 11:30 PM

# These restriction types block regardless of vehicle or permit
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
    if rule.get("all_week"):
        return True
    return day in rule.get("days", [])


def _time_in_range(start: str, end: str, t: time) -> bool:
    s = time.fromisoformat(start)
    e = time.fromisoformat(end)
    if s <= e:
        return s <= t < e
    return t >= s or t < e        # overnight span (e.g. 22:00–06:00)


def _time_applies(rule: dict, t: time) -> bool:
    if rule.get("all_day"):
        return True
    if rule.get("start_time") and rule.get("end_time"):
        return _time_in_range(rule["start_time"], rule["end_time"], t)
    return True


def _vehicle_applies(rule: dict, vtype: VehicleType) -> bool:
    """False only when the rule explicitly targets a *different* vehicle type."""
    vt = rule.get("vehicle_type")
    if not vt:
        return True
    return vtype.value.upper() in vt.upper()


def _fmt_time(t_str: str) -> str:
    h, m = map(int, t_str.split(":"))
    ampm = "AM" if h < 12 else "PM"
    h12  = h % 12 or 12
    return f"{h12}:{m:02d} {ampm}" if m else f"{h12} {ampm}"


def _describe(rule: dict) -> str:
    rt    = rule.get("restriction", "")
    base  = _LABELS.get(rt, rt.replace("_", " ").title())
    parts = [base]

    days = rule.get("days", [])
    if rule.get("all_week"):
        parts.append("every day")
    elif days:
        parts.append("/".join(d.capitalize() for d in days))

    if rule.get("all_day"):
        parts.append("all day")
    elif rule.get("start_time") and rule.get("end_time"):
        parts.append(f"{_fmt_time(rule['start_time'])}–{_fmt_time(rule['end_time'])}")

    dur = rule.get("duration_limit_minutes")
    if dur:
        h, m = divmod(dur, 60)
        parts.append(f"{h}h limit" if m == 0 else f"{h}h {m}m limit" if h else f"{m}m limit")

    ptype = rule.get("permit_type")
    if ptype:
        parts.append(f"Permit {ptype}")

    return " · ".join(parts)


# ── Core slot evaluator ──────────────────────────────────────────────────────

def _evaluate_slot(
    rules: list[dict],
    day:   str,
    t:     time,
    ctx:   VehicleContext,
) -> tuple[SlotStatus, list[TriggeredRule], int | None]:
    """
    Returns (status, triggered_rules, max_duration_minutes).
    """
    applicable = [
        r for r in rules
        if _day_applies(r, day) and _time_applies(r, t) and _vehicle_applies(r, ctx.vehicle_type)
    ]

    triggered:    list[TriggeredRule] = []
    max_duration: int | None          = None

    # ── Priority 1-3: absolute blocks ───────────────────────────────────────
    for rule in applicable:
        rt = rule.get("restriction", "")
        if rt in _ABSOLUTE_BLOCKS:
            triggered.append(TriggeredRule(rt, _describe(rule), blocking=True))
            return SlotStatus.CANNOT_PARK, triggered, None

    # ── Priority 4: street cleaning ─────────────────────────────────────────
    for rule in applicable:
        if rule.get("restriction") != "STREET_CLEANING":
            continue
        triggered.append(TriggeredRule("STREET_CLEANING", _describe(rule), blocking=True))
        return SlotStatus.CANNOT_PARK, triggered, None

    # ── Priority 5: NO_PARKING ───────────────────────────────────────────────
    for rule in applicable:
        if rule.get("restriction") != "NO_PARKING":
            continue
        desc        = _describe(rule)
        is_absolute = bool(rule.get("all_day")) or not rule.get("start_time")

        # ADA overrides *timed* (non-all-day) no-parking at metered/timed spaces.
        # It does NOT override absolute all-day no-parking zones.
        if ctx.has_disabled_permit and not is_absolute:
            triggered.append(TriggeredRule(
                "NO_PARKING", desc, blocking=False,
                exemption_applied="ADA disabled permit exempts you from this time-limited restriction",
            ))
        else:
            triggered.append(TriggeredRule("NO_PARKING", desc, blocking=True))
            return SlotStatus.CANNOT_PARK, triggered, None

    # ── Priority 6: DISABLED_ONLY ────────────────────────────────────────────
    for rule in applicable:
        if rule.get("restriction") != "DISABLED_ONLY":
            continue
        desc = _describe(rule)
        if ctx.has_disabled_permit:
            triggered.append(TriggeredRule(
                "DISABLED_ONLY", desc, blocking=False,
                exemption_applied="You have a valid disabled/ADA permit",
            ))
        else:
            triggered.append(TriggeredRule("DISABLED_ONLY", desc, blocking=True))
            return SlotStatus.PERMIT_REQUIRED, triggered, None

    # ── Priority 7: LOADING_ZONE ─────────────────────────────────────────────
    for rule in applicable:
        if rule.get("restriction") != "LOADING_ZONE":
            continue
        desc = _describe(rule)
        if ctx.is_loading_unloading:
            dur = rule.get("duration_limit_minutes") or 30
            triggered.append(TriggeredRule(
                "LOADING_ZONE", desc, blocking=False,
                exemption_applied=f"Loading/unloading permitted (max {dur} min)",
            ))
            max_duration = min(max_duration, dur) if max_duration else dur
        else:
            triggered.append(TriggeredRule("LOADING_ZONE", desc, blocking=True))
            return SlotStatus.CANNOT_PARK, triggered, None

    # ── Priority 8: PERMIT_ONLY ──────────────────────────────────────────────
    for rule in applicable:
        if rule.get("restriction") != "PERMIT_ONLY":
            continue
        desc        = _describe(rule)
        permit_type = (rule.get("permit_type") or "").strip().upper()
        user_zone   = ctx.permit_zone.strip().upper()

        zone_match = ctx.has_residential_permit and (
            not permit_type
            or permit_type in user_zone
            or user_zone in permit_type
        )
        # In most US states ADA permits override residential permit requirements.
        ada_override = ctx.has_disabled_permit

        if zone_match:
            triggered.append(TriggeredRule(
                "PERMIT_ONLY", desc, blocking=False,
                exemption_applied="Your permit matches this zone",
            ))
        elif ada_override:
            triggered.append(TriggeredRule(
                "PERMIT_ONLY", desc, blocking=False,
                exemption_applied="ADA permit exempts from residential permit requirement",
            ))
        else:
            triggered.append(TriggeredRule("PERMIT_ONLY", desc, blocking=True))
            return SlotStatus.PERMIT_REQUIRED, triggered, None

    # ── Priority 9: EV_CHARGING ──────────────────────────────────────────────
    for rule in applicable:
        if rule.get("restriction") != "EV_CHARGING":
            continue
        desc = _describe(rule)
        if ctx.vehicle_type == VehicleType.EV:
            triggered.append(TriggeredRule(
                "EV_CHARGING", desc, blocking=False,
                exemption_applied="Your EV qualifies for this charging space",
            ))
        else:
            triggered.append(TriggeredRule("EV_CHARGING", desc, blocking=True))
            return SlotStatus.CANNOT_PARK, triggered, None

    # ── Priority 10: TIMED_PARKING ───────────────────────────────────────────
    status = SlotStatus.CAN_PARK
    for rule in applicable:
        if rule.get("restriction") != "TIMED_PARKING":
            continue
        desc = _describe(rule)
        dur  = rule.get("duration_limit_minutes")

        # ADA permits grant unlimited stay at metered / timed spaces.
        if ctx.has_disabled_permit:
            triggered.append(TriggeredRule(
                "TIMED_PARKING", desc, blocking=False,
                exemption_applied="ADA permit: no time limit applies to you",
            ))
        else:
            triggered.append(TriggeredRule("TIMED_PARKING", desc, blocking=False))
            status = SlotStatus.TIMED_PARK
            if dur:
                max_duration = min(max_duration, dur) if max_duration else dur

    return status, triggered, max_duration


# ── Next-change-at ────────────────────────────────────────────────────────────

def _next_change_at(
    rules:          list[dict],
    current_day:    str,
    current_slot:   int,
    current_status: SlotStatus,
    ctx:            VehicleContext,
) -> str | None:
    """Scan up to 48 half-hour slots forward to find when the status next flips."""
    day_idx  = ALL_DAYS.index(current_day)
    can_now  = current_status in (SlotStatus.CAN_PARK, SlotStatus.TIMED_PARK)

    for delta in range(1, 49):
        abs_slot   = current_slot + delta
        day        = ALL_DAYS[(day_idx + abs_slot // 48) % 7]
        slot       = abs_slot % 48
        hour       = slot // 2
        minute     = 30 if slot % 2 else 0
        status, _, _ = _evaluate_slot(rules, day, time(hour, minute), ctx)
        can_next   = status in (SlotStatus.CAN_PARK, SlotStatus.TIMED_PARK)

        if can_now != can_next:
            ampm    = "AM" if hour < 12 else "PM"
            h12     = hour % 12 or 12
            min_str = f":{minute:02d}" if minute else ""
            return f"{h12}{min_str} {ampm}"

    return None


# ── Headline / reason builders ────────────────────────────────────────────────

def _headline(decision: ParkingDecision, status: SlotStatus) -> str:
    if decision == ParkingDecision.PARK:
        return "YES, BUT TIME-LIMITED." if status == SlotStatus.TIMED_PARK else "YES, YOU CAN PARK HERE."
    if status == SlotStatus.PERMIT_REQUIRED:
        return "PERMIT REQUIRED."
    return "NO, YOU CANNOT PARK HERE."


def _build_reason_and_warnings(
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
        rule   = blocking[0] if blocking else None
        reason = f"{rule.description}." if rule else "A restriction prevents parking here."
        if next_change:
            reason += f" Restriction lifts at {next_change}."
    else:
        if not triggered:
            reason = "No restrictions apply at this time."
        else:
            active = [t.exemption_applied or t.description for t in triggered if not t.blocking]
            reason = " · ".join(active) if active else "No active restrictions."

        if max_duration:
            h, m = divmod(max_duration, 60)
            dur  = f"{h}h" if m == 0 else f"{h}h {m}m" if h else f"{m}m"
            warnings.append(
                f"Time limit: {dur}. Move your vehicle before it expires to avoid a ticket."
            )

        if next_change:
            warnings.append(f"A restriction begins at {next_change} — plan to move before then.")

    # EV + street cleaning advisory
    if ctx.vehicle_type == VehicleType.EV:
        for t in triggered:
            if t.restriction == "STREET_CLEANING":
                warnings.append(
                    "Some cities (e.g. San Francisco) exempt EVs from street-cleaning rules "
                    "when actively charging. Check your local ordinance before relying on this."
                )
                break

    # Surface any ADA exemptions that were applied
    ada_notes = {t.exemption_applied for t in exemptions if t.exemption_applied and "ADA" in t.exemption_applied}
    for note in ada_notes:
        warnings.append(f"ADA exemption applied: {note}.")

    return reason, warnings


# ── Public API ────────────────────────────────────────────────────────────────

def generate_weekly_grid(
    rules:        list[dict],
    vehicle_type: str = "regular",
    has_permit:   bool = False,
    ctx:          VehicleContext | None = None,
) -> dict[str, list[dict]]:
    if ctx is None:
        ctx = VehicleContext(
            vehicle_type=VehicleType(vehicle_type),
            has_residential_permit=has_permit,
        )
    grid: dict[str, list[dict]] = {}
    for day in ALL_DAYS:
        grid[day] = []
        for slot in range(DISPLAY_START, DISPLAY_END + 1):
            hour   = slot // 2
            minute = 30 if slot % 2 else 0
            status, _, _ = _evaluate_slot(rules, day, time(hour, minute), ctx)
            grid[day].append({
                "slot":   slot,
                "time":   f"{hour:02d}:{minute:02d}",
                "status": status.value,
            })
    return grid


def get_current_verdict(
    rules:        list[dict],
    vehicle_type: str = "regular",
    has_permit:   bool = False,
    ctx:          VehicleContext | None = None,
) -> dict:
    if ctx is None:
        ctx = VehicleContext(
            vehicle_type=VehicleType(vehicle_type),
            has_residential_permit=has_permit,
        )

    now          = datetime.now()
    current_day  = _WEEKDAY_MAP[now.weekday()]
    current_slot = now.hour * 2 + (1 if now.minute >= 30 else 0)

    status, triggered, max_duration = _evaluate_slot(rules, current_day, now.time(), ctx)

    can_park     = status in (SlotStatus.CAN_PARK, SlotStatus.TIMED_PARK)
    decision     = ParkingDecision.PARK if can_park else ParkingDecision.DO_NOT_PARK
    next_change  = _next_change_at(rules, current_day, current_slot, status, ctx)
    headline     = _headline(decision, status)
    reason, warnings = _build_reason_and_warnings(
        decision, triggered, max_duration, next_change, ctx
    )

    return {
        "decision":             decision.value,
        "status":               status.value,
        "can_park":             can_park,
        "headline":             headline,
        "reason":               reason,
        "warnings":             warnings,
        "triggered_rules": [
            {
                "restriction":       t.restriction,
                "description":       t.description,
                "blocking":          t.blocking,
                "exemption_applied": t.exemption_applied,
            }
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
