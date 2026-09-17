#!/usr/bin/env python3
"""
Simple web UI for the parking garage - same Garage logic as cli.py,
just exposed over HTTP + a browser page instead of a terminal.

Run:  python app.py
Then open the forwarded port (Codespaces will prompt you), or
http://localhost:5000 locally.

The garage runs on a SimulatedClock (garage/clock.py): between calls to
POST /clock it ticks forward exactly like a real clock, so normal
check-in/check-out during a demo behaves normally. POST /clock lets a
grader pin or fast-forward time exactly, which is what makes the
nightly auto-close job (Twist 2) deterministically testable.
"""
from datetime import datetime
from pathlib import Path

from flask import Flask, jsonify, render_template, request

from garage.clock import SimulatedClock
from garage.exceptions import (
    GarageError,
    InvalidTransferError,
    TicketNotFoundError,
    VehicleAlreadyParkedError,
)
from garage.garage import Garage
from garage.models import SpotType, VehicleType

DEFAULT_CONFIG = Path(__file__).parent / "data" / "config.json"
MESSY_RATES_CSV = Path(__file__).parent / "data" / "rates_messy.csv"

app = Flask(__name__)

clock = SimulatedClock()

# Set USE_MESSY_RATES = True to boot the garage pricing from the cleaned
# messy-CSV import (Twist 1) instead of data/config.json's rates.
USE_MESSY_RATES = False
if USE_MESSY_RATES:
    garage = Garage.from_config_with_messy_rates(DEFAULT_CONFIG, MESSY_RATES_CSV, clock=clock)
else:
    garage = Garage.from_config(DEFAULT_CONFIG, clock=clock)


def ticket_json(t):
    return {
        "ticket_id": t.ticket_id,
        "plate": t.plate,
        "vehicle_type": t.vehicle_type.value,
        "spot_id": t.spot_id,
        "entry_time": t.entry_time.isoformat(sep=" ", timespec="seconds"),
        "exit_time": t.exit_time.isoformat(sep=" ", timespec="seconds") if t.exit_time else None,
        "fee": t.fee,
        "status": t.status.value,
        "closed_by": t.closed_by,
        "auto_closed": t.auto_closed,
        "plate_history": t.plate_history,
    }


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/checkin", methods=["POST"])
def api_checkin():
    data = request.get_json(force=True)
    plate = (data.get("plate") or "").strip()
    vtype = (data.get("vehicle_type") or "").strip().lower()
    if not plate or vtype not in [v.value for v in VehicleType]:
        return jsonify({"ok": False, "error": "plate and a valid vehicle_type are required"}), 400
    try:
        result = garage.check_in(plate, VehicleType(vtype))
        return jsonify({
            "ok": True,
            "ticket": ticket_json(result.ticket),
            "spot_id": result.spot.spot_id,
        })
    except GarageError as e:
        return jsonify({"ok": False, "error": str(e)}), 409


@app.route("/api/checkout", methods=["POST"])
def api_checkout():
    data = request.get_json(force=True)
    plate = (data.get("plate") or "").strip()
    if not plate:
        return jsonify({"ok": False, "error": "plate is required"}), 400
    try:
        result = garage.check_out(plate)
        return jsonify({
            "ok": True,
            "ticket": ticket_json(result.ticket),
            "fee": result.fee,
            "duration_minutes": round(result.duration_minutes, 1),
        })
    except GarageError as e:
        return jsonify({"ok": False, "error": str(e)}), 404


@app.route("/api/status/<plate>")
def api_status(plate):
    ticket = garage.find_car(plate)
    if ticket is None:
        return jsonify({"ok": True, "parked": False})
    return jsonify({"ok": True, "parked": True, "ticket": ticket_json(ticket)})


@app.route("/api/available/<spot_type>")
def api_available(spot_type):
    try:
        st = SpotType(spot_type.lower())
    except ValueError:
        return jsonify({"ok": False, "error": "invalid spot type"}), 400
    return jsonify({
        "ok": True,
        "spot_type": st.value,
        "available": garage.is_spot_type_available(st),
        "count": garage.spot_manager.count_available(st),
    })


@app.route("/api/summary")
def api_summary():
    return jsonify({"ok": True, "summary": garage.availability_summary()})


@app.route("/api/active")
def api_active():
    return jsonify({"ok": True, "tickets": [ticket_json(t) for t in garage.active_tickets()]})


@app.route("/api/history")
def api_history():
    return jsonify({"ok": True, "tickets": [ticket_json(t) for t in garage.history()]})


@app.route("/api/clock")
def api_clock_readonly():
    """Read-only peek at the current simulated time - does NOT run the
    nightly job (that only happens on POST /clock). Used by the UI to
    display 'now' without side effects on every page refresh."""
    return jsonify({"ok": True, "now": clock.now().isoformat(sep=" ", timespec="seconds")})


# ---------- Twist 3: valet hand-off ----------
@app.route("/api/transfer", methods=["POST"])
def api_transfer():
    data = request.get_json(force=True) or {}
    old_plate = (data.get("from") or "").strip()
    new_plate = (data.get("to") or "").strip()
    if not old_plate or not new_plate:
        return jsonify({"ok": False, "error": "'from' and 'to' plates are required"}), 400
    try:
        ticket = garage.transfer_plate(old_plate, new_plate)
        return jsonify({"ok": True, "ticket": ticket_json(ticket)})
    except TicketNotFoundError as e:
        return jsonify({"ok": False, "error": str(e)}), 404
    except InvalidTransferError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    except VehicleAlreadyParkedError as e:
        return jsonify({"ok": False, "error": str(e)}), 409


# ---------- Twist 2: nightly auto-close, graded via POST /clock ----------
@app.route("/clock", methods=["POST"])
def api_clock():
    """
    Body: {"now": "<ISO8601>"}  -> pin the clock to an exact instant, OR
          {"advance_hours": N}  -> fast-forward by N hours (float ok)

    Either way, immediately runs the nightly auto-close job at the new
    "now" and returns what it closed. Idempotent: posting the same "now"
    twice (or a `now` <= the last one) closes nothing the second time,
    since an already-closed ticket is no longer active.
    """
    data = request.get_json(force=True) or {}

    if "now" in data:
        try:
            new_now = datetime.fromisoformat(data["now"])
        except (ValueError, TypeError):
            return jsonify({"ok": False, "error": "'now' must be a valid ISO8601 timestamp"}), 400
        clock.set(new_now)
    elif "advance_hours" in data:
        try:
            hours = float(data["advance_hours"])
        except (TypeError, ValueError):
            return jsonify({"ok": False, "error": "'advance_hours' must be numeric"}), 400
        clock.advance(hours=hours)
    else:
        return jsonify({"ok": False, "error": "provide either 'now' (ISO8601) or 'advance_hours'"}), 400

    current_now = clock.now()
    results = garage.run_nightly_job(now=current_now)

    closed = [{
        "plate": r.ticket.plate,
        "spot_id": r.ticket.spot_id,
        "entry_time": r.ticket.entry_time.isoformat(sep=" ", timespec="seconds"),
        "exit_time": r.ticket.exit_time.isoformat(sep=" ", timespec="seconds"),
        "duration_minutes": round(r.duration_minutes, 1),
        "fee": r.fee,
    } for r in results]

    return jsonify({
        "ok": True,
        "now": current_now.isoformat(sep=" ", timespec="seconds"),
        "closed": closed,
        "count": len(closed),
    })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True, use_reloader=False)
