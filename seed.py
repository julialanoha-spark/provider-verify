"""
Seed dummy providers and pre-seeded verifications for demo purposes.
Run once after python app.py has been started (to create the DB).
"""
import sqlite3
import uuid
import os
from datetime import datetime, timedelta

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "verifications.db")

PROVIDERS = [
    {
        "npi": "1234567890",
        "name": "Dr. Maria Santos, MD",
        "practice": "Sunrise Internal Medicine",
        "email": "office@sunriseim.example.com",
        "phone": "(305) 555-0101",
        "specialty": "Internal Medicine",
        "zip_code": "33101",
    },
    {
        "npi": "2345678901",
        "name": "Dr. James Okafor, DO",
        "practice": "Gulf Coast Family Medicine",
        "email": "info@gulfcoastfm.example.com",
        "phone": "(713) 555-0202",
        "specialty": "Family Medicine",
        "zip_code": "77001",
    },
    {
        "npi": "3456789012",
        "name": "Dr. Linda Chu, MD",
        "practice": "Pacific Cardiology Associates",
        "email": "scheduling@pacificcardio.example.com",
        "phone": "(310) 555-0303",
        "specialty": "Cardiology",
        "zip_code": "90001",
    },
    {
        "npi": "4567890123",
        "name": "Riverside Medical Group",
        "practice": "Riverside Medical Group",
        "email": "contact@riversidemedgroup.example.com",
        "phone": "(305) 555-0404",
        "specialty": "Multi-specialty",
        "zip_code": "33133",
    },
    {
        "npi": "5678901234",
        "name": "Dr. Robert Patel, MD",
        "practice": "Desert Senior Care",
        "email": "drpatel@desertseniorcare.example.com",
        "phone": "(602) 555-0505",
        "specialty": "Geriatrics",
        "zip_code": "85001",
    },
]


def get_location(conn, zip_code):
    """Look up state, county, and FIPS from zip_counties table."""
    row = conn.execute(
        "SELECT state, county_name, fips_code FROM zip_counties WHERE zip_code = ? LIMIT 1",
        (zip_code,)
    ).fetchone()
    if row:
        return row["state"], row["county_name"], row["fips_code"]
    return "FL", "Unknown County", None


def get_sample_plans(conn, state, n=8):
    """Get a sample of MA plans for a given state."""
    rows = conn.execute(
        """SELECT contract_id, plan_id, segment_id, plan_name, carrier
           FROM plans
           WHERE state = ? AND contract_id LIKE 'H%'
           ORDER BY carrier, plan_name
           LIMIT ?""",
        (state, n)
    ).fetchall()
    return rows


def seed():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    # Insert providers
    inserted_providers = []
    for p in PROVIDERS:
        state, county_name, fips_code = get_location(conn, p["zip_code"])
        try:
            conn.execute(
                """INSERT INTO providers (npi, name, practice, email, phone, specialty,
                   zip_code, state, county_name, fips_code)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (p["npi"], p["name"], p["practice"], p["email"], p["phone"],
                 p["specialty"], p["zip_code"], state, county_name, fips_code)
            )
            provider_id = conn.execute(
                "SELECT id FROM providers WHERE npi = ?", (p["npi"],)
            ).fetchone()["id"]
            inserted_providers.append((provider_id, state))
            print(f"  Added provider: {p['name']} ({state}, {county_name})")
        except sqlite3.IntegrityError:
            provider_row = conn.execute(
                "SELECT id, state FROM providers WHERE npi = ?", (p["npi"],)
            ).fetchone()
            inserted_providers.append((provider_row["id"], provider_row["state"]))
            print(f"  Provider already exists: {p['name']}")

    conn.commit()

    # Pre-seed verifications with varied statuses for demo narrative
    statuses = ["Verified", "Declined", "Pending", "Verified", "Unknown"]
    days_ago = [7, 14, 3, 10, 30]

    for i, (provider_id, state) in enumerate(inserted_providers):
        plans = get_sample_plans(conn, state, n=3)
        if not plans:
            print(f"  No plans found for state {state}, skipping verifications")
            continue

        plan = plans[0]  # Use first plan for pre-seeded verification
        status = statuses[i % len(statuses)]
        days = days_ago[i % len(days_ago)]
        requested_at = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
        responded_at = None
        last_verified = None
        last_reviewed = None

        if status in ("Verified",):
            responded_at = (datetime.now() - timedelta(days=days - 1)).strftime("%Y-%m-%d %H:%M:%S")
            last_verified = responded_at
            last_reviewed = responded_at
        elif status == "Declined":
            responded_at = (datetime.now() - timedelta(days=days - 2)).strftime("%Y-%m-%d %H:%M:%S")

        token = str(uuid.uuid4())
        try:
            conn.execute(
                """INSERT INTO verifications
                   (provider_id, contract_id, plan_id_ref, segment_id, status,
                    requested_by, requested_at, responded_at, last_verified, last_reviewed, token)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (provider_id, plan["contract_id"], plan["plan_id"], plan["segment_id"],
                 status, "Demo Agent", requested_at, responded_at, last_verified, last_reviewed, token)
            )
            print(f"  Added verification: provider {provider_id} + {plan['plan_name'][:40]} → {status}")
        except sqlite3.IntegrityError:
            print(f"  Verification already exists for provider {provider_id}")

    conn.commit()
    conn.close()
    print("\nSeed complete.")


if __name__ == "__main__":
    seed()
