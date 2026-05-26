from datetime import datetime, time
from enum import Enum

ALL_DAYS = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]

_WEEKDAY_MAP = {0: "MON", 1: "TUE", 2: "WED", 3: "THU", 4: "FRI", 5: "SAT", 6: "SUN"}

# Display slots: 5 AM to 11:30 PM = slot 10 to slot 47 (0-indexed 30-min slots)
DISPLAY_START = 10   # 5:00 AM
DISPLAY_END = 47     # 11:30 PM


class ParkingStatus(str, Enum):
    CAN_PARK = "CAN_PARK"
    CANNOT_PARK = "CANNOT_PARK"
    TIMED_PARK = "TIMED_PARK"
    PERMIT_REQUIRED = "PERMIT_REQUIRED"


def _time_in_range(start: str, end: str, current: time) -> bool:
    s = time.fromisoformat(start)
    e = time.fromisoformat(end)
    if s <= e:
        return s <= current < e
    # Overnight span (e.g. 10 PM – 6 AM)
    return current >= s or current < e


def _evaluate_slot(
    rules: list[dict],
    day: str,
    slot_time: time,
    vehicle_type: str = "regular",
    has_permit: bool = False,
) -> ParkingStatus:
    applicable: set[str] = set()

    for rule in rules:
        days = list(ALL_DAYS) if rule.get("all_week") else rule.get("days", [])
        if day not in days:
            continue

        if rule.get("all_day"):
            time_ok = True
        elif rule.get("start_time") and rule.get("end_time"):
            time_ok = _time_in_range(rule["start_time"], rule["end_time"], slot_time)
        else:
            time_ok = True

        if not time_ok:
            continue

        vt = rule.get("vehicle_type")
        if vt and vehicle_type.upper() not in vt.upper():
            continue

        applicable.add(rule.get("restriction", ""))

    # Priority: NO_PARKING/NO_STOPPING > PERMIT_ONLY > TIMED_PARKING > default CAN
    if "NO_PARKING" in applicable or "NO_STOPPING" in applicable:
        return ParkingStatus.CANNOT_PARK
    if "PERMIT_ONLY" in applicable:
        return ParkingStatus.CAN_PARK if has_permit else ParkingStatus.PERMIT_REQUIRED
    if "TIMED_PARKING" in applicable:
        return ParkingStatus.TIMED_PARK
    return ParkingStatus.CAN_PARK


def generate_weekly_grid(
    rules: list[dict],
    vehicle_type: str = "regular",
    has_permit: bool = False,
) -> dict[str, list[dict]]:
    grid: dict[str, list[dict]] = {}
    for day in ALL_DAYS:
        grid[day] = []
        for slot in range(DISPLAY_START, DISPLAY_END + 1):
            hour = slot // 2
            minute = 30 if slot % 2 else 0
            slot_time = time(hour, minute)
            status = _evaluate_slot(rules, day, slot_time, vehicle_type, has_permit)
            grid[day].append({
                "slot": slot,
                "time": f"{hour:02d}:{minute:02d}",
                "status": status.value,
            })
    return grid


def get_current_verdict(
    rules: list[dict],
    vehicle_type: str = "regular",
    has_permit: bool = False,
) -> dict:
    now = datetime.now()
    current_day = _WEEKDAY_MAP[now.weekday()]
    current_slot = now.hour * 2 + (1 if now.minute >= 30 else 0)
    status = _evaluate_slot(rules, current_day, now.time(), vehicle_type, has_permit)

    return {
        "can_park": status in (ParkingStatus.CAN_PARK, ParkingStatus.TIMED_PARK),
        "status": status.value,
        "current_day": current_day,
        "current_time": now.strftime("%I:%M %p").lstrip("0"),
        "current_day_full": now.strftime("%A"),
        "current_slot": current_slot,
        "day_index": ALL_DAYS.index(current_day),
        "display_start_slot": DISPLAY_START,
    }
