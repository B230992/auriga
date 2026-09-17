"""
Twist 1 (T4 - messy data): import a messy per-spot-type rate card and
price correctly from the cleaned rates.

Handles, per row:
  - Currency symbols and prefixes: "₹20", "Rs.20", "Rs 20", "$20"
  - Thousands separators: "1,200"
  - Stray whitespace: " 30 "
  - Case/punctuation variants of the spot type: "COMPACT", "e.v.", "EV"
  - Null-ish values: "", "-", "N/A", "n/a", "null", "None"
  - The word "free" -> 0
  - Floats-as-strings: "20.00"
  - Duplicate rows for the same spot type (first VALID occurrence wins,
    every later one is logged as an ignored duplicate)
  - Missing/aliased header names ("1st_hr", "extra_hour", "max_daily", ...)
  - Junk/blank rows, footer rows ("TOTAL,,,"), an unsupported spot type
    ("Motorbike"), a BOM on the first header cell
  - Negative rates and first_hour > daily_cap (both rejected, logged)

The cleaner never silently guesses a number it isn't confident about -
anything it can't parse is dropped and reported, not defaulted to 0 or
skipped silently.
"""
import csv
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

from .exceptions import RateCardImportError
from .models import SpotType
from .pricing import RateCard

# Column-name aliases a real export might use for each logical field.
HEADER_ALIASES: Dict[str, set] = {
    "spot_type": {"spot type", "type", "spot_type", "spottype"},
    "first_hour": {
        "first hour", "first_hour", "1st_hr", "first hour rate",
        "first_hour_rate", "firsthour",
    },
    "additional_hour": {
        "additional hour", "additional_hour", "extra_hour",
        "additional_hour_rate", "extrahour", "additionalhour",
    },
    "daily_cap": {"daily cap", "daily_cap", "cap", "max_daily", "dailycap"},
}

# Spot-type name aliases, normalized (lowercased, spaces/dots stripped)
# before comparison, so "EV", "ev", "e.v." and "Electric Vehicle" all match.
TYPE_ALIASES: Dict[str, SpotType] = {
    "compact": SpotType.COMPACT,
    "standard": SpotType.STANDARD,
    "ev": SpotType.EV,
    "e.v.": SpotType.EV,
    "electric": SpotType.EV,
    "electricvehicle": SpotType.EV,
}

NULLISH = {"", "-", "n/a", "na", "null", "none"}
_CURRENCY_RE = re.compile(r"[₹$]|(?i:rs\.?)")


@dataclass
class RowResult:
    row_number: int  # 1-indexed, matching the raw file (header = row 1)
    status: str  # "used" | "duplicate_ignored" | "dropped"
    spot_type: Optional[str] = None
    parsed: Optional[dict] = None
    reason: str = ""


@dataclass
class ImportReport:
    source: str = ""
    rows: List[RowResult] = field(default_factory=list)

    @property
    def used(self) -> List[RowResult]:
        return [r for r in self.rows if r.status == "used"]

    @property
    def dropped(self) -> List[RowResult]:
        return [r for r in self.rows if r.status == "dropped"]

    @property
    def duplicates(self) -> List[RowResult]:
        return [r for r in self.rows if r.status == "duplicate_ignored"]

    def as_lines(self) -> List[str]:
        lines = []
        for r in self.rows:
            if r.status == "used":
                lines.append(f"row {r.row_number}: OK  {r.spot_type:<8} -> {r.parsed}")
            elif r.status == "duplicate_ignored":
                lines.append(
                    f"row {r.row_number}: duplicate {r.spot_type} ignored "
                    f"(parsed {r.parsed}; first occurrence kept) - {r.reason}"
                )
            else:
                lines.append(f"row {r.row_number}: DROPPED - {r.reason}")
        return lines


def _clean_header_cell(name: str) -> str:
    return name.replace("\ufeff", "").strip().lower()


def _resolve_header(header_row: List[str]) -> Dict[str, int]:
    cleaned = [_clean_header_cell(h) for h in header_row]
    colmap: Dict[str, int] = {}
    for field_name, aliases in HEADER_ALIASES.items():
        for i, h in enumerate(cleaned):
            if h in aliases:
                colmap[field_name] = i
                break
    missing = [f for f in HEADER_ALIASES if f not in colmap]
    if missing:
        raise RateCardImportError(f"rate card header missing required column(s): {missing}")
    return colmap


def _clean_number(raw: str) -> Optional[float]:
    if raw is None:
        return None
    s = raw.strip()
    if s.lower() in NULLISH:
        return None
    if s.lower() == "free":
        return 0.0
    s = _CURRENCY_RE.sub("", s)
    s = s.replace(",", "").strip()
    if s == "":
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _clean_spot_type(raw: str) -> Optional[SpotType]:
    if raw is None:
        return None
    key = raw.strip().lower().replace(" ", "").replace(".", "")
    for alias, spot_type in TYPE_ALIASES.items():
        if key == alias.replace(" ", "").replace(".", ""):
            return spot_type
    return None


def load_rate_cards(path: Union[str, Path]) -> Tuple[Dict[SpotType, RateCard], ImportReport]:
    """
    Reads a messy rate-card CSV and returns (cleaned rates, audit report).

    Raises RateCardImportError if the header can't be resolved at all, or
    if after cleaning some spot type has no valid row (nothing usable to
    price it with).
    """
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f))

    if not rows:
        raise RateCardImportError(f"rate card file is empty: {path}")

    colmap = _resolve_header(rows[0])
    report = ImportReport(source=str(path))
    resolved: Dict[SpotType, RateCard] = {}

    def cell(row: List[str], field_name: str) -> str:
        i = colmap[field_name]
        return row[i] if i < len(row) else ""

    for row_number, row in enumerate(rows[1:], start=2):
        if not row or all((c or "").strip() == "" for c in row):
            report.rows.append(RowResult(row_number, "dropped", reason="blank row"))
            continue

        raw_type = cell(row, "spot_type")
        spot_type = _clean_spot_type(raw_type)
        if spot_type is None:
            report.rows.append(RowResult(
                row_number, "dropped",
                reason=f"unrecognized/unsupported spot type '{raw_type.strip()}'",
            ))
            continue

        fh = _clean_number(cell(row, "first_hour"))
        ah = _clean_number(cell(row, "additional_hour"))
        cap = _clean_number(cell(row, "daily_cap"))

        if fh is None or ah is None or cap is None:
            report.rows.append(RowResult(
                row_number, "dropped", spot_type=spot_type.value,
                reason="missing/unparseable numeric field",
            ))
            continue
        if fh < 0 or ah < 0 or cap < 0:
            report.rows.append(RowResult(
                row_number, "dropped", spot_type=spot_type.value,
                reason="negative rate",
            ))
            continue
        if fh > cap:
            report.rows.append(RowResult(
                row_number, "dropped", spot_type=spot_type.value,
                reason="first_hour exceeds daily_cap",
            ))
            continue

        parsed = {"first_hour": fh, "additional_hour": ah, "daily_cap": cap}

        if spot_type in resolved:
            report.rows.append(RowResult(
                row_number, "duplicate_ignored", spot_type=spot_type.value,
                parsed=parsed, reason=f"{spot_type.value} already set by an earlier row",
            ))
            continue

        resolved[spot_type] = RateCard(**parsed)
        report.rows.append(RowResult(row_number, "used", spot_type=spot_type.value, parsed=parsed))

    missing_types = [t.value for t in SpotType if t not in resolved]
    if missing_types:
        raise RateCardImportError(
            f"rate card has no valid entry for: {missing_types} "
            f"(after cleaning {len(rows) - 1} data row(s), see report for why each was dropped)"
        )

    return resolved, report
