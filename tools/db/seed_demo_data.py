#!/usr/bin/env python3
# CUI // SP-PROPIN
"""Seed realistic GovCon demo data for ERP and CRM modules.

Creates:
  ERP:  10 employees (own/sub/partner), 18 skills, certifications,
        6 LCATs with DCAA-compliant rate cards, employee assignments
  CRM:  12 contacts across 6 relationship types, interaction history

Usage:
    python tools/db/seed_demo_data.py [--json]
"""

import argparse
import json
import os
import sqlite3
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent
DB_PATH = Path(os.environ.get(
    "GOVPROPOSAL_DB_PATH", str(BASE_DIR / "data" / "govproposal.db")
))


def _db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _id():
    return str(uuid.uuid4())


def _date(days_from_today=0):
    """Positive = future, negative = past."""
    return (date.today() + timedelta(days=days_from_today)).isoformat()


# ---------------------------------------------------------------------------
# ERP — Skills  (column: skill_name)
# ---------------------------------------------------------------------------
SKILLS = [
    # (skill_name, category, description)
    ("Cloud Architecture",        "Cloud",         "AWS GovCloud / Azure Government design"),
    ("Kubernetes / OpenShift",    "Cloud",         "Container orchestration and DevSecOps pipelines"),
    ("Terraform / IaC",           "Cloud",         "Infrastructure-as-code, multi-cloud"),
    ("Zero Trust Architecture",   "Cybersecurity", "NIST 800-207, ICAM, micro-segmentation"),
    ("SIEM / Log Analytics",      "Cybersecurity", "Splunk, ELK stack, threat detection"),
    ("Penetration Testing",       "Cybersecurity", "DISA STIG, vulnerability assessment"),
    ("Machine Learning / AI",     "AI/Data",       "Model development, MLOps, AWS Bedrock"),
    ("Data Engineering",          "AI/Data",       "ETL pipelines, Databricks, Spark"),
    ("Systems Engineering",       "Engineering",   "MBSE, SysML, digital thread"),
    ("Software Development",      "Engineering",   "Python, Java, Go — full stack"),
    ("Program Management",        "Management",    "PMP, EVM, IPT leadership"),
    ("Capture Management",        "Management",    "BD strategy, win themes, color reviews"),
    ("Technical Writing",         "Management",    "Proposals, SOWs, CDRLs"),
    ("FedRAMP / ATO",             "Compliance",    "SSP, POAM, continuous monitoring"),
    ("CMMC Level 2/3",            "Compliance",    "CUI handling, SPRS scoring"),
    ("SAP / ERP",                 "Enterprise",    "SAP S/4HANA, financial systems"),
    ("Network Engineering",       "Engineering",   "MPLS, SD-WAN, DISA STIG networks"),
    ("Training / Instruction",    "Management",    "Curriculum development, LMS"),
]

# ---------------------------------------------------------------------------
# ERP — LCATs  (columns: lcat_code, lcat_name, description, typical_skills)
#              Rates go into lcat_rates (no fully_burdened_rate column)
# ---------------------------------------------------------------------------
LCATS = [
    # (lcat_code, lcat_name, description, dlr, fringe, overhead, ga, fee, typical_skills)
    ("PM-SR",  "Program Manager",
     "Senior leader responsible for program execution, client relationships, and team oversight.",
     95.00, 0.28, 0.20, 0.12, 0.08, ["Program Management", "Capture Management"]),
    ("SE-SR",  "Senior Systems Engineer",
     "Lead technical architect — MBSE, systems design, requirements traceability.",
     88.00, 0.28, 0.20, 0.12, 0.08, ["Systems Engineering", "FedRAMP / ATO"]),
    ("CSA-SR", "Cloud Solutions Architect",
     "Design and implement cloud-native solutions on AWS GovCloud / Azure Government.",
     92.00, 0.28, 0.20, 0.12, 0.08, ["Cloud Architecture", "Kubernetes / OpenShift", "Terraform / IaC"]),
    ("CA-SR",  "Cybersecurity Analyst",
     "IA/ISSO functions, STIG compliance, continuous monitoring, incident response.",
     82.00, 0.28, 0.18, 0.12, 0.08, ["Zero Trust Architecture", "SIEM / Log Analytics", "FedRAMP / ATO"]),
    ("ML-SR",  "AI/ML Engineer",
     "Build, train, and deploy ML models in government environments.",
     98.00, 0.28, 0.20, 0.12, 0.08, ["Machine Learning / AI", "Data Engineering", "Cloud Architecture"]),
    ("SWE-JR", "Junior Software Developer",
     "Full-stack development under senior technical guidance.",
     58.00, 0.30, 0.22, 0.12, 0.08, ["Software Development"]),
]

# ---------------------------------------------------------------------------
# ERP — Employees
# ---------------------------------------------------------------------------
EMPLOYEES = [
    # own company
    dict(full_name="James Holloway",  email="jholloway@example.com",    job_title="Program Manager",
         company_type="own",     clearance_level="Top Secret",   lcat_code="PM-SR",
         skills=["Program Management", "Capture Management", "FedRAMP / ATO"]),
    dict(full_name="Priya Nair",       email="pnair@example.com",         job_title="Cloud Solutions Architect",
         company_type="own",     clearance_level="Secret",        lcat_code="CSA-SR",
         skills=["Cloud Architecture", "Kubernetes / OpenShift", "Terraform / IaC", "Zero Trust Architecture"]),
    dict(full_name="DeShawn Brooks",   email="dbrooks@example.com",       job_title="Senior Systems Engineer",
         company_type="own",     clearance_level="TS/SCI",        lcat_code="SE-SR",
         skills=["Systems Engineering", "Software Development", "FedRAMP / ATO"]),
    dict(full_name="Caitlin Torres",   email="ctorres@example.com",       job_title="AI/ML Engineer",
         company_type="own",     clearance_level="Secret",        lcat_code="ML-SR",
         skills=["Machine Learning / AI", "Data Engineering", "Cloud Architecture"]),
    dict(full_name="Raj Patel",        email="rpatel@example.com",        job_title="Cybersecurity Analyst",
         company_type="own",     clearance_level="TS/SCI",        lcat_code="CA-SR",
         skills=["Zero Trust Architecture", "SIEM / Log Analytics", "Penetration Testing", "CMMC Level 2/3"]),
    # subcontractors
    dict(full_name="Linda Osei",       email="losei@subco-tech.com",      job_title="Senior Software Developer",
         company_type="sub",     clearance_level="Secret",        lcat_code="SWE-JR",
         skills=["Software Development", "Cloud Architecture"]),
    dict(full_name="Tom Garrison",     email="tgarrison@subco-tech.com",  job_title="Network Engineer",
         company_type="sub",     clearance_level="Secret",        lcat_code="SE-SR",
         skills=["Network Engineering", "Zero Trust Architecture"]),
    # teaming partners
    dict(full_name="Angela Kim",       email="akim@partner-llc.com",     job_title="Technical Writer / PM",
         company_type="partner", clearance_level="Secret",        lcat_code="PM-SR",
         skills=["Technical Writing", "Program Management", "Training / Instruction"]),
    dict(full_name="Victor Sandoval",  email="vsandoval@partner-llc.com", job_title="Data Engineer",
         company_type="partner", clearance_level=None,            lcat_code="ML-SR",
         skills=["Data Engineering", "Machine Learning / AI", "SAP / ERP"]),
    dict(full_name="Michelle Okonkwo", email="mokonkwo@partner-llc.com",  job_title="Compliance Specialist",
         company_type="partner", clearance_level="Public Trust",  lcat_code="CA-SR",
         skills=["FedRAMP / ATO", "CMMC Level 2/3", "Technical Writing"]),
]

# Certifications: {employee_name: [(cert_name, issuer, expiry_days_from_today, issue_days_ago)]}
CERTS = {
    "James Holloway":   [("PMP",                      "PMI",         365,  -365*2)],
    "Priya Nair":       [("AWS Solutions Architect Pro","Amazon",     200,  -300),
                         ("CKA",                      "CNCF",        300,  -200)],
    "DeShawn Brooks":   [("CISSP",                    "ISC2",        400,  -365)],
    "Caitlin Torres":   [("AWS ML Specialty",          "Amazon",     250,  -200)],
    "Raj Patel":        [("CISSP",                    "ISC2",        400,  -365*2),
                         ("CEH",                      "EC-Council",  180,  -180)],
    "Michelle Okonkwo": [("CISA",                     "ISACA",       500,  -365)],
}

# ---------------------------------------------------------------------------
# CRM — Contacts
# ---------------------------------------------------------------------------
CRM_CONTACTS = [
    # competitors
    dict(full_name="Marcus Webb",       title="VP Business Development",
         company="SAIC",        agency="Army",      sub_agency="CECOM",            sector="Defense",
         rel="competitor",      email="mwebb@saic.com"),
    dict(full_name="Karen Briggs",      title="Capture Manager",
         company="Booz Allen",  agency="DHS",       sub_agency="CISA",             sector="DHS",
         rel="competitor",      email="kbriggs@bah.com"),
    # partners
    dict(full_name="Sarah Mitchell",    title="Contracting Officer Representative",
         company="Leidos",      agency="Army",      sub_agency="PEO C3T",          sector="Defense",
         rel="partner",         email="smitchell@leidos.com"),
    dict(full_name="David Nguyen",      title="BD Director",
         company="CACI",        agency="Navy",      sub_agency="NAVWAR",           sector="Defense",
         rel="partner",         email="dnguyen@caci.com"),
    # frienemy
    dict(full_name="Teresa Holt",       title="Senior VP Programs",
         company="Peraton",     agency="IC",        sub_agency="NSA",              sector="Intel",
         rel="frienemy",        email="tholt@peraton.com"),
    # customers / gov stakeholders
    dict(full_name="Col. Brian Marsh",  title="Program Executive Officer",
         company="U.S. Army",   agency="Army",      sub_agency="PEO C2S",          sector="Defense",
         rel="customer",        email="brian.marsh@army.mil"),
    dict(full_name="Donna Ashford",     title="Contracting Officer",
         company="DHS S&T",     agency="DHS",       sub_agency="S&T Directorate",  sector="DHS",
         rel="customer",        email="dashford@dhs.gov"),
    # vendors
    dict(full_name="Eric Tan",          title="Federal Account Executive",
         company="Palantir",    agency=None,        sub_agency=None,               sector="Commercial",
         rel="vendor",          email="etan@palantir.com"),
    dict(full_name="Simone Reyes",      title="Gov Sales Manager",
         company="Databricks",  agency=None,        sub_agency=None,               sector="Commercial",
         rel="vendor",          email="sreyes@databricks.com"),
    # prospects
    dict(full_name="Capt. Alexis Ford", title="IT Program Officer",
         company="USAF",        agency="Air Force", sub_agency="AFMC",             sector="Defense",
         rel="prospect",        email="alexis.ford@af.mil"),
    dict(full_name="Jerome Bailey",     title="Deputy CTO",
         company="VA",          agency="VA",        sub_agency="OIT",              sector="Civilian",
         rel="prospect",        email="jbailey@va.gov"),
    # mentor
    dict(full_name="Dr. Fiona Walsh",   title="Former SES / Independent Advisor",
         company="Self",        agency=None,        sub_agency=None,               sector="Civilian",
         rel="mentor",          email="fwalsh@consult.net",
         notes="Former SES at DoD CIO. Invaluable network across Army, Navy, and OSD."),
]

# Interaction history: {contact_name: [interaction_dicts]}
INTERACTIONS = {
    "Sarah Mitchell": [
        dict(itype="meeting", subject="AFCEA Industry Day", outcome="positive",
             notes="Met at Army C2 session. Strong teaming interest. RFP expected Q3.",
             next_action="Send capabilities deck", days_ago=14),
        dict(itype="call", subject="Teaming NDA Discussion", outcome="neutral",
             notes="Discussed NDA terms. Legal review underway on both sides.",
             next_action="Follow up on NDA signature", days_ago=7),
    ],
    "Col. Brian Marsh": [
        dict(itype="meeting", subject="Initial Requirements Meeting", outcome="positive",
             notes="CO confirmed $45M IDIQ re-compete targeting Q4. Expressed desire for cloud-native C2 approach. Strong fit for our capabilities.",
             next_action="Prepare capability briefing", days_ago=21),
        dict(itype="demo", subject="Cloud C2 Demo", outcome="positive",
             notes="Demo of containerized C2 stack on AWS GovCloud went extremely well. CO asked about FedRAMP High authorization timeline.",
             next_action="Draft technical white paper", days_ago=5),
    ],
    "Marcus Webb": [
        dict(itype="conference", subject="AUSA Annual", outcome="neutral",
             notes="Crossed paths at AUSA. SAIC pitching similar solution set. Key differentiator: our ZTA posture and IL5 certifications.",
             next_action=None, days_ago=30),
    ],
    "Karen Briggs": [
        dict(itype="note", subject="Intel from industry day", outcome="negative",
             notes="Booz Allen submitted a lowball price on the CISA SOC award. They appear willing to buy-in on this vehicle.",
             next_action="Review pricing strategy", days_ago=10),
    ],
    "Teresa Holt": [
        dict(itype="meeting", subject="Potential teaming — NSA IDIQ", outcome="positive",
             notes="Peraton leads the vehicle, needs a cloud-native sub. Good alignment if we can agree on work share (we want 35% min).",
             next_action="Send past performance matrix", days_ago=8),
    ],
    "Dr. Fiona Walsh": [
        dict(itype="call", subject="Monthly advisory call", outcome="positive",
             notes="Fiona flagged an incoming OSD cloud modernization RFI — not yet public. Recommended we get in front of the PM now.",
             next_action="Request meeting with OSD PM", days_ago=3),
    ],
    "Capt. Alexis Ford": [
        dict(itype="meeting", subject="Industry Engagement — AFMC IT Modernization", outcome="positive",
             notes="Early-stage requirements gathering. No RFP yet but budget is committed ($12M). Captain very interested in DevSecOps automation.",
             next_action="Send ICDEV product overview", days_ago=12),
    ],
}


# ---------------------------------------------------------------------------
# Seed functions
# ---------------------------------------------------------------------------

def seed_erp(conn):
    now = _now()
    created = {"skills": 0, "employees": 0, "certs": 0, "lcats": 0, "rates": 0, "assignments": 0}

    # Skills  (skill_name column)
    skill_ids = {}
    for skill_name, category, desc in SKILLS:
        row = conn.execute("SELECT id FROM skills WHERE skill_name = ?", (skill_name,)).fetchone()
        if row:
            skill_ids[skill_name] = row["id"]
        else:
            sid = _id()
            conn.execute(
                "INSERT INTO skills (id, skill_name, category, description, created_at) VALUES (?,?,?,?,?)",
                (sid, skill_name, category, desc, now)
            )
            skill_ids[skill_name] = sid
            created["skills"] += 1

    # LCATs  (lcat_code, lcat_name; rates separate)
    lcat_ids = {}
    for lcat_code, lcat_name, ldesc, dlr, fringe, oh, ga, fee, typical in LCATS:
        row = conn.execute("SELECT id FROM lcats WHERE lcat_code = ?", (lcat_code,)).fetchone()
        if row:
            lcat_ids[lcat_code] = row["id"]
        else:
            lid = _id()
            conn.execute("""
                INSERT INTO lcats (id, lcat_code, lcat_name, description, typical_skills,
                                   created_at)
                VALUES (?,?,?,?,?,?)
            """, (lid, lcat_code, lcat_name, ldesc, json.dumps(typical), now))
            lcat_ids[lcat_code] = lid
            created["lcats"] += 1

            # Rate card  (no fully_burdened_rate column)
            wrap = round(1 + fringe + oh + ga + fee, 4)
            conn.execute("""
                INSERT INTO lcat_rates (id, lcat_id, effective_date, direct_labor_rate,
                                        fringe_rate, overhead_rate, ga_rate, fee_rate,
                                        wrap_rate, cost_type, created_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """, (_id(), lid, _date(0), dlr, fringe, oh, ga, fee, wrap, "fixed_price", now))
            created["rates"] += 1

    # Employees
    emp_ids = {}
    for emp in EMPLOYEES:
        row = conn.execute("SELECT id FROM employees WHERE email = ?", (emp["email"],)).fetchone()
        if row:
            emp_ids[emp["full_name"]] = row["id"]
            continue

        eid = _id()
        conn.execute("""
            INSERT INTO employees (id, full_name, email, job_title, company_type,
                                   clearance_level, availability, status, created_at, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?)
        """, (eid, emp["full_name"], emp["email"], emp["job_title"],
              emp["company_type"], emp.get("clearance_level"),
              "available", "active", now, now))
        emp_ids[emp["full_name"]] = eid
        created["employees"] += 1

        # LCAT assignment  (column: effective_date, not start_date)
        lcat_code = emp.get("lcat_code")
        if lcat_code and lcat_code in lcat_ids:
            conn.execute("""
                INSERT OR IGNORE INTO employee_lcats
                    (id, employee_id, lcat_id, effective_date, is_primary, created_at)
                VALUES (?,?,?,?,?,?)
            """, (_id(), eid, lcat_ids[lcat_code], _date(-180), 1, now))
            created["assignments"] += 1

        # Skills  (no updated_at on employee_skills)
        for skill_name in emp.get("skills", []):
            if skill_name in skill_ids:
                conn.execute("""
                    INSERT OR IGNORE INTO employee_skills
                        (id, employee_id, skill_id, proficiency, created_at)
                    VALUES (?,?,?,?,?)
                """, (_id(), eid, skill_ids[skill_name], "advanced", now))

    # Certifications  (column: issue_date, not issued_date; no updated_at)
    for emp_name, certs in CERTS.items():
        eid = emp_ids.get(emp_name)
        if not eid:
            continue
        for cert_name, issuer, expiry_days, issue_days in certs:
            row = conn.execute(
                "SELECT id FROM certifications WHERE employee_id=? AND cert_name=?",
                (eid, cert_name)
            ).fetchone()
            if not row:
                expiry = _date(expiry_days)
                status = "active" if expiry >= _date(0) else "expired"
                conn.execute("""
                    INSERT INTO certifications
                        (id, employee_id, cert_name, issuing_body, issue_date,
                         expiry_date, status, created_at)
                    VALUES (?,?,?,?,?,?,?,?)
                """, (_id(), eid, cert_name, issuer,
                      _date(issue_days), expiry, status, now))
                created["certs"] += 1

    return created


def seed_crm(conn):
    now = _now()
    created = {"contacts": 0, "interactions": 0}

    rt_rows = conn.execute("SELECT id, type_name FROM relationship_types").fetchall()
    rt_map = {r["type_name"]: r["id"] for r in rt_rows}

    contact_ids = {}
    for c in CRM_CONTACTS:
        row = conn.execute(
            "SELECT id FROM contacts WHERE full_name=? AND company=?",
            (c["full_name"], c["company"])
        ).fetchone()
        if row:
            contact_ids[c["full_name"]] = row["id"]
            continue

        cid = _id()
        rt_id = rt_map.get(c["rel"])
        conn.execute("""
            INSERT INTO contacts (id, full_name, title, email, company,
                                  agency, sub_agency, sector, relationship_type_id,
                                  notes, status, created_at, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (cid, c["full_name"], c.get("title"), c.get("email"),
              c.get("company"), c.get("agency"), c.get("sub_agency"),
              c.get("sector"), rt_id, c.get("notes"), "active", now, now))
        contact_ids[c["full_name"]] = cid
        created["contacts"] += 1

    # Interactions  (no updated_at on interactions)
    for contact_name, ints in INTERACTIONS.items():
        cid = contact_ids.get(contact_name)
        if not cid:
            continue
        last_date = None
        for i in ints:
            idate = _date(-i["days_ago"])
            conn.execute("""
                INSERT INTO interactions
                    (id, contact_id, interaction_date, interaction_type,
                     subject, notes, outcome, next_action, created_at)
                VALUES (?,?,?,?,?,?,?,?,?)
            """, (_id(), cid, idate, i["itype"], i.get("subject"),
                  i["notes"], i.get("outcome"), i.get("next_action"), now))
            created["interactions"] += 1
            if last_date is None or idate > last_date:
                last_date = idate

        if last_date:
            conn.execute(
                "UPDATE contacts SET last_contact_date=?, updated_at=? WHERE id=?",
                (last_date, now, cid)
            )

    return created


def run_seed():
    if not DB_PATH.exists():
        return {"success": False, "error": f"DB not found: {DB_PATH}"}

    conn = _db()
    try:
        erp = seed_erp(conn)
        crm = seed_crm(conn)
        conn.commit()
        return {"success": True, "erp": erp, "crm": crm, "db": str(DB_PATH)}
    except Exception as e:
        conn.rollback()
        import traceback
        return {"success": False, "error": str(e), "trace": traceback.format_exc()}
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(description="Seed ERP/CRM demo data")
    parser.add_argument("--json", action="store_true", dest="json_out")
    args = parser.parse_args()

    result = run_seed()

    if args.json_out:
        print(json.dumps(result, indent=2))
    else:
        if result.get("success"):
            e = result["erp"]
            c = result["crm"]
            print("Demo data seeded successfully")
            print(f"  ERP: {e['employees']} employees  |  {e['skills']} skills  |  "
                  f"{e['lcats']} LCATs  |  {e['rates']} rate cards  |  "
                  f"{e['certs']} certs  |  {e['assignments']} LCAT assignments")
            print(f"  CRM: {c['contacts']} contacts  |  {c['interactions']} interactions")
        else:
            print(f"FAILED: {result.get('error')}")
            if result.get("trace"):
                print(result["trace"])
            raise SystemExit(1)


if __name__ == "__main__":
    main()
