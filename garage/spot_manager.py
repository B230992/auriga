"""
Owns every physical Spot and answers the two questions the attendant
asks constantly:
  1. "Is there a free spot for this vehicle?" / "Is an EV spot free right now?"
  2. "Park this vehicle" / "Free this spot" - without ever double-parking.

Design notes:
  - Spots are grouped by type into a `set` of free spot_ids
    (`_free_by_type`). Checking / picking availability is O(1) instead
    of scanning every spot in the garage, which matters once the
    garage (and its log) is large.
  - Allocation rule: a vehicle must get a spot of its own type EXCEPT
    a compact car may fall back to a standard spot if compact is full
    (a smaller car fits a bigger spot). An EV *always* needs an EV
    spot because that's the only place with a charger - no fallback.
    This fallback order is configurable via `fallback_order`.
"""
from typing import Dict, List, Optional

from .exceptions import (
    GarageFullError,
    SpotAlreadyOccupiedError,
    SpotNotFoundError,
)
from .models import Spot, SpotType, VehicleType

# vehicle_type -> ordered list of spot types it is allowed to use.
# First entry is the "natural" spot type; later entries are fallbacks.
DEFAULT_FALLBACK_ORDER: Dict[VehicleType, List[SpotType]] = {
    VehicleType.EV: [SpotType.EV],  # EV must get an EV (charger) spot, no fallback
    VehicleType.COMPACT: [SpotType.COMPACT, SpotType.STANDARD],
    VehicleType.STANDARD: [SpotType.STANDARD],
}


class SpotManager:
    def __init__(
        self,
        fallback_order: Optional[Dict[VehicleType, List[SpotType]]] = None,
    ):
        self._spots: Dict[str, Spot] = {}
        self._free_by_type: Dict[SpotType, set] = {t: set() for t in SpotType}
        self.fallback_order = fallback_order or DEFAULT_FALLBACK_ORDER

    # ---------- setup ----------
    def add_spot(self, spot: Spot) -> None:
        if spot.spot_id in self._spots:
            raise ValueError(f"Duplicate spot id {spot.spot_id}")
        self._spots[spot.spot_id] = spot
        if not spot.is_occupied:
            self._free_by_type[spot.spot_type].add(spot.spot_id)

    # ---------- queries (all O(1)) ----------
    def count_available(self, spot_type: SpotType) -> int:
        return len(self._free_by_type[spot_type])

    def is_available(self, spot_type: SpotType) -> bool:
        """Answers: 'Is an EV spot free right now?'"""
        return self.count_available(spot_type) > 0

    def get_spot(self, spot_id: str) -> Spot:
        if spot_id not in self._spots:
            raise SpotNotFoundError(spot_id)
        return self._spots[spot_id]

    def availability_summary(self) -> Dict[str, int]:
        return {t.value: self.count_available(t) for t in SpotType}

    # ---------- allocation ----------
    def find_free_spot_id(self, vehicle_type: VehicleType) -> Optional[str]:
        """Picks (but does NOT occupy) the best free spot id for this
        vehicle type, walking the fallback order. Returns None if the
        garage is full for that vehicle type. Because EV's fallback
        order is only [EV], this is also what guarantees an EV can
        never be matched to a non-EV spot.
        """
        for candidate_type in self.fallback_order[vehicle_type]:
            free_ids = self._free_by_type[candidate_type]
            if free_ids:
                return next(iter(free_ids))
        return None

    def allocate_spot(self, vehicle_type: VehicleType, ticket_id: str) -> Spot:
        """Finds AND occupies the best free spot for this vehicle type
        in one step. Raises GarageFullError if nothing suitable is free.
        """
        spot_id = self.find_free_spot_id(vehicle_type)
        if spot_id is None:
            raise GarageFullError(f"No available spot for vehicle type {vehicle_type.value}")
        return self.occupy_spot(spot_id, ticket_id)

    def occupy_spot(self, spot_id: str, ticket_id: str) -> Spot:
        spot = self.get_spot(spot_id)
        if spot.is_occupied:
            raise SpotAlreadyOccupiedError(spot_id)
        spot.is_occupied = True
        spot.current_ticket_id = ticket_id
        self._free_by_type[spot.spot_type].discard(spot_id)
        return spot

    def free_spot(self, spot_id: str) -> Spot:
        spot = self.get_spot(spot_id)
        spot.is_occupied = False
        spot.current_ticket_id = None
        self._free_by_type[spot.spot_type].add(spot_id)
        return spot

    def all_spots(self) -> List[Spot]:
        return list(self._spots.values())
