"""
Deterministic unit tests for the rule engine.
No network calls. Rules are injected directly.

Run: python -m pytest tests/ -v
"""
import pytest
from datetime import time

from app.models import VehicleContext, VehicleType, SlotStatus
from app.rule_engine import _evaluate_slot, generate_weekly_grid, ALL_DAYS


# ── Rule builders ────────────────────────────────────────────────────────────

def no_park(days, start=None, end=None, all_day=False, all_week=False):
    return {"restriction":"NO_PARKING","days":days,"all_week":all_week,
            "start_time":start,"end_time":end,"all_day":all_day,
            "duration_limit_minutes":None,"permit_type":None,"conditions":None,"vehicle_type":None}

def timed(days, start, end, minutes, all_week=False):
    return {"restriction":"TIMED_PARKING","days":days,"all_week":all_week,
            "start_time":start,"end_time":end,"all_day":False,
            "duration_limit_minutes":minutes,"permit_type":None,"conditions":None,"vehicle_type":None}

def permit_only(days, zone=None, all_week=False):
    return {"restriction":"PERMIT_ONLY","days":days,"all_week":all_week,
            "start_time":None,"end_time":None,"all_day":True,
            "duration_limit_minutes":None,"permit_type":zone,"conditions":None,"vehicle_type":None}

def street_clean(days, start, end):
    return {"restriction":"STREET_CLEANING","days":days,"all_week":False,
            "start_time":start,"end_time":end,"all_day":False,
            "duration_limit_minutes":None,"permit_type":None,"conditions":None,"vehicle_type":None}

def disabled_only():
    return {"restriction":"DISABLED_ONLY","days":[],"all_week":True,
            "start_time":None,"end_time":None,"all_day":True,
            "duration_limit_minutes":None,"permit_type":None,"conditions":None,"vehicle_type":None}

def ev_only():
    return {"restriction":"EV_CHARGING","days":[],"all_week":True,
            "start_time":None,"end_time":None,"all_day":True,
            "duration_limit_minutes":None,"permit_type":None,"conditions":None,"vehicle_type":None}

def no_stop():
    return {"restriction":"NO_STOPPING","days":[],"all_week":True,
            "start_time":None,"end_time":None,"all_day":True,
            "duration_limit_minutes":None,"permit_type":None,"conditions":None,"vehicle_type":None}

def loading(days, start, end, minutes=30):
    return {"restriction":"LOADING_ZONE","days":days,"all_week":False,
            "start_time":start,"end_time":end,"all_day":False,
            "duration_limit_minutes":minutes,"permit_type":None,"conditions":None,"vehicle_type":None}


# ── Contexts ─────────────────────────────────────────────────────────────────

CTX          = VehicleContext()
CTX_ADA      = VehicleContext(has_disabled_permit=True)
CTX_PERMIT_A = VehicleContext(has_residential_permit=True, permit_zone="A")
CTX_EV       = VehicleContext(vehicle_type=VehicleType.EV)
CTX_LOADING  = VehicleContext(is_loading_unloading=True)


# ── 1. No parking ────────────────────────────────────────────────────────────

def test_no_parking_blocks_during_hours():
    rules = [no_park(["MON","TUE","WED","THU","FRI"], "08:00", "18:00")]
    s, _, _ = _evaluate_slot(rules, "MON", time(9, 0), CTX)
    assert s == SlotStatus.CANNOT_PARK

def test_no_parking_free_outside_hours():
    rules = [no_park(["MON","TUE","WED","THU","FRI"], "08:00", "18:00")]
    s, _, _ = _evaluate_slot(rules, "MON", time(7, 30), CTX)
    assert s == SlotStatus.CAN_PARK

def test_no_parking_free_on_excluded_day():
    rules = [no_park(["MON","TUE","WED","THU","FRI"], "08:00", "18:00")]
    s, _, _ = _evaluate_slot(rules, "SAT", time(9, 0), CTX)
    assert s == SlotStatus.CAN_PARK


# ── 2. ADA / disabled permit ─────────────────────────────────────────────────

def test_ada_overrides_timed_no_parking():
    rules = [no_park(["MON","TUE","WED","THU","FRI"], "08:00", "18:00")]
    s, triggered, _ = _evaluate_slot(rules, "MON", time(9, 0), CTX_ADA)
    assert s == SlotStatus.CAN_PARK
    assert any(t.exemption_applied for t in triggered)

def test_ada_cannot_override_all_day_zone():
    rules = [no_park([], all_day=True, all_week=True)]
    s, _, _ = _evaluate_slot(rules, "MON", time(9, 0), CTX_ADA)
    assert s == SlotStatus.CANNOT_PARK

def test_ada_removes_timed_parking_cap():
    rules = [timed(["MON","TUE","WED","THU","FRI"], "09:00", "18:00", 120)]
    s, triggered, max_dur = _evaluate_slot(rules, "MON", time(10, 0), CTX_ADA)
    assert s       == SlotStatus.CAN_PARK
    assert max_dur is None
    assert any("ADA" in (t.exemption_applied or "") for t in triggered)

def test_ada_overrides_permit_only():
    rules = [permit_only(["MON"], zone="A")]
    s, triggered, _ = _evaluate_slot(rules, "MON", time(10, 0), CTX_ADA)
    assert s == SlotStatus.CAN_PARK
    assert any("ADA" in (t.exemption_applied or "") for t in triggered)


# ── 3. Timed parking ─────────────────────────────────────────────────────────

def test_timed_parking_inside_hours():
    rules = [timed(["MON","TUE","WED","THU","FRI"], "09:00", "18:00", 120)]
    s, _, max_dur = _evaluate_slot(rules, "MON", time(10, 0), CTX)
    assert s       == SlotStatus.TIMED_PARK
    assert max_dur == 120

def test_timed_parking_free_outside_hours():
    rules = [timed(["MON","TUE","WED","THU","FRI"], "09:00", "18:00", 120)]
    s, _, _ = _evaluate_slot(rules, "MON", time(19, 0), CTX)
    assert s == SlotStatus.CAN_PARK


# ── 4. Permit only ───────────────────────────────────────────────────────────

def test_permit_blocks_without_permit():
    rules = [permit_only(["MON"], zone="A")]
    s, _, _ = _evaluate_slot(rules, "MON", time(10, 0), CTX)
    assert s == SlotStatus.PERMIT_REQUIRED

def test_permit_grants_access_matching_zone():
    rules = [permit_only(["MON"], zone="A")]
    s, _, _ = _evaluate_slot(rules, "MON", time(10, 0), CTX_PERMIT_A)
    assert s == SlotStatus.CAN_PARK


# ── 5. Street cleaning ───────────────────────────────────────────────────────

def test_street_cleaning_blocks_all():
    rules = [street_clean(["MON"], "08:00", "10:00")]
    for ctx in [CTX, CTX_ADA, CTX_EV]:
        s, _, _ = _evaluate_slot(rules, "MON", time(9, 0), ctx)
        assert s == SlotStatus.CANNOT_PARK, f"Should block for {ctx}"

def test_street_cleaning_free_outside_window():
    rules = [street_clean(["MON"], "08:00", "10:00")]
    s, _, _ = _evaluate_slot(rules, "MON", time(11, 0), CTX)
    assert s == SlotStatus.CAN_PARK


# ── 6. Absolute blocks ───────────────────────────────────────────────────────

def test_no_stopping_blocks_all_vehicles():
    rules = [no_stop()]
    for ctx in [CTX, CTX_ADA, CTX_PERMIT_A, CTX_EV]:
        s, _, _ = _evaluate_slot(rules, "MON", time(12, 0), ctx)
        assert s == SlotStatus.CANNOT_PARK


# ── 7. EV charging ───────────────────────────────────────────────────────────

def test_ev_spot_blocks_non_ev():
    s, _, _ = _evaluate_slot([ev_only()], "MON", time(12, 0), CTX)
    assert s == SlotStatus.CANNOT_PARK

def test_ev_spot_allows_ev():
    s, _, _ = _evaluate_slot([ev_only()], "MON", time(12, 0), CTX_EV)
    assert s == SlotStatus.CAN_PARK


# ── 8. Loading zone ──────────────────────────────────────────────────────────

def test_loading_zone_blocks_regular():
    rules = [loading(["MON","TUE","WED","THU","FRI"], "07:00", "18:00")]
    s, _, _ = _evaluate_slot(rules, "MON", time(9, 0), CTX)
    assert s == SlotStatus.CANNOT_PARK

def test_loading_zone_allows_loading_vehicle():
    rules = [loading(["MON","TUE","WED","THU","FRI"], "07:00", "18:00", 30)]
    s, _, max_dur = _evaluate_slot(rules, "MON", time(9, 0), CTX_LOADING)
    assert s       == SlotStatus.CAN_PARK
    assert max_dur == 30


# ── 9. Grid sanity ───────────────────────────────────────────────────────────

def test_weekly_grid_structure():
    rules = [no_park(["MON","TUE","WED","THU","FRI"], "08:00", "18:00")]
    grid  = generate_weekly_grid(rules)
    assert set(grid.keys()) == set(ALL_DAYS)
    valid = {s.value for s in SlotStatus}
    for day in ALL_DAYS:
        assert len(grid[day]) > 0
        for slot in grid[day]:
            assert "slot" in slot and "time" in slot and "status" in slot
            assert slot["status"] in valid
