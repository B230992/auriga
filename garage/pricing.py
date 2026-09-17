"""
Tiered pricing.

Rules implemented (from the spec):
  - First hour billed at `first_hour` rate.
  - Every additional hour billed at the cheaper `additional_hour` rate.
  - Part-hours round UP (5 minutes over counts as a full extra hour).
  - A `daily_cap` limits the max charge for any 24-hour block, so a
    long stay is never overcharged.
  - Stays longer than 24h are billed as (full days * daily_cap) +
    (the tiered/capped fee for the remaining partial day).

Rates are per spot_type so different garages can price compact /
standard / EV parking differently (e.g. EV includes charging).
"""
import math
from dataclasses import dataclass
from datetime import datetime
from typing import Dict

from .models import SpotType

MINUTES_PER_HOUR = 60
HOURS_PER_DAY = 24


@dataclass
class RateCard:
    first_hour: float
    additional_hour: float
    daily_cap: float

    def __post_init__(self):
        if self.first_hour < 0 or self.additional_hour < 0 or self.daily_cap < 0:
            raise ValueError("Rates must be non-negative")
        if self.first_hour > self.daily_cap:
            raise ValueError("first_hour rate cannot exceed the daily_cap")


class PricingEngine:
    def __init__(self, rates: Dict[SpotType, RateCard]):
        self.rates = rates

    def _hours_billed(self, entry_time: datetime, exit_time: datetime) -> int:
        if exit_time < entry_time:
            raise ValueError("exit_time cannot be before entry_time")
        minutes = (exit_time - entry_time).total_seconds() / 60
        # any parked duration (even a few minutes) is at least 1 billable hour
        hours = math.ceil(minutes / MINUTES_PER_HOUR)
        return max(hours, 1)

    def _fee_for_partial_day(self, hours: int, rate: RateCard) -> float:
        """hours is 1..24, tiered fee capped at the daily cap."""
        if hours <= 0:
            return 0.0
        fee = rate.first_hour + max(hours - 1, 0) * rate.additional_hour
        return min(fee, rate.daily_cap)

    def calculate_fee(
        self, entry_time: datetime, exit_time: datetime, spot_type: SpotType
    ) -> float:
        if spot_type not in self.rates:
            raise KeyError(f"No rate card configured for spot type {spot_type}")
        rate = self.rates[spot_type]

        total_hours = self._hours_billed(entry_time, exit_time)
        full_days, remaining_hours = divmod(total_hours, HOURS_PER_DAY)

        fee = full_days * rate.daily_cap
        fee += self._fee_for_partial_day(remaining_hours, rate)
        return round(fee, 2)
