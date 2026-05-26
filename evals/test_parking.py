"""
Deterministic unit tests for the parking rule engine.
No network calls — all rules are injected directly.

Run with:  python -m pytest evals/test_parking.py -v
"""
import pytest
from datetime import time

from parking.models import VehicleContext, VehicleType, SlotStatus
from parking.rule_engine import _evaluate_slot, generate_weekly_grid, ALL_DAYS

# ── Fixture helpers ──────────────────────────────────────────────────────────

def _no_park(days, start=None, end=None, all_day=False, all_week=False):
    return {
        "restriction": "NO_PARKING",
        "days": days, "all_week": all_week,
        "start_time": start, "end_time": end, "all_day": all_day,
        "duration_limit_minutes": None, "permit_type": None,
        "conditions": None, "vehicle_type": None,
    }

def _timed(days, start, end, minutes, all_week=False):
    return {
        "restriction": "TIMED_PARKING",
        "days": days, "all_week": all_week,
        "start_time": start, "end_time": end, "all_day": False,
        "duration_limit_minutes": minutes, "permit_type": None,
        "conditions": None, "vehicle_type": None,
    }

def _permit(days, zone=None, all_week=False):
    return {
        "restriction": "PERMIT_ONLY",
        "days": days, "all_week": all_week,
        "start_time": None, "end_time": None, "all_day": True,
        "duration_limit_minutes": None, "permit_type": zone,
        "conditions": None, "vehicle_type": None,
    }

def _street_clean(days, start, end):
    return {
        "restriction": "STREET_CLEANING",
        "days": days, "all_week": False,
        "start_time": start, "end_time": end, "all_day": False,
        "duration_limit_minutes": None, "permit_type": None,
        "conditions": None, "vehicle_type": None,
    }

def _disabled_only():
    return {
        "restriction": "DISABLED_ONLY",
        "days": [], "all_week": True,
        "start_time": None, "end_time": None, "all_day": True,
        "duration_limit_minutes": None, "permit_type": None,
        "conditions": None, "vehicle_type": None,
    }

def _ev_only():
    return {
        "restriction": "EV_CHARGING",
        "days": [], "all_week": True,
        "start_time": None, "end_time": None, "all_day": True,
        "duration_limit_minutes": None, "permit_type": None,
        "conditions": None, "vehicle_type": None,
    }

def _no_stop():
    return {
        "restriction": "NO_STOPPING",
        "days": [], "all_week": True,
        "start_time": None, "end_time": None, "all_day": True,
        "duration_limit_minutes": None, "permit_type": None,
        "conditions": None, "vehicle_type": None,
    }

def _loading(days, start, end, minutes=30):
    return {
        "restriction": "LOADING_ZONE",
        "days": days, "all_week": False,
        "start_time": start, "end_time": end, "all_day": False,
        "duration_limit_minutes": minutes, "permit_type": None,
        "conditions": None, "vehicle_type": None,
    }

CTX_DEFAULT  = VehicleContext()
CTX_DISABLED = VehicleContext(has_disabled_permit=True)
CTX_PERMIT_A = VehicleContext(has_residential_permit=True, permit_zone="A")
CTX_EV       = VehicleContext(vehicle_type=VehicleType.EV)
CTX_LOADING  = VehicleContext(is_loading_unloading=True)


# ── 1. Basic NO_PARKING during restricted hours ──────────────────────────────

def test_no_parking_during_hours():
    rules = [_no_park(["MON","TUE","WED","THU","FRI"], "08:00", "18:00")]
    s, _, _ = _evaluate_slot(rules, "MON", time(9, 0), CTX_DEFAULT)
    assert s == SlotStatus.CANNOT_PARK

def test_no_parking_outside_hours():
    rules = [_no_park(["MON","TUE","WED","THU","FRI"], "08:00", "18:00")]
    s, _, _ = _evaluate_slot(rules, "MON", time(7, 30), CTX_DEFAULT)
    assert s == SlotStatus.CAN_PARK

def test_no_parking_not_applies_on_weekend():
    rules = [_no_park(["MON","TUE","WED","THU","FRI"], "08:00", "18:00")]
    s, _, _ = _evaluate_slot(rules, "SAT", time(9, 0), CTX_DEFAULT)
    assert s == SlotStatus.CAN_PARK


# ── 2. ADA / disabled permit exemptions ──────────────────────────────────────

def test_ada_overrides_timed_no_parking():
    """ADA permit should override a time-limited NO_PARKING rule."""
    rules = [_no_park(["MON","TUE","WED","THU","FRI"], "08:00", "18:00")]
    s, triggered, _ = _evaluate_slot(rules, "MON", time(9, 0), CTX_DISABLED)
    assert s == SlotStatus.CAN_PARK
    assert any(t.exemption_applied for t in triggered)

def test_ada_does_not_override_all_day_no_parking():
    """ADA should NOT override an absolute all-day no-parking zone."""
    rules = [_no_park([], all_day=True, all_week=True)]
    s, _, _ = _evaluate_slot(rules, "MON", time(9, 0), CTX_DISABLED)
    assert s == SlotStatus.CANNOT_PARK

def test_ada_removes_timed_parking_limit():
    """ADA permit: timed parking rule should still allow parking, just with no time cap."""
    rules = [_timed(["MON","TUE","WED","THU","FRI"], "09:00", "18:00", 120)]
    s, triggered, max_dur = _evaluate_slot(rules, "MON", time(10, 0), CTX_DISABLED)
    assert s == SlotStatus.CAN_PARK   # ADA: no time limit
    assert max_dur is None
    assert any("ADA" in (t.exemption_applied or "") for t in triggered)

def test_ada_overrides_permit_only():
    """ADA should grant access to permit-only zones."""
    rules = [_permit(["MON"], zone="A")]
    s, triggered, _ = _evaluate_slot(rules, "MON", time(10, 0), CTX_DISABLED)
    assert s == SlotStatus.CAN_PARK
    assert any("ADA" in (t.exemption_applied or "") for t in triggered)


# ── 3. Timed parking ─────────────────────────────────────────────────────────

def test_timed_parking_inside_hours():
    rules = [_timed(["MON","TUE","WED","THU","FRI"], "09:00", "18:00", 120)]
    s, _, max_dur = _evaluate_slot(rules, "MON", time(10, 0), CTX_DEFAULT)
    assert s       == SlotStatus.TIMED_PARK
    assert max_dur == 120

def test_timed_parking_outside_hours_is_free():
    rules = [_timed(["MON","TUE","WED","THU","FRI"], "09:00", "18:00", 120)]
    s, _, _ = _evaluate_slot(rules, "MON", time(19, 0), CTX_DEFAULT)
    assert s == SlotStatus.CAN_PARK


# ── 4. Permit-only ───────────────────────────────────────────────────────────

def test_permit_blocks_without_permit():
    rules = [_permit(["MON"], zone="A")]
    s, _, _ = _evaluate_slot(rules, "MON", time(10, 0), CTX_DEFAULT)
    assert s == SlotStatus.PERMIT_REQUIRED

def test_permit_grants_access_with_matching_zone():
    rules = [_permit(["MON"], zone="A")]
    s, _, _ = _evaluate_slot(rules, "MON", time(10, 0), CTX_PERMIT_A)
    assert s == SlotStatus.CAN_PARK


# ── 5. Street cleaning ───────────────────────────────────────────────────────

def test_street_cleaning_blocks_all_vehicles():
    rules = [_street_clean(["MON"], "08:00", "10:00")]
    for ctx in [CTX_DEFAULT, CTX_DISABLED, CTX_EV]:
        s, _, _ = _evaluate_slot(rules, "MON", time(9, 0), ctx)
        assert s == SlotStatus.CANNOT_PARK, f"Expected block for ctx {ctx}"

def test_street_cleaning_outside_hours_is_free():
    rules = [_street_clean(["MON"], "08:00", "10:00")]
    s, _, _ = _evaluate_slot(rules, "MON", time(11, 0), CTX_DEFAULT)
    assert s == SlotStatus.CAN_PARK


# ── 6. Absolute blocks ───────────────────────────────────────────────────────

def test_no_stopping_blocks_everyone():
    rules = [_no_stop()]
    for ctx in [CTX_DEFAULT, CTX_DISABLED, CTX_PERMIT_A, CTX_EV]:
        s, _, _ = _evaluate_slot(rules, "MON", time(12, 0), ctx)
        assert s == SlotStatus.CANNOT_PARK


# ── 7. EV charging ───────────────────────────────────────────────────────────

def test_ev_only_blocks_regular_car():
    rules = [_ev_only()]
    s, _, _ = _evaluate_slot(rules, "MON", time(12, 0), CTX_DEFAULT)
    assert s == SlotStatus.CANNOT_PARK

def test_ev_only_allows_ev():
    rules = [_ev_only()]
    s, _, _ = _evaluate_slot(rules, "MON", time(12, 0), CTX_EV)
    assert s == SlotStatus.CAN_PARK


# ── 8. Loading zone ──────────────────────────────────────────────────────────

def test_loading_zone_blocks_non_loader():
    rules = [_loading(["MON","TUE","WED","THU","FRI"], "07:00", "18:00")]
    s, _, _ = _evaluate_slot(rules, "MON", time(9, 0), CTX_DEFAULT)
    assert s == SlotStatus.CANNOT_PARK

def test_loading_zone_permits_loader():
    rules = [_loading(["MON","TUE","WED","THU","FRI"], "07:00", "18:00", 30)]
    s, _, max_dur = _evaluate_slot(rules, "MON", time(9, 0), CTX_LOADING)
    assert s       == SlotStatus.CAN_PARK
    assert max_dur == 30


# ── 9. Weekly grid sanity ────────────────────────────────────────────────────

def test_weekly_grid_shape():
    rules  = [_no_park(["MON","TUE","WED","THU","FRI"], "08:00", "18:00")]
    grid   = generate_weekly_grid(rules)
    assert set(grid.keys()) == set(ALL_DAYS)
    for day in ALL_DAYS:
        assert len(grid[day]) > 0
        for slot in grid[day]:
            assert "status" in slot
            assert slot["status"] in {s.value for s in SlotStatus}
