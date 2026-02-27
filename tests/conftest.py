#!/usr/bin/env python3
# CUI // SP-PROPIN
"""Shared test fixtures for GovProposal test suite."""

import os
import sqlite3
import sys
from pathlib import Path

import pytest

# Add project root to path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))


def _patch_db_path(db_path):
    """Patch DB_PATH in all tool modules that cache it at import time."""
    p = Path(db_path)
    modules_to_patch = [
        "tools.monitor.pipeline_manager",
        "tools.monitor.opportunity_scorer",
        "tools.monitor.sam_scanner",
        "tools.knowledge.kb_manager",
        "tools.knowledge.kb_search",
        "tools.knowledge.past_performance",
        "tools.cag.data_tagger",
        "tools.cag.rules_engine",
        "tools.cag.aggregation_monitor",
        "tools.cag.exposure_register",
        "tools.proposal.section_parser",
        "tools.proposal.compliance_matrix",
        "tools.proposal.content_drafter",
        "tools.capture.win_theme_generator",
        "tools.capture.teaming_engine",
        "tools.capture.black_hat_review",
        "tools.review.review_engine",
        "tools.production.submission_packager",
        "tools.competitive.competitor_tracker",
        "tools.learning.debrief_capture",
        "tools.learning.win_loss_analyzer",
        "tools.learning.pricing_calibrator",
        "tools.mcp.proposal_server",
        "tools.dashboard.app",
    ]
    for mod_name in modules_to_patch:
        if mod_name in sys.modules:
            mod = sys.modules[mod_name]
            if hasattr(mod, "DB_PATH"):
                mod.DB_PATH = p


@pytest.fixture
def tmp_db(tmp_path):
    """Create a temporary GovProposal database with full schema."""
    db_path = tmp_path / "test_govproposal.db"

    from tools.db.init_db import init_db
    init_db(str(db_path))

    os.environ["GOVPROPOSAL_DB_PATH"] = str(db_path)
    _patch_db_path(db_path)
    yield db_path
    if "GOVPROPOSAL_DB_PATH" in os.environ:
        del os.environ["GOVPROPOSAL_DB_PATH"]


@pytest.fixture
def db_conn(tmp_db):
    """Get a connection to the test database."""
    conn = sqlite3.connect(str(tmp_db))
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()


@pytest.fixture
def sample_opportunity(db_conn):
    """Insert a sample opportunity and return its ID."""
    opp_id = "OPP-test-001"
    db_conn.execute(
        """INSERT INTO opportunities
           (id, title, agency, sam_notice_id, naics_code,
            set_aside_type, response_deadline, status, description,
            estimated_value_low, estimated_value_high,
            discovered_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (opp_id, "IT Modernization Support Services",
         "Department of Defense", "SAM-001",
         "541512", "Total Small Business", "2026-06-15",
         "discovered",
         "The Department of Defense requires information technology "
         "modernization support services including cloud migration, "
         "cybersecurity operations, and DevSecOps implementation. "
         "Contractor shall provide cleared personnel with TS/SCI "
         "clearance to support mission-critical systems at "
         "Fort Meade, Maryland. Period of performance is 5 years "
         "with a ceiling of $50M. Key capabilities include "
         "AWS GovCloud, Kubernetes, Zero Trust Architecture.",
         10000000, 50000000,
         "2026-01-15T00:00:00Z", "2026-01-15T00:00:00Z")
    )
    db_conn.commit()
    return opp_id


@pytest.fixture
def sample_proposal(db_conn, sample_opportunity):
    """Insert a sample proposal and return its ID."""
    prop_id = "PROP-test-001"
    db_conn.execute(
        """INSERT INTO proposals
           (id, opportunity_id, title, status, cag_status, due_date,
            created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (prop_id, sample_opportunity,
         "IT Modernization Support Services — Technical Volume",
         "draft", "clear", "2026-06-10",
         "2026-02-01T00:00:00Z", "2026-02-01T00:00:00Z")
    )
    db_conn.commit()
    return prop_id


@pytest.fixture
def sample_sections(db_conn, sample_proposal):
    """Insert sample proposal sections."""
    sections = [
        ("SEC-001", sample_proposal, "technical", 1, "Technical Approach",
         "Our team will leverage AWS GovCloud and Kubernetes for cloud migration. "
         "We employ Zero Trust Architecture with mTLS service mesh.",
         "drafted", None),
        ("SEC-002", sample_proposal, "technical", 2, "Staffing Plan",
         "We will provide 15 TS/SCI cleared engineers stationed at Fort Meade. "
         "Key personnel include a Program Manager with 20 years DoD experience.",
         "drafted", None),
        ("SEC-003", sample_proposal, "management", 1, "Management Approach",
         "Our CMMI Level 3 processes ensure quality delivery. "
         "Agile/SAFe methodology with 2-week sprints.",
         "drafted", None),
        ("SEC-004", sample_proposal, "past_performance", 1, "Past Performance",
         "Contract W91278-20-C-0045 with Army CECOM provided similar IT services.",
         "drafted", None),
    ]
    for s in sections:
        db_conn.execute(
            """INSERT INTO proposal_sections
               (id, proposal_id, volume, section_number, section_title, content,
                status, cag_categories)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            s
        )
    db_conn.commit()
    return [s[0] for s in sections]


@pytest.fixture
def sample_kb_entries(db_conn):
    """Insert sample knowledge base entries."""
    entries = [
        ("KB-001", "Cloud Migration Capabilities", "capability",
         "Our team specializes in AWS GovCloud migration, including "
         "lift-and-shift, re-platforming, and cloud-native development. "
         "Certified AWS Solutions Architects and DevSecOps engineers.",
         "cloud,aws,migration,govcloud", 5, 0.75),
        ("KB-002", "Cybersecurity Operations", "capability",
         "24/7 SOC operations with SIEM integration, vulnerability management, "
         "and incident response. Zero Trust Architecture implementation "
         "using Istio service mesh and Kubernetes network policies.",
         "cybersecurity,soc,zero-trust,siem", 3, 0.80),
        ("KB-003", "DevSecOps Pipeline", "methodology",
         "CI/CD pipeline with automated security scanning (SAST, DAST, SCA), "
         "container security, and compliance-as-code. GitLab CI with "
         "Kubernetes deployment orchestration.",
         "devsecops,cicd,pipeline,security", 2, 0.70),
    ]
    for e in entries:
        db_conn.execute(
            """INSERT INTO kb_entries
               (id, title, entry_type, content, tags, usage_count,
                quality_score, is_active, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, 1, '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')""",
            e
        )
    db_conn.commit()
    return [e[0] for e in entries]


@pytest.fixture
def sample_past_performance(db_conn):
    """Insert sample past performance records."""
    pp_id = "PP-test-001"
    db_conn.execute(
        """INSERT INTO past_performances
           (id, contract_number, contract_name, agency, sub_agency,
            naics_code, contract_value,
            period_of_performance_start, period_of_performance_end,
            scope_description, role, cpars_rating, is_active,
            created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)""",
        (pp_id, "W91278-20-C-0045",
         "Army CECOM IT Modernization",
         "Department of Defense", "Army CECOM",
         "541512", 25000000,
         "2020-01-01", "2025-01-01",
         "Full lifecycle IT modernization including cloud migration "
         "to AWS GovCloud, DevSecOps pipeline implementation, and "
         "24/7 cybersecurity operations.",
         "prime", "exceptional",
         "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z")
    )
    db_conn.commit()
    return pp_id


@pytest.fixture
def sample_competitor(db_conn):
    """Insert a sample competitor."""
    comp_id = "COMP-test-001"
    db_conn.execute(
        """INSERT INTO competitors
           (id, company_name, cage_code, naics_codes, set_aside_status,
            strengths, weaknesses, is_active, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?)""",
        (comp_id, "Rival Corp", "ABC12", '["541512"]', "Total Small Business",
         "Strong DoD relationships, Large workforce",
         "Limited cloud expertise, High pricing",
         "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z")
    )
    db_conn.commit()
    return comp_id
