"""
Core domain objects for the parking garage system.

Kept deliberately dumb (plain dataclasses) - all behaviour/rules live in
the manager / engine classes so the data model stays reusable across
any garage configuration.
"""
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import List, Optional


class SpotType(str, Enum):
    COMPACT = "compact"
    STANDARD = "standard"
    EV = "ev"


# A vehicle's type drives which spot type(s) it is allowed to use.
# Kept as an alias of SpotType so "compact car / compact spot" etc. line
# up 1:1, but defined separately in case a garage ever needs a vehicle
# type that has no matching spot type (e.g. motorcycle -> any spot).
class VehicleType(str, Enum):
    COMPACT = "compact"
    STANDARD = "standard"
    EV = "ev"


class TicketStatus(str, Enum):
    ACTIVE = "active"
    CLOSED = "closed"


@dataclass
class Spot:
    spot_id: str
    level: int
    spot_type: SpotType
    is_occupied: bool = False
    current_ticket_id: Optional[str] = None


@dataclass
class Vehicle:
    plate: str
    vehicle_type: VehicleType


@dataclass
class Ticket:
    ticket_id: str
    plate: str
    vehicle_type: VehicleType
    spot_id: str
    entry_time: datetime
    exit_time: Optional[datetime] = None
    fee: Optional[float] = None
    status: TicketStatus = TicketStatus.ACTIVE

    # --- Twist 2: nightly auto-close (T2) ---
    # Who closed this ticket: "attendant" (normal checkout) or
    # "nightly_job" (auto-closed for exceeding the 24h threshold).
    closed_by: Optional[str] = None
    auto_closed: bool = False

    # --- Twist 3: valet hand-off / plate transfer (T6) ---
    # Every previous plate this ticket was ever under, oldest first.
    # spot_id and entry_time are untouched by a transfer - only the
    # plate key changes - so this list is purely an audit trail.
    plate_history: List[str] = field(default_factory=list)
