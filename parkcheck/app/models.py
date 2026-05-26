from dataclasses import dataclass
from enum import Enum


class RestrictionType(str, Enum):
    NO_PARKING      = "NO_PARKING"
    NO_STOPPING     = "NO_STOPPING"
    STREET_CLEANING = "STREET_CLEANING"
    TIMED_PARKING   = "TIMED_PARKING"
    PERMIT_ONLY     = "PERMIT_ONLY"
    DISABLED_ONLY   = "DISABLED_ONLY"
    LOADING_ZONE    = "LOADING_ZONE"
    BUS_ZONE        = "BUS_ZONE"
    FIRE_LANE       = "FIRE_LANE"
    EV_CHARGING     = "EV_CHARGING"
    FREE_PARKING    = "FREE_PARKING"


class ParkingDecision(str, Enum):
    PARK        = "PARK"
    DO_NOT_PARK = "DO_NOT_PARK"


class SlotStatus(str, Enum):
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
    has_disabled_permit:    bool = False
    has_residential_permit: bool = False
    permit_zone:            str  = ""
    is_loading_unloading:   bool = False


@dataclass
class TriggeredRule:
    restriction:       str
    description:       str
    blocking:          bool
    exemption_applied: str | None = None


@dataclass
class ParkingResult:
    decision:             ParkingDecision
    status:               SlotStatus
    headline:             str
    reason:               str
    warnings:             list[str]
    triggered_rules:      list[TriggeredRule]
    max_duration_minutes: int | None
    next_change_at:       str | None
    current_day:          str
    current_time:         str
    current_day_full:     str
    current_slot:         int
    day_index:            int
    display_start_slot:   int
    can_park:             bool
