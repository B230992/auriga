import pytest

from garage.exceptions import GarageFullError, SpotAlreadyOccupiedError
from garage.models import Spot, SpotType, VehicleType
from garage.spot_manager import SpotManager


def build_manager(compact=1, standard=1, ev=1):
    mgr = SpotManager()
    n = 1
    for _ in range(compact):
        mgr.add_spot(Spot(f"S{n}", 1, SpotType.COMPACT)); n += 1
    for _ in range(standard):
        mgr.add_spot(Spot(f"S{n}", 1, SpotType.STANDARD)); n += 1
    for _ in range(ev):
        mgr.add_spot(Spot(f"S{n}", 1, SpotType.EV)); n += 1
    return mgr


def test_availability_reflects_occupancy():
    mgr = build_manager(compact=2)
    assert mgr.count_available(SpotType.COMPACT) == 2
    spot = mgr.allocate_spot(VehicleType.COMPACT, "T1")
    assert mgr.count_available(SpotType.COMPACT) == 1
    mgr.free_spot(spot.spot_id)
    assert mgr.count_available(SpotType.COMPACT) == 2


def test_ev_vehicle_only_ever_gets_ev_spot():
    mgr = build_manager(compact=5, standard=5, ev=1)
    spot = mgr.allocate_spot(VehicleType.EV, "T1")
    assert spot.spot_type == SpotType.EV


def test_ev_vehicle_never_falls_back_to_other_types():
    mgr = build_manager(compact=5, standard=5, ev=0)  # no EV spots at all
    with pytest.raises(GarageFullError):
        mgr.allocate_spot(VehicleType.EV, "T1")


def test_compact_car_falls_back_to_standard_when_compact_full():
    mgr = build_manager(compact=0, standard=1, ev=0)
    spot = mgr.allocate_spot(VehicleType.COMPACT, "T1")
    assert spot.spot_type == SpotType.STANDARD


def test_garage_full_raises_for_vehicle_type():
    mgr = build_manager(compact=1, standard=0, ev=0)
    mgr.allocate_spot(VehicleType.COMPACT, "T1")  # takes the only compact spot
    with pytest.raises(GarageFullError):
        mgr.allocate_spot(VehicleType.COMPACT, "T2")


def test_cannot_double_occupy_a_spot():
    mgr = build_manager(compact=1)
    mgr.occupy_spot("S1", "T1")
    with pytest.raises(SpotAlreadyOccupiedError):
        mgr.occupy_spot("S1", "T2")


def test_no_spot_is_ever_double_allocated_under_load():
    # allocate every compact spot exactly once, confirm all ids unique
    mgr = build_manager(compact=20, standard=0, ev=0)
    seen = set()
    for i in range(20):
        spot = mgr.allocate_spot(VehicleType.COMPACT, f"T{i}")
        assert spot.spot_id not in seen
        seen.add(spot.spot_id)
    assert mgr.count_available(SpotType.COMPACT) == 0
    with pytest.raises(GarageFullError):
        mgr.allocate_spot(VehicleType.COMPACT, "T-overflow")
