from datetime import datetime, timedelta
from pathlib import Path

import pytest

from garage.clock import SimulatedClock
from garage.garage import Garage
from garage.models import VehicleType

CONFIG = Path(__file__).parent.parent / "data" / "config.json"


@pytest.fixture
def garage():
    clock = SimulatedClock(start=datetime(2026, 1, 1, 8, 0))
    return Garage.from_config(CONFIG, clock=clock)


def test_session_under_24h_is_not_closed(garage):
    garage.check_in("KA01AA0001", VehicleType.COMPACT)
    later = garage.clock.now() + timedelta(hours=23)
    results = garage.run_nightly_job(now=later)
    assert results == []
    assert garage.find_car("KA01AA0001") is not None


def test_session_over_24h_is_auto_closed_and_billed(garage):
    entry = garage.clock.now()
    garage.check_in("KA01AA0002", VehicleType.COMPACT)
    now = entry + timedelta(hours=25)

    results = garage.run_nightly_job(now=now)

    assert len(results) == 1
    r = results[0]
    assert r.ticket.plate == "KA01AA0002"
    assert r.ticket.status.value == "closed"
    assert r.ticket.auto_closed is True
    assert r.ticket.closed_by == "nightly_job"
    # 25h = 1 full day (cap 120) + 1 remaining billable hour (first_hour 20)
    assert r.fee == 120.0 + 20.0
    assert garage.find_car("KA01AA0002") is None  # no longer active


def test_auto_closed_spot_is_freed_for_reuse(garage):
    result = garage.check_in("KA01AA0003", VehicleType.EV)
    spot_id = result.spot.spot_id
    now = garage.clock.now() + timedelta(hours=30)

    garage.run_nightly_job(now=now)

    assert garage.spot_manager.get_spot(spot_id).is_occupied is False
    # can be re-issued to a new car
    result2 = garage.check_in("KA01AA0004", VehicleType.EV)
    assert result2.spot.spot_id == spot_id


def test_fee_matches_manual_checkout_at_same_instant(garage):
    """The nightly job must bill exactly what a manual checkout would at
    the same timestamp - no special-cased math."""
    entry = garage.clock.now()
    garage.check_in("KA01AA0005", VehicleType.STANDARD, entry_time=entry)
    now = entry + timedelta(hours=50)  # multi-day stay

    auto_results = garage.run_nightly_job(now=now)
    auto_fee = auto_results[0].fee

    # Compute what a manual checkout at the same instant would charge,
    # using a second identical garage/vehicle so state isn't shared.
    clock2 = SimulatedClock(start=entry)
    garage2 = Garage.from_config(CONFIG, clock=clock2)
    garage2.check_in("KA01AA0005", VehicleType.STANDARD, entry_time=entry)
    manual = garage2.check_out("KA01AA0005", exit_time=now)

    assert auto_fee == manual.fee


def test_idempotent_same_instant_closes_nothing_twice(garage):
    entry = garage.clock.now()
    garage.check_in("KA01AA0006", VehicleType.COMPACT, entry_time=entry)
    now = entry + timedelta(hours=26)

    first = garage.run_nightly_job(now=now)
    second = garage.run_nightly_job(now=now)  # same instant again

    assert len(first) == 1
    assert second == []


def test_idempotent_re_running_at_later_instant_does_not_reclose(garage):
    entry = garage.clock.now()
    garage.check_in("KA01AA0007", VehicleType.COMPACT, entry_time=entry)
    now1 = entry + timedelta(hours=26)
    now2 = now1 + timedelta(hours=5)

    first = garage.run_nightly_job(now=now1)
    second = garage.run_nightly_job(now=now2)

    assert len(first) == 1
    assert second == []  # already closed, not re-billed for the extra 5h


def test_mixed_batch_only_closes_the_ones_over_threshold(garage):
    entry = garage.clock.now()
    garage.check_in("KA01AA0008", VehicleType.COMPACT, entry_time=entry)  # will be old
    garage.check_in("KA01AA0009", VehicleType.STANDARD,
                     entry_time=entry + timedelta(hours=20))  # still fresh at now

    now = entry + timedelta(hours=25)
    results = garage.run_nightly_job(now=now)

    plates_closed = {r.ticket.plate for r in results}
    assert plates_closed == {"KA01AA0008"}
    assert garage.find_car("KA01AA0009") is not None
