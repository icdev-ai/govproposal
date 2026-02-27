#!/usr/bin/env python3
# CUI // SP-PROPIN
"""
GovProposal Demo Seeder
=======================
Seeds the live GovProposal DB with 5 RFP/RFI opportunities spread across
every Kanban stage, culminating in a fully awarded proposal with a CLIN
pricing table.

  Opportunity 1 — DISA Zero Trust Network Access Platform    → AWARDED  (showcase)
  Opportunity 2 — DHS CISA Cyber Incident Response Platform  → GOLD REVIEW
  Opportunity 3 — VA Digital Modernization Initiative (RFI)  → RED REVIEW
  Opportunity 4 — DoD AI/ML Operations Platform              → PINK REVIEW
  Opportunity 5 — NSF Research Data Analytics Platform       → DRAFT

Calls llm_bridge.generate_section() for key AI sections (real LLM).
Falls back to rich pre-written content if LLM is unavailable.

Usage:
    python seed_demo.py          # seed everything
    python seed_demo.py --wipe   # remove previous demo data first
"""

import argparse
import hashlib
import json
import os
import sqlite3
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Force UTF-8 output on Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = Path(os.environ.get("GOVPROPOSAL_DB_PATH",
               str(BASE_DIR / "data" / "govproposal.db")))
sys.path.insert(0, str(BASE_DIR))

DEMO_TAG = "NEXUS-DEMO-2026"


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _conn():
    c = sqlite3.connect(str(DB_PATH))
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA foreign_keys=ON")
    return c


def uid():
    return str(uuid.uuid4())


def fake_hash(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


_NOW = datetime.now(timezone.utc)


def dt(days=0, hours=0):
    return (_NOW + timedelta(days=days, hours=hours)).strftime("%Y-%m-%d %H:%M:%S")


def d(days=0):
    return (_NOW + timedelta(days=days)).strftime("%Y-%m-%d")


# ─────────────────────────────────────────────────────────────────────────────
# LLM wrapper (real call + fallback)
# ─────────────────────────────────────────────────────────────────────────────

def llm_section(title, volume, rfp_ctx, themes, prop_id, fallback):
    """Call generate_section(); returns real LLM content or fallback."""
    try:
        from tools.rfx.llm_bridge import generate_section
        print(f"    [LLM] Generating: {title} ...", end="", flush=True)
        result = generate_section(
            section_title=title,
            volume=volume,
            rfp_context=rfp_ctx,
            rag_chunks=[],
            kb_entries=[],
            win_themes=themes,
            proposal_id=prop_id,
        )
        content = (result.get("content_draft") or "").strip()
        # Treat router error strings as empty so pre-written fallback is used
        if not content or content.startswith("[LLM error") or content.startswith("[LLM unavailable") or len(content) < 200:
            content = fallback
            print(f" [fallback — no real LLM] {len(content)} chars [OK]")
        else:
            print(f" {len(content)} chars [OK]")
        return content
    except Exception as e:
        print(f" [fallback] {e}")
        return fallback


# ─────────────────────────────────────────────────────────────────────────────
# Static content fallbacks
# ─────────────────────────────────────────────────────────────────────────────

FALLBACK = {
    # ── DISA ──────────────────────────────────────────────────────────────────
    ("prop-disa-zt-001", "executive_summary"): """\
CUI // SP-PROPIN

EXECUTIVE SUMMARY — Zero Trust Network Access Platform (ZTNAP)
Solicitation HC1047-25-R-0042 | Defense Information Systems Agency

Nexus Federal Solutions proposes a proven, enterprise-scale Zero Trust Network Access Platform
that will replace DISA's legacy VPN infrastructure across 300+ DoD installations while reducing
lateral movement risk by 94% within the first 12 months.

Our solution is built on three discriminating pillars:

1. PROVEN ZTA AT SCALE. We have deployed ZTA solutions protecting 50,000+ DoD endpoints across
   three active task orders. Our architecture meets DISA's Zero Trust Reference Architecture v2.0
   and DoD ZT Strategy 2022 without requiring a forklift replacement of existing network infrastructure.

2. LOWEST RISK. Our team is 100% cleared (TS/SCI), on-contract, and available for transition within
   30 days of award. We have zero subcontractor dependency risk on critical path activities.

3. BEST VALUE. Our AWS Enterprise Discount Program pricing delivers a 10% cost reduction against
   GSA schedule rates, bringing total contract value to $47.2M — the most competitive pricing
   DISA will receive while meeting all technical requirements.

We are ready to mobilize immediately. Our program leadership, Cleared Cloud Architect, and senior
systems engineering team will be on-site at Fort Meade within 30 days of award.

CUI // SP-PROPIN""",

    ("prop-disa-zt-001", "technical"): """\
CUI // SP-PROPIN

SECTION C.2 — TECHNICAL APPROACH: ZERO TRUST NETWORK ACCESS PLATFORM

2.1 ZERO TRUST ARCHITECTURE DESIGN

Nexus Federal Solutions will implement a DISA-compliant Zero Trust architecture using our
proprietary ZT-Alpha methodology, which maps directly to all seven pillars of the DoD Zero
Trust Strategy (Users, Devices, Networks/Environment, Applications/Workloads, Data, Automation
& Orchestration, Visibility & Analytics).

Our implementation leverages a three-layer trust enforcement model:

  Layer 1 — Identity Verification: CAC/PIV integration with DISA's existing ICAM infrastructure
  (DISA GovCloud Active Directory Federation Services). Multi-factor authentication enforced
  at every access request with continuous session risk scoring.

  Layer 2 — Device Posture Assessment: Continuous compliance checks against DISA STIGs via
  CrowdStrike Falcon for Government (FedRAMP High authorized). Non-compliant devices quarantined
  automatically within 90 seconds of posture degradation.

  Layer 3 — Microsegmentation: Zscaler Private Access (ZPA) enforces least-privilege access
  to all DISA applications. Software-defined perimeter replaces legacy VPN tunnels. No implicit
  trust granted based on network location.

2.2 PHASED IMPLEMENTATION APPROACH

Phase 1 (Months 1–4): Foundation
  • Deploy ZTNAP core infrastructure in AWS GovCloud (us-gov-west-1)
  • Integrate with DISA PKI, ICAM, and Active Directory
  • Pilot with 5,000 endpoints across 3 DISA pilot sites
  • Achieve FedRAMP High ATO on all platform components

Phase 2 (Months 5–8): Expansion
  • Roll out to 150,000 endpoints across 150 CONUS installations
  • Implement Splunk SIEM integration for real-time ZT telemetry
  • Deploy SOAR playbooks for automated threat response
  • Establish DISA CSSP-compliant continuous monitoring

Phase 3 (Months 9–12): Full Deployment
  • Complete deployment to 300+ DoD installations globally
  • Achieve operational capability for all OCONUS locations
  • Deliver final compliance documentation (SSP, POAM, A&A package)
  • Transition to steady-state O&M operations

2.3 SECURITY AND COMPLIANCE

All platform components will maintain FedRAMP High authorization. Our team holds active
DISA STIG compliance across all 47 applicable STIGs. We will deliver a complete ATO package
including SSP, POAM, SAR, and continuous monitoring reports within 30 days of deployment.

CUI // SP-PROPIN""",

    ("prop-disa-zt-001", "management"): """\
CUI // SP-PROPIN

SECTION C.3 — MANAGEMENT APPROACH

3.1 PROGRAM MANAGEMENT STRUCTURE

James Holloway, PMP (TS/SCI), will serve as Program Manager with direct authority over
all contract resources and deliverables. Mr. Holloway brings 18 years of DISA program management
experience including three prior DISA task orders with a combined value of $85M.

Priya Nair, AWS GovCloud Certified Solutions Architect, will serve as Technical Lead and Deputy PM.
Ms. Nair designed and deployed the ZTA solution now protecting 28,000 DISA endpoints at Fort Meade.

Reporting Structure:
  • PM (Holloway) → DISA Contracting Officer Representative (COR)
  • PM → Technical Lead (Nair) → Integrated Product Teams (ZTA, DevSecOps, Ops)
  • PM → Subcontractor Leads (Linda Osei, SWE; Michelle Okonkwo, Cybersecurity)

3.2 INTEGRATED PROJECT TEAM (IPT) STRUCTURE

Three IPTs will manage the work, each led by a senior engineer with TS/SCI clearances:

  ZTA Architecture IPT: 2 Cloud Architects + 3 Systems Engineers
  DevSecOps IPT: 2 AI/ML Engineers + 4 Software Developers
  Cyber Operations IPT: 3 Cybersecurity Analysts + 2 SIEM Engineers

3.3 RISK MANAGEMENT

Top-3 Risks Identified and Mitigated:

  RISK 1 — Integration with Legacy DISA Systems (Medium/High)
    Mitigation: 90-day discovery sprint in Months 1-3. Full API catalog completed before
    Phase 2 deployment. Technical Lead has direct experience with DISA HAIPE and TACLANE systems.

  RISK 2 — Cleared Personnel Availability (Low/Medium)
    Mitigation: All key personnel are on-contract today. Zero reliance on recruiting for
    critical path activities. Backup-cleared personnel identified for all key roles.

  RISK 3 — FedRAMP ATO Timeline (Medium)
    Mitigation: Three of our four proposed cloud services (AWS GovCloud, Zscaler ZPA,
    CrowdStrike Falcon) are already FedRAMP High authorized. ATO risk limited to SIEM integration.

CUI // SP-PROPIN""",

    ("prop-disa-zt-001", "past_performance"): """\
CUI // SP-PROPIN

SECTION C.4 — PAST PERFORMANCE

Nexus Federal Solutions submits three recent and relevant past performance references
that directly demonstrate our capability to perform this contract.

────────────────────────────────────────────────────────────────────────────────
REFERENCE 1: DISA Zero Trust Pilot — Task Order HC1047-23-F-0018
Contract Value:   $12.4M
Period:           Jan 2023 – Present (active)
Agency POC:       Col. Brian Marsh, DISA J6, (571) 305-XXXX, brian.marsh@disa.mil
Summary: Deployed ZTA protecting 28,000 DISA endpoints at Fort Meade. Implemented
Zscaler ZPA, CrowdStrike Falcon, and Splunk SIEM integration. Delivered Phase 1
30 days ahead of schedule. Achieved FedRAMP High ATO in 4 months. CPARS rating: Outstanding.
────────────────────────────────────────────────────────────────────────────────

REFERENCE 2: Army Zero Trust Network Segmentation — W911NF-22-D-0012, Task Order 0003
Contract Value:   $31.8M
Period:           Oct 2022 – Sep 2025 (complete)
Agency POC:       Col. Brian Marsh (rotated from DISA), (571) 305-XXXX
Summary: Deployed microsegmentation across 22 Army installations protecting 65,000 devices.
Zero critical incidents during transition. 99.97% uptime during 36-month performance period.
CPARS rating: Outstanding.
────────────────────────────────────────────────────────────────────────────────

REFERENCE 3: DHS CISA Security Operations Center Modernization — 70RCSA-21-D-00156
Contract Value:   $18.6M
Period:           Mar 2021 – Dec 2024 (complete)
Agency POC:       Donna Ashford, DHS S&T, (202) 254-XXXX, donna.ashford@hq.dhs.gov
Summary: Deployed and sustained CISA's national SOC infrastructure. Integrated 200+ SOAR
playbooks. Reduced Mean Time to Respond (MTTR) from 4.2 hours to 1.4 hours. Zero data
breaches during performance period. CPARS rating: Very Good.
────────────────────────────────────────────────────────────────────────────────

CUI // SP-PROPIN""",

    ("prop-disa-zt-001", "cost"): None,  # built dynamically with CLIN table

    # ── DHS ───────────────────────────────────────────────────────────────────
    ("prop-dhs-cir-001", "technical"): """\
CUI // SP-PROPIN

SECTION C.2 — TECHNICAL APPROACH: CYBER INCIDENT RESPONSE PLATFORM

Nexus Federal Solutions proposes a cloud-native Cyber Incident Response Platform (CIRP)
leveraging open-standard SOAR architecture, pre-built CISA playbooks, and real-time threat
intelligence feeds to reduce CISA SOC Mean Time to Respond (MTTR) from the current 4.2 hours
to under 45 minutes within 90 days of deployment.

KEY TECHNICAL DIFFERENTIATORS:

  1. 200+ Pre-Built Playbooks: Our proprietary SOAR playbook library covers all 22 CISA
     Incident Categories. Playbooks are modular, STIX/TAXII compatible, and auto-trigger
     on SIEM correlation alerts with zero analyst intervention required for Tier 1 events.

  2. Threat Intelligence Integration: Real-time feeds from CISA AIS, DHS EINSTEIN 3A,
     MITRE ATT&CK Navigator, and 14 commercial threat intel providers. Contextual enrichment
     reduces false positive rate by 73%.

  3. Federated Architecture: Supports classification boundaries (CUI, Secret, TS) with
     automated data diode enforcement. Replicated across two AZs in AWS GovCloud for 99.99%
     availability.

IMPLEMENTATION TIMELINE: 120-day deployment to full operational capability.

CUI // SP-PROPIN""",

    ("prop-dhs-cir-001", "management"): """\
CUI // SP-PROPIN

SECTION C.3 — MANAGEMENT APPROACH: DHS CIRP

James Holloway (PM) and Raj Patel (Technical Lead, CISSP, CEH) will lead this effort.
Raj brings 8 years of direct CISA SOC experience as an on-site contractor and understands
CISA's existing tool stack, personnel workflows, and escalation procedures.

Program Controls:
  • Weekly status reports delivered to CISA COR every Monday by 0900 EST
  • Bi-weekly sprint reviews with CISA SOC leadership
  • Monthly EVM reports (CPI/SPI baseline at month 3)
  • Integrated Master Schedule maintained in MS Project, shared via SharePoint

Quality Assurance:
  All deliverables reviewed by independent QA team before submission.
  Target defect rate: < 2% on initial delivery.

CUI // SP-PROPIN""",

    ("prop-dhs-cir-001", "cost"): """\
CUI // SP-PROPIN

SECTION B — PRICE/COST: DHS CYBER INCIDENT RESPONSE PLATFORM

CONTRACT TYPE: Time & Material (T&M) with Not-to-Exceed (NTE) ceiling

BASE PERIOD (12 months) — NTE: $10,842,400
  Labor: $9,218,200 | ODCs: $1,624,200

OPTION YEAR 1 (12 months) — NTE: $10,620,000
OPTION YEAR 2 (12 months) — NTE: $10,950,000

TOTAL NTE (Base + 2 Options): $32,412,400

LABOR RATE SCHEDULE (fully burdened):
  Program Manager (PM-SR):     $228.48/hr
  Cybersecurity Analyst (CA-SR): $197.33/hr
  SIEM Engineer (SE-SR):       $211.42/hr
  Software Developer (SWE-JR): $139.54/hr
  Technical Writer:            $149.82/hr

SMALL BUSINESS PARTICIPATION: 38% of total labor hours subcontracted to
Linda Osei (SWE) and Michelle Okonkwo (Cybersecurity) — both SB certified.

*PENDING FINAL PRICING REVIEW — DO NOT RELEASE*

CUI // SP-PROPIN""",

    # ── VA ────────────────────────────────────────────────────────────────────
    ("prop-va-dm-001", "executive_summary"): """\
CUI // SP-PROPIN

RFI RESPONSE — VA DIGITAL MODERNIZATION INITIATIVE
Solicitation: 36C10B25I0001 | Department of Veterans Affairs

Nexus Federal Solutions is uniquely positioned to support VA OIT's COBOL modernization
initiative. Our team has successfully migrated 4 million lines of COBOL to modern Java
microservices across two federal legacy modernization programs — with zero service disruption
to end users during transition.

RECOMMENDED APPROACH: Strangler Fig pattern with parallel-run validation
  • Month 1-3: Application discovery, dependency mapping, business rule extraction
  • Month 4-9: Incremental microservice replacement with live traffic validation
  • Month 10-18: Legacy system decommission and cost savings realization

We estimate VA can achieve $8.2M in annual operational savings by Year 3 through
elimination of COBOL mainframe hosting costs and reduced maintenance burden.

CUI // SP-PROPIN""",

    ("prop-va-dm-001", "technical"): """\
CUI // SP-PROPIN

SECTION C.2 — TECHNICAL APPROACH: VA COBOL MODERNIZATION

MODERNIZATION METHODOLOGY: AI-Assisted Strangler Fig

Our approach uses AI-powered COBOL analysis tools to extract 100% of business rules
from legacy code before writing a single line of replacement code. This eliminates the
#1 risk in modernization: undocumented business logic buried in 40-year-old COBOL.

TOOL STACK:
  • IBM Watsonx Code Assistant for Z (COBOL analysis and translation)
  • AWS Application Migration Service (infrastructure lift)
  • Spring Boot + Java 21 (target microservice framework)
  • PostgreSQL on RDS for Government (data migration)

RISK MITIGATION: Parallel-run architecture runs legacy and modern systems simultaneously
for 90 days, comparing outputs line-by-line before cutover. Zero downtime guaranteed.

CUI // SP-PROPIN""",

    # ── DoD ───────────────────────────────────────────────────────────────────
    ("prop-dod-aiml-001", "executive_summary"): """\
CUI // SP-PROPIN

EXECUTIVE SUMMARY — DoD AI/ML OPERATIONS PLATFORM
Solicitation W911NF25R0002 | DoD Chief Digital and AI Office (CDAO)

Nexus Federal Solutions proposes an enterprise AI/ML Operations Platform that enables
DoD to govern, deploy, and monitor AI/ML models across classification boundaries from
NIPR to SECRET to TS/SCI — a capability no other offeror can demonstrate today.

THREE DISCRIMINATORS:

  1. MULTI-DOMAIN AI OPERATIONS: Our MLOps platform is the only solution with active
     deployments on NIPRNET, SIPRNET, and JWICS. Classification-aware model registry
     prevents accidental cross-domain data leakage.

  2. RESPONSIBLE AI BUILT IN: Automated bias detection, explainability reports, and
     DoD AI Principles compliance scoring are embedded in every model deployment pipeline.
     Satisfies all OMB M-24-10 responsible AI requirements.

  3. PROVEN TEAM: Caitlin Torres (ML-SR, PhD, TS/SCI) serves on the DoD AI Steering
     Committee and co-authored the Responsible AI Deployment Framework adopted by CDAO.

*DRAFT — PINK REVIEW IN PROGRESS — DO NOT DISTRIBUTE*

CUI // SP-PROPIN""",
}

# CLIN table embedded in DISA cost section
DISA_CLIN_TABLE = """\
CUI // SP-PROPIN

SECTION B — CONTRACT LINE ITEMS (CLINs) & PRICE/COST
Solicitation: HC1047-25-R-0042 | Contractor: Nexus Federal Solutions

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TOTAL CONTRACT VALUE (BASE + 4 OPTION YEARS): $47,216,800
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

─── CLIN SUMMARY TABLE ────────────────────────────────────────────────────────
CLIN   Description                                    Type  Period         Total
────── ─────────────────────────────────────────────  ────  ────────────   ──────────────
0001   Program Management — Base Year                 FFP   12 months      $1,842,240
0002   Zero Trust Architecture & Engineering          FFP   12 months      $5,618,960
0003   Platform Development & Integration             FFP   12 months      $3,224,680
0004   Cybersecurity Operations Center                FFP   12 months      $2,891,520
0005   Training, Documentation & Transition           FFP   12 months        $748,320
1001   O&M Program Management — Option Year 1         FFP   12 months      $1,906,716
1002   O&M Technical Operations — Option Year 1       FFP   12 months      $6,025,710
2001   O&M Program Management — Option Year 2         FFP   12 months      $1,972,451
2002   O&M Technical Operations — Option Year 2       FFP   12 months      $6,236,610
3001   O&M Program Management — Option Year 3         FFP   12 months      $2,040,987
3002   O&M Technical Operations — Option Year 3       FFP   12 months      $6,454,892
4001   O&M Program Management — Option Year 4         FFP   12 months      $2,112,421
4002   O&M Technical Operations — Option Year 4       FFP   12 months      $6,680,713
9001   Travel (All Periods)                           CPFF  Base+Options     $281,600
9002   Other Direct Costs (SW Licenses, Cloud Infra)  CPFF  Base+Options   $4,484,980
                                                                         ──────────────
                                          TOTAL CONTRACT VALUE:          $47,216,800
─── DETAILED LABOR — BASE YEAR ────────────────────────────────────────────────
CLIN   Labor Category                    FTE  Hrs    DLR    Mult   Burd.Rate   Total
────── ──────────────────────────────── ──── ──────  ─────  ─────  ─────────   ───────────
0001   Program Manager (PM-SR)           1.0  2,080  $95.00  1.935  $183.83   $382,366
0001   Deputy PM / Capture Lead (PM-SR)  0.5  1,040  $95.00  1.935  $183.83   $191,183
0001   Contracts & Admin Support         0.5  1,040  $68.00  1.935  $131.58   $136,843
       CLIN 0001 Labor Subtotal                                               $710,392

0002   Cloud Solutions Architect (CSA)   2.0  4,160  $92.00  1.935  $178.02   $740,563
0002   Senior Systems Engineer (SE-SR)   3.0  6,240  $88.00  1.935  $170.28  $1,062,547
0002   Cybersecurity Analyst ZTA (CA)    2.0  4,160  $82.00  1.935  $158.67   $660,067
       CLIN 0002 Labor Subtotal                                              $2,463,177

0003   AI/ML Engineer (ML-SR)            2.0  4,160  $98.00  1.935  $189.63   $788,861
0003   Software Developer Jr (SWE-JR)    4.0  8,320  $58.00  1.935  $112.23   $933,754
       CLIN 0003 Labor Subtotal                                              $1,722,615

0004   Cybersecurity Ops Analyst (CA)    3.0  6,240  $82.00  1.935  $158.67   $990,101
0004   SIEM/SOAR Engineer (SE-SR)        2.0  4,160  $88.00  1.935  $170.28   $708,365
       CLIN 0004 Labor Subtotal                                              $1,698,466

0005   Technical Writer / Trainer        1.0  2,080  $62.00  1.935  $119.97   $249,538
       CLIN 0005 Labor Subtotal                                               $249,538

                                         BASE YEAR LABOR TOTAL:            $6,844,188
─── OTHER DIRECT COSTS — BASE YEAR ───────────────────────────────────────────
Item     Description                          Qty    Unit Price    Total
──────── ──────────────────────────────────── ────   ──────────    ──────────
9001.AA  TDY Travel (12 trips × $4,200 avg)   12     $4,200        $50,400
9002.AA  AWS GovCloud Infrastructure           12 mo  $38,500/mo   $462,000
9002.AB  Zscaler ZIA/ZPA Enterprise License    1 yr   $284,000     $284,000
9002.AC  Splunk Cloud (SIEM) Gov License        1 yr   $196,000     $196,000
9002.AD  CrowdStrike Falcon Gov License         1 yr   $124,000     $124,000
9002.AE  Tenable.sc (Vulnerability Mgmt)        1 yr    $68,000      $68,000

         BASE YEAR ODC TOTAL:                                      $1,184,400
─── WRAP RATE BASIS ───────────────────────────────────────────────────────────
  Direct Labor Rate (DLR)  =  market salary / 2,080 hrs
  Fringe Benefits           =  28.0%  (medical, dental, 401k, FICA, PTO)
  Overhead (OH)             =  20.5%  (indirect labor, facilities, equipment)
  G&A                       =  12.0%  (exec, BD, finance, legal)
  Fee (Profit)              =   8.0%  (FFP contract risk premium)
  ─────────────────────────────────────────────────────────────────────────
  Multiplier = (1 + 0.28) × (1 + 0.205) × (1 + 0.12) × (1 + 0.08) = 1.935

─── OPTION YEAR ESCALATION ────────────────────────────────────────────────────
  Labor escalation: 3.5% per option year (COLA + merit pool)
  Cloud ODCs repriced annually per AWS EDP agreement
  AWS Enterprise Discount Program (EDP): 12% reduction on compute

─── SMALL BUSINESS SUBCONTRACTING PLAN ───────────────────────────────────────
  Prime (Nexus Federal Solutions):  58%  ($27.4M)
  Linda Osei (SWE, SB):             22%  ($10.4M)
  Michelle Okonkwo (Cyber, SB):     20%   ($9.4M)
  Total SB Participation:           42%  ($19.8M)  ← exceeds FAR 52.219-9 goal

*Pricing is source-selection sensitive. Marked CUI // SP-PROPIN.
 Authorized disclosure: DISA Source Selection Evaluation Board only.*

CUI // SP-PROPIN"""


# ─────────────────────────────────────────────────────────────────────────────
# DATA DEFINITIONS
# ─────────────────────────────────────────────────────────────────────────────

OPPORTUNITIES = [
    {
        "id": "opp-disa-zt-001",
        "sam_notice_id": "DISA-2025-ZT-0042",
        "title": "Zero Trust Network Access Platform (ZTNAP) Enterprise Deployment",
        "solicitation_number": "HC1047-25-R-0042",
        "agency": "Defense Information Systems Agency",
        "sub_agency": "DISA Infrastructure Directorate",
        "naics_code": "541512",
        "set_aside_type": "Full and Open",
        "contract_type": "FFP",
        "opportunity_type": "solicitation",
        "description": (
            "DISA seeks an enterprise Zero Trust Network Access Platform to replace legacy "
            "VPN infrastructure across 300+ DoD installations. Includes architecture, "
            "implementation, and 4 option years of O&M. Requires FedRAMP High, DISA STIG, "
            "and ZTA Reference Architecture v2.0 compliance."
        ),
        "response_deadline": d(-45),
        "posted_date": d(-120),
        "pop_start": d(-30),
        "pop_end": d(-30 + 365 * 5),
        "estimated_value_low": 42000000,
        "estimated_value_high": 52000000,
        "place_of_performance": "Fort Meade, MD / CONUS DISA Sites",
        "status": "awarded",
        "fit_score": 0.94,
        "qualification_score": 0.91,
        "go_decision": "go",
        "go_decision_rationale": (
            "Strong past performance with DoD ZTA programs. NAICS 541512 matches primary LCAT. "
            "94% probability of win with discriminating ZT architecture."
        ),
        "go_decision_by": "James Holloway",
        "go_decision_at": dt(-110),
        "metadata": json.dumps({"demo": DEMO_TAG}),
    },
    {
        "id": "opp-dhs-cir-001",
        "sam_notice_id": "DHS-CISA-2025-CIRP-089",
        "title": "Cyber Incident Response Platform (CIRP) — CISA SOC Modernization",
        "solicitation_number": "70RCSA25R00089",
        "agency": "Department of Homeland Security",
        "sub_agency": "CISA",
        "naics_code": "541512",
        "set_aside_type": "Small Business Set-Aside",
        "contract_type": "T&M",
        "opportunity_type": "solicitation",
        "description": (
            "CISA requires a modernized Cyber Incident Response Platform integrating automated "
            "threat detection, SOAR playbook orchestration, and real-time reporting for the "
            "National Cybersecurity Operations Center (NCOC). Must integrate with EINSTEIN 3A."
        ),
        "response_deadline": d(18),
        "posted_date": d(-60),
        "pop_start": d(45),
        "pop_end": d(45 + 365 * 3),
        "estimated_value_low": 28000000,
        "estimated_value_high": 35000000,
        "place_of_performance": "Arlington, VA / Remote",
        "status": "gold_review",
        "fit_score": 0.87,
        "qualification_score": 0.85,
        "go_decision": "go",
        "go_decision_rationale": (
            "Incumbent advantage. Team has SIEM/SOAR expertise. Competitive pricing for SB set-aside."
        ),
        "go_decision_by": "Priya Nair",
        "go_decision_at": dt(-55),
        "metadata": json.dumps({"demo": DEMO_TAG}),
    },
    {
        "id": "opp-va-dm-001",
        "sam_notice_id": "VA-OIT-2025-RFI-001",
        "title": "Digital Modernization Initiative — Legacy System Migration (RFI)",
        "solicitation_number": "36C10B25I0001",
        "agency": "Department of Veterans Affairs",
        "sub_agency": "VA Office of Information Technology",
        "naics_code": "541519",
        "set_aside_type": "Service-Disabled Veteran-Owned Small Business",
        "contract_type": "IDIQ",
        "opportunity_type": "rfi",
        "description": (
            "VA OIT seeks information on approaches to modernize legacy COBOL-based benefits "
            "processing systems. Potential follow-on RFP estimated at $22M. Responses will "
            "inform acquisition strategy. SDVOSB set-aside anticipated for follow-on."
        ),
        "response_deadline": d(10),
        "posted_date": d(-30),
        "pop_start": d(90),
        "pop_end": d(90 + 365 * 3),
        "estimated_value_low": 18000000,
        "estimated_value_high": 26000000,
        "place_of_performance": "Washington, DC / Remote",
        "status": "red_review",
        "fit_score": 0.78,
        "qualification_score": 0.76,
        "go_decision": "go",
        "go_decision_rationale": (
            "RFI response positions us for follow-on RFP. SDVOSB aligns with team composition."
        ),
        "go_decision_by": "DeShawn Brooks",
        "go_decision_at": dt(-25),
        "metadata": json.dumps({"demo": DEMO_TAG}),
    },
    {
        "id": "opp-dod-aiml-001",
        "sam_notice_id": "DOD-CDAO-2025-AIML-002",
        "title": "AI/ML Operations Platform — DoD Enterprise Deployment",
        "solicitation_number": "W911NF25R0002",
        "agency": "Department of Defense",
        "sub_agency": "Chief Digital and AI Office (CDAO)",
        "naics_code": "541715",
        "set_aside_type": "Full and Open",
        "contract_type": "CPFF",
        "opportunity_type": "solicitation",
        "description": (
            "DoD CDAO requires an enterprise AI/ML Operations Platform for model lifecycle "
            "management, responsible AI governance, and federated learning across classified "
            "and unclassified networks. Must support NIPR, SIPR, and JWICS."
        ),
        "response_deadline": d(35),
        "posted_date": d(-15),
        "pop_start": d(90),
        "pop_end": d(90 + 365 * 5),
        "estimated_value_low": 52000000,
        "estimated_value_high": 65000000,
        "place_of_performance": "Arlington, VA / CONUS",
        "status": "pink_review",
        "fit_score": 0.82,
        "qualification_score": 0.80,
        "go_decision": "go",
        "go_decision_rationale": (
            "Core competency in AI/ML. Team has two ML engineers with DoD experience."
        ),
        "go_decision_by": "Caitlin Torres",
        "go_decision_at": dt(-10),
        "metadata": json.dumps({"demo": DEMO_TAG}),
    },
    {
        "id": "opp-nsf-rdap-001",
        "sam_notice_id": "NSF-OD-2025-RDAP-001",
        "title": "Research Data Analytics Platform — NSF Open Science Initiative",
        "solicitation_number": "2500001",
        "agency": "National Science Foundation",
        "sub_agency": "NSF Office of the Director",
        "naics_code": "541511",
        "set_aside_type": "Small Business Set-Aside",
        "contract_type": "FFP",
        "opportunity_type": "solicitation",
        "description": (
            "NSF seeks a cloud-native Research Data Analytics Platform to aggregate, process, "
            "and visualize multi-disciplinary research datasets. Includes REST API development, "
            "interactive dashboard, and researcher training program."
        ),
        "response_deadline": d(55),
        "posted_date": d(-5),
        "pop_start": d(120),
        "pop_end": d(120 + 365 * 2),
        "estimated_value_low": 8500000,
        "estimated_value_high": 10500000,
        "place_of_performance": "Alexandria, VA / Remote",
        "status": "capture",
        "fit_score": 0.71,
        "qualification_score": 0.68,
        "go_decision": "go",
        "go_decision_rationale": (
            "Good fit for junior team development. Low risk, strong reference for future NSF work."
        ),
        "go_decision_by": "Angela Kim",
        "go_decision_at": dt(-3),
        "metadata": json.dumps({"demo": DEMO_TAG}),
    },
]

PROPOSALS = [
    {
        "id": "prop-disa-zt-001",
        "opportunity_id": "opp-disa-zt-001",
        "title": "Technical and Management Proposal: Zero Trust Network Access Platform",
        "status": "awarded",
        "volumes": json.dumps(["executive_summary", "technical", "management",
                                "past_performance", "cost"]),
        "classification": "CUI // SP-PROPIN",
        "cag_status": "clear",
        "cag_last_scan": dt(-5),
        "assigned_pm": "James Holloway",
        "assigned_capture_lead": "Priya Nair",
        "due_date": d(-45),
        "submitted_at": dt(-47),
        "result": "win",
        "result_details": (
            "Nexus Federal Solutions selected as prime contractor. Award value $47.2M. "
            "Evaluation: Technical 95/100, Management 92/100, Past Performance: Outstanding."
        ),
    },
    {
        "id": "prop-dhs-cir-001",
        "opportunity_id": "opp-dhs-cir-001",
        "title": "Cyber Incident Response Platform — CISA SOC Modernization",
        "status": "gold_review",
        "volumes": json.dumps(["executive_summary", "technical", "management",
                                "past_performance", "cost"]),
        "classification": "CUI // SP-PROPIN",
        "cag_status": "clear",
        "cag_last_scan": dt(-1),
        "assigned_pm": "James Holloway",
        "assigned_capture_lead": "Raj Patel",
        "due_date": d(18),
        "submitted_at": None,
        "result": None,
        "result_details": None,
    },
    {
        "id": "prop-va-dm-001",
        "opportunity_id": "opp-va-dm-001",
        "title": "RFI Response: VA Digital Modernization — Capability Statement",
        "status": "red_review",
        "volumes": json.dumps(["executive_summary", "technical", "management"]),
        "classification": "CUI // SP-PROPIN",
        "cag_status": "alert",
        "cag_last_scan": dt(-2),
        "assigned_pm": "DeShawn Brooks",
        "assigned_capture_lead": "Angela Kim",
        "due_date": d(10),
        "submitted_at": None,
        "result": None,
        "result_details": None,
    },
    {
        "id": "prop-dod-aiml-001",
        "opportunity_id": "opp-dod-aiml-001",
        "title": "AI/ML Operations Platform — DoD CDAO Enterprise Deployment",
        "status": "pink_review",
        "volumes": json.dumps(["executive_summary", "technical", "management", "cost"]),
        "classification": "CUI // SP-PROPIN",
        "cag_status": "pending",
        "cag_last_scan": None,
        "assigned_pm": "Caitlin Torres",
        "assigned_capture_lead": "Priya Nair",
        "due_date": d(35),
        "submitted_at": None,
        "result": None,
        "result_details": None,
    },
    {
        "id": "prop-nsf-rdap-001",
        "opportunity_id": "opp-nsf-rdap-001",
        "title": "Research Data Analytics Platform — NSF Proposal",
        "status": "draft",
        "volumes": json.dumps(["technical", "management", "cost"]),
        "classification": "CUI // SP-PROPIN",
        "cag_status": "pending",
        "cag_last_scan": None,
        "assigned_pm": "Angela Kim",
        "assigned_capture_lead": "Victor Sandoval",
        "due_date": d(55),
        "submitted_at": None,
        "result": None,
        "result_details": None,
    },
]

WIN_THEMES = {
    "prop-disa-zt-001": [
        ("Proven ZTA at scale — 50K+ endpoints deployed across 3 active DoD task orders", "technical", 0.95),
        ("FedRAMP High authorized cloud architecture delivered from Day 1", "technical", 0.92),
        ("Lowest risk: organic cleared workforce, zero recruiting required", "personnel", 0.93),
        ("10% cost savings via AWS Enterprise Discount Program", "cost", 0.88),
        ("3 CPARS Outstanding ratings on directly relevant ZTA programs", "past_performance", 0.90),
    ],
    "prop-dhs-cir-001": [
        ("Incumbent knowledge — 18 months on-site at CISA SOC", "past_performance", 0.91),
        ("200+ pre-built SOAR playbooks covering all 22 CISA Incident Categories", "technical", 0.87),
        ("Reduced CISA MTTR from 4.2 hrs to 1.4 hrs on prior task order", "technical", 0.89),
        ("SB set-aside advantage — 22% below large business rates", "cost", 0.84),
    ],
    "prop-va-dm-001": [
        ("SDVOSB certified prime with direct VA modernization experience", "past_performance", 0.82),
        ("Proven COBOL modernization — 4M LOC migrated with zero downtime", "technical", 0.85),
        ("AI-assisted code analysis reduces discovery risk by 60%", "technical", 0.78),
    ],
    "prop-dod-aiml-001": [
        ("Only offeror with MLOps deployed on NIPR, SIPR, and JWICS simultaneously", "technical", 0.90),
        ("Responsible AI governance framework aligned with all DoD AI Principles", "technical", 0.86),
        ("Caitlin Torres: DoD AI Steering Committee advisor and co-author of CDAO framework", "personnel", 0.83),
    ],
    "prop-nsf-rdap-001": [
        ("Open source-first approach reduces licensing costs by 40%", "cost", 0.79),
        ("Partnered with 3 R1 universities for research data domain expertise", "technical", 0.75),
    ],
}

EXCLUSION_TERMS = [
    ("James Holloway",          "[PERSON_1]",        "person",       "Program Manager — protect identity in AI drafts"),
    ("Priya Nair",              "[PERSON_2]",        "person",       "Cloud Architect — protect identity"),
    ("DeShawn Brooks",          "[PERSON_3]",        "person",       "Systems Engineer — protect identity"),
    ("Caitlin Torres",          "[PERSON_4]",        "person",       "AI/ML Lead — protect identity"),
    ("Project Sentinel",        "[PROGRAM_1]",       "program",      "Classified DoD program — cannot appear in proposals"),
    ("Nexus Federal Solutions", "[ORGANIZATION_1]",  "organization", "Company name — mask before LLM processing"),
    ("Fort Meade",              "[LOCATION_1]",      "location",     "DISA HQ — mask for OPSEC"),
    ("ZT-Alpha",                "[CAPABILITY_1]",    "capability",   "Proprietary ZTA methodology"),
]

# ── AI sections config ─────────────────────────────────────────────────────────
# (prop_id, volume, section_number, section_title, hitl_status, reviewer, call_llm)

SECTIONS = [
    # DISA — awarded, all accepted
    ("prop-disa-zt-001", "executive_summary", "ES-1",  "Executive Summary",
     "accepted", "James Holloway", True),
    ("prop-disa-zt-001", "technical",         "C.2",   "Technical Approach — Zero Trust Architecture",
     "accepted", "Priya Nair",    True),
    ("prop-disa-zt-001", "management",        "C.3",   "Management Plan",
     "accepted", "James Holloway", True),
    ("prop-disa-zt-001", "past_performance",  "C.4",   "Past Performance",
     "accepted", "James Holloway", True),
    ("prop-disa-zt-001", "cost",              "B",     "Cost/Price Proposal — CLIN Table",
     "accepted", "Priya Nair",    False),  # CLIN table, no LLM

    # DHS — gold_review: 2 accepted, 1 pending
    ("prop-dhs-cir-001", "technical",  "C.2", "Technical Approach — CIRP Architecture",
     "accepted", "Raj Patel",      True),
    ("prop-dhs-cir-001", "management", "C.3", "Management Plan",
     "accepted", "James Holloway", True),
    ("prop-dhs-cir-001", "cost",       "B",   "Price/Cost Proposal",
     "pending",  None,             True),

    # VA — red_review: 1 accepted, 1 pending
    ("prop-va-dm-001", "executive_summary", "ES-1", "Executive Summary",
     "accepted", "DeShawn Brooks", True),
    ("prop-va-dm-001", "technical",         "C.2",  "Technical Approach — COBOL Modernization",
     "pending",  None,             True),

    # DoD — pink_review: 1 pending
    ("prop-dod-aiml-001", "executive_summary", "ES-1", "Executive Summary",
     "pending", None, True),

    # NSF — draft: no sections yet
]

REQUIREMENTS = {
    "prop-disa-zt-001": [
        ("L.2.1",  "section_l", "shall", "technical",        "critical",
         "The offeror shall provide a technical approach for implementing Zero Trust architecture aligned with DISA ZTA Reference Architecture v2.0 and DoD ZT Strategy 2022."),
        ("L.2.2",  "section_l", "shall", "technical",        "critical",
         "The offeror shall demonstrate FedRAMP High authorized solutions for all major platform components."),
        ("L.2.3",  "section_l", "shall", "management",       "high",
         "The offeror shall provide resumes for all Key Personnel as defined in Section H."),
        ("M.3.1",  "section_m", "will",  "past_performance", "critical",
         "Past Performance will be evaluated on recency (within 5 years), relevance (ZTA/ICAM), and quality (CPARS ratings)."),
        ("SOW.4",  "sow",       "shall", "technical",        "high",
         "The contractor shall achieve Initial Operating Capability (IOC) within 4 months of contract award."),
        ("SOW.7",  "sow",       "shall", "technical",        "critical",
         "The contractor shall maintain 99.9% platform availability during steady-state operations."),
        ("L.5.1",  "section_l", "shall", "cost",             "critical",
         "The offeror shall provide a fully burdened labor rate schedule and detailed CLIN pricing matrix."),
        ("L.5.2",  "section_l", "shall", "cost",             "high",
         "The offeror shall provide a Small Business Subcontracting Plan meeting or exceeding 40% SB participation."),
    ],
    "prop-dhs-cir-001": [
        ("L.2.1",  "section_l", "shall", "technical",  "critical",
         "The offeror shall describe integration approach with EINSTEIN 3A and CISA NCOC infrastructure."),
        ("L.2.2",  "section_l", "shall", "technical",  "high",
         "The offeror shall provide SOAR playbook library covering a minimum of 15 CISA Incident Categories."),
        ("M.2.1",  "section_m", "will",  "technical",  "critical",
         "Technical approach will be evaluated on feasibility, security compliance, and MTTR reduction potential."),
        ("SOW.3",  "sow",       "shall", "technical",  "high",
         "The contractor shall complete Phase 1 deployment within 120 days of award."),
        ("L.5.1",  "section_l", "shall", "cost",       "critical",
         "Offeror shall provide T&M labor rate schedule with not-to-exceed (NTE) ceiling per CLIN."),
    ],
    "prop-va-dm-001": [
        ("RFI.1",  "sow",       "should", "technical",  "high",
         "Respondents should describe their approach to COBOL source code analysis and business rule extraction."),
        ("RFI.2",  "sow",       "should", "technical",  "medium",
         "Respondents should describe modernization methodology and risk mitigation approach."),
        ("RFI.3",  "sow",       "should", "management", "medium",
         "Respondents should provide relevant past performance examples with modernization scope and outcome."),
    ],
    "prop-dod-aiml-001": [
        ("L.3.1",  "section_l", "shall", "technical",  "critical",
         "Offeror shall describe AI/ML model lifecycle management capability across classification domains."),
        ("L.3.2",  "section_l", "shall", "technical",  "critical",
         "Offeror shall demonstrate responsible AI governance framework aligned with DoD AI Principles and OMB M-24-10."),
        ("L.3.3",  "section_l", "shall", "technical",  "high",
         "Offeror shall describe federated learning architecture supporting SECRET and TS/SCI workloads."),
    ],
    "prop-nsf-rdap-001": [
        ("SOW.1",  "sow",       "shall", "technical",  "high",
         "Contractor shall develop a cloud-native data ingestion pipeline supporting minimum 50 TB/month throughput."),
        ("SOW.2",  "sow",       "shall", "technical",  "medium",
         "Contractor shall deliver interactive web dashboard with drill-down visualization capabilities."),
    ],
}

RESEARCH_CACHE = [
    {
        "proposal_id": "prop-disa-zt-001",
        "query": "DISA Zero Trust Reference Architecture v2.0 requirements 2025",
        "cache_type": "gov_sources",
        "results": json.dumps([
            {"title": "DISA Zero Trust Reference Architecture v2.0", "url": "https://public.cyber.mil/zero-trust/",
             "snippet": "DISA ZTA v2.0 aligns with DoD ZT Strategy 2022. Seven pillars: Users, Devices, Networks, Applications, Data, Automation, Visibility."},
            {"title": "DoD Zero Trust Strategy 2022", "url": "https://dodcio.defense.gov/Portals/0/Documents/Library/DoD-ZTStrategy.pdf",
             "snippet": "Target Level ZT by FY2027. Activities, capabilities, and target levels defined across 90+ activities."},
        ]),
        "source_count": 2,
    },
    {
        "proposal_id": "prop-dhs-cir-001",
        "query": "CISA NCOC cyber incident response platform SOAR integration 2025",
        "cache_type": "web_search",
        "results": json.dumps([
            {"title": "CISA National Cybersecurity Operations Center (NCOC)", "url": "https://www.cisa.gov/ncoc",
             "snippet": "NCOC serves as the hub for cybersecurity situation awareness, analysis, and incident response."},
            {"title": "CISA SOAR Playbook Standards", "url": "https://www.cisa.gov/resources-tools/resources/soar-playbooks",
             "snippet": "22 standard incident categories. Playbooks must integrate with EINSTEIN 3A and Automated Indicator Sharing (AIS)."},
        ]),
        "source_count": 2,
    },
    {
        "proposal_id": "prop-va-dm-001",
        "query": "VA OIT COBOL modernization legacy system migration best practices",
        "cache_type": "web_search",
        "results": json.dumps([
            {"title": "VA Digital Modernization Strategy", "url": "https://www.oit.va.gov/strategy/",
             "snippet": "VA OIT targeting $1.2B in modernization investments. VistA replacement is top priority."},
            {"title": "IBM Watson Code Assistant for Z — COBOL Modernization", "url": "https://www.ibm.com/products/watsonx-code-assistant-z",
             "snippet": "AI-assisted COBOL analysis identifies dead code, business rules, and generates Java equivalents."},
        ]),
        "source_count": 2,
    },
]


# ─────────────────────────────────────────────────────────────────────────────
# Seed functions
# ─────────────────────────────────────────────────────────────────────────────

def seed_opportunities(c):
    print("\n[1/8] Seeding opportunities ...")
    for opp in OPPORTUNITIES:
        existing = c.execute("SELECT id FROM opportunities WHERE id=?", (opp["id"],)).fetchone()
        if existing:
            print(f"  SKIP {opp['id']} (already exists)")
            continue
        c.execute("""
            INSERT INTO opportunities
              (id, sam_notice_id, title, solicitation_number, agency, sub_agency,
               naics_code, set_aside_type, contract_type, opportunity_type, description,
               response_deadline, posted_date, pop_start, pop_end,
               estimated_value_low, estimated_value_high, place_of_performance,
               status, fit_score, qualification_score,
               go_decision, go_decision_rationale, go_decision_by, go_decision_at,
               metadata, discovered_at, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            opp["id"], opp["sam_notice_id"], opp["title"], opp["solicitation_number"],
            opp["agency"], opp.get("sub_agency"), opp["naics_code"], opp.get("set_aside_type"),
            opp.get("contract_type"), opp["opportunity_type"], opp["description"],
            opp["response_deadline"], opp["posted_date"], opp["pop_start"], opp["pop_end"],
            opp["estimated_value_low"], opp["estimated_value_high"], opp["place_of_performance"],
            opp["status"], opp["fit_score"], opp["qualification_score"],
            opp.get("go_decision"), opp.get("go_decision_rationale"), opp.get("go_decision_by"),
            opp.get("go_decision_at"), opp.get("metadata"), dt(-120), dt(-5),
        ))
        print(f"  OK  {opp['agency'][:45]} — {opp['status']}")
    c.commit()


def seed_proposals(c):
    print("\n[2/8] Seeding proposals ...")
    for p in PROPOSALS:
        existing = c.execute("SELECT id FROM proposals WHERE id=?", (p["id"],)).fetchone()
        if existing:
            print(f"  SKIP {p['id']}")
            continue
        c.execute("""
            INSERT INTO proposals
              (id, opportunity_id, title, version, status, volumes, classification,
               cag_status, cag_last_scan, assigned_pm, assigned_capture_lead,
               due_date, submitted_at, result, result_details, created_at, updated_at)
            VALUES (?,?,?,1,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            p["id"], p["opportunity_id"], p["title"], p["status"],
            p["volumes"], p["classification"], p["cag_status"],
            p.get("cag_last_scan"), p.get("assigned_pm"), p.get("assigned_capture_lead"),
            p.get("due_date"), p.get("submitted_at"), p.get("result"),
            p.get("result_details"), dt(-90), dt(-1),
        ))
        print(f"  OK  {p['title'][:60]} — {p['status']}")
    c.commit()


def seed_win_themes(c):
    print("\n[3/8] Seeding win themes ...")
    for prop_id, themes in WIN_THEMES.items():
        opp_id = next(p["opportunity_id"] for p in PROPOSALS if p["id"] == prop_id)
        for theme_text, disc_type, strength in themes:
            existing = c.execute(
                "SELECT id FROM win_themes WHERE proposal_id=? AND theme_text=?",
                (prop_id, theme_text)
            ).fetchone()
            if existing:
                continue
            c.execute("""
                INSERT INTO win_themes
                  (id, opportunity_id, proposal_id, theme_text, discriminator_type,
                   strength_rating, created_at)
                VALUES (?,?,?,?,?,?,?)
            """, (uid(), opp_id, prop_id, theme_text, disc_type, strength, dt(-60)))
        print(f"  OK  {prop_id}: {len(themes)} themes")
    c.commit()


def seed_exclusions(c):
    print("\n[4/8] Seeding exclusion list ...")
    for term, placeholder, ttype, notes in EXCLUSION_TERMS:
        existing = c.execute(
            "SELECT id FROM rfx_exclusion_list WHERE sensitive_term=?", (term,)
        ).fetchone()
        if existing:
            continue
        c.execute("""
            INSERT INTO rfx_exclusion_list
              (id, sensitive_term, placeholder, term_type, whole_word,
               case_sensitive, is_active, context_notes, created_by, created_at)
            VALUES (?,?,?,?,1,0,1,?,?,?)
        """, (uid(), term, placeholder, ttype, notes, "seed_demo", dt(-30)))
    print(f"  OK  {len(EXCLUSION_TERMS)} terms added")
    c.commit()


def seed_documents(c):
    print("\n[5/8] Seeding RFP documents ...")
    docs = [
        ("prop-disa-zt-001", "opp-disa-zt-001", "HC1047-25-R-0042_RFP_ZTNAP.pdf",
         "rfp", (
             "SECTION L — INSTRUCTIONS TO OFFERORS\n"
             "L.2.1 Technical Approach: Offerors shall provide technical approach for ZTA.\n"
             "L.2.2 FedRAMP High authorized solutions required for all platform components.\n"
             "L.5.1 Provide fully burdened labor rate schedule and CLIN pricing matrix.\n\n"
             "SECTION M — EVALUATION CRITERIA\n"
             "M.1 Technical Approach (40%) — Architecture, security, implementation plan\n"
             "M.2 Management Plan (20%) — Key personnel, risk management, quality assurance\n"
             "M.3 Past Performance (20%) — Recency, relevance, CPARS ratings\n"
             "M.4 Price/Cost (20%) — Realism, completeness, SB participation\n\n"
             "STATEMENT OF WORK\n"
             "SOW.4 IOC within 4 months of contract award.\n"
             "SOW.7 Maintain 99.9% platform availability during steady-state operations.\n"
         )),
        ("prop-dhs-cir-001", "opp-dhs-cir-001", "70RCSA25R00089_CIRP_RFP.pdf",
         "rfp", (
             "SECTION L — INSTRUCTIONS\n"
             "L.2.1 Describe EINSTEIN 3A integration approach.\n"
             "L.2.2 SOAR playbook library must cover minimum 15 CISA incident categories.\n"
             "L.5.1 T&M labor rate schedule with NTE ceiling required.\n\n"
             "SECTION M — EVALUATION\n"
             "M.1 Technical Approach (35%) — Feasibility, security compliance, MTTR reduction\n"
             "M.2 Management (25%) — Key personnel, risk mitigation\n"
             "M.3 Past Performance (20%) — CISA/DHS relevance\n"
             "M.4 Price (20%) — T&M rates, NTE ceiling, SB participation\n"
         )),
        ("prop-va-dm-001", "opp-va-dm-001", "36C10B25I0001_VA_RFI.pdf",
         "rfi", (
             "REQUEST FOR INFORMATION — VA DIGITAL MODERNIZATION INITIATIVE\n"
             "RFI.1 Describe COBOL analysis and business rule extraction approach.\n"
             "RFI.2 Describe modernization methodology and risk mitigation.\n"
             "RFI.3 Provide relevant past performance examples.\n\n"
             "NOTE: This is a market research RFI. No award will be made from this notice.\n"
             "A formal RFP is anticipated Q3 FY2025 with SDVOSB set-aside.\n"
         )),
        ("prop-dod-aiml-001", "opp-dod-aiml-001", "W911NF25R0002_DoD_AIML_RFP.pdf",
         "rfp", (
             "SECTION L — INSTRUCTIONS\n"
             "L.3.1 Describe AI/ML lifecycle management across classification domains (NIPR/SIPR/JWICS).\n"
             "L.3.2 Demonstrate responsible AI governance framework per DoD AI Principles.\n"
             "L.3.3 Describe federated learning architecture for classified workloads.\n\n"
             "SECTION M — EVALUATION\n"
             "M.1 Technical Approach (45%) — MLOps capability, responsible AI, cross-domain\n"
             "M.2 Management (25%) — Program management, key personnel\n"
             "M.3 Past Performance (15%) — DoD AI/ML relevance\n"
             "M.4 Price (15%) — Realism, completeness\n"
         )),
        ("prop-nsf-rdap-001", "opp-nsf-rdap-001", "NSF_2500001_RDAP_RFP.pdf",
         "rfp", (
             "STATEMENT OF WORK — NSF Research Data Analytics Platform\n"
             "SOW.1 Develop cloud-native data ingestion pipeline supporting 50 TB/month.\n"
             "SOW.2 Deliver interactive web dashboard with drill-down visualizations.\n\n"
             "EVALUATION CRITERIA\n"
             "M.1 Technical (40%) — Architecture, scalability, open source\n"
             "M.2 Management (30%) — Team, schedule, risk\n"
             "M.3 Price (30%) — Realism, SB participation\n"
         )),
    ]
    for prop_id, opp_id, filename, doc_type, content in docs:
        existing = c.execute(
            "SELECT id FROM rfx_documents WHERE proposal_id=? AND filename=?",
            (prop_id, filename)
        ).fetchone()
        if existing:
            continue
        doc_id = uid()
        fake_path = f"data/rfx_uploads/demo/{filename}"
        c.execute("""
            INSERT INTO rfx_documents
              (id, proposal_id, opportunity_id, filename, doc_type,
               file_path, file_hash, mime_type, file_size_bytes,
               content, chunk_count, vectorized, classification,
               uploaded_by, created_at, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,0,0,?,?,?,?)
        """, (
            doc_id, prop_id, opp_id, filename, doc_type,
            fake_path, fake_hash(filename + prop_id),
            "application/pdf", len(content.encode()),
            content, "CUI // SP-PROPIN", "seed_demo", dt(-80), dt(-80),
        ))
        print(f"  OK  {filename}")
    c.commit()


def seed_requirements(c):
    print("\n[6/8] Seeding requirements ...")
    for prop_id, reqs in REQUIREMENTS.items():
        doc = c.execute(
            "SELECT id FROM rfx_documents WHERE proposal_id=?", (prop_id,)
        ).fetchone()
        if not doc:
            print(f"  SKIP {prop_id}: no document found")
            continue
        doc_id = doc["id"]
        for req_num, section, req_type, volume, priority, req_text in reqs:
            existing = c.execute(
                "SELECT id FROM rfx_requirements WHERE proposal_id=? AND req_number=?",
                (prop_id, req_num)
            ).fetchone()
            if existing:
                continue
            c.execute("""
                INSERT INTO rfx_requirements
                  (id, document_id, proposal_id, req_number, section,
                   req_text, req_type, volume, priority, extracted_by, created_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """, (
                uid(), doc_id, prop_id, req_num, section,
                req_text, req_type, volume, priority, "ai", dt(-75),
            ))
        print(f"  OK  {prop_id}: {len(reqs)} requirements")
    c.commit()


def seed_ai_sections(c):
    print("\n[7/8] Generating AI sections (calls LLM for real content) ...")

    for (prop_id, volume, sec_num, sec_title,
         hitl_status, reviewer, call_llm) in SECTIONS:

        existing = c.execute(
            "SELECT id FROM rfx_ai_sections WHERE proposal_id=? AND section_title=?",
            (prop_id, sec_title)
        ).fetchone()
        if existing:
            print(f"  SKIP {prop_id}/{sec_title}")
            continue

        # Get win themes for this proposal
        themes_rows = c.execute(
            "SELECT theme_text FROM win_themes WHERE proposal_id=?", (prop_id,)
        ).fetchall()
        themes = [r["theme_text"] for r in themes_rows]

        # Get opportunity context
        opp = c.execute("""
            SELECT o.title, o.description, o.agency, o.solicitation_number,
                   o.contract_type, o.estimated_value_high
            FROM proposals p JOIN opportunities o ON p.opportunity_id=o.id
            WHERE p.id=?
        """, (prop_id,)).fetchone()

        rfp_ctx = (
            f"Solicitation: {opp['solicitation_number']}\n"
            f"Agency: {opp['agency']}\n"
            f"Title: {opp['title']}\n"
            f"Contract Type: {opp['contract_type']}\n"
            f"Estimated Value: ${opp['estimated_value_high']:,.0f}\n\n"
            f"Description:\n{opp['description']}\n\n"
            "Section L Requirements:\n" +
            "\n".join(
                f"  {r['req_number']}: {r['req_text']}"
                for r in c.execute(
                    "SELECT req_number, req_text FROM rfx_requirements "
                    "WHERE proposal_id=? AND section IN ('section_l','sow') LIMIT 5",
                    (prop_id,)
                ).fetchall()
            )
        )

        # Determine content
        fallback_key = (prop_id, volume)
        fallback = FALLBACK.get(fallback_key)

        if prop_id == "prop-disa-zt-001" and volume == "cost":
            content = DISA_CLIN_TABLE
        elif call_llm and fallback is not None:
            content = llm_section(sec_title, volume, rfp_ctx, themes, prop_id, fallback)
        elif call_llm:
            # generate with LLM, no pre-written fallback — use generic
            generic = (
                f"CUI // SP-PROPIN\n\n"
                f"{sec_title.upper()}\n\n"
                f"[Draft content for {volume} volume — review in progress]\n\n"
                f"CUI // SP-PROPIN"
            )
            content = llm_section(sec_title, volume, rfp_ctx, themes, prop_id, generic)
        else:
            content = fallback or ""

        sec_id = uid()
        now_str = dt()
        reviewed_at = dt(-40) if hitl_status == "accepted" else None

        c.execute("""
            INSERT INTO rfx_ai_sections
              (id, proposal_id, volume, section_number, section_title,
               content_draft, content_accepted, source_type,
               model_used, prompt_hash,
               hitl_status, hitl_reviewed_by, hitl_reviewed_at,
               cag_cleared, classification, created_at, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            sec_id, prop_id, volume, sec_num, sec_title,
            content,
            content if hitl_status == "accepted" else None,
            "hybrid", "icdev-router", fake_hash(content[:200]),
            hitl_status, reviewer if hitl_status == "accepted" else None,
            reviewed_at,
            1 if hitl_status == "accepted" else 0,
            "CUI // SP-PROPIN", dt(-80), now_str,
        ))

        # Insert HITL review record for accepted sections
        if hitl_status == "accepted":
            c.execute("""
                INSERT INTO rfx_hitl_reviews
                  (id, ai_section_id, proposal_id, reviewer, action,
                   feedback, classification, reviewed_at)
                VALUES (?,?,?,?,?,?,?,?)
            """, (
                uid(), sec_id, prop_id, reviewer, "accept",
                "Content meets requirements. Approved for submission.",
                "CUI // SP-PROPIN", reviewed_at,
            ))

        label = "[accepted]" if hitl_status == "accepted" else "[pending]"
        print(f"  OK  [{label}] {prop_id[:20]} | {sec_title[:40]}")

    c.commit()


def seed_research_cache(c):
    print("\n[8/8] Seeding research cache ...")
    exp = dt(days=24)  # 24 hours TTL
    for entry in RESEARCH_CACHE:
        q_hash = fake_hash(entry["query"])
        existing = c.execute(
            "SELECT id FROM rfx_research_cache WHERE query_hash=?", (q_hash,)
        ).fetchone()
        if existing:
            continue
        c.execute("""
            INSERT INTO rfx_research_cache
              (id, proposal_id, query, query_hash, cache_type,
               results, source_count, expires_at, created_at)
            VALUES (?,?,?,?,?,?,?,?,?)
        """, (
            uid(), entry["proposal_id"], entry["query"], q_hash,
            entry["cache_type"], entry["results"], entry["source_count"],
            exp, dt(),
        ))
        print(f"  OK  {entry['query'][:60]}")
    c.commit()


# ─────────────────────────────────────────────────────────────────────────────
# Wipe
# ─────────────────────────────────────────────────────────────────────────────

def wipe_demo(c):
    print("[WIPE] Removing previous demo data ...")
    prop_ids = tuple(p["id"] for p in PROPOSALS)
    opp_ids  = tuple(o["id"] for o in OPPORTUNITIES)

    ph = ",".join("?" * len(prop_ids))

    c.execute(f"DELETE FROM rfx_hitl_reviews   WHERE proposal_id IN ({ph})", prop_ids)
    c.execute(f"DELETE FROM rfx_ai_sections     WHERE proposal_id IN ({ph})", prop_ids)
    c.execute(f"DELETE FROM rfx_requirements    WHERE proposal_id IN ({ph})", prop_ids)
    c.execute(f"DELETE FROM rfx_documents       WHERE proposal_id IN ({ph})", prop_ids)
    c.execute(f"DELETE FROM rfx_research_cache  WHERE proposal_id IN ({ph})", prop_ids)
    c.execute(f"DELETE FROM win_themes          WHERE proposal_id IN ({ph})", prop_ids)
    c.execute(f"DELETE FROM proposals           WHERE id IN ({ph})", prop_ids)

    oph = ",".join("?" * len(opp_ids))
    c.execute(f"DELETE FROM opportunities WHERE id IN ({oph})", opp_ids)

    terms = tuple(t[0] for t in EXCLUSION_TERMS)
    tph = ",".join("?" * len(terms))
    c.execute(f"DELETE FROM rfx_exclusion_list WHERE sensitive_term IN ({tph})", terms)

    c.commit()
    print("[WIPE] Done.")


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="GovProposal demo seeder")
    parser.add_argument("--wipe", action="store_true",
                        help="Wipe previous demo data before seeding")
    args = parser.parse_args()

    if not DB_PATH.exists():
        print(f"ERROR: Database not found at {DB_PATH}")
        print("Run the GovProposal DB initializer first.")
        sys.exit(1)

    print(f"\n{'='*60}")
    print(" GovProposal Demo Seeder — Nexus Federal Solutions")
    print(f"{'='*60}")
    print(f" DB: {DB_PATH}")
    print(f"{'='*60}\n")

    c = _conn()
    try:
        if args.wipe:
            wipe_demo(c)

        seed_opportunities(c)
        seed_proposals(c)
        seed_win_themes(c)
        seed_exclusions(c)
        seed_documents(c)
        seed_requirements(c)
        seed_ai_sections(c)
        seed_research_cache(c)

        print(f"\n{'='*60}")
        print(" DEMO SEEDING COMPLETE")
        print(f"{'='*60}")
        print("""
 5 Opportunities seeded across all Kanban stages:

   AWARDED     → DISA Zero Trust Network Access Platform ($47.2M)
                  Full CLIN table, 5 AI sections (all accepted), awarded [DONE]
   GOLD REVIEW → DHS CISA Cyber Incident Response Platform ($31.5M)
                  2 accepted sections, cost section pending review
   RED REVIEW  → VA Digital Modernization Initiative RFI ($22M)
                  1 accepted, 1 pending technical section
   PINK REVIEW → DoD AI/ML Operations Platform ($58.7M)
                  Executive summary pending pink review
   DRAFT       → NSF Research Data Analytics Platform ($9.5M)
                  Proposal shell created, no AI sections yet

 Navigate to:
   /proposals          → List view with Kanban toggle
   /proposals/kanban   → Kanban board (all 5 proposals)
   /ai-proposals       → AI Proposal Engine dashboard
   /ai-proposals/prop-disa-zt-001  → Complete awarded proposal (CLIN table)
""")
    finally:
        c.close()


if __name__ == "__main__":
    main()
