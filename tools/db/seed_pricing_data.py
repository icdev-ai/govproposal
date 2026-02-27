#!/usr/bin/env python3
# CUI // SP-PROPIN
"""Seed Bronze/Silver/Gold service package pricing data for GovProposal.

Indirect rates based on small business DCAA norms.
Service packages derived from government RFP market research (FY2024-2025).

Usage:
    python tools/db/seed_pricing_data.py [--reset]
"""

import json
import os
import sqlite3
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent
DB_PATH = Path(os.environ.get(
    "GOVPROPOSAL_DB_PATH", str(BASE_DIR / "data" / "govproposal.db")
))

RESET = "--reset" in sys.argv


def _now():
    return datetime.now(timezone.utc).isoformat()


def _id():
    return str(uuid.uuid4())


def seed(conn):
    cur = conn.cursor()
    now = _now()

    if RESET:
        for t in ["pricing_scenarios", "service_packages", "pricing_labor", "indirect_rates"]:
            cur.execute(f"DELETE FROM {t}")
        print("  Cleared existing pricing data.")

    # ── 1. Indirect Rate Configuration ────────────────────────────────────────
    # Small business standard (DCAA-compliant structure)
    # Wrap T&M  = (1+fringe)(1+OH)(1+G&A)(1+fee_tm)
    #           = 1.30 × 1.12 × 1.15 × 1.10 = 1.842
    # Wrap FFP  = 1.30 × 1.12 × 1.15 × 1.12 = 1.875
    rate_id = _id()
    cur.execute("""
        INSERT OR IGNORE INTO indirect_rates
            (id, name, fringe_rate, overhead_rate, ga_rate, fee_tm, fee_ffp,
             odc_markup, is_active, notes, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        rate_id,
        "FY2025 Small Business Standard",
        0.30,   # fringe  — 30%  (benefits, FICA, WC, UI)
        0.12,   # OH      — 12%  (facilities, mgmt, tools)
        0.15,   # G&A     — 15%  (corp support, BD, finance)
        0.10,   # fee T&M — 10%
        0.12,   # fee FFP — 12%
        0.10,   # ODC markup — 10%
        1,
        "DCAA-compliant small biz pool structure. "
        "T&M wrap ≈1.84x, FFP wrap ≈1.88x. "
        "ODCs billed at cost + 10% handling fee.",
        now, now,
    ))
    print(f"  [+] Indirect rate: FY2025 Small Business Standard  (wrap T&M~1.84x, FFP~1.88x)")

    # ── 2. Pricing Labor Categories ────────────────────────────────────────────
    labors = [
        # (lcat_code, lcat_name, base_rate, skill_level, discipline)
        ("CE-II",  "Cloud Engineer II",          75.00, "mid",       "cloud"),
        ("CE-III", "Cloud Engineer III / Sr",    95.00, "senior",    "cloud"),
        ("PT-II",  "Penetration Tester II",       85.00, "mid",       "cyber"),
        ("PT-III", "Penetration Tester III / Sr", 95.00, "senior",    "cyber"),
        ("CA-II",  "Cybersecurity Analyst II",    80.00, "mid",       "cyber"),
        ("ML-II",  "AI/ML Engineer II",           90.00, "mid",       "ai_ml"),
        ("ML-III", "AI/ML Engineer III / Sr",     110.00, "senior",   "ai_ml"),
        ("HD-I",   "Help Desk Analyst I (T1)",    35.00, "junior",    "helpdesk"),
        ("HD-II",  "Help Desk Analyst II (T2)",   52.00, "mid",       "helpdesk"),
        ("SM-II",  "Systems Manager / T3 Lead",   75.00, "senior",    "helpdesk"),
        ("PM-II",  "Program Manager II",          80.00, "mid",       "pm"),
        ("PM-III", "Program Manager III / Sr",    100.00, "senior",   "pm"),
    ]
    for lc, ln, rate, skill, disc in labors:
        cur.execute("""
            INSERT OR IGNORE INTO pricing_labor
                (id, lcat_code, lcat_name, base_rate, skill_level, discipline, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (_id(), lc, ln, rate, skill, disc, now))
    print(f"  [+] Labor categories: {len(labors)} LCATs seeded")

    # ── 3. Service Packages ────────────────────────────────────────────────────
    # labor_mix = list of {lcat_code, hours} for the package period
    packages = [

        # ── CLOUD INFRASTRUCTURE ─────────────────────────────────────────
        # Bronze: up to 10 EC2 + 2 RDS  (~3 hrs/EC2 + 4 hrs/RDS + PM)
        {
            "service_line": "cloud_infra", "tier": "bronze",
            "name": "Bronze Cloud Managed Services",
            "description": (
                "Managed AWS/Azure/GCP infrastructure for small environments. "
                "Up to 10 compute instances + 2 managed databases. "
                "Includes patching, monitoring, incident response (business hours), "
                "monthly security posture review, and cost optimization."
            ),
            "period": "monthly",
            "labor_mix": [
                {"lcat_code": "CE-II",  "hours": 33},   # 3 hrs × 10 EC2 + 3 hrs setup
                {"lcat_code": "PM-II",  "hours": 4},
            ],
            "odc_base": 450,    # CloudWatch, alerting tools, S3 storage
            "market_low": 3500, "market_high": 8500,
            "notes": "Entry-level managed cloud. Excludes multi-cloud and 24/7 NOC.",
        },
        # Silver: up to 25 EC2 + 5 RDS + LB + auto-scaling
        {
            "service_line": "cloud_infra", "tier": "silver",
            "name": "Silver Cloud Managed Services",
            "description": (
                "Full managed cloud operations for mid-size environments. "
                "Up to 25 compute instances + 5 managed databases + load balancers. "
                "Includes continuous monitoring, automated patching, weekly reporting, "
                "DevSecOps pipeline support, and cost governance."
            ),
            "period": "monthly",
            "labor_mix": [
                {"lcat_code": "CE-II",  "hours": 75},   # 3 hrs × 25 EC2
                {"lcat_code": "CE-III", "hours": 20},   # architecture + escalations
                {"lcat_code": "PM-II",  "hours": 6},
            ],
            "odc_base": 1100,   # extended monitoring stack, log aggregation
            "market_low": 10000, "market_high": 25000,
            "notes": "Includes monthly ATO evidence collection for cATO programs.",
        },
        # Gold: 50+ EC2 + 10 RDS + full DevSecOps + 24/7
        {
            "service_line": "cloud_infra", "tier": "gold",
            "name": "Gold Cloud Managed Services",
            "description": (
                "Enterprise managed cloud with 24/7 NOC coverage. "
                "Unlimited compute instances + 10+ databases + container orchestration. "
                "Full DevSecOps pipeline, multi-region DR, advanced cost engineering, "
                "compliance evidence automation (FedRAMP/CMMC), and dedicated TAM."
            ),
            "period": "monthly",
            "labor_mix": [
                {"lcat_code": "CE-III", "hours": 100},  # primary architect + lead
                {"lcat_code": "CE-II",  "hours": 80},   # day-to-day ops
                {"lcat_code": "PM-III", "hours": 10},
            ],
            "odc_base": 2800,   # full SIEM, WAF, IDS/IPS, multi-cloud tools
            "market_low": 28000, "market_high": 60000,
            "notes": "Priced per period. Scale via labor mix for > 100 instances.",
        },

        # ── CYBERSECURITY / PENTEST ──────────────────────────────────────
        # Bronze: single application (OWASP Top 10), 40 hrs per engagement
        {
            "service_line": "cyber_pentest", "tier": "bronze",
            "name": "Bronze Application Pentest",
            "description": (
                "Targeted penetration test of a single web application or API. "
                "OWASP Top 10 coverage, manual + automated testing (Burp Suite, OWASP ZAP). "
                "Deliverables: executive summary, technical findings report, remediation roadmap."
            ),
            "period": "quarterly",
            "labor_mix": [
                {"lcat_code": "PT-II",  "hours": 36},
                {"lcat_code": "PM-II",  "hours": 4},
            ],
            "odc_base": 200,    # tooling licenses, cloud sandboxing
            "market_low": 5000, "market_high": 20000,
            "notes": "Recommended cadence: quarterly. Add-on: remediation verification retest $2K.",
        },
        # Silver: 2 apps + network perimeter, 80 hrs
        {
            "service_line": "cyber_pentest", "tier": "silver",
            "name": "Silver Pentest Program",
            "description": (
                "Quarterly penetration testing covering 2 applications + network perimeter. "
                "Includes phishing simulation (up to 100 targets), vulnerability assessment, "
                "and one remediation retest. NIST 800-115 compliant methodology."
            ),
            "period": "quarterly",
            "labor_mix": [
                {"lcat_code": "PT-III", "hours": 56},
                {"lcat_code": "CA-II",  "hours": 20},
                {"lcat_code": "PM-II",  "hours": 4},
            ],
            "odc_base": 400,
            "market_low": 15000, "market_high": 50000,
            "notes": "Includes one free retest per finding. Annual plan: 4 × quarterly.",
        },
        # Gold: full red team + purple team, 180 hrs
        {
            "service_line": "cyber_pentest", "tier": "gold",
            "name": "Gold Red Team / Full-Scope Assessment",
            "description": (
                "Full-scope adversary simulation targeting people, process, and technology. "
                "Includes red team (APT TTPs, MITRE ATT&CK), purple team tabletop, "
                "cloud config review (CIS benchmarks), and privileged access assessment. "
                "Final deliverable: board-level and CISO technical briefing."
            ),
            "period": "quarterly",
            "labor_mix": [
                {"lcat_code": "PT-III", "hours": 100},
                {"lcat_code": "CA-II",  "hours": 60},
                {"lcat_code": "PM-III", "hours": 20},
            ],
            "odc_base": 800,    # C2 infra, threat intel feeds, specialized tooling
            "market_low": 50000, "market_high": 120000,
            "notes": "Requires signed Rules of Engagement and NDA. Schedule 60 days ahead.",
        },

        # ── AI / ML OPERATIONS ───────────────────────────────────────────
        # Bronze: 1-2 models, monitoring + basic drift detection
        {
            "service_line": "ai_ml_ops", "tier": "bronze",
            "name": "Bronze MLOps — Model Monitoring",
            "description": (
                "MLOps support for 1-2 production models. "
                "Includes model performance monitoring, data drift alerts, "
                "monthly model health report, and on-call support for model failures. "
                "Inference cost optimization and API gateway management included."
            ),
            "period": "monthly",
            "labor_mix": [
                {"lcat_code": "ML-II",  "hours": 20},
                {"lcat_code": "PM-II",  "hours": 2},
            ],
            "odc_base": 1400,   # GPU inference costs, monitoring platform (Evidently/WhyLabs)
            "market_low": 4000, "market_high": 12000,
            "notes": "Scales to Silver at 3+ models or when retraining is needed monthly.",
        },
        # Silver: 3-5 models, monitoring + retraining + drift + AIML engineering
        {
            "service_line": "ai_ml_ops", "tier": "silver",
            "name": "Silver MLOps — Active Management",
            "description": (
                "Full MLOps lifecycle for 3-5 production models. "
                "Includes all Bronze features plus: quarterly model retraining, "
                "A/B testing, feature engineering, responsible AI checks (bias/fairness), "
                "OMB M-25-21 AI inventory maintenance, and shadow model evaluation."
            ),
            "period": "monthly",
            "labor_mix": [
                {"lcat_code": "ML-II",  "hours": 40},
                {"lcat_code": "ML-III", "hours": 10},
                {"lcat_code": "PM-II",  "hours": 4},
            ],
            "odc_base": 3800,   # cloud GPU (A10G on-demand), data pipeline, MLflow/SageMaker
            "market_low": 15000, "market_high": 40000,
            "notes": "Government AI Act compliance (OMB M-25-21, M-26-04) included.",
        },
        # Gold: 5+ models, full pipeline, custom model development
        {
            "service_line": "ai_ml_ops", "tier": "gold",
            "name": "Gold MLOps — Full AI Program",
            "description": (
                "End-to-end AI program management for 5+ production models. "
                "Includes all Silver features plus: custom model fine-tuning, "
                "RAG pipeline management, agentic AI orchestration, multi-cloud LLM routing, "
                "full NIST AI RMF governance, model cards, system cards, and CAIO support."
            ),
            "period": "monthly",
            "labor_mix": [
                {"lcat_code": "ML-III", "hours": 60},
                {"lcat_code": "ML-II",  "hours": 40},
                {"lcat_code": "PM-III", "hours": 8},
            ],
            "odc_base": 7500,   # dedicated GPU cluster, enterprise MLOps platform, data labeling
            "market_low": 40000, "market_high": 100000,
            "notes": "Includes quarterly NIST AI RMF assessment and FedRAMP AI Annex evidence.",
        },

        # ── HELP DESK ────────────────────────────────────────────────────
        # Bronze: up to 200 users, Tier 1 only, 8×5
        {
            "service_line": "help_desk", "tier": "bronze",
            "name": "Bronze Help Desk — Tier 1 (8×5)",
            "description": (
                "Tier 1 end-user support for up to 200 users, business hours (8×5). "
                "Covers: password resets, software installs, VPN/MFA troubleshooting, "
                "peripheral support, and M365/Google Workspace. "
                "Average SLA: P1 < 1hr, P2 < 4hr, P3 < 1 day. ITSM ticketing included."
            ),
            "period": "monthly",
            "labor_mix": [
                {"lcat_code": "HD-I",  "hours": 220},   # ~1.3 FTE Tier 1
                {"lcat_code": "PM-II", "hours": 4},
            ],
            "odc_base": 320,    # ITSM license (ServiceNow/Jira), remote support tools
            "market_low": 8000, "market_high": 25000,
            "notes": "Assumes ~400 tickets/month. Overage: $45/ticket T&M.",
        },
        # Silver: up to 500 users, Tier 1+2, 12×5
        {
            "service_line": "help_desk", "tier": "silver",
            "name": "Silver Help Desk — Tier 1+2 (12×5)",
            "description": (
                "Tier 1+2 support for up to 500 users, extended hours (7am–7pm M-F). "
                "All Bronze features plus: application support (ERP/CRM/custom apps), "
                "network connectivity triage, device management (MDM), "
                "monthly reporting, and quarterly SLA reviews."
            ),
            "period": "monthly",
            "labor_mix": [
                {"lcat_code": "HD-I",  "hours": 400},   # ~2.4 FTE Tier 1
                {"lcat_code": "HD-II", "hours": 100},   # ~0.6 FTE Tier 2
                {"lcat_code": "PM-II", "hours": 6},
            ],
            "odc_base": 620,
            "market_low": 22000, "market_high": 65000,
            "notes": "~1,000 tickets/month capacity. Overage: $38/T1 ticket, $65/T2 ticket.",
        },
        # Gold: up to 1,000 users, Tier 1+2+3, 24×7
        {
            "service_line": "help_desk", "tier": "gold",
            "name": "Gold Help Desk — Tier 1/2/3 (24×7)",
            "description": (
                "Mission-critical 24×7 support for up to 1,000 users, all tiers. "
                "Full Tier 1+2+3 coverage including: server/network ops, cloud infrastructure, "
                "security incident first response, change management, asset lifecycle, "
                "and dedicated service delivery manager (SDM)."
            ),
            "period": "monthly",
            "labor_mix": [
                {"lcat_code": "HD-I",  "hours": 700},   # 24/7 adds ~40% hrs vs 8×5
                {"lcat_code": "HD-II", "hours": 200},
                {"lcat_code": "SM-II", "hours": 80},    # T3 / sys mgr
                {"lcat_code": "PM-III","hours": 10},
            ],
            "odc_base": 2100,   # ITSM enterprise, monitoring, knowledge base platform
            "market_low": 55000, "market_high": 150000,
            "notes": "CISA-aware incident triage included. FISMA/FedRAMP ticket audit trail.",
        },
    ]

    for p in packages:
        cur.execute("""
            INSERT OR IGNORE INTO service_packages
                (id, service_line, tier, name, description, period,
                 labor_mix, odc_base, market_low, market_high, notes,
                 created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            _id(),
            p["service_line"], p["tier"], p["name"], p["description"],
            p["period"], json.dumps(p["labor_mix"]),
            p["odc_base"], p["market_low"], p["market_high"], p["notes"],
            now, now,
        ))
    print(f"  [+] Service packages: {len(packages)} packages seeded (3 tiers × 4 service lines)")

    # ── 4. Demo Pricing Scenarios ─────────────────────────────────────────────
    # Pre-calculate a handful of saved scenarios so the UI has something to show.
    # Formula:
    #   cost_pool = DLC × (1+fringe) × (1+OH) × (1+G&A)
    #   fee       = cost_pool × fee_rate
    #   odc_total = odc_base × (1 + odc_markup)
    #   price     = cost_pool + fee + odc_total
    #   breakeven = cost_pool + odc_total  (no fee)

    FRINGE = 0.30
    OH     = 0.12
    GA     = 0.15
    FEE_TM  = 0.10
    FEE_FFP = 0.12
    ODC_MK  = 0.10

    # Pull the indirect_rate_id we just inserted
    row = conn.execute("SELECT id FROM indirect_rates WHERE name LIKE '%FY2025%' LIMIT 1").fetchone()
    ir_id = row["id"] if row else rate_id

    # Pull package IDs keyed by (service_line, tier)
    pkg_rows = conn.execute(
        "SELECT id, service_line, tier FROM service_packages"
    ).fetchall()
    pkg_map = {(r["service_line"], r["tier"]): r["id"] for r in pkg_rows}

    # Pull labor rates keyed by lcat_code
    lab_rows = conn.execute("SELECT lcat_code, base_rate FROM pricing_labor").fetchall()
    labor_rates = {r["lcat_code"]: r["base_rate"] for r in lab_rows}

    def calc_scenario(name, service_line, tier, period, ctype, labor_mix, odc_base, notes=""):
        """Return a dict with all pricing fields."""
        dlc = sum(
            labor_rates.get(lm["lcat_code"], 0) * lm["hours"]
            for lm in labor_mix
        )
        hours = sum(lm["hours"] for lm in labor_mix)
        fee_rate = FEE_FFP if ctype == "ffp" else FEE_TM
        cost_pool = dlc * (1 + FRINGE) * (1 + OH) * (1 + GA)
        fringe_cost    = dlc * FRINGE
        overhead_cost  = dlc * (1 + FRINGE) * OH
        ga_cost        = dlc * (1 + FRINGE) * (1 + OH) * GA
        fee_amount     = cost_pool * fee_rate
        odc_total      = odc_base * (1 + ODC_MK)
        total_price    = cost_pool + fee_amount + odc_total
        breakeven      = cost_pool + odc_total
        margin_amt     = fee_amount
        margin_pct     = (fee_amount / total_price * 100) if total_price else 0
        pkg_id         = pkg_map.get((service_line, tier))
        return {
            "id": _id(),
            "name": name,
            "opportunity_id": None,
            "package_id": pkg_id,
            "indirect_rate_id": ir_id,
            "service_line": service_line,
            "tier": tier,
            "period": period,
            "contract_type": ctype,
            "labor_hours": hours,
            "direct_labor_cost": dlc,
            "fringe_cost": fringe_cost,
            "overhead_cost": overhead_cost,
            "ga_cost": ga_cost,
            "total_cost_before_fee": cost_pool,
            "fee_amount": fee_amount,
            "odc_cost": odc_total,
            "total_price": total_price,
            "breakeven_price": breakeven,
            "margin_amount": margin_amt,
            "margin_pct": margin_pct,
            "notes": notes,
        }

    scenarios_data = [
        calc_scenario(
            "ACME Agency — Bronze Cloud (FFP Monthly)",
            "cloud_infra", "bronze", "monthly", "ffp",
            [{"lcat_code": "CE-II", "hours": 33}, {"lcat_code": "PM-II", "hours": 4}],
            450,
            "Baseline Bronze FFP for ACME cloud env. 10 EC2 + 2 RDS."
        ),
        calc_scenario(
            "DHS CISA — Silver Cloud (T&M Monthly)",
            "cloud_infra", "silver", "monthly", "tm",
            [{"lcat_code": "CE-II", "hours": 75},
             {"lcat_code": "CE-III", "hours": 20},
             {"lcat_code": "PM-II", "hours": 6}],
            1100,
            "T&M managed cloud for DHS CISA task order. Covers GovCloud + on-prem hybrid."
        ),
        calc_scenario(
            "Army PEO C3T — Silver Pentest Q1 (FFP)",
            "cyber_pentest", "silver", "quarterly", "ffp",
            [{"lcat_code": "PT-III", "hours": 56},
             {"lcat_code": "CA-II", "hours": 20},
             {"lcat_code": "PM-II", "hours": 4}],
            400,
            "Quarterly pentest under ITES-3S. IL5 environment."
        ),
        calc_scenario(
            "VA AI Analytics — Bronze MLOps (FFP Monthly)",
            "ai_ml_ops", "bronze", "monthly", "ffp",
            [{"lcat_code": "ML-II", "hours": 20}, {"lcat_code": "PM-II", "hours": 2}],
            1400,
            "VA predictive analytics model monitoring. 2 models in production."
        ),
        calc_scenario(
            "DoD DISA — Silver Help Desk (FFP Monthly)",
            "help_desk", "silver", "monthly", "ffp",
            [{"lcat_code": "HD-I", "hours": 400},
             {"lcat_code": "HD-II", "hours": 100},
             {"lcat_code": "PM-II", "hours": 6}],
            620,
            "Help desk for DISA field users. 500 seats, 12×5."
        ),
    ]

    conn.execute("DELETE FROM pricing_scenarios")
    for s in scenarios_data:
        conn.execute("""
            INSERT INTO pricing_scenarios
                (id, name, opportunity_id, package_id, indirect_rate_id,
                 service_line, tier, period, contract_type,
                 labor_hours, direct_labor_cost, fringe_cost, overhead_cost,
                 ga_cost, total_cost_before_fee, fee_amount, odc_cost,
                 total_price, breakeven_price, margin_amount, margin_pct,
                 notes, created_at, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            s["id"], s["name"], s["opportunity_id"], s["package_id"],
            s["indirect_rate_id"],
            s["service_line"], s["tier"], s["period"], s["contract_type"],
            s["labor_hours"], s["direct_labor_cost"], s["fringe_cost"],
            s["overhead_cost"], s["ga_cost"], s["total_cost_before_fee"],
            s["fee_amount"], s["odc_cost"], s["total_price"],
            s["breakeven_price"], s["margin_amount"], s["margin_pct"],
            s["notes"], now, now,
        ))
    print(f"  [+] Pricing scenarios: {len(scenarios_data)} demo scenarios seeded")

    conn.commit()


def main():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    print(f"Seeding pricing data -> {DB_PATH}")
    try:
        seed(conn)
        print("Done.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
