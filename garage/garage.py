"""
Public facade the attendant (or any front-end - CLI, API, UI) talks to.

Everything that makes this work for "any garage, not one" lives in
`from_config`: number of levels, how many spots of each type per level,
and the rate card per spot type are all data, not code.
"""
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Union

from .exceptions import GarageFullError
from .models import Spot, SpotType, Ticket, VehicleType
from .pricing import PricingEngine, RateCard
from .spot_manager import SpotManager
from .ticket_manager import TicketManager


@dataclass
class CheckInResult:
    ticket: Ticket
    spot: Spot


@dataclass
class CheckOutResult:
    ticket: Ticket
    fee: float
    duration_minutes: float


class Garage:
    def __init__(self, spot_manager: SpotManager, pricing_engine: PricingEngine):
        self.spot_manager = spot_manager
        self.pricing_engine = pricing_engine
        self.ticket_manager = TicketManager()

    # ---------- construction ----------
    @classmethod
    def from_config(cls, config: Union[str, Path, dict]) -> "Garage":
        """Build a Garage from a JSON config file/dict, e.g.:

        {
          "levels": 3,
          "spots_per_level": {"compact": 10, "standard": 15, "ev": 5},
          "rates": {
            "compact":  {"first_hour": 20, "additional_hour": 10, "daily_cap": 120},
            "standard": {"first_hour": 30, "additional_hour": 15, "daily_cap": 150},
            "ev":       {"first_hour": 40, "additional_hour": 20, "daily_cap": 200}
          }
        }
        """
        if isinstance(config, (str, Path)):
            with open(config, "r") as f:
                config = json.load(f)

        spot_manager = SpotManager()
        counter = 1
        for level in range(1, config["levels"] + 1):
            for type_name, count in config["spots_per_level"].items():
                spot_type = SpotType(type_name)
                for _ in range(count):
                    spot_manager.add_spot(
                        Spot(spot_id=f"L{level}-{spot_type.value.upper()}-{counter:03d}",
                             level=level, spot_type=spot_type)
                    )
                    counter += 1

        rates: Dict[SpotType, RateCard] = {
            SpotType(type_name): RateCard(**rate)
            for type_name, rate in config["rates"].items()
        }
        pricing_engine = PricingEngine(rates)
        return cls(spot_manager, pricing_engine)

    # ---------- attendant operations ----------
    def check_in(
        self,
        plate: str,
        vehicle_type: VehicleType,
        entry_time: Optional[datetime] = None,
    ) -> CheckInResult:
        # Check availability FIRST (raise before touching any state) so a
        # failed check-in never creates a dangling ticket. An EV's fallback
        # order is only [EV], so this is also what guarantees an EV can
        # never be matched to a non-EV spot.
        spot_id = self.spot_manager.find_free_spot_id(vehicle_type)
        if spot_id is None:
            raise GarageFullError(f"No available spot for vehicle type {vehicle_type.value}")

        # Open the ticket, then atomically occupy the spot we just found.
        # occupy_spot() re-checks is_occupied and raises rather than ever
        # letting two tickets land on the same spot.
        ticket = self.ticket_manager.open_ticket(
            plate=plate, vehicle_type=vehicle_type,
            spot_id=spot_id, entry_time=entry_time,
        )
        spot = self.spot_manager.occupy_spot(spot_id, ticket.ticket_id)
        return CheckInResult(ticket=ticket, spot=spot)

    def check_out(
        self, plate: str, exit_time: Optional[datetime] = None
    ) -> CheckOutResult:
        active = self.ticket_manager.find_active_by_plate(plate)
        if active is None:
            from .exceptions import TicketNotFoundError
            raise TicketNotFoundError(f"No active ticket for plate {plate}")

        exit_time = exit_time or datetime.now()
        spot = self.spot_manager.get_spot(active.spot_id)
        fee = self.pricing_engine.calculate_fee(active.entry_time, exit_time, spot.spot_type)

        ticket = self.ticket_manager.close_ticket(plate, fee=fee, exit_time=exit_time)
        self.spot_manager.free_spot(spot.spot_id)

        duration_minutes = (exit_time - ticket.entry_time).total_seconds() / 60
        return CheckOutResult(ticket=ticket, fee=fee, duration_minutes=duration_minutes)

    # ---------- driver / attendant queries ----------
    def is_spot_type_available(self, spot_type: SpotType) -> bool:
        return self.spot_manager.is_available(spot_type)

    def availability_summary(self) -> Dict[str, int]:
        return self.spot_manager.availability_summary()

    def find_car(self, plate: str) -> Optional[Ticket]:
        return self.ticket_manager.find_active_by_plate(plate)

    def active_tickets(self) -> List[Ticket]:
        return self.ticket_manager.active_tickets()

    def history(self) -> List[Ticket]:
        return self.ticket_manager.history()
