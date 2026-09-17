

Readme · MD
Parking Garage Attendant System
A check-in / check-out system for a multi-level parking garage: correct tiered billing, spot-type aware allocation (compact / standard / EV), instant "is a spot free?" and "where's my car?" lookups, a guarantee that no spot is ever double-parked, and both a terminal console and a web UI on top of the same logic.

Built generically — the number of levels, spots per type, and rates all come from a config file, so this works for any garage, not one.

1. The problem, restated
An attendant needs to, all day, for any car:

Check it in (assign it a spot, start the clock).
Check it out (stop the clock, charge the right fee).
Answer, instantly: "is an EV spot free right now?" and "where is car X?"
Never let two cars land on the same spot.
Never put an EV in a spot without a charger.
Handle a full day's worth of cars without the lookups getting slow as the log grows.
2. How each requirement maps to the code
Requirement	Where it's handled	How
Tiered pricing, part-hour rounds up, daily cap	garage/pricing.py (PricingEngine)	First hour at first_hour rate, every extra billable hour (ceil) at the cheaper additional_hour rate, capped at daily_cap per 24h window. Multi-day stays = full_days * daily_cap + capped_fee(remaining_hours).
Spot types incl. "EV must get EV spot"	garage/spot_manager.py (SpotManager)	A DEFAULT_FALLBACK_ORDER table says which spot types each vehicle type may use, in priority order. EV's list is just [EV] — no fallback, so an EV can only ever be matched to an EV spot. Compact falls back to standard if compact is full (a small car fits a bigger space); standard doesn't fall back.
Never double-park a spot	SpotManager.occupy_spot	Checks is_occupied before assigning and raises SpotAlreadyOccupiedError otherwise. Garage.check_in also finds & confirms a free spot before opening a ticket, so a failed check-in never leaves a dangling ticket either.
"Is an EV spot free right now?"	Garage.is_spot_type_available()	O(1) — backed by a set of free spot-ids per spot type, not a scan over every spot.
"Where is car X?"	Garage.find_car()	O(1) — a dict keyed by plate, holding only currently-active tickets.
Log gets huge by evening	garage/ticket_manager.py (TicketManager)	Active tickets live in a small dict (_active_by_plate) — that's the hot path the attendant hits constantly. Closed tickets go to a separate append-only _history list, so the "is this car here?" lookup never has to scan the whole day's log.
Works for any garage	Garage.from_config()	Reads levels, spot counts per type, and the rate card per type from data/config.json — pure data, no code changes needed for a different garage.
The pricing rule, precisely
billable_hours = ceil(duration_minutes / 60), minimum 1
full_days, remaining_hours = divmod(billable_hours, 24)

day_fee(hours) = min(first_hour + max(hours-1, 0) * additional_hour, daily_cap)

total_fee = full_days * daily_cap + day_fee(remaining_hours)
Example (compact: first hour ₹20, +₹10/hr after, cap ₹120):

45 min → 1 hr billed → ₹20
2h 5m → 3 hr billed → 20 + 2×10 = ₹40
20 hours → would be ₹210 uncapped, capped to ₹120
50 hours → 2 full days (2×120) + 2 remaining hours (20+10) = ₹270
The allocation rule, precisely
EV vehicle       -> [EV]                    (no fallback)
Compact vehicle  -> [Compact, Standard]      (fallback if compact full)
Standard vehicle -> [Standard]               (no fallback)
This is one table in spot_manager.py (DEFAULT_FALLBACK_ORDER) — change the policy for a different garage in one place, no logic rewrites.

3. Project structure
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
Layering: models (data) → pricing / spot_manager / ticket_manager (single-responsibility engines) → garage.py (facade that composes them) → cli.py / app.py (two interchangeable front-ends over the same facade). This is what makes it trivial to add a third front-end (say, a REST API for a mobile app) later without touching the core logic at all.

4. Setup & run (GitHub Codespaces)
bash
# in the Codespace terminal
pip install -r requirements.txt

# confirm everything works
python -m pytest -v          # -> 57 passed

# terminal console
python cli.py

# OR the web UI
python app.py
For the web UI: Codespaces will pop up "Your application running on port 5000 is available" — click Open in Browser. If you miss it, open the Ports tab (next to Terminal) and click the globe icon on port 5000.

CLI commands: checkin <PLATE> <compact|standard|ev>, checkout <PLATE>, status <PLATE>, available <type>, summary, active, history, exit.

Note: the CLI and the web app each start their own in-memory Garage (separate processes), so they don't share state — run one or the other for a given demo, not both at once expecting shared data.

5. API Endpoints
All endpoints are served by app.py (python app.py, default http://localhost:5000). The /api/* prefix is used for JSON data endpoints; / and /clock are the two exceptions.

Method	Path	Body	What it does
GET	/	—	Serves the web UI (templates/index.html).
POST	/api/checkin	{"plate": "...", "vehicle_type": "compact|standard|ev"}	Assigns a spot (EV-only for EV, compact falls back to standard), opens a ticket, starts the clock.
POST	/api/checkout	{"plate": "..."}	Closes the active ticket for that plate, computes the tiered/capped fee, frees the spot.
GET	/api/status/<plate>	—	"Where is car X?" — O(1) lookup of the active ticket for a plate, or {"parked": false}.
GET	/api/available/<spot_type>	—	"Is an EV spot free right now?" — availability + free count for compact|standard|ev.
GET	/api/summary	—	Free-spot counts for every spot type.
GET	/api/active	—	Every car currently parked.
GET	/api/history	—	Every closed ticket so far (includes fee, auto_closed, closed_by, plate_history).
POST	/api/transfer	{"from": "...", "to": "..."}	Twist 3 (T6): valet hand-off — moves an open session to a new plate; spot and entry time carry over unchanged.
GET	/api/clock	—	Read-only peek at the current simulated time (no side effects, does not run the nightly job).
POST	/clock	{"now": "<ISO8601>"} or {"advance_hours": N}	Twist 2 (T2): sets/advances the simulated clock and immediately runs the nightly auto-close job on every session parked ≥ 24h. Idempotent — re-posting the same instant closes nothing further.
6. Testing & debugging
bash
python -m pytest -v          # -> 57 passed
57 tests across six files:

tests/test_pricing.py — rounding, tiers, daily cap, multi-day stacking, bad input.
tests/test_spot_manager.py — EV never falls back, compact does, no double-occupancy, garage-full behaviour.
tests/test_garage.py — full check-in/out flow, plate lookup, case-insensitive plates, double check-in rejected, failed check-in leaves no dangling ticket.
tests/test_rate_import.py — messy rate card cleaning (Twist 1).
tests/test_nightly_job.py — nightly auto-close (Twist 2).
tests/test_transfer.py — valet hand-off (Twist 3).
Debugging tips:

python -m pytest -v isolates exactly which layer broke (pricing math vs. spot allocation vs. facade wiring) — start here before touching the running app.
The web app and CLI each start their own in-memory Garage — if /api/status/<plate> says "not parked" right after a CLI check-in, you're looking at two different processes' state, not a bug.
garage/clock.py's SimulatedClock is the single source of truth for every timestamp in app.py; if fees look off by an hour, check GET /api/clock first to see what the app currently thinks "now" is before suspecting the pricing math.
python cli.py --messy-rates data/rates_messy.csv prints the full rate-cleaning audit trail on startup (rates command re-prints it anytime) — use it to see exactly why any row was accepted, deduplicated, or dropped.
7. Scaling notes (why it stays fast as the day's log grows)
Plate lookup and spot-type availability are both O(1): a dict and a set, not a scan over every car or every spot.
Closed tickets currently accumulate in memory for the day (Garage.history()). For a real deployment, swap the in-memory _history list in ticket_manager.py for a write to a database/log file at close_ticket() time — the O(1) active-ticket path is completely unaffected either way, since it never touches history.
8. Twists (campus recruitment build round)
Twist 1 — T4, messy data: import a messy rate card
garage/rate_import.py (load_rate_cards) reads data/rates_messy.csv and returns cleaned RateCards plus a row-by-row ImportReport you can print (see cli.py rates command, or --messy-rates flag on startup).

Handles per row: currency symbols (₹, Rs., $), thousands commas ("1,200"), stray whitespace, case/punctuation in the spot-type name (COMPACT, e.v., EV ), null-ish values ("", -, N/A, null), the word "free" → 0, floats-as-strings, duplicate rows for a type (first valid row wins, later ones logged as ignored duplicates), header aliases (1st_hr, extra_hour, max_daily, ...), a BOM on the first header cell, blank/footer junk rows, and an unsupported spot type (Motorbike). Negative rates and first_hour > daily_cap are rejected too. Nothing is silently guessed — anything unparseable is dropped and logged with a reason.

Garage.from_config_with_messy_rates(layout_config, rates_csv_path) builds a garage whose layout still comes from config.json but whose rates come from the cleaned CSV; garage.last_rate_import_report holds the full audit trail. Set USE_MESSY_RATES = True at the top of app.py to boot the web UI this way, or run python cli.py --messy-rates data/rates_messy.csv.

Twist 2 — T2, automation: nightly auto-close, graded via POST /clock
garage/clock.py gives every timestamp in the system a single injected clock instead of calling datetime.now() directly. app.py runs on a SimulatedClock: between calls it ticks forward exactly like a real clock (so a normal demo — checking cars in/out minutes apart — behaves normally), but POST /clock lets a grader pin or fast-forward it exactly.

POST /clock
{"now": "2026-01-02T09:00:00"}     # pin to an exact instant
# or
{"advance_hours": 26}              # fast-forward by N hours
Either form immediately runs Garage.run_nightly_job(now=...), which auto-closes and bills (via the same PricingEngine, so multi-day tiering/caps apply identically) every active session parked >= 24h as of that instant, frees its spot, and marks ticket.auto_closed = True, ticket.closed_by = "nightly_job". Response:

json
{"ok": true, "now": "...", "count": 1,
 "closed": [{"plate": "...", "spot_id": "...", "fee": 160.0, "duration_minutes": 1620.0, ...}]}
Idempotent: an already-closed ticket is no longer "active", so posting the same (or an earlier) now again closes nothing further — covered by tests/test_nightly_job.py. From the CLI: advance <HOURS>.

Twist 3 — T6, lifecycle: valet hand-off (transfer an open session)
TicketManager.transfer_plate(old_plate, new_plate) (via Garage.transfer_plate) moves an open session to a different plate: same ticket_id, same spot_id, same entry_time — only the plate key changes. ticket.plate_history records every plate it's ever been under. The SpotManager is never touched, which is the proof this is implemented correctly (the car's physical spot doesn't move — only its paperwork does).

Rejects: old plate has no active ticket (TicketNotFoundError), new plate is blank or equal to the old one (InvalidTransferError), new plate already has an active ticket of its own (VehicleAlreadyParkedError).

POST /api/transfer
{"from": "KA01AB1234", "to": "KA01ZZ9999"}
CLI: transfer <OLD_PLATE> <NEW_PLATE>.

New test coverage
57 tests total (27 original + 30 new):

tests/test_rate_import.py — every junk category above, plus an end-to-end "garage prices correctly from cleaned rates" check.
tests/test_nightly_job.py — under/over 24h, spot freed for reuse, fee matches a manual checkout at the same instant, idempotency (same instant twice, and a later instant after already closed), mixed batches only close what's actually over threshold.
tests/test_transfer.py — spot/entry-time carry-over, fee computed from the original entry time, plate_history, all rejection cases.
9. Possible next steps
Persist state (SQLite) so the garage survives a restart mid-day.
A REST API + auth in front of Garage for a real multi-attendant deployment.
Reservation / pre-booking of a spot.
Time-of-day rate cards (peak / off-peak pricing).
WebSocket push so the web UI's availability board updates live across multiple attendants, instead of polling on refresh.















