import sqlite3
import uuid
import re
import shutil
import os
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, jsonify, flash

app = Flask(__name__)
app.secret_key = "dev-secret-key-change-in-prod"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "verifications.db")
INGESTION_DB_PATH = "/Users/julialanoha/Desktop/ingestion.db"


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    """Create app tables and copy plan data from ingestion.db if needed."""
    conn = get_db()

    # Create providers + verifications tables
    with open(os.path.join(BASE_DIR, "schema.sql")) as f:
        conn.executescript(f.read())

    # Copy plan tables from ingestion.db if not already present
    if os.path.exists(INGESTION_DB_PATH):
        plan_count = conn.execute(
            "SELECT count(*) FROM sqlite_master WHERE type='table' AND name='plans'"
        ).fetchone()[0]

        if plan_count == 0:
            print("Copying plan data from ingestion.db...")
            conn.execute(f"ATTACH DATABASE '{INGESTION_DB_PATH}' AS src")
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS plans AS SELECT * FROM src.plans;
                CREATE TABLE IF NOT EXISTS plan_counties AS SELECT * FROM src.plan_counties;
                CREATE TABLE IF NOT EXISTS zip_counties AS SELECT * FROM src.zip_counties;
            """)
            conn.execute("DETACH DATABASE src")
            print("Plan data copied.")
    else:
        # Create empty stubs so the app doesn't crash without ingestion.db
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS plans (
                contract_id TEXT, plan_id TEXT, segment_id TEXT,
                plan_name TEXT, carrier TEXT, state TEXT,
                sb_url TEXT, eoc_url TEXT
            );
            CREATE TABLE IF NOT EXISTS plan_counties (
                contract_id TEXT, plan_id TEXT, segment_id TEXT,
                state TEXT, county_name TEXT, fips_code TEXT
            );
            CREATE TABLE IF NOT EXISTS zip_counties (
                zip_code TEXT, fips_code TEXT, state TEXT, county_name TEXT, pct_pop REAL
            );
        """)
        print(f"WARNING: {INGESTION_DB_PATH} not found. Plan data unavailable.")

    conn.commit()
    conn.close()


def extract_plan_type(plan_name):
    """Extract plan type abbreviation from plan name, e.g. '(HMO)' → 'HMO'."""
    match = re.search(r'\(([^)]+)\)\s*$', plan_name or "")
    return match.group(1) if match else "MA"


# ---------------------------------------------------------------------------
# Agent routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/provider-search")
def provider_search():
    """Path A: search by provider name or NPI."""
    return render_template("index.html", mode="provider")


@app.route("/plan-search")
def plan_search():
    """Path B: search by ZIP to find MA plans."""
    zip_code = request.args.get("zip", "").strip()
    plans = []
    zip_info = None

    if zip_code:
        conn = get_db()
        zip_info = conn.execute(
            "SELECT state, county_name, fips_code FROM zip_counties WHERE zip_code = ? LIMIT 1",
            (zip_code,)
        ).fetchone()

        if zip_info:
            plans = conn.execute(
                """SELECT DISTINCT p.contract_id, p.plan_id, p.segment_id,
                          p.plan_name, p.carrier, p.state
                   FROM plans p
                   JOIN plan_counties pc
                     ON p.contract_id = pc.contract_id
                    AND p.plan_id = pc.plan_id
                    AND p.segment_id = pc.segment_id
                   WHERE pc.fips_code = ? AND p.contract_id LIKE 'H%'
                   ORDER BY p.carrier, p.plan_name""",
                (zip_info["fips_code"],)
            ).fetchall()
        conn.close()

    return render_template("plan_search.html", plans=plans, zip_code=zip_code,
                           zip_info=zip_info)


@app.route("/provider/<npi>")
def provider_detail(npi):
    """Path A: provider profile with all state MA plans + verification status."""
    conn = get_db()
    provider = conn.execute(
        "SELECT * FROM providers WHERE npi = ?", (npi,)
    ).fetchone()

    if not provider:
        conn.close()
        flash("Provider not found.", "danger")
        return redirect(url_for("index"))

    # All MA plans in the provider's state with verification status overlay
    plans = conn.execute(
        """SELECT p.contract_id, p.plan_id, p.segment_id,
                  p.plan_name, p.carrier, p.state,
                  v.id AS ver_id, v.status, v.last_verified, v.last_reviewed,
                  v.requested_at, v.token
           FROM plans p
           LEFT JOIN verifications v
             ON v.provider_id = ?
            AND v.contract_id = p.contract_id
            AND v.plan_id_ref = p.plan_id
            AND v.segment_id = p.segment_id
           WHERE p.state = ? AND p.contract_id LIKE 'H%'
           ORDER BY p.carrier, p.plan_name""",
        (provider["id"], provider["state"])
    ).fetchall()

    carriers = sorted(set(p["carrier"] for p in plans))
    conn.close()
    return render_template("provider_detail.html", provider=provider,
                           plans=plans, carriers=carriers)


@app.route("/plan/<contract_id>/<plan_id>/<segment_id>")
def plan_detail(contract_id, plan_id, segment_id):
    """Path B: plan detail page with provider search for verification."""
    conn = get_db()
    plan = conn.execute(
        "SELECT * FROM plans WHERE contract_id=? AND plan_id=? AND segment_id=?",
        (contract_id, plan_id, segment_id)
    ).fetchone()

    if not plan:
        conn.close()
        flash("Plan not found.", "danger")
        return redirect(url_for("index"))

    # Providers with existing verifications for this plan
    verified_providers = conn.execute(
        """SELECT p.*, v.status, v.last_verified, v.last_reviewed, v.requested_at
           FROM providers p
           JOIN verifications v ON v.provider_id = p.id
           WHERE v.contract_id = ? AND v.plan_id_ref = ? AND v.segment_id = ?
           ORDER BY v.status, p.name""",
        (contract_id, plan_id, segment_id)
    ).fetchall()

    conn.close()
    return render_template("plan_detail.html", plan=plan,
                           verified_providers=verified_providers,
                           plan_type=extract_plan_type(plan["plan_name"]))


@app.route("/verify", methods=["POST"])
def verify():
    """Create a verification request."""
    provider_npi = request.form.get("provider_npi", "").strip()
    contract_id = request.form.get("contract_id", "").strip()
    plan_id_ref = request.form.get("plan_id", "").strip()
    segment_id = request.form.get("segment_id", "0").strip()
    requested_by = request.form.get("requested_by", "Agent").strip()

    conn = get_db()
    provider = conn.execute(
        "SELECT * FROM providers WHERE npi = ?", (provider_npi,)
    ).fetchone()
    plan = conn.execute(
        "SELECT * FROM plans WHERE contract_id=? AND plan_id=? AND segment_id=?",
        (contract_id, plan_id_ref, segment_id)
    ).fetchone()

    if not provider or not plan:
        conn.close()
        flash("Provider or plan not found.", "danger")
        return redirect(url_for("index"))

    # Check if verification already exists
    existing = conn.execute(
        """SELECT * FROM verifications
           WHERE provider_id=? AND contract_id=? AND plan_id_ref=? AND segment_id=?""",
        (provider["id"], contract_id, plan_id_ref, segment_id)
    ).fetchone()

    if existing:
        conn.close()
        flash(f"A verification for this provider + plan already exists (status: {existing['status']}).", "warning")
        return redirect(url_for("email_preview", ver_id=existing["id"]))

    token = str(uuid.uuid4())
    conn.execute(
        """INSERT INTO verifications
           (provider_id, contract_id, plan_id_ref, segment_id, status, requested_by, token)
           VALUES (?,?,?,?,?,?,?)""",
        (provider["id"], contract_id, plan_id_ref, segment_id, "Pending", requested_by, token)
    )
    conn.commit()

    ver = conn.execute(
        "SELECT id FROM verifications WHERE token = ?", (token,)
    ).fetchone()
    conn.close()

    return redirect(url_for("email_preview", ver_id=ver["id"]))


@app.route("/email-preview/<int:ver_id>")
def email_preview(ver_id):
    conn = get_db()
    ver = conn.execute(
        """SELECT v.*, p.name AS provider_name, p.practice, p.email AS provider_email,
                  p.npi, p.specialty, p.state AS provider_state,
                  pl.plan_name, pl.carrier, pl.plan_id AS cms_plan_id,
                  pl.contract_id AS cms_contract_id
           FROM verifications v
           JOIN providers p ON p.id = v.provider_id
           JOIN plans pl ON pl.contract_id = v.contract_id
                        AND pl.plan_id = v.plan_id_ref
                        AND pl.segment_id = v.segment_id
           WHERE v.id = ?""",
        (ver_id,)
    ).fetchone()
    conn.close()

    if not ver:
        flash("Verification not found.", "danger")
        return redirect(url_for("dashboard"))

    portal_url = url_for("provider_portal", token=ver["token"], _external=True)
    return render_template("email_preview.html", ver=ver, portal_url=portal_url)


@app.route("/dashboard")
def dashboard():
    status_filter = request.args.get("status", "all")
    conn = get_db()

    query = """
        SELECT v.*, p.name AS provider_name, p.npi, p.specialty, p.state AS provider_state,
               pl.plan_name, pl.carrier
        FROM verifications v
        JOIN providers p ON p.id = v.provider_id
        JOIN plans pl ON pl.contract_id = v.contract_id
                     AND pl.plan_id = v.plan_id_ref
                     AND pl.segment_id = v.segment_id
    """
    params = []
    if status_filter != "all":
        query += " WHERE v.status = ?"
        params.append(status_filter)
    query += " ORDER BY v.requested_at DESC"

    verifications = conn.execute(query, params).fetchall()
    counts = conn.execute(
        """SELECT status, COUNT(*) as n FROM verifications GROUP BY status"""
    ).fetchall()
    conn.close()

    count_map = {row["status"]: row["n"] for row in counts}
    total = sum(count_map.values())
    return render_template("dashboard.html", verifications=verifications,
                           status_filter=status_filter, count_map=count_map,
                           total=total)


@app.route("/network")
def network():
    """Filter providers by plan."""
    selected_plan_key = request.args.get("plan_key", "")
    state_filter = request.args.get("state", "")

    conn = get_db()

    # Get distinct states for filter
    states = [r[0] for r in conn.execute(
        "SELECT DISTINCT state FROM plans WHERE contract_id LIKE 'H%' ORDER BY state"
    ).fetchall()]

    # Build plan list for dropdown (filtered by state if provided)
    plan_query = """SELECT DISTINCT contract_id || '|' || plan_id || '|' || segment_id AS plan_key,
                           plan_name, carrier, state
                    FROM plans WHERE contract_id LIKE 'H%'"""
    plan_params = []
    if state_filter:
        plan_query += " AND state = ?"
        plan_params.append(state_filter)
    plan_query += " ORDER BY carrier, plan_name LIMIT 500"
    all_plans = conn.execute(plan_query, plan_params).fetchall()

    providers = []
    selected_plan = None
    if selected_plan_key:
        parts = selected_plan_key.split("|")
        if len(parts) == 3:
            contract_id, plan_id, segment_id = parts
            selected_plan = conn.execute(
                "SELECT * FROM plans WHERE contract_id=? AND plan_id=? AND segment_id=?",
                (contract_id, plan_id, segment_id)
            ).fetchone()
            providers = conn.execute(
                """SELECT p.*, v.status, v.last_verified, v.last_reviewed, v.requested_at
                   FROM providers p
                   JOIN verifications v ON v.provider_id = p.id
                   WHERE v.contract_id=? AND v.plan_id_ref=? AND v.segment_id=?
                   ORDER BY v.status, p.name""",
                (contract_id, plan_id, segment_id)
            ).fetchall()

    conn.close()
    return render_template("network_status.html", all_plans=all_plans,
                           selected_plan_key=selected_plan_key,
                           selected_plan=selected_plan,
                           providers=providers, states=states,
                           state_filter=state_filter)


# ---------------------------------------------------------------------------
# Provider portal routes
# ---------------------------------------------------------------------------

@app.route("/portal/<token>")
def provider_portal(token):
    conn = get_db()
    ver = conn.execute(
        """SELECT v.*, p.name AS provider_name, p.practice, p.npi,
                  p.specialty, p.state AS provider_state, p.id AS provider_id,
                  pl.plan_name, pl.carrier, pl.plan_id AS cms_plan_id,
                  pl.contract_id AS cms_contract_id
           FROM verifications v
           JOIN providers p ON p.id = v.provider_id
           JOIN plans pl ON pl.contract_id = v.contract_id
                        AND pl.plan_id = v.plan_id_ref
                        AND pl.segment_id = v.segment_id
           WHERE v.token = ?""",
        (token,)
    ).fetchone()

    if not ver:
        conn.close()
        return render_template("portal_invalid.html"), 404

    provider_id = ver["provider_id"]
    provider_state = ver["provider_state"]

    # Step 2: previously verified plans
    verified_plans = conn.execute(
        """SELECT v.*, pl.plan_name, pl.carrier, pl.plan_id AS cms_plan_id
           FROM verifications v
           JOIN plans pl ON pl.contract_id = v.contract_id
                        AND pl.plan_id = v.plan_id_ref
                        AND pl.segment_id = v.segment_id
           WHERE v.provider_id = ? AND v.status = 'Verified'
             AND NOT (v.contract_id = ? AND v.plan_id_ref = ? AND v.segment_id = ?)
           ORDER BY v.last_verified DESC""",
        (provider_id, ver["contract_id"], ver["plan_id_ref"], ver["segment_id"])
    ).fetchall()

    # Bulk update last_reviewed for all verified plans on portal visit
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute(
        """UPDATE verifications SET last_reviewed = ?
           WHERE provider_id = ? AND status = 'Verified'""",
        (now, provider_id)
    )
    conn.commit()

    # Step 3: all MA plans in state, grouped by carrier
    all_state_plans = conn.execute(
        """SELECT p.contract_id, p.plan_id, p.segment_id, p.plan_name, p.carrier,
                  v.status AS ver_status, v.last_verified
           FROM plans p
           LEFT JOIN verifications v
             ON v.provider_id = ?
            AND v.contract_id = p.contract_id
            AND v.plan_id_ref = p.plan_id
            AND v.segment_id = p.segment_id
           WHERE p.state = ? AND p.contract_id LIKE 'H%'
           ORDER BY p.carrier, p.plan_name""",
        (provider_id, provider_state)
    ).fetchall()

    # Group by carrier
    carriers = {}
    for p in all_state_plans:
        carriers.setdefault(p["carrier"], []).append(p)

    conn.close()
    return render_template("provider_portal.html", ver=ver, token=token,
                           verified_plans=verified_plans,
                           carriers=carriers)


@app.route("/portal/<token>/respond", methods=["POST"])
def portal_respond(token):
    conn = get_db()
    ver = conn.execute(
        """SELECT v.*, p.id AS provider_id, p.state AS provider_state
           FROM verifications v JOIN providers p ON p.id = v.provider_id
           WHERE v.token = ?""",
        (token,)
    ).fetchone()

    if not ver:
        conn.close()
        return render_template("portal_invalid.html"), 404

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    provider_id = ver["provider_id"]
    provider_state = ver["provider_state"]

    # Step 1: response for the requested plan
    step1_response = request.form.get("step1_response")
    if step1_response in ("Verified", "Declined"):
        last_verified = now if step1_response == "Verified" else None
        conn.execute(
            """UPDATE verifications SET status=?, responded_at=?, last_verified=?
               WHERE token=?""",
            (step1_response, now, last_verified, token)
        )

    # Step 2: updates to previously verified plans
    for key, value in request.form.items():
        if key.startswith("update_ver_"):
            ver_id = key.replace("update_ver_", "")
            if value in ("Verified", "Declined"):
                last_verified = now if value == "Verified" else None
                conn.execute(
                    """UPDATE verifications SET status=?, responded_at=?, last_verified=?
                       WHERE id=? AND provider_id=?""",
                    (value, now, last_verified, ver_id, provider_id)
                )

    # Step 3: new plans accepted by provider
    for key in request.form:
        if key.startswith("accept_plan_"):
            parts = key.replace("accept_plan_", "").split("|")
            if len(parts) == 3:
                c_id, p_id, s_id = parts
                # Check if verification already exists
                existing = conn.execute(
                    """SELECT id FROM verifications
                       WHERE provider_id=? AND contract_id=? AND plan_id_ref=? AND segment_id=?""",
                    (provider_id, c_id, p_id, s_id)
                ).fetchone()
                if existing:
                    conn.execute(
                        """UPDATE verifications SET status='Verified', responded_at=?,
                                  last_verified=?, last_reviewed=?
                           WHERE id=?""",
                        (now, now, now, existing["id"])
                    )
                else:
                    new_token = str(uuid.uuid4())
                    conn.execute(
                        """INSERT INTO verifications
                           (provider_id, contract_id, plan_id_ref, segment_id,
                            status, requested_by, responded_at, last_verified, last_reviewed, token)
                           VALUES (?,?,?,?,'Verified','Provider Portal',?,?,?,?)""",
                        (provider_id, c_id, p_id, s_id, now, now, now, new_token)
                    )

    conn.commit()
    conn.close()

    flash("Thank you! Your plan participation status has been recorded.", "success")
    return redirect(url_for("portal_complete", token=token))


@app.route("/portal/<token>/complete")
def portal_complete(token):
    conn = get_db()
    ver = conn.execute(
        """SELECT v.*, p.name AS provider_name, p.practice,
                  pl.plan_name, pl.carrier
           FROM verifications v
           JOIN providers p ON p.id = v.provider_id
           JOIN plans pl ON pl.contract_id = v.contract_id
                        AND pl.plan_id = v.plan_id_ref
                        AND pl.segment_id = v.segment_id
           WHERE v.token = ?""",
        (token,)
    ).fetchone()

    # Count total verified plans for this provider
    verified_count = 0
    if ver:
        row = conn.execute(
            "SELECT COUNT(*) as n FROM verifications WHERE provider_id=? AND status='Verified'",
            (ver["provider_id"],)
        ).fetchone()
        verified_count = row["n"] if row else 0

    conn.close()
    return render_template("portal_complete.html", ver=ver, verified_count=verified_count)


# ---------------------------------------------------------------------------
# API routes
# ---------------------------------------------------------------------------

@app.route("/api/providers/search")
def api_providers_search():
    q = request.args.get("q", "").strip()
    if len(q) < 2:
        return jsonify([])
    conn = get_db()
    results = conn.execute(
        """SELECT npi, name, practice, specialty, state, zip_code
           FROM providers
           WHERE name LIKE ? OR npi LIKE ?
           LIMIT 10""",
        (f"%{q}%", f"%{q}%")
    ).fetchall()
    conn.close()
    return jsonify([dict(r) for r in results])


@app.route("/api/plans/by-zip/<zip_code>")
def api_plans_by_zip(zip_code):
    conn = get_db()
    zip_info = conn.execute(
        "SELECT state, county_name, fips_code FROM zip_counties WHERE zip_code = ? LIMIT 1",
        (zip_code,)
    ).fetchone()
    if not zip_info:
        conn.close()
        return jsonify({"error": "ZIP code not found", "plans": []})

    plans = conn.execute(
        """SELECT DISTINCT p.contract_id, p.plan_id, p.segment_id,
                  p.plan_name, p.carrier, p.state
           FROM plans p
           JOIN plan_counties pc
             ON p.contract_id = pc.contract_id
            AND p.plan_id = pc.plan_id
            AND p.segment_id = pc.segment_id
           WHERE pc.fips_code = ? AND p.contract_id LIKE 'H%'
           ORDER BY p.carrier, p.plan_name""",
        (zip_info["fips_code"],)
    ).fetchall()
    conn.close()

    return jsonify({
        "zip_code": zip_code,
        "state": zip_info["state"],
        "county": zip_info["county_name"],
        "plans": [dict(p) for p in plans]
    })


# ---------------------------------------------------------------------------
# Dev utilities
# ---------------------------------------------------------------------------

@app.route("/reset", methods=["POST"])
def reset():
    """Wipe providers + verifications and re-seed. Keeps plan data."""
    conn = get_db()
    conn.execute("DELETE FROM verifications")
    conn.execute("DELETE FROM providers")
    conn.commit()
    conn.close()

    import seed as seed_module
    seed_module.seed()

    flash("Database reset and re-seeded.", "success")
    return redirect(url_for("dashboard"))


# ---------------------------------------------------------------------------
# Template filters
# ---------------------------------------------------------------------------

@app.template_filter("plan_type")
def plan_type_filter(plan_name):
    return extract_plan_type(plan_name)


@app.template_filter("friendly_date")
def friendly_date_filter(dt_str):
    if not dt_str:
        return "—"
    try:
        dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S")
        return dt.strftime("%b %d, %Y")
    except Exception:
        return dt_str


@app.template_filter("days_ago")
def days_ago_filter(dt_str):
    if not dt_str:
        return ""
    try:
        dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S")
        delta = datetime.now() - dt
        if delta.days == 0:
            return "today"
        elif delta.days == 1:
            return "1 day ago"
        else:
            return f"{delta.days} days ago"
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Status badge helper (available in templates via context processor)
# ---------------------------------------------------------------------------

@app.context_processor
def inject_helpers():
    STATUS_COLORS = {
        "Verified": "success",
        "Declined": "danger",
        "Pending": "warning",
        "Unknown": "secondary",
    }

    def status_badge(status):
        cls_map = {
            "Verified": "status-badge status-verified",
            "Declined": "status-badge status-declined",
            "Pending":  "status-badge status-pending",
            "Unknown":  "status-badge status-unknown",
        }
        cls = cls_map.get(status, "status-badge status-not-requested")
        label = status or "Not Requested"
        return f'<span class="{cls}">{label}</span>'

    return dict(status_badge=status_badge)


# ---------------------------------------------------------------------------
# App entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    init_db()
    app.run(debug=True, port=5000)
