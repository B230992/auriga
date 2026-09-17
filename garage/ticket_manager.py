"""
Owns ticket lifecycle (open on check-in, closed on check-out) and answers
"find this car by its plate" instantly.

Design notes for a garage whose "log is huge" by evening:
  - `_active_by_plate` is a dict -> O(1) lookup for "is this car currently
    inside, and where". This is the hot path the attendant hits all day.
  - Closed tickets go to `_history` (append-only list) for the day's
    log/reporting. This grows unbounded over a long day, which is fine
    for in-memory demo use; the natural next step for a production
    system is to stream closed tickets straight to a database/log file
    instead of keeping them all in RAM (see README "Scaling notes").
  - A plate can only have ONE active ticket at a time, preventing the
    same car from being "checked in" twice.

Time source:
  - All timestamps default through an injected clock (SystemClock by
    default) instead of calling datetime.now() directly. This is what
    lets the nightly auto-close job (Twist 2) be driven deterministically
    by a grader via POST /clock instead of real wall-clock time.
"""
import itertools
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from .clock import Clock, SystemClock
from .exceptions import (
    InvalidTransferError,
    TicketNotFoundError,
    VehicleAlreadyParkedError,
)
from .models import Ticket, TicketStatus, VehicleType


class TicketManager:
    def __init__(self, clock: Optional[Clock] = None):
        self._clock = clock or SystemClock()
        self._id_counter = itertools.count(1)
        self._active_by_plate: Dict[str, Ticket] = {}
        self._tickets_by_id: Dict[str, Ticket] = {}
        self._history: List[Ticket] = []

    def _new_ticket_id(self) -> str:
        return f"T{next(self._id_counter):06d}"

    def open_ticket(
        self,
        plate: str,
        vehicle_type: VehicleType,
        spot_id: str,
        entry_time: Optional[datetime] = None,
    ) -> Ticket:
        plate = plate.strip().upper()
        if plate in self._active_by_plate:
            raise VehicleAlreadyParkedError(
                f"{plate} already has an active ticket "
                f"({self._active_by_plate[plate].ticket_id})"
            )
        ticket = Ticket(
            ticket_id=self._new_ticket_id(),
            plate=plate,
            vehicle_type=vehicle_type,
            spot_id=spot_id,
            entry_time=entry_time or self._clock.now(),
        )
        self._active_by_plate[plate] = ticket
        self._tickets_by_id[ticket.ticket_id] = ticket
        return ticket

    def close_ticket(
        self,
        plate: str,
        fee: float,
        exit_time: Optional[datetime] = None,
        closed_by: str = "attendant",
    ) -> Ticket:
        plate = plate.strip().upper()
        ticket = self._active_by_plate.get(plate)
        if ticket is None:
            raise TicketNotFoundError(f"No active ticket for plate {plate}")
        ticket.exit_time = exit_time or self._clock.now()
        ticket.fee = fee
        ticket.status = TicketStatus.CLOSED
        ticket.closed_by = closed_by
        ticket.auto_closed = closed_by == "nightly_job"
        del self._active_by_plate[plate]
        self._history.append(ticket)
        return ticket

    # ---------- Twist 3: valet hand-off ----------
    def transfer_plate(self, old_plate: str, new_plate: str) -> Ticket:
        """
        Move an OPEN session from old_plate to new_plate. The ticket
        object itself (spot_id, entry_time, ticket_id) is untouched -
        only the key it's filed under changes, plus an audit trail of
        every plate it's ever been under.
        """
        old_plate = (old_plate or "").strip().upper()
        new_plate = (new_plate or "").strip().upper()

        if not old_plate or not new_plate:
            raise InvalidTransferError("both the current and new plate are required")
        if old_plate == new_plate:
            raise InvalidTransferError("new plate must be different from the current plate")

        ticket = self._active_by_plate.get(old_plate)
        if ticket is None:
            raise TicketNotFoundError(f"No active ticket for plate {old_plate}")
        if new_plate in self._active_by_plate:
            raise VehicleAlreadyParkedError(
                f"{new_plate} already has an active ticket "
                f"({self._active_by_plate[new_plate].ticket_id})"
            )

        del self._active_by_plate[old_plate]
        ticket.plate_history.append(ticket.plate)
        ticket.plate = new_plate
        self._active_by_plate[new_plate] = ticket
        return ticket

    # ---------- Twist 2: nightly auto-close ----------
    def active_tickets_over(self, hours: float, now: datetime) -> List[Ticket]:
        """Active tickets whose elapsed parked time has reached `hours`."""
        cutoff = timedelta(hours=hours)
        return [
            t for t in self._active_by_plate.values()
            if (now - t.entry_time) >= cutoff
        ]

    # ---------- lookups ----------
    def find_active_by_plate(self, plate: str) -> Optional[Ticket]:
        """O(1) answer to 'where is car XYZ right now?'"""
        return self._active_by_plate.get(plate.strip().upper())

    def get_ticket(self, ticket_id: str) -> Ticket:
        if ticket_id not in self._tickets_by_id:
            raise TicketNotFoundError(ticket_id)
        return self._tickets_by_id[ticket_id]

    def active_tickets(self) -> List[Ticket]:
        return list(self._active_by_plate.values())

    def history(self) -> List[Ticket]:
        return list(self._history)
