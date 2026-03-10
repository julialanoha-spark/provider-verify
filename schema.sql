CREATE TABLE IF NOT EXISTS providers (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    npi         TEXT UNIQUE NOT NULL,
    name        TEXT NOT NULL,
    practice    TEXT,
    email       TEXT,
    phone       TEXT,
    specialty   TEXT,
    zip_code    TEXT NOT NULL,
    state       TEXT NOT NULL,
    county_name TEXT,
    fips_code   TEXT,
    created_at  TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS verifications (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    provider_id     INTEGER NOT NULL REFERENCES providers(id),
    contract_id     TEXT NOT NULL,
    plan_id_ref     TEXT NOT NULL,
    segment_id      TEXT NOT NULL DEFAULT '0',
    status          TEXT NOT NULL DEFAULT 'Pending',
    requested_by    TEXT,
    requested_at    TEXT DEFAULT (datetime('now')),
    responded_at    TEXT,
    last_verified   TEXT,
    last_reviewed   TEXT,
    notes           TEXT,
    token           TEXT UNIQUE,
    UNIQUE(provider_id, contract_id, plan_id_ref, segment_id)
);
