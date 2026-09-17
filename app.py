#!/usr/bin/env python3
"""
Simple web UI for the parking garage - same Garage logic as cli.py,
just exposed over HTTP + a browser page instead of a terminal.

Run:  python app.py
Then open the forwarded port (Codespaces will prompt you), or
http://localhost:5000 locally.
"""
from pathlib import Path

from flask import Flask, jsonify, render_template, request

from garage.exceptions import GarageError
from garage.garage import Garage
from garage.models import SpotType, VehicleType

DEFAULT_CONFIG = Path(__file__).parent / "data" / "config.json"

app = Flask(__name__)
garage = Garage.from_config(DEFAULT_CONFIG)


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


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True, use_reloader=False)
