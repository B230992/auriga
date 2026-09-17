# Parking Garage Attendant System

A check-in / check-out system for a multi-level parking garage: correct
tiered billing, spot-type aware allocation (compact / standard / EV),
instant "is a spot free?" and "where's my car?" lookups, a guarantee that
no spot is ever double-parked, and both a terminal console and a web UI
on top of the same logic.

Built generically — the number of levels, spots per type, and rates all
come from a config file, so this works for **any** garage, not one.

---

## 1. The problem, restated

An attendant needs to, all day, for any car:
- **Check it in** (assign it a spot, start the clock).
- **Check it out** (stop the clock, charge the right fee).
- Answer, instantly: **"is an EV spot free right now?"** and **"where is car X?"**
- Never let two cars land on the same spot.
- Never put an EV in a spot without a charger.
- Handle a full day's worth of cars without the lookups getting slow as the log grows.

## 2. How each requirement maps to the code

| Requirement | Where it's handled | How |
|---|---|---|
| Tiered pricing, part-hour rounds up, daily cap | `garage/pricing.py` (`PricingEngine`) | First hour at `first_hour` rate, every extra *billable* hour (`ceil`) at the cheaper `additional_hour` rate, capped at `daily_cap` per 24h window. Multi-day stays = `full_days * daily_cap + capped_fee(remaining_hours)`. |
| Spot types incl. "EV must get EV spot" | `garage/spot_manager.py` (`SpotManager`) | A `DEFAULT_FALLBACK_ORDER` table says which spot types each vehicle type may use, in priority order. EV's list is just `[EV]` — no fallback, so an EV can *only* ever be matched to an EV spot. Compact falls back to standard if compact is full (a small car fits a bigger space); standard doesn't fall back. |
| Never double-park a spot | `SpotManager.occupy_spot` | Checks `is_occupied` before assigning and raises `SpotAlreadyOccupiedError` otherwise. `Garage.check_in` also finds & confirms a free spot **before** opening a ticket, so a failed check-in never leaves a dangling ticket either. |
| "Is an EV spot free right now?" | `Garage.is_spot_type_available()` | O(1) — backed by a `set` of free spot-ids per spot type, not a scan over every spot. |
| "Where is car X?" | `Garage.find_car()` | O(1) — a `dict` keyed by plate, holding only currently-active tickets. |
| Log gets huge by evening | `garage/ticket_manager.py` (`TicketManager`) | Active tickets live in a small dict (`_active_by_plate`) — that's the hot path the attendant hits constantly. Closed tickets go to a separate append-only `_history` list, so the "is this car here?" lookup never has to scan the whole day's log. |
| Works for **any** garage | `Garage.from_config()` | Reads levels, spot counts per type, and the rate card per type from `data/config.json` — pure data, no code changes needed for a different garage. |

### The pricing rule, precisely
```
billable_hours = ceil(duration_minutes / 60), minimum 1
full_days, remaining_hours = divmod(billable_hours, 24)

day_fee(hours) = min(first_hour + max(hours-1, 0) * additional_hour, daily_cap)

total_fee = full_days * daily_cap + day_fee(remaining_hours)
```
Example (compact: first hour ₹20, +₹10/hr after, cap ₹120):
- 45 min → 1 hr billed → ₹20
- 2h 5m → 3 hr billed → 20 + 2×10 = ₹40
- 20 hours → would be ₹210 uncapped, capped to **₹120**
- 50 hours → 2 full days (2×120) + 2 remaining hours (20+10) = **₹270**

### The allocation rule, precisely
```
EV vehicle       -> [EV]                    (no fallback)
Compact vehicle  -> [Compact, Standard]      (fallback if compact full)
Standard vehicle -> [Standard]               (no fallback)
```
This is one table in `spot_manager.py` (`DEFAULT_FALLBACK_ORDER`) — change
the policy for a different garage in one place, no logic rewrites.

## 3. Project structure
```
parking-garage/
├── garage/
│   ├── models.py          # Spot, Vehicle, Ticket, enums — plain data holders
│   ├── pricing.py          # RateCard + PricingEngine (all fee math)
│   ├── spot_manager.py      # spot allocation / availability, O(1) lookups
│   ├── ticket_manager.py    # check-in/out lifecycle, O(1) plate lookup
│   ├── garage.py             # public facade (`Garage`) wiring it all together
│   └── exceptions.py
├── data/
│   └── config.json           # garage layout + rates — edit this for a new garage
├── cli.py                    # terminal attendant console
├── app.py                    # Flask web app (same Garage logic, HTTP + browser UI)
├── templates/index.html       # the web UI (garage-signage themed)
├── tests/                    # 27 pytest tests — pricing, allocation, end-to-end
├── requirements.txt
└── .gitignore
```

Layering: `models` (data) → `pricing` / `spot_manager` / `ticket_manager`
(single-responsibility engines) → `garage.py` (facade that composes them) →
`cli.py` / `app.py` (two interchangeable front-ends over the same facade).
This is what makes it trivial to add a third front-end (say, a REST API for
a mobile app) later without touching the core logic at all.

## 4. Setup & run (GitHub Codespaces)

```bash
# in the Codespace terminal
pip install -r requirements.txt

# confirm everything works
python -m pytest -v          # -> 27 passed

# terminal console
python cli.py

# OR the web UI
python app.py
```

For the web UI: Codespaces will pop up **"Your application running on
port 5000 is available"** — click **Open in Browser**. If you miss it,
open the **Ports** tab (next to Terminal) and click the globe icon on
port 5000.

CLI commands: `checkin <PLATE> <compact|standard|ev>`, `checkout <PLATE>`,
`status <PLATE>`, `available <type>`, `summary`, `active`, `history`, `exit`.

> Note: the CLI and the web app each start their own in-memory `Garage`
> (separate processes), so they don't share state — run one or the other
> for a given demo, not both at once expecting shared data.

## 5. Testing

```bash
python -m pytest -v
```
27 tests across three files:
- `tests/test_pricing.py` — rounding, tiers, daily cap, multi-day stacking, bad input.
- `tests/test_spot_manager.py` — EV never falls back, compact does, no double-occupancy, garage-full behaviour.
- `tests/test_garage.py` — full check-in/out flow, plate lookup, case-insensitive plates, double check-in rejected, failed check-in leaves no dangling ticket.

## 6. Scaling notes (why it stays fast as the day's log grows)
- Plate lookup and spot-type availability are both **O(1)**: a dict and a
  set, not a scan over every car or every spot.
- Closed tickets currently accumulate in memory for the day
  (`Garage.history()`). For a real deployment, swap the in-memory
  `_history` list in `ticket_manager.py` for a write to a database/log
  file at `close_ticket()` time — the O(1) active-ticket path is
  completely unaffected either way, since it never touches history.

## 7. Possible next steps
- Persist state (SQLite) so the garage survives a restart mid-day.
- A REST API + auth in front of `Garage` for a real multi-attendant deployment.
- Reservation / pre-booking of a spot.
- Time-of-day rate cards (peak / off-peak pricing).
- WebSocket push so the web UI's availability board updates live across multiple attendants, instead of polling on refresh.
