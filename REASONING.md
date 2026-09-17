# Reasoning Behind the Solution

## 1. Understanding the Problem

The main goal was to build a reusable parking garage system for an attendant.

The system needs to handle the complete parking lifecycle:

1. Check a vehicle in.
2. Assign a suitable and available parking spot.
3. Record when the vehicle entered.
4. Check the vehicle out.
5. Calculate the correct parking fee.
6. Free the parking spot.
7. Allow the attendant to quickly find a vehicle by its plate.
8. Check whether a particular type of parking spot is available.

The solution also needs to make sure that two vehicles can never occupy the same parking spot.

The system was designed generically so that the garage size, number of spots, spot types, and rates can be changed through configuration rather than changing the application logic.

---

## 2. Breaking the Problem Into Components

Instead of putting all the logic into one large file, the solution was divided into separate components.

The main components are:

- `models.py` — stores the basic data structures such as vehicles, spots, and tickets.
- `pricing.py` — contains all parking fee calculations.
- `spot_manager.py` — handles parking spot allocation and availability.
- `ticket_manager.py` — handles active and completed parking sessions.
- `garage.py` — acts as the main facade that connects the different components.
- `cli.py` — provides a terminal-based interface.
- `app.py` — provides the web interface and API.

This separation makes each part easier to understand, test, and modify independently.

---

## 3. Pricing Logic

The pricing rules were implemented separately in `PricingEngine`.

The important requirements were:

- The first hour has a specific rate.
- Every additional billable hour uses a cheaper rate.
- Partial hours are rounded up.
- A daily maximum prevents excessive charges.
- Stays longer than 24 hours continue using the daily cap correctly.

The calculation follows:

    billable_hours = ceil(duration_minutes / 60)

At least one hour is always charged.

The billable hours are then divided into complete 24-hour periods and the remaining hours.

For one 24-hour period:

    day_fee = min(
        first_hour_rate + (hours - 1) * additional_hour_rate,
        daily_cap
    )

For multiple days:

    total_fee = full_days * daily_cap + remaining_period_fee

Keeping the pricing logic in its own class means the rest of the application does not need to know how the fee is calculated.

---

## 4. Parking Spot Allocation

There are three main spot types:

- Compact
- Standard
- EV

The allocation rules were kept in one fallback-order table.

The current policy is:

    EV vehicle       -> EV only
    Compact vehicle  -> Compact, then Standard
    Standard vehicle -> Standard only

An EV vehicle cannot use a normal spot because it requires a charging spot.

A compact vehicle can use a standard spot if all compact spots are occupied.

A standard vehicle cannot fall back to another type.

This approach makes the allocation policy easy to change for another garage without rewriting the allocation algorithm.

---

## 5. Preventing Double Parking

A major requirement was that no two vehicles should ever receive the same spot.

Before occupying a spot, `SpotManager` checks whether it is already occupied.

If the spot is occupied, a `SpotAlreadyOccupiedError` is raised.

The check-in process also makes sure that a free spot has been successfully found before creating an active ticket.

This is important because a failed check-in should not leave behind an incomplete or dangling parking ticket.

---

## 6. Fast Lookups

The problem states that the parking log can become very large during the day.

Scanning every parking record whenever an attendant searches for a vehicle would become inefficient.

Therefore, two direct lookup structures were used.

### Finding a vehicle

Active tickets are stored using the vehicle plate as the key.

This allows:

    Garage.find_car()

to perform an O(1) lookup instead of scanning the complete history.

### Checking spot availability

Free spots are maintained in sets grouped by spot type.

Therefore, checking whether an EV spot is available does not require scanning every spot.

This provides an O(1) availability check.

Closed tickets are kept separately in history, so the active-ticket lookup remains small and efficient.

---

## 7. Garage Facade

`garage.py` provides the main `Garage` interface.

Instead of the CLI or web application directly managing pricing, spots, and tickets, they communicate with the `Garage` class.

For example:

    garage.check_in(...)
    garage.check_out(...)
    garage.find_car(...)
    garage.is_spot_type_available(...)

The Garage then coordinates the appropriate manager.

This keeps the business logic independent from the user interface.

Because of this design, both the CLI and Flask web application can use the same core parking logic.

---

## 8. Configuration and Reusability

The garage should not be designed for only one fixed building.

Therefore, garage configuration is stored in:

    data/config.json

The configuration contains information such as:

- Number of levels
- Number of spots
- Spot types
- Rate information

`Garage.from_config()` reads this information when creating a garage.

This means a different garage can be created by changing configuration data rather than changing the application logic.

---

# Twist 1 — T4: Messy Rate Card

## 9. Handling Messy Input Data

The rate card can contain inconsistent or invalid data.

A separate `rate_import.py` module was used to clean and validate the imported rate card before the rates are used for billing.

The importer handles issues such as:

- Currency symbols such as `₹`, `Rs.`, and `$`
- Thousands separators
- Extra whitespace
- Different capitalization
- Different spellings/punctuation of spot types
- Empty values
- `-`, `N/A`, and `null`
- The word `free`
- Numeric values stored as strings
- Duplicate rows
- Different header names
- BOM characters
- Blank or footer rows
- Unsupported spot types
- Negative rates
- Invalid relationships such as first-hour price being greater than the daily cap

Invalid data is rejected and recorded in the import report rather than silently guessing a value.

For duplicate valid rows, the first valid row is retained and later duplicates are recorded as ignored.

The cleaned rate cards are then passed to the normal pricing system.

This keeps data-cleaning logic separate from fee-calculation logic.

---

# Twist 2 — T2: Nightly Auto-Close

## 10. Simulated Clock

The nightly job needs to be testable without actually waiting 24 hours.

For this reason, the system uses `SimulatedClock` in `garage/clock.py`.

The application can:

- Read the current simulated time.
- Set the clock to an exact timestamp.
- Advance the clock by a number of hours.

The `/clock` endpoint is used to control this simulated time.

For example:

    POST /clock

with:

    {"advance_hours": 26}

moves the simulated time forward by 26 hours.

---

## 11. Auto-Close Logic

After the simulated clock is changed, the nightly job checks all active sessions.

Any session that has been parked for at least 24 hours is:

1. Automatically closed.
2. Billed using the same `PricingEngine`.
3. Removed from the active ticket collection.
4. Removed from its occupied spot.
5. Added to history.
6. Marked as `auto_closed = True`.
7. Marked as `closed_by = "nightly_job"`.

Using the same pricing engine for automatic checkout and normal checkout avoids having two different fee-calculation implementations.

The operation is also idempotent because once a ticket is closed, it is no longer an active ticket.

---

# Twist 3 — T6: Valet Plate Transfer

## 12. Transferring an Open Session

The valet hand-off requirement means an active parking session can be transferred from one plate to another.

For example:

    KA01AB1234 -> KA01ZZ9999

The important point is that the physical vehicle session does not move to another parking spot.

Therefore, the following information remains unchanged:

- Ticket ID
- Spot ID
- Entry time

Only the plate associated with the active session changes.

The `plate_history` field records the plates that the ticket has been associated with.

The `SpotManager` is not modified during a transfer because the physical parking spot has not changed.

---

## 13. Transfer Validation

The transfer operation rejects invalid situations such as:

- The old plate does not have an active ticket.
- The new plate is blank.
- The new plate is the same as the old plate.
- The new plate already belongs to another active parking session.

This prevents the transfer operation from creating conflicting active sessions.

---

# 14. Testing Strategy

Testing was performed at multiple levels.

The tests cover:

### Pricing

- Partial-hour rounding
- First-hour pricing
- Additional-hour pricing
- Daily cap
- Multi-day stays
- Invalid input

### Spot Management

- EV-only allocation
- Compact fallback to standard
- Double-occupancy prevention
- Full garage behaviour

### Garage Flow

- Check-in
- Check-out
- Plate lookup
- Case-insensitive plates
- Duplicate check-in
- Failed check-in cleanup

### T4

Tests verify that messy rate-card values are cleaned correctly and that the cleaned rates are actually used for billing.

### T2

Tests verify:

- Sessions under 24 hours remain active.
- Sessions over 24 hours are automatically closed.
- The correct fee is calculated.
- The spot becomes available again.
- Repeating the same clock request does not close the same ticket twice.
- Mixed active sessions are handled correctly.

### T6

Tests verify:

- Spot remains unchanged after transfer.
- Entry time remains unchanged.
- Plate history is maintained.
- Fee is calculated from the original entry time.
- Invalid transfers are rejected.

The project currently contains 57 tests covering the original functionality and the three additional twists.

---

# 15. Debugging Approach

The system was designed so that individual layers can be tested independently.

When a problem occurs, the first step is to run:

    python -m pytest -v

This helps determine whether the issue is related to:

- Pricing
- Spot allocation
- Ticket management
- Garage integration
- Rate importing
- Nightly jobs
- Transfers

For time-related issues, the simulated clock can be checked using:

    GET /api/clock

This helps distinguish a clock problem from a pricing calculation problem.

The CLI and web application use separate in-memory Garage instances, so their parking data is not shared when both are running as separate processes.

---

# 16. Design Decisions

The main design decisions were:

1. **Separate pricing from parking management**
   - Makes fee calculations easier to test.

2. **Separate spot management from ticket management**
   - A parking spot represents physical capacity.
   - A ticket represents a vehicle's parking session.

3. **Use dictionaries and sets for active lookups**
   - Avoids repeatedly scanning the entire parking history.

4. **Keep configuration outside the application logic**
   - Makes the system reusable for different garages.

5. **Use one pricing engine for both normal and automatic checkout**
   - Prevents different billing rules from being accidentally introduced.

6. **Keep transfer independent from spot allocation**
   - A valet plate transfer changes the paperwork, not the physical parking location.

7. **Keep CLI and web UI on top of the same Garage facade**
   - Allows additional frontends to be added without rewriting the core parking logic.

---

# 17. Possible Improvements

The current implementation keeps closed parking history in memory.

For a real production system, the history could be stored in a database such as SQLite.

Other possible future improvements include:

- REST API authentication
- Reservation/pre-booking
- Peak and off-peak pricing
- Persistent garage state
- Live availability updates using WebSockets

These improvements are not required for the current implementation but could make the system more suitable for a real multi-attendant deployment.

---

# 18. Final Result

The final solution provides a reusable parking garage system with:

- Correct tiered and capped billing
- Partial-hour rounding
- Multiple spot types
- EV-only parking
- No double-booking
- Fast plate lookup
- Fast spot availability lookup
- Messy rate-card import and validation
- Automatic 24-hour session closure
- Valet plate transfer
- CLI interface
- Flask web interface
- Automated test coverage

The core parking logic is kept independent from the user interfaces, making the system easier to test, maintain, and extend.