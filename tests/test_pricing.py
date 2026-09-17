from datetime import datetime, timedelta

import pytest

from garage.models import SpotType
from garage.pricing import PricingEngine, RateCard

RATES = {
    SpotType.COMPACT: RateCard(first_hour=20, additional_hour=10, daily_cap=120),
    SpotType.STANDARD: RateCard(first_hour=30, additional_hour=15, daily_cap=150),
    SpotType.EV: RateCard(first_hour=40, additional_hour=20, daily_cap=200),
}


@pytest.fixture
def engine():
    return PricingEngine(RATES)


def fee(engine, minutes, spot_type=SpotType.COMPACT):
    start = datetime(2026, 1, 1, 9, 0)
    end = start + timedelta(minutes=minutes)
    return engine.calculate_fee(start, end, spot_type)


def test_under_one_hour_charges_first_hour_rate(engine):
    assert fee(engine, 10) == 20
    assert fee(engine, 59) == 20


def test_exactly_one_hour_charges_first_hour_rate(engine):
    assert fee(engine, 60) == 20


def test_partial_hour_rounds_up(engine):
    # 61 minutes -> 2 billable hours: 20 + 10 = 30
    assert fee(engine, 61) == 30
    # 90 minutes -> still 2 billable hours
    assert fee(engine, 90) == 30


def test_multiple_additional_hours(engine):
    # 3h 5m -> 4 billable hours: 20 + 3*10 = 50
    assert fee(engine, 185) == 50


def test_daily_cap_is_enforced(engine):
    # 20 hours would be 20 + 19*10 = 210, way above the 120 cap
    assert fee(engine, 20 * 60) == 120


def test_multi_day_stay_stacks_daily_caps(engine):
    # exactly 2 days -> 2 * daily_cap
    assert fee(engine, 48 * 60) == 240
    # 2 days + 2 hours -> 2*cap + (first_hour + 1*additional_hour)
    assert fee(engine, 50 * 60) == 240 + (20 + 10)


def test_different_spot_types_have_different_rates(engine):
    assert fee(engine, 30, SpotType.EV) == 40
    assert fee(engine, 30, SpotType.STANDARD) == 30


def test_zero_or_negative_duration_still_charges_minimum_hour(engine):
    assert fee(engine, 0) == 20


def test_exit_before_entry_raises(engine):
    start = datetime(2026, 1, 1, 9, 0)
    end = start - timedelta(minutes=5)
    with pytest.raises(ValueError):
        engine.calculate_fee(start, end, SpotType.COMPACT)


def test_unknown_spot_type_raises(engine):
    with pytest.raises(KeyError):
        engine.calculate_fee(
            datetime(2026, 1, 1, 9, 0), datetime(2026, 1, 1, 10, 0), "motorcycle"
        )


def test_rate_card_rejects_first_hour_above_cap():
    with pytest.raises(ValueError):
        RateCard(first_hour=500, additional_hour=10, daily_cap=100)
