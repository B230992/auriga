#!/usr/bin/env python3
"""
Interactive attendant console.

Run:  python cli.py
Optional custom config:  python cli.py --config path/to/config.json
Optional messy rate card: python cli.py --messy-rates data/rates_messy.csv
"""
import argparse
import sys
from datetime import datetime
from pathlib import Path

from garage.clock import SimulatedClock
from garage.exceptions import GarageError
from garage.garage import Garage
from garage.models import SpotType, VehicleType

DEFAULT_CONFIG = Path(__file__).parent / "data" / "config.json"

HELP = """
Commands:
  checkin <PLATE> <compact|standard|ev>   Check a car in
  checkout <PLATE>                        Check a car out and get the fee
  status <PLATE>                          Find a car / see its ticket
  available <compact|standard|ev>         Is a spot of this type free right now?
  summary                                 Free-spot counts for every type
  active                                  List every car currently parked
  history                                 List today's closed tickets
  transfer <OLD_PLATE> <NEW_PLATE>        Valet hand-off: move an open session to a new plate
  advance <HOURS>                         Fast-forward the clock by HOURS and run the nightly auto-close job
  rates                                   Show the rate-card cleaning report (only if --messy-rates was used)
  help                                    Show this message
  exit                                    Quit
"""


def money(x: float) -> str:
    return f"Rs.{x:.2f}"


def main():
    parser = argparse.ArgumentParser(description="Parking garage attendant console")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG), help="Path to garage config JSON")
    parser.add_argument("--messy-rates", default=None,
                         help="Path to a messy rate-card CSV to clean and price from (Twist 1)")
    args = parser.parse_args()

    clock = SimulatedClock()
    if args.messy_rates:
        garage = Garage.from_config_with_messy_rates(args.config, args.messy_rates, clock=clock)
        print(f"Garage loaded from {args.config}, rates cleaned from {args.messy_rates}")
        for line in garage.last_rate_import_report.as_lines():
            print(f"  {line}")
    else:
        garage = Garage.from_config(args.config, clock=clock)
        print(f"Garage loaded from {args.config}")
    print(HELP)

    while True:
        try:
            raw = input("attendant> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not raw:
            continue
        parts = raw.split()
        cmd = parts[0].lower()

        try:
            if cmd == "checkin" and len(parts) == 3:
                plate, vtype = parts[1], parts[2].lower()
                result = garage.check_in(plate, VehicleType(vtype))
                print(f"  OK  ticket={result.ticket.ticket_id} "
                      f"spot={result.spot.spot_id} plate={result.ticket.plate}")

            elif cmd == "checkout" and len(parts) == 2:
                plate = parts[1]
                result = garage.check_out(plate)
                print(f"  OK  ticket={result.ticket.ticket_id} "
                      f"duration={result.duration_minutes:.1f} min "
                      f"fee={money(result.fee)}")

            elif cmd == "status" and len(parts) == 2:
                ticket = garage.find_car(parts[1])
                if ticket is None:
                    print("  Not currently parked here.")
                else:
                    print(f"  {ticket.plate}: spot={ticket.spot_id} "
                          f"entry={ticket.entry_time} type={ticket.vehicle_type.value}")

            elif cmd == "available" and len(parts) == 2:
                stype = SpotType(parts[1].lower())
                free = garage.is_spot_type_available(stype)
                count = garage.spot_manager.count_available(stype)
                print(f"  {stype.value}: {'YES' if free else 'NO'} ({count} free)")

            elif cmd == "summary":
                for k, v in garage.availability_summary().items():
                    print(f"  {k:10s}: {v} free")

            elif cmd == "active":
                tickets = garage.active_tickets()
                print(f"  {len(tickets)} car(s) currently parked")
                for t in tickets:
                    print(f"   - {t.plate:10s} spot={t.spot_id} entry={t.entry_time}")

            elif cmd == "history":
                closed = garage.history()
                print(f"  {len(closed)} closed ticket(s) today")
                for t in closed:
                    tag = " [auto-closed]" if t.auto_closed else ""
                    print(f"   - {t.plate:10s} spot={t.spot_id} fee={money(t.fee)}{tag}")

            elif cmd == "transfer" and len(parts) == 3:
                old_plate, new_plate = parts[1], parts[2]
                ticket = garage.transfer_plate(old_plate, new_plate)
                print(f"  OK  {old_plate.upper()} -> {ticket.plate}  "
                      f"(spot={ticket.spot_id}, entry unchanged: {ticket.entry_time})")

            elif cmd == "advance" and len(parts) == 2:
                hours = float(parts[1])
                new_now = clock.advance(hours=hours)
                results = garage.run_nightly_job(now=new_now)
                print(f"  Clock advanced to {new_now}")
                if not results:
                    print("  Nightly job: nothing over 24h, nothing closed.")
                else:
                    print(f"  Nightly job auto-closed {len(results)} session(s):")
                    for r in results:
                        print(f"   - {r.ticket.plate:10s} spot={r.ticket.spot_id} fee={money(r.fee)}")

            elif cmd == "rates":
                if garage.last_rate_import_report is None:
                    print("  No messy rate card was loaded (run with --messy-rates to see this).")
                else:
                    for line in garage.last_rate_import_report.as_lines():
                        print(f"  {line}")

            elif cmd == "help":
                print(HELP)

            elif cmd == "exit":
                break

            else:
                print("  Unrecognised command. Type 'help'.")

        except GarageError as e:
            print(f"  ERROR: {e}")
        except ValueError as e:
            print(f"  ERROR: {e}")

    print("Bye.")


if __name__ == "__main__":
    sys.exit(main())
