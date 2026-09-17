from pathlib import Path

import pytest

from garage.exceptions import (
    InvalidTransferError,
    TicketNotFoundError,
    VehicleAlreadyParkedError,
)
from garage.garage import Garage
from garage.models import VehicleType

CONFIG = Path(__file__).parent.parent / "data" / "config.json"


@pytest.fixture
def garage():
    return Garage.from_config(CONFIG)


def test_transfer_moves_plate_and_keeps_spot_and_entry_time(garage):
    result = garage.check_in("OLD1234", VehicleType.COMPACT)
    original_spot = result.spot.spot_id
    original_entry = result.ticket.entry_time

    ticket = garage.transfer_plate("OLD1234", "NEW5678")

    assert ticket.plate == "NEW5678"
    assert ticket.spot_id == original_spot
    assert ticket.entry_time == original_entry
    assert ticket.ticket_id == result.ticket.ticket_id


def test_old_plate_no_longer_finds_the_car(garage):
    garage.check_in("OLD1234", VehicleType.COMPACT)
    garage.transfer_plate("OLD1234", "NEW5678")

    assert garage.find_car("OLD1234") is None
    assert garage.find_car("NEW5678") is not None


def test_new_plate_can_check_out_and_is_billed_from_original_entry(garage):
    from datetime import datetime

    entry = datetime(2026, 1, 1, 10, 0)
    garage.check_in("OLD1234", VehicleType.COMPACT, entry_time=entry)
    garage.transfer_plate("OLD1234", "NEW5678")

    exit_ = datetime(2026, 1, 1, 12, 5)  # 2h5m -> 3 billable hours from ORIGINAL entry
    out = garage.check_out("NEW5678", exit_time=exit_)

    assert out.fee == 40.0  # 20 + 2*10, same as if never transferred


def test_spot_manager_state_untouched_by_transfer(garage):
    result = garage.check_in("OLD1234", VehicleType.COMPACT)
    spot_id = result.spot.spot_id
    spot_before = garage.spot_manager.get_spot(spot_id)
    assert spot_before.is_occupied is True
    assert spot_before.current_ticket_id == result.ticket.ticket_id

    garage.transfer_plate("OLD1234", "NEW5678")

    spot_after = garage.spot_manager.get_spot(spot_id)
    assert spot_after.is_occupied is True
    assert spot_after.current_ticket_id == result.ticket.ticket_id  # unchanged


def test_plate_history_records_the_handoff(garage):
    garage.check_in("OLD1234", VehicleType.COMPACT)
    ticket = garage.transfer_plate("OLD1234", "NEW5678")
    assert ticket.plate_history == ["OLD1234"]

    ticket2 = garage.transfer_plate("NEW5678", "NEWEST99")
    assert ticket2.plate_history == ["OLD1234", "NEW5678"]


def test_transfer_rejects_nonexistent_old_plate(garage):
    with pytest.raises(TicketNotFoundError):
        garage.transfer_plate("GHOST999", "NEW5678")


def test_transfer_rejects_new_plate_already_active(garage):
    garage.check_in("OLD1234", VehicleType.COMPACT)
    garage.check_in("TAKEN999", VehicleType.STANDARD)

    with pytest.raises(VehicleAlreadyParkedError):
        garage.transfer_plate("OLD1234", "TAKEN999")


def test_transfer_rejects_blank_new_plate(garage):
    garage.check_in("OLD1234", VehicleType.COMPACT)
    with pytest.raises(InvalidTransferError):
        garage.transfer_plate("OLD1234", "   ")


def test_transfer_rejects_same_plate(garage):
    garage.check_in("OLD1234", VehicleType.COMPACT)
    with pytest.raises(InvalidTransferError):
        garage.transfer_plate("OLD1234", "old1234")  # case-insensitive same plate
