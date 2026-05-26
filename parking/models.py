from dataclasses import dataclass
from enum import Enum


class RestrictionType(str, Enum):
    NO_PARKING      = "NO_PARKING"
    NO_STOPPING     = "NO_STOPPING"        # tow-away / no stopping / no standing
    STREET_CLEANING = "STREET_CLEANING"    # street sweeping
    TIMED_PARKING   = "TIMED_PARKING"      # can park but time-limited
    PERMIT_ONLY     = "PERMIT_ONLY"        # residential / area permit
    DISABLED_ONLY   = "DISABLED_ONLY"      # ADA / handicap placard required
    LOADING_ZONE    = "LOADING_ZONE"       # commercial loading / unloading
    BUS_ZONE        = "BUS_ZONE"           # bus stop / transit zone
    FIRE_LANE       = "FIRE_LANE"          # fire lane / fire hydrant
    EV_CHARGING     = "EV_CHARGING"        # electric-vehicle charging only
    FREE_PARKING    = "FREE_PARKING"       # explicitly unrestricted


class ParkingDecision(str, Enum):
    PARK        = "PARK"
    DO_NOT_PARK = "DO_NOT_PARK"


class SlotStatus(str, Enum):
    """Per-slot status used for weekly-grid colour coding."""
    CAN_PARK        = "CAN_PARK"
    CANNOT_PARK     = "CANNOT_PARK"
    TIMED_PARK      = "TIMED_PARK"
    PERMIT_REQUIRED = "PERMIT_REQUIRED"


class VehicleType(str, Enum):
    REGULAR    = "regular"
    EV         = "ev"
    MOTORCYCLE = "motorcycle"
    TRUCK      = "truck"
    COMMERCIAL = "commercial"


@dataclass
class VehicleContext:
    vehicle_type:           VehicleType = VehicleType.REGULAR
    has_disabled_permit:    bool = False   # ADA / handicap placard
    has_residential_permit: bool = False
    permit_zone:            str  = ""      # e.g. "A", "B", "Zone 3"
    is_loading_unloading:   bool = False   # actively loading/unloading freight


@dataclass
class TriggeredRule:
    restriction:       str
    description:       str         # human-readable rule summary
    blocking:          bool        # True → caused DO_NOT_PARK
    exemption_applied: str | None = None  # why the rule was overridden


@dataclass
class ParkingResult:
    decision:             ParkingDecision
    status:               SlotStatus
    headline:             str
    reason:               str
    warnings:             list[str]
    triggered_rules:      list[TriggeredRule]
    max_duration_minutes: int | None
    next_change_at:       str | None     # e.g. "6:00 PM"
    current_day:          str
    current_time:         str
    current_day_full:     str
    current_slot:         int
    day_index:            int
    display_start_slot:   int
    can_park:             bool           # convenience alias for frontend
