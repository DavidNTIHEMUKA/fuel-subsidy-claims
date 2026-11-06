"""Create temporary test accounts (they stop working after --days).

Run from the fuel_subsidy folder, with the app stopped or running:

    python create_test_accounts.py            # valid 7 days
    python create_test_accounts.py --days 3

Fresh random passwords are generated on every run and printed once; they are
also written to test_accounts.csv so you can hand them out. Delete that file
after sharing. Running again replaces the passwords and the expiry date.
"""
import argparse
import csv

import pandas as pd

from engine import register as reg

OFFICERS = [
    ("rra.analyst", "RRA Analyst (test)"),
    ("rra.finance", "RRA Finance Officer (test)"),
]
# Fuel suppliers from the 14th submission (username = TIN)
SUPPLIERS = [
    ("100482874", "MEREZ PETROLEUM LTD"),
    ("122241160", "LUX Energies"),
    ("101835101", "VIVO Energy Ltd"),
    ("101928116", "MOUNT MERU PETROLEUM (RWANDA) Ltd"),
]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--days", type=int, default=7, help="how many days the accounts stay valid (default 7)")
    ap.add_argument("--out", default="test_accounts.csv")
    a = ap.parse_args()

    con = reg.connect()
    expires = pd.Timestamp.now().normalize() + pd.Timedelta(days=a.days, hours=23, minutes=59)
    rows = []
    for username, name in OFFICERS:
        pw = reg.make_password()
        reg.create_user(con, username, name, "officer", pw, expires_at=expires)
        rows.append(("RRA officer", name, username, pw))
    for tin, name in SUPPLIERS:
        pw = reg.make_password()
        reg.create_user(con, tin, name, "supplier", pw, tin=tin, expires_at=expires)
        rows.append(("Fuel supplier", name, tin, pw))

    with open(a.out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Role", "Name", "Username", "Password", "Valid until"])
        for r in rows:
            w.writerow([*r, f"{expires:%d/%m/%Y %H:%M}"])

    width = max(len(r[1]) for r in rows)
    print(f"\nTemporary accounts — valid until {expires:%d/%m/%Y %H:%M}\n")
    print(f"{'Role':<14} {'Name':<{width}}  {'Username':<12} Password")
    print("-" * (width + 42))
    for role, name, user, pw in rows:
        print(f"{role:<14} {name:<{width}}  {user:<12} {pw}")
    print(f"\nAlso saved to {a.out} — delete it after sharing the passwords.")
    print("Officers can create more accounts in the app: Home › Accounts.\n")


if __name__ == "__main__":
    main()
