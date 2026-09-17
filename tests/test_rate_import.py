from pathlib import Path

import pytest

from garage.exceptions import RateCardImportError
from garage.garage import Garage
from garage.models import SpotType, VehicleType
from garage.pricing import RateCard
from garage.rate_import import load_rate_cards

MESSY_CSV = Path(__file__).parent.parent / "data" / "rates_messy.csv"
CONFIG = Path(__file__).parent.parent / "data" / "config.json"


def test_cleans_all_three_spot_types():
    rates, report = load_rate_cards(MESSY_CSV)
    assert set(rates.keys()) == {SpotType.COMPACT, SpotType.STANDARD, SpotType.EV}


def test_currency_symbols_and_whitespace_cleaned():
    rates, _ = load_rate_cards(MESSY_CSV)
    # "₹20" / "₹10" / "₹120" -> 20/10/120
    assert rates[SpotType.COMPACT] == RateCard(first_hour=20.0, additional_hour=10.0, daily_cap=120.0)
    # " Rs. 30 " -> 30, "Rs.150" -> 150, header alias "1st_hr"/"extra_hour"/"max_daily" resolved
    assert rates[SpotType.STANDARD] == RateCard(first_hour=30.0, additional_hour=15.0, daily_cap=150.0)
    # "Rs 40" -> 40, type "e.v." normalized to EV
    assert rates[SpotType.EV] == RateCard(first_hour=40.0, additional_hour=20.0, daily_cap=200.0)


def test_first_valid_occurrence_wins_over_duplicates():
    rates, report = load_rate_cards(MESSY_CSV)
    # compact appears again later as "free" (0/10/120) - must NOT override
    # the first valid row's 20/10/120.
    assert rates[SpotType.COMPACT].first_hour == 20.0
    dup_types = {r.spot_type for r in report.duplicates}
    assert "compact" in dup_types
    assert "ev" in dup_types
    assert "standard" in dup_types  # the "Rs. 1,200" duplicate row


def test_thousands_comma_and_currency_combo_parsed_even_when_ignored():
    _, report = load_rate_cards(MESSY_CSV)
    comma_row = next(r for r in report.duplicates if r.parsed and r.parsed["first_hour"] == 1200.0)
    assert comma_row.spot_type == "standard"
    assert comma_row.parsed["daily_cap"] == 1200.0


def test_free_parses_to_zero():
    _, report = load_rate_cards(MESSY_CSV)
    free_row = next(r for r in report.duplicates if r.spot_type == "compact" and r.parsed["first_hour"] == 0.0)
    assert free_row.parsed["additional_hour"] == 10.0


def test_unsupported_spot_type_dropped():
    _, report = load_rate_cards(MESSY_CSV)
    reasons = [r.reason for r in report.dropped]
    assert any("Motorbike" in r for r in reasons)
    assert any("TOTAL" in r for r in reasons)


def test_blank_rows_dropped():
    _, report = load_rate_cards(MESSY_CSV)
    blank_drops = [r for r in report.dropped if r.reason == "blank row"]
    assert len(blank_drops) == 2


def test_nullish_and_invalid_numeric_dropped():
    _, report = load_rate_cards(MESSY_CSV)
    # "N/A" additional_hour and "-" daily_cap both count as unparseable
    assert sum(1 for r in report.dropped if r.reason == "missing/unparseable numeric field") == 2


def test_negative_rate_dropped():
    _, report = load_rate_cards(MESSY_CSV)
    assert any(r.reason == "negative rate" for r in report.dropped)


def test_bom_on_header_does_not_break_parsing():
    with open(MESSY_CSV, "rb") as f:
        assert f.read(3) == b"\xef\xbb\xbf"  # confirm the fixture really has a BOM
    rates, _ = load_rate_cards(MESSY_CSV)  # must not raise
    assert len(rates) == 3


def test_row_counts_are_consistent():
    _, report = load_rate_cards(MESSY_CSV)
    assert len(report.used) == 3
    assert len(report.duplicates) == 4
    assert len(report.dropped) == 7


def test_all_types_missing_raises():
    import tempfile, os
    with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False) as f:
        f.write("Spot Type,First Hour,Additional Hour,Daily Cap\n")
        f.write("Motorbike,10,5,60\n")
        path = f.name
    try:
        with pytest.raises(RateCardImportError):
            load_rate_cards(path)
    finally:
        os.unlink(path)


def test_unresolvable_header_raises():
    import tempfile, os
    with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False) as f:
        f.write("foo,bar,baz,qux\n1,2,3,4\n")
        path = f.name
    try:
        with pytest.raises(RateCardImportError):
            load_rate_cards(path)
    finally:
        os.unlink(path)


def test_garage_prices_correctly_from_cleaned_rates():
    """End-to-end: build a Garage off the messy CSV and confirm the fee
    math matches what the cleaned rates say it should."""
    from datetime import datetime

    garage = Garage.from_config_with_messy_rates(CONFIG, MESSY_CSV)
    assert garage.last_rate_import_report is not None
    assert len(garage.last_rate_import_report.used) == 3

    entry = datetime(2026, 1, 1, 9, 0)
    exit_ = datetime(2026, 1, 1, 11, 5)  # 2h5m -> 3 billable hours
    result = garage.check_in("KA01AB1234", VehicleType.COMPACT, entry_time=entry)
    out = garage.check_out("KA01AB1234", exit_time=exit_)
    # compact cleaned rate: 20 first hour + 2*10 = 40
    assert out.fee == 40.0
