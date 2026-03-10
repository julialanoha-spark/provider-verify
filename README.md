# Provider Verify

A Medicare Advantage provider network verification tool for insurance agents. Agents can look up providers or plans, send tokenized verification requests to provider offices, and track participation status across their book of business.

## Features

- **Provider search** — look up a provider by name or NPI and see their Medicare Advantage plan participation status across all plans in their state
- **Plan search** — enter a ZIP code to find all MA plans available in that county, then check which providers are verified in-network
- **Verification requests** — generate a unique portal link per provider/plan pair and preview the outreach email before sending
- **Provider portal** — providers confirm or decline plan participation via a tokenized link (no login required); they can also update previously verified plans and self-report new ones
- **Dashboard** — view all verifications with status filters (Pending / Verified / Declined / Unknown)
- **Network status** — filter providers by plan and state to see the full in-network roster

## Tech Stack

- Python / Flask
- SQLite (local)
- Jinja2 templates
- Bootstrap (via CDN)

## Setup

### Prerequisites

- Python 3.9+
- Medicare Advantage plan data loaded into `ingestion.db` (see below)

### Install dependencies

```bash
pip install -r requirements.txt
```

### Plan data

The app expects an `ingestion.db` SQLite file at `/Users/julialanoha/Desktop/ingestion.db` containing three tables:

| Table | Key columns |
|---|---|
| `plans` | `contract_id`, `plan_id`, `segment_id`, `plan_name`, `carrier`, `state` |
| `plan_counties` | `contract_id`, `plan_id`, `segment_id`, `fips_code` |
| `zip_counties` | `zip_code`, `fips_code`, `state`, `county_name` |

If `ingestion.db` is not present, the app starts with empty plan data (providers and verifications still work).

### Run

```bash
python app.py
```

The app runs on [http://localhost:5000](http://localhost:5000).

On first launch it creates `verifications.db` and copies plan data from `ingestion.db`.

### Seed demo data

To load sample providers and pre-seeded verifications for testing:

```bash
python seed.py
```

To reset and re-seed at any time, use the **Reset** button on the dashboard (dev only).

## Project Structure

```
app.py          # Flask app — routes, DB helpers, template filters
seed.py         # Demo data: 5 sample providers + verifications
schema.sql      # providers + verifications table definitions
requirements.txt
templates/      # Jinja2 HTML templates
static/         # CSS / JS assets
verifications.db  # SQLite DB (git-ignored, created at runtime)
```

## Routes

| Route | Description |
|---|---|
| `/` | Home / provider search |
| `/plan-search` | ZIP-based plan search |
| `/provider/<npi>` | Provider detail + plan status |
| `/plan/<contract_id>/<plan_id>/<segment_id>` | Plan detail + verified providers |
| `/verify` (POST) | Create verification request |
| `/email-preview/<id>` | Preview outreach email |
| `/portal/<token>` | Provider self-service portal |
| `/dashboard` | All verifications with status filter |
| `/network` | Network roster by plan |
| `/api/providers/search` | Provider autocomplete API |
| `/api/plans/by-zip/<zip>` | Plans by ZIP API |
