from datetime import datetime, timedelta

import pytest

from garage.exceptions import (
    GarageFullError,
    TicketNotFoundError,
    VehicleAlreadyParkedError,
)
from garage.garage import Garage
from garage.models import SpotType, VehicleType

CONFIG = {
    "levels": 1,
    "spots_per_level": {"compact": 1, "standard": 1, "ev": 1},
    "rates": {
        "compact": {"first_hour": 20, "additional_hour": 10, "daily_cap": 120},
        "standard": {"first_hour": 30, "additional_hour": 15, "daily_cap": 150},
        "ev": {"first_hour": 40, "additional_hour": 20, "daily_cap": 200},
    },
}


@pytest.fixture
def garage():
    return Garage.from_config(CONFIG)


def test_checkin_checkout_charges_correct_fee(garage):
    in_time = datetime(2026, 1, 1, 9, 0)
    out_time = in_time + timedelta(hours=2, minutes=5)  # -> 3 billable hours

    garage.check_in("dl1ab1234", VehicleType.COMPACT, entry_time=in_time)
    result = garage.check_out("DL1AB1234", exit_time=out_time)  # case-insensitive plate

    assert result.fee == 20 + 2 * 10  # first hour + 2 extra hours
    assert result.ticket.status.value == "closed"


def test_plate_lookup_while_parked(garage):
    garage.check_in("KA05XY0001", VehicleType.STANDARD)
    found = garage.find_car("ka05xy0001")
    assert found is not None
    assert found.spot_id.startswith("L1-STANDARD")


def test_plate_not_found_after_checkout(garage):
    garage.check_in("MH12ZZ9999", VehicleType.COMPACT)
    garage.check_out("MH12ZZ9999")
    assert garage.find_car("MH12ZZ9999") is None


def test_double_checkin_same_plate_rejected(garage):
    garage.check_in("TS09QQ0001", VehicleType.COMPACT)
    with pytest.raises(VehicleAlreadyParkedError):
        garage.check_in("TS09QQ0001", VehicleType.COMPACT)


def test_checkout_without_checkin_rejected(garage):
    with pytest.raises(TicketNotFoundError):
        garage.check_out("NOCAR0001")


def test_ev_spot_availability_query(garage):
    assert garage.is_spot_type_available(SpotType.EV) is True
    garage.check_in("EV0001", VehicleType.EV)
    assert garage.is_spot_type_available(SpotType.EV) is False


def test_ev_checkin_fails_gracefully_when_full_no_fallback(garage):
    garage.check_in("EV0001", VehicleType.EV)  # takes the only EV spot
    with pytest.raises(GarageFullError):
        garage.check_in("EV0002", VehicleType.EV)
    # failed attempt must not leave a dangling ticket
    assert garage.find_car("EV0002") is None


def test_freed_spot_can_be_reused_by_next_car(garage):
    garage.check_in("CAR-A", VehicleType.COMPACT)
    garage.check_out("CAR-A")
    result = garage.check_in("CAR-B", VehicleType.COMPACT)
    assert result.spot.spot_type == SpotType.COMPACT


def test_history_and_active_lists(garage):
    garage.check_in("ACTIVE1", VehicleType.COMPACT)
    garage.check_in("DONE1", VehicleType.STANDARD)
    garage.check_out("DONE1")

    assert [t.plate for t in garage.active_tickets()] == ["ACTIVE1"]
    assert [t.plate for t in garage.history()] == ["DONE1"]
