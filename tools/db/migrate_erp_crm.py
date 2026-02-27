#!/usr/bin/env python3
# CUI // SP-PROPIN
# Controlled by: GovProposal Portal
# CUI Category: PROPIN (Proprietary Business Information)
# Distribution: D
"""Add ERP and CRM module tables to GovProposal database.

New tables:
  ERP:
    employees           — Employee master (own company + subs/partners)
    skills              — Skill registry
    employee_skills     — Employee ↔ skill M:M with proficiency
    certifications      — Employee certifications with expiry
    lcats               — LCAT (Labor Category) definitions
    employee_lcats      — Employee ↔ LCAT assignments
    lcat_rates          — LCAT rate cards (direct labor, fringe, OH, G&A, fee)
    capabilities        — Company core capabilities

  CRM:
    relationship_types  — Lookup: competitor/partner/frienemy/vendor/prospect
    contacts            — CRM contact master
    interactions        — Interaction/activity log
    pipeline_contacts   — Contact ↔ opportunity association
    vendor_capabilities — Vendor/partner capability assessments
    linkedin_imports    — LinkedIn CSV import audit log

Existing table enhancements:
    teaming_partners   — ADD COLUMN relationship_type_id
    competitors        — ADD COLUMN relationship_type_id

Usage:
    python tools/db/migrate_erp_crm.py [--dry-run] [--json]
"""

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent
DB_PATH = Path(os.environ.get(
    "GOVPROPOSAL_DB_PATH", str(BASE_DIR / "data" / "govproposal.db")
))


MIGRATION_SQL = """
-- ============================================================
-- ERP: EMPLOYEE MASTER
-- ============================================================
CREATE TABLE IF NOT EXISTS employees (
    id                  TEXT PRIMARY KEY,
    full_name           TEXT NOT NULL,
    email               TEXT,
    phone               TEXT,
    job_title           TEXT,
    company_type        TEXT NOT NULL DEFAULT 'own'
        CHECK(company_type IN ('own', 'sub', 'partner')),
    partner_firm_id     TEXT,  -- FK teaming_partners.id
    department          TEXT,
    hire_date           TEXT,
    status              TEXT NOT NULL DEFAULT 'active'
        CHECK(status IN ('active', 'inactive', 'on_leave', 'contractor')),
    clearance_level     TEXT
        CHECK(clearance_level IN ('none', 'public_trust', 'secret',
              'top_secret', 'ts_sci', 'ts_sci_poly', NULL)),
    clearance_status    TEXT
        CHECK(clearance_status IN ('active', 'interim', 'expired',
              'pending', 'not_applicable', NULL)),
    clearance_expiry    TEXT,
    years_experience    INTEGER,
    location            TEXT,
    availability        TEXT DEFAULT 'available'
        CHECK(availability IN ('available', 'committed', 'partial', NULL)),
    resume_id           TEXT,  -- FK resumes.id (nullable)
    education           TEXT,
    linkedin_url        TEXT,
    notes               TEXT,
    classification      TEXT NOT NULL DEFAULT 'CUI // SP-PROPIN',
    created_at          TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at          TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_emp_status    ON employees(status);
CREATE INDEX IF NOT EXISTS idx_emp_clearance ON employees(clearance_level);
CREATE INDEX IF NOT EXISTS idx_emp_type      ON employees(company_type);
CREATE INDEX IF NOT EXISTS idx_emp_avail     ON employees(availability);


-- ============================================================
-- ERP: SKILLS REGISTRY
-- ============================================================
CREATE TABLE IF NOT EXISTS skills (
    id          TEXT PRIMARY KEY,
    skill_name  TEXT NOT NULL UNIQUE,
    category    TEXT,  -- technical|management|functional|domain|tool|language
    description TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);


-- ============================================================
-- ERP: EMPLOYEE SKILLS (M:M)
-- ============================================================
CREATE TABLE IF NOT EXISTS employee_skills (
    id          TEXT PRIMARY KEY,
    employee_id TEXT NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
    skill_id    TEXT NOT NULL REFERENCES skills(id) ON DELETE CASCADE,
    proficiency TEXT DEFAULT 'intermediate'
        CHECK(proficiency IN ('beginner', 'intermediate', 'advanced', 'expert')),
    years_used  INTEGER,
    last_used   TEXT,
    notes       TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(employee_id, skill_id)
);

CREATE INDEX IF NOT EXISTS idx_empskill_emp   ON employee_skills(employee_id);
CREATE INDEX IF NOT EXISTS idx_empskill_skill ON employee_skills(skill_id);


-- ============================================================
-- ERP: CERTIFICATIONS
-- ============================================================
CREATE TABLE IF NOT EXISTS certifications (
    id              TEXT PRIMARY KEY,
    employee_id     TEXT NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
    cert_name       TEXT NOT NULL,
    issuing_body    TEXT,
    cert_number     TEXT,
    issue_date      TEXT,
    expiry_date     TEXT,
    status          TEXT DEFAULT 'active'
        CHECK(status IN ('active', 'expired', 'pending', 'renewal_due')),
    classification  TEXT NOT NULL DEFAULT 'CUI // SP-PROPIN',
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_cert_emp    ON certifications(employee_id);
CREATE INDEX IF NOT EXISTS idx_cert_status ON certifications(status);
CREATE INDEX IF NOT EXISTS idx_cert_expiry ON certifications(expiry_date);


-- ============================================================
-- ERP: LCAT DEFINITIONS
-- ============================================================
CREATE TABLE IF NOT EXISTS lcats (
    id                    TEXT PRIMARY KEY,
    lcat_code             TEXT NOT NULL UNIQUE,
    lcat_name             TEXT NOT NULL,
    description           TEXT,
    naics_code            TEXT,
    min_education         TEXT,
    min_experience_years  INTEGER,
    typical_skills        TEXT,  -- JSON array of skill names
    created_at            TEXT NOT NULL DEFAULT (datetime('now'))
);


-- ============================================================
-- ERP: EMPLOYEE LCAT ASSIGNMENTS
-- ============================================================
CREATE TABLE IF NOT EXISTS employee_lcats (
    id              TEXT PRIMARY KEY,
    employee_id     TEXT NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
    lcat_id         TEXT NOT NULL REFERENCES lcats(id),
    effective_date  TEXT NOT NULL,
    end_date        TEXT,
    is_primary      INTEGER NOT NULL DEFAULT 1,
    notes           TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_emplace_emp  ON employee_lcats(employee_id);
CREATE INDEX IF NOT EXISTS idx_emplace_lcat ON employee_lcats(lcat_id);


-- ============================================================
-- ERP: LCAT RATE CARDS (DCAA-Compliant Cost Structure)
-- ============================================================
CREATE TABLE IF NOT EXISTS lcat_rates (
    id                  TEXT PRIMARY KEY,
    lcat_id             TEXT NOT NULL REFERENCES lcats(id),
    effective_date      TEXT NOT NULL,
    end_date            TEXT,
    direct_labor_rate   REAL NOT NULL,   -- $/hr base rate
    fringe_rate         REAL DEFAULT 0.0,  -- % of direct labor (e.g., 0.28)
    overhead_rate       REAL DEFAULT 0.0,  -- % (e.g., 0.15)
    ga_rate             REAL DEFAULT 0.0,  -- G&A % (e.g., 0.10)
    fee_rate            REAL DEFAULT 0.0,  -- Profit/fee % (e.g., 0.08)
    wrap_rate           REAL,              -- Computed total multiplier
    cost_type           TEXT DEFAULT 'cost_reimbursable'
        CHECK(cost_type IN ('cost_reimbursable', 'fixed_price', 'time_materials')),
    contract_vehicle    TEXT,
    agency              TEXT,
    notes               TEXT,
    created_at          TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_rate_lcat      ON lcat_rates(lcat_id);
CREATE INDEX IF NOT EXISTS idx_rate_effective ON lcat_rates(effective_date);


-- ============================================================
-- ERP: COMPANY CORE CAPABILITIES
-- ============================================================
CREATE TABLE IF NOT EXISTS capabilities (
    id              TEXT PRIMARY KEY,
    capability_name TEXT NOT NULL,
    category        TEXT,  -- technical|domain|management|certification|clearance
    description     TEXT,
    evidence_source TEXT DEFAULT 'employees'
        CHECK(evidence_source IN ('employees', 'past_performance', 'manual')),
    employee_count  INTEGER DEFAULT 0,
    proficiency_avg TEXT,   -- average proficiency (beginner-expert)
    relevant_naics  TEXT,   -- JSON array of NAICS codes
    proposal_count  INTEGER DEFAULT 0,
    last_used       TEXT,
    is_active       INTEGER NOT NULL DEFAULT 1,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);


-- ============================================================
-- CRM: RELATIONSHIP TYPE LOOKUP
-- ============================================================
CREATE TABLE IF NOT EXISTS relationship_types (
    id          TEXT PRIMARY KEY,
    type_name   TEXT NOT NULL UNIQUE,
    description TEXT,
    color_code  TEXT  -- CSS color for UI badges
);

-- Seed default relationship types
INSERT OR IGNORE INTO relationship_types (id, type_name, description, color_code)
VALUES
    ('rt_competitor',  'competitor',  'Direct competitor in our market space', '#e74c3c'),
    ('rt_partner',     'partner',     'Teaming partner or preferred sub', '#27ae60'),
    ('rt_frienemy',    'frienemy',    'Competitor in some areas, partner in others', '#e67e22'),
    ('rt_vendor',      'vendor',      'Supplier or service vendor', '#3498db'),
    ('rt_prospect',    'prospect',    'Prospective customer or agency stakeholder', '#9b59b6'),
    ('rt_customer',    'customer',    'Active or past customer/agency', '#1abc9c'),
    ('rt_mentor',      'mentor',      'Industry mentor or advisor', '#95a5a6');


-- ============================================================
-- CRM: CONTACTS MASTER
-- ============================================================
CREATE TABLE IF NOT EXISTS contacts (
    id                  TEXT PRIMARY KEY,
    full_name           TEXT NOT NULL,
    title               TEXT,
    email               TEXT,
    phone               TEXT,
    company             TEXT,
    relationship_type_id TEXT REFERENCES relationship_types(id),
    sector              TEXT,  -- DoD|DHS|IC|Civilian|State|Local|Commercial
    agency              TEXT,
    sub_agency          TEXT,
    linkedin_url        TEXT,
    sam_entity_id       TEXT,
    notes               TEXT,
    last_contact_date   TEXT,
    status              TEXT DEFAULT 'active'
        CHECK(status IN ('active', 'inactive', 'do_not_contact')),
    classification      TEXT NOT NULL DEFAULT 'CUI // SP-PROPIN',
    created_at          TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at          TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_contact_rel    ON contacts(relationship_type_id);
CREATE INDEX IF NOT EXISTS idx_contact_sector ON contacts(sector);
CREATE INDEX IF NOT EXISTS idx_contact_status ON contacts(status);
CREATE INDEX IF NOT EXISTS idx_contact_agency ON contacts(agency);


-- ============================================================
-- CRM: INTERACTION LOG
-- ============================================================
CREATE TABLE IF NOT EXISTS interactions (
    id                  TEXT PRIMARY KEY,
    contact_id          TEXT NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
    opportunity_id      TEXT,  -- FK opportunities.id (optional)
    interaction_date    TEXT NOT NULL,
    interaction_type    TEXT DEFAULT 'note'
        CHECK(interaction_type IN ('meeting', 'call', 'email', 'conference',
              'site_visit', 'note', 'rfp_response', 'bid_review', 'demo')),
    subject             TEXT,
    notes               TEXT NOT NULL,
    outcome             TEXT
        CHECK(outcome IN ('positive', 'neutral', 'negative', NULL)),
    next_action         TEXT,
    next_action_date    TEXT,
    logged_by           TEXT,
    classification      TEXT NOT NULL DEFAULT 'CUI // SP-PROPIN',
    created_at          TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_inter_contact ON interactions(contact_id);
CREATE INDEX IF NOT EXISTS idx_inter_opp     ON interactions(opportunity_id);
CREATE INDEX IF NOT EXISTS idx_inter_date    ON interactions(interaction_date);


-- ============================================================
-- CRM: PIPELINE CONTACT ASSOCIATIONS
-- ============================================================
CREATE TABLE IF NOT EXISTS pipeline_contacts (
    id              TEXT PRIMARY KEY,
    contact_id      TEXT NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
    opportunity_id  TEXT NOT NULL,  -- FK opportunities.id
    role            TEXT,  -- decision_maker|influencer|technical_evaluator|co|pm
    influence_level TEXT DEFAULT 'medium'
        CHECK(influence_level IN ('high', 'medium', 'low')),
    notes           TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(contact_id, opportunity_id)
);

CREATE INDEX IF NOT EXISTS idx_pc_contact ON pipeline_contacts(contact_id);
CREATE INDEX IF NOT EXISTS idx_pc_opp     ON pipeline_contacts(opportunity_id);


-- ============================================================
-- CRM: VENDOR/PARTNER CAPABILITY ASSESSMENTS
-- ============================================================
CREATE TABLE IF NOT EXISTS vendor_capabilities (
    id                  TEXT PRIMARY KEY,
    company_id          TEXT,   -- FK teaming_partners.id or competitors.id
    company_type        TEXT NOT NULL DEFAULT 'partner'
        CHECK(company_type IN ('partner', 'competitor', 'vendor', 'subcontractor')),
    company_name        TEXT NOT NULL,
    technical_areas     TEXT,   -- JSON array of domain areas
    certifications      TEXT,   -- JSON array: CMMC, ISO 9001, etc.
    contract_vehicles   TEXT,   -- JSON array: GSA MAS, CIO-SP3, etc.
    clearance_level     TEXT,
    employee_count      INTEGER,
    sam_score           REAL,   -- SAM.gov performance rating (0-100)
    cpars_rating        TEXT
        CHECK(cpars_rating IN ('exceptional', 'very_good', 'satisfactory',
              'marginal', 'unsatisfactory', NULL)),
    last_assessed       TEXT,
    notes               TEXT,
    classification      TEXT NOT NULL DEFAULT 'CUI // SP-PROPIN',
    created_at          TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at          TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_vc_company ON vendor_capabilities(company_id);


-- ============================================================
-- CRM: LINKEDIN IMPORT AUDIT LOG (append-only)
-- ============================================================
CREATE TABLE IF NOT EXISTS linkedin_imports (
    id              TEXT PRIMARY KEY,
    import_type     TEXT NOT NULL
        CHECK(import_type IN ('profile', 'connections')),
    filename        TEXT NOT NULL,
    record_count    INTEGER DEFAULT 0,
    imported_count  INTEGER DEFAULT 0,
    skipped_count   INTEGER DEFAULT 0,
    target_type     TEXT DEFAULT 'contact'
        CHECK(target_type IN ('employee', 'contact')),
    field_mapping   TEXT,  -- JSON field mapping used
    status          TEXT DEFAULT 'completed'
        CHECK(status IN ('pending', 'processing', 'completed', 'failed')),
    error_message   TEXT,
    imported_by     TEXT,
    imported_at     TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

ALTER_SQL = [
    "ALTER TABLE teaming_partners ADD COLUMN relationship_type_id TEXT",
    "ALTER TABLE competitors ADD COLUMN relationship_type_id TEXT",
    "ALTER TABLE pricing_benchmarks ADD COLUMN lcat_id TEXT",
    "ALTER TABLE pricing_benchmarks ADD COLUMN sector TEXT",
    "ALTER TABLE resumes ADD COLUMN employee_id TEXT",
]


def run_migration(dry_run: bool = False) -> dict:
    if not DB_PATH.exists():
        return {"success": False, "error": f"Database not found: {DB_PATH}"}

    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row

    results = {
        "migration": "erp_crm",
        "dry_run": dry_run,
        "tables_created": [],
        "columns_added": [],
        "errors": [],
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    try:
        conn.execute("BEGIN")

        # Create new tables
        for stmt in MIGRATION_SQL.strip().split(";"):
            # Strip leading comment lines — splits can leave comment blocks before CREATE
            lines = [l for l in stmt.splitlines() if not l.strip().startswith("--")]
            stmt = "\n".join(lines).strip()
            if not stmt:
                continue
            if dry_run:
                # Just try to parse; don't execute
                results["tables_created"].append(stmt[:60] + "...")
                continue
            try:
                conn.execute(stmt)
                # Track created tables
                if stmt.upper().startswith("CREATE TABLE"):
                    table = stmt.split("IF NOT EXISTS")[-1].strip().split("(")[0].strip()
                    results["tables_created"].append(table)
            except sqlite3.Error as e:
                if "already exists" not in str(e):
                    results["errors"].append(f"DDL error: {e} | stmt: {stmt[:80]}")

        # Alter existing tables
        for alter in ALTER_SQL:
            if dry_run:
                results["columns_added"].append(alter)
                continue
            try:
                conn.execute(alter)
                col = alter.split("ADD COLUMN")[-1].strip().split()[0]
                table = alter.split("ALTER TABLE")[1].strip().split()[0]
                results["columns_added"].append(f"{table}.{col}")
            except sqlite3.OperationalError as e:
                if "duplicate column" in str(e).lower():
                    col = alter.split("ADD COLUMN")[-1].strip().split()[0]
                    results["columns_added"].append(f"(already exists) {col}")
                else:
                    results["errors"].append(f"ALTER error: {e}")

        if not dry_run:
            conn.execute("COMMIT")
        else:
            conn.execute("ROLLBACK")

        results["success"] = len(results["errors"]) == 0

    except Exception as e:
        conn.execute("ROLLBACK")
        results["success"] = False
        results["errors"].append(str(e))
    finally:
        conn.close()

    return results


def main():
    parser = argparse.ArgumentParser(description="Migrate GovProposal DB for ERP/CRM")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print what would be executed without making changes")
    parser.add_argument("--json", action="store_true", dest="json_out",
                        help="Output JSON")
    args = parser.parse_args()

    result = run_migration(dry_run=args.dry_run)

    if args.json_out:
        print(json.dumps(result, indent=2))
    else:
        status = "DRY RUN" if args.dry_run else ("OK" if result["success"] else "FAILED")
        print(f"Migration: {status}")
        print(f"Tables created: {len(result['tables_created'])}")
        for t in result["tables_created"]:
            print(f"  + {t}")
        print(f"Columns added: {len(result['columns_added'])}")
        for c in result["columns_added"]:
            print(f"  ~ {c}")
        if result["errors"]:
            print("Errors:")
            for e in result["errors"]:
                print(f"  ! {e}")

    sys.exit(0 if result["success"] else 1)


if __name__ == "__main__":
    main()
