#!/usr/bin/env python3
# CUI // SP-PROPIN
"""Add pricing module tables: indirect_rates, pricing_labor, service_packages, pricing_scenarios."""

import os
import sqlite3
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent
DB_PATH = Path(os.environ.get(
    "GOVPROPOSAL_DB_PATH", str(BASE_DIR / "data" / "govproposal.db")
))


def run():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    cur = conn.cursor()
    created = []

    # ── indirect_rates ────────────────────────────────────────────────────────
    cur.execute("""
        CREATE TABLE IF NOT EXISTS indirect_rates (
            id          TEXT PRIMARY KEY,
            name        TEXT NOT NULL,
            fringe_rate REAL NOT NULL DEFAULT 0.30,
            overhead_rate REAL NOT NULL DEFAULT 0.12,
            ga_rate     REAL NOT NULL DEFAULT 0.15,
            fee_tm      REAL NOT NULL DEFAULT 0.10,
            fee_ffp     REAL NOT NULL DEFAULT 0.12,
            odc_markup  REAL NOT NULL DEFAULT 0.10,
            is_active   INTEGER NOT NULL DEFAULT 1,
            notes       TEXT,
            created_at  TEXT NOT NULL,
            updated_at  TEXT NOT NULL
        )
    """)
    created.append("indirect_rates")

    # ── pricing_labor ─────────────────────────────────────────────────────────
    cur.execute("""
        CREATE TABLE IF NOT EXISTS pricing_labor (
            id          TEXT PRIMARY KEY,
            lcat_code   TEXT NOT NULL UNIQUE,
            lcat_name   TEXT NOT NULL,
            base_rate   REAL NOT NULL,
            skill_level TEXT NOT NULL
                CHECK(skill_level IN ('junior','mid','senior','principal')),
            discipline  TEXT NOT NULL
                CHECK(discipline IN ('cloud','cyber','ai_ml','helpdesk','pm','other')),
            created_at  TEXT NOT NULL
        )
    """)
    created.append("pricing_labor")

    # ── service_packages ──────────────────────────────────────────────────────
    cur.execute("""
        CREATE TABLE IF NOT EXISTS service_packages (
            id           TEXT PRIMARY KEY,
            service_line TEXT NOT NULL
                CHECK(service_line IN ('cloud_infra','cyber_pentest','ai_ml_ops','help_desk')),
            tier         TEXT NOT NULL
                CHECK(tier IN ('bronze','silver','gold')),
            name         TEXT NOT NULL,
            description  TEXT,
            period       TEXT NOT NULL
                CHECK(period IN ('monthly','quarterly','annual')),
            labor_mix    TEXT NOT NULL,
            odc_base     REAL NOT NULL DEFAULT 0,
            market_low   REAL,
            market_high  REAL,
            notes        TEXT,
            created_at   TEXT NOT NULL,
            updated_at   TEXT NOT NULL
        )
    """)
    created.append("service_packages")

    # ── pricing_scenarios ─────────────────────────────────────────────────────
    cur.execute("""
        CREATE TABLE IF NOT EXISTS pricing_scenarios (
            id                    TEXT PRIMARY KEY,
            name                  TEXT NOT NULL,
            opportunity_id        TEXT,
            package_id            TEXT,
            indirect_rate_id      TEXT NOT NULL,
            service_line          TEXT NOT NULL,
            tier                  TEXT,
            period                TEXT NOT NULL,
            contract_type         TEXT NOT NULL
                CHECK(contract_type IN ('tm','ffp')),
            labor_hours           REAL NOT NULL,
            direct_labor_cost     REAL NOT NULL,
            fringe_cost           REAL NOT NULL,
            overhead_cost         REAL NOT NULL,
            ga_cost               REAL NOT NULL,
            total_cost_before_fee REAL NOT NULL,
            fee_amount            REAL NOT NULL,
            odc_cost              REAL NOT NULL DEFAULT 0,
            total_price           REAL NOT NULL,
            breakeven_price       REAL NOT NULL,
            margin_amount         REAL NOT NULL,
            margin_pct            REAL NOT NULL,
            notes                 TEXT,
            created_at            TEXT NOT NULL,
            updated_at            TEXT NOT NULL
        )
    """)
    created.append("pricing_scenarios")

    conn.commit()
    conn.close()

    print(f"Pricing migration complete. Tables ensured: {', '.join(created)}")


if __name__ == "__main__":
    run()
