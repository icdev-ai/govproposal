#!/usr/bin/env python3
# CUI // SP-PROPIN
# Controlled by: GovProposal Portal
# CUI Category: PROPIN (Proprietary Business Information)
# Distribution: D
# POC: GovProposal System Administrator
"""Initialize the GovProposal database with all required tables.

Creates tables for:
  - Opportunity Intelligence (SAM.gov monitoring, scoring, pipeline)
  - Proposals & Sections (proposal lifecycle, content, compliance)
  - Knowledge Base (capabilities, past performance, resumes, boilerplate)
  - Classification Aggregation Guard (tagging, rules, alerts, exposure)
  - Capture Management (win themes, teaming, customer intel)
  - Competitive Intelligence (competitors, FPDS, pricing)
  - Review Cycles (Pink/Red/Gold/White team reviews)
  - Production (templates, formatting, packaging)
  - Learning (debriefs, win/loss analysis, pricing calibration)
  - System (audit trail, acronyms, config)

Usage:
    python tools/db/init_db.py [--json]
"""

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


SCHEMA_SQL = """
-- ============================================================
-- OPPORTUNITY INTELLIGENCE
-- ============================================================

-- Opportunities discovered from SAM.gov and other sources
CREATE TABLE IF NOT EXISTS opportunities (
    id TEXT PRIMARY KEY,
    sam_notice_id TEXT UNIQUE,
    title TEXT NOT NULL,
    solicitation_number TEXT,
    agency TEXT NOT NULL,
    sub_agency TEXT,
    office TEXT,
    naics_code TEXT,
    set_aside_type TEXT,
    contract_type TEXT,
    classification_code TEXT,
    description TEXT,
    response_deadline TEXT,
    posted_date TEXT,
    archive_date TEXT,
    pop_start TEXT,
    pop_end TEXT,
    estimated_value_low REAL,
    estimated_value_high REAL,
    place_of_performance TEXT,
    contact_name TEXT,
    contact_email TEXT,
    contact_phone TEXT,
    opportunity_type TEXT
        CHECK(opportunity_type IN ('solicitation', 'presolicitation',
              'combined_synopsis', 'sources_sought', 'rfi', 'modification',
              'award_notice', 'special_notice')),
    source_url TEXT,
    full_text TEXT,
    attachments TEXT,
    status TEXT NOT NULL DEFAULT 'discovered'
        CHECK(status IN ('discovered', 'qualifying', 'go_decision',
              'capture', 'drafting', 'pink_review', 'red_review',
              'gold_review', 'white_review', 'production', 'submitted',
              'awarded', 'lost', 'no_bid', 'archived')),
    fit_score REAL,
    qualification_score REAL,
    go_decision TEXT CHECK(go_decision IN ('go', 'no_bid', 'conditional', NULL)),
    go_decision_rationale TEXT,
    go_decision_by TEXT,
    go_decision_at TEXT,
    metadata TEXT,
    discovered_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_opp_status ON opportunities(status);
CREATE INDEX IF NOT EXISTS idx_opp_agency ON opportunities(agency);
CREATE INDEX IF NOT EXISTS idx_opp_naics ON opportunities(naics_code);
CREATE INDEX IF NOT EXISTS idx_opp_deadline ON opportunities(response_deadline);
CREATE INDEX IF NOT EXISTS idx_opp_sam_id ON opportunities(sam_notice_id);
CREATE INDEX IF NOT EXISTS idx_opp_fit ON opportunities(fit_score);

-- Opportunity qualification scores (per-dimension breakdown)
CREATE TABLE IF NOT EXISTS opportunity_scores (
    id TEXT PRIMARY KEY,
    opportunity_id TEXT NOT NULL REFERENCES opportunities(id),
    dimension TEXT NOT NULL,
    score REAL NOT NULL CHECK(score BETWEEN 0.0 AND 1.0),
    rationale TEXT,
    evidence TEXT,
    scored_by TEXT,
    scored_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_oppscore_opp ON opportunity_scores(opportunity_id);

-- Pipeline stage tracking (append-only history)
CREATE TABLE IF NOT EXISTS pipeline_stages (
    id TEXT PRIMARY KEY,
    opportunity_id TEXT NOT NULL REFERENCES opportunities(id),
    stage TEXT NOT NULL,
    entered_at TEXT NOT NULL DEFAULT (datetime('now')),
    exited_at TEXT,
    duration_hours REAL,
    notes TEXT,
    advanced_by TEXT
);

CREATE INDEX IF NOT EXISTS idx_pipeline_opp ON pipeline_stages(opportunity_id);
CREATE INDEX IF NOT EXISTS idx_pipeline_stage ON pipeline_stages(stage);

-- ============================================================
-- PROPOSALS & SECTIONS
-- ============================================================

-- Proposals (one per opportunity bid)
CREATE TABLE IF NOT EXISTS proposals (
    id TEXT PRIMARY KEY,
    opportunity_id TEXT NOT NULL REFERENCES opportunities(id),
    title TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    status TEXT NOT NULL DEFAULT 'draft'
        CHECK(status IN ('draft', 'pink_review', 'red_review',
              'gold_review', 'white_review', 'final', 'submitted',
              'awarded', 'lost')),
    volumes TEXT NOT NULL DEFAULT '["technical","management","past_performance","cost"]',
    win_themes TEXT,
    section_l_parsed TEXT,
    section_m_parsed TEXT,
    compliance_matrix_id TEXT,
    classification TEXT NOT NULL DEFAULT 'CUI // SP-PROPIN',
    cag_status TEXT DEFAULT 'pending'
        CHECK(cag_status IN ('pending', 'clear', 'alert', 'blocked', 'quarantined')),
    cag_last_scan TEXT,
    assigned_pm TEXT,
    assigned_capture_lead TEXT,
    due_date TEXT,
    submitted_at TEXT,
    result TEXT CHECK(result IN ('win', 'loss', NULL)),
    result_details TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_prop_opp ON proposals(opportunity_id);
CREATE INDEX IF NOT EXISTS idx_prop_status ON proposals(status);
CREATE INDEX IF NOT EXISTS idx_prop_cag ON proposals(cag_status);

-- Proposal sections (individual content blocks)
CREATE TABLE IF NOT EXISTS proposal_sections (
    id TEXT PRIMARY KEY,
    proposal_id TEXT NOT NULL REFERENCES proposals(id),
    volume TEXT NOT NULL
        CHECK(volume IN ('technical', 'management', 'past_performance',
              'cost', 'executive_summary', 'attachments')),
    section_number TEXT NOT NULL,
    section_title TEXT NOT NULL,
    content TEXT,
    content_html TEXT,
    word_count INTEGER DEFAULT 0,
    page_count REAL DEFAULT 0.0,
    page_limit REAL,
    status TEXT NOT NULL DEFAULT 'outline'
        CHECK(status IN ('outline', 'drafting', 'drafted', 'reviewed',
              'revised', 'final', 'locked')),
    assigned_writer TEXT,
    kb_sources TEXT,
    cag_tags TEXT,
    cag_categories TEXT,
    review_score REAL,
    review_notes TEXT,
    version INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_section_prop ON proposal_sections(proposal_id);
CREATE INDEX IF NOT EXISTS idx_section_volume ON proposal_sections(volume);
CREATE INDEX IF NOT EXISTS idx_section_status ON proposal_sections(status);

-- Compliance matrices (Section L/M mapping)
CREATE TABLE IF NOT EXISTS compliance_matrices (
    id TEXT PRIMARY KEY,
    proposal_id TEXT NOT NULL REFERENCES proposals(id),
    requirement_id TEXT NOT NULL,
    requirement_text TEXT NOT NULL,
    source TEXT NOT NULL CHECK(source IN ('section_l', 'section_m', 'cdrl', 'sow', 'other')),
    volume TEXT,
    section_number TEXT,
    section_title TEXT,
    compliance_status TEXT NOT NULL DEFAULT 'not_addressed'
        CHECK(compliance_status IN ('not_addressed', 'partially_addressed',
              'fully_addressed', 'not_applicable')),
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_compliance_prop ON compliance_matrices(proposal_id);
CREATE INDEX IF NOT EXISTS idx_compliance_status ON compliance_matrices(compliance_status);

-- Proposal reviews (color team results)
CREATE TABLE IF NOT EXISTS proposal_reviews (
    id TEXT PRIMARY KEY,
    proposal_id TEXT NOT NULL REFERENCES proposals(id),
    review_type TEXT NOT NULL
        CHECK(review_type IN ('pink', 'red', 'gold', 'white')),
    section_id TEXT REFERENCES proposal_sections(id),
    overall_score REAL,
    criteria_scores TEXT,
    strengths TEXT,
    weaknesses TEXT,
    deficiencies TEXT,
    recommendations TEXT,
    reviewer TEXT,
    review_status TEXT NOT NULL DEFAULT 'pending'
        CHECK(review_status IN ('pending', 'in_progress', 'completed')),
    reviewed_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_review_prop ON proposal_reviews(proposal_id);
CREATE INDEX IF NOT EXISTS idx_review_type ON proposal_reviews(review_type);

-- ============================================================
-- KNOWLEDGE BASE
-- ============================================================

-- Core knowledge base entries
CREATE TABLE IF NOT EXISTS kb_entries (
    id TEXT PRIMARY KEY,
    entry_type TEXT NOT NULL
        CHECK(entry_type IN ('capability', 'boilerplate', 'case_study',
              'win_theme', 'solution_architecture', 'methodology',
              'certification', 'tool_technology', 'domain_expertise',
              'corporate_overview', 'management_approach')),
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    tags TEXT,
    naics_codes TEXT,
    agencies TEXT,
    keywords TEXT,
    classification TEXT NOT NULL DEFAULT 'CUI // SP-PROPIN',
    cag_categories TEXT,
    cag_tags TEXT,
    usage_count INTEGER DEFAULT 0,
    last_used_at TEXT,
    last_used_in TEXT,
    quality_score REAL,
    win_rate REAL,
    created_by TEXT,
    approved_by TEXT,
    version INTEGER NOT NULL DEFAULT 1,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_kb_type ON kb_entries(entry_type);
CREATE INDEX IF NOT EXISTS idx_kb_active ON kb_entries(is_active);

-- KB embeddings for semantic search
CREATE TABLE IF NOT EXISTS kb_embeddings (
    id TEXT PRIMARY KEY,
    kb_entry_id TEXT NOT NULL REFERENCES kb_entries(id),
    embedding BLOB,
    model TEXT NOT NULL DEFAULT 'text-embedding-3-small',
    dimensions INTEGER NOT NULL DEFAULT 1536,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_kbembed_entry ON kb_embeddings(kb_entry_id);

-- Past performance library
CREATE TABLE IF NOT EXISTS past_performances (
    id TEXT PRIMARY KEY,
    contract_name TEXT NOT NULL,
    contract_number TEXT,
    agency TEXT NOT NULL,
    sub_agency TEXT,
    contract_type TEXT,
    contract_value REAL,
    period_of_performance_start TEXT,
    period_of_performance_end TEXT,
    naics_code TEXT,
    set_aside TEXT,
    role TEXT CHECK(role IN ('prime', 'subcontractor', 'joint_venture', 'teaming')),
    prime_contractor TEXT,
    scope_description TEXT NOT NULL,
    technical_approach TEXT,
    key_accomplishments TEXT,
    metrics_achieved TEXT,
    cpars_rating TEXT
        CHECK(cpars_rating IN ('exceptional', 'very_good', 'satisfactory',
              'marginal', 'unsatisfactory', NULL)),
    cpars_narrative TEXT,
    relevance_tags TEXT,
    contact_name TEXT,
    contact_title TEXT,
    contact_email TEXT,
    contact_phone TEXT,
    classification TEXT NOT NULL DEFAULT 'CUI // SP-PROPIN',
    cag_categories TEXT,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_pp_agency ON past_performances(agency);
CREATE INDEX IF NOT EXISTS idx_pp_naics ON past_performances(naics_code);
CREATE INDEX IF NOT EXISTS idx_pp_rating ON past_performances(cpars_rating);
CREATE INDEX IF NOT EXISTS idx_pp_active ON past_performances(is_active);

-- Resume / personnel database
CREATE TABLE IF NOT EXISTS resumes (
    id TEXT PRIMARY KEY,
    full_name TEXT NOT NULL,
    title TEXT,
    clearance_level TEXT
        CHECK(clearance_level IN ('none', 'public_trust', 'secret',
              'top_secret', 'ts_sci', 'ts_sci_poly', NULL)),
    clearance_status TEXT
        CHECK(clearance_status IN ('active', 'interim', 'expired',
              'pending', 'not_applicable', NULL)),
    years_experience INTEGER,
    education TEXT,
    certifications TEXT,
    skills TEXT,
    past_performance_ids TEXT,
    labor_category TEXT,
    bill_rate REAL,
    location TEXT,
    availability TEXT
        CHECK(availability IN ('available', 'committed', 'partial', NULL)),
    resume_text TEXT,
    bio_short TEXT,
    bio_long TEXT,
    classification TEXT NOT NULL DEFAULT 'CUI // SP-PROPIN',
    cag_categories TEXT,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_resume_clearance ON resumes(clearance_level);
CREATE INDEX IF NOT EXISTS idx_resume_active ON resumes(is_active);
CREATE INDEX IF NOT EXISTS idx_resume_avail ON resumes(availability);

-- ============================================================
-- CLASSIFICATION AGGREGATION GUARD (CAG)
-- ============================================================

-- Data tags on content elements
CREATE TABLE IF NOT EXISTS cag_data_tags (
    id TEXT PRIMARY KEY,
    source_type TEXT NOT NULL
        CHECK(source_type IN ('kb_entry', 'proposal_section', 'past_performance',
              'resume', 'opportunity', 'free_text')),
    source_id TEXT NOT NULL,
    category TEXT NOT NULL
        CHECK(category IN ('PERSONNEL', 'CAPABILITY', 'LOCATION', 'TIMING',
              'PROGRAM', 'VULNERABILITY', 'METHOD', 'SCALE', 'SOURCE',
              'RELATIONSHIP')),
    confidence REAL NOT NULL CHECK(confidence BETWEEN 0.0 AND 1.0),
    indicator_text TEXT,
    indicator_type TEXT CHECK(indicator_type IN ('strong', 'moderate', 'manual')),
    position_start INTEGER,
    position_end INTEGER,
    paragraph_index INTEGER,
    section_context TEXT,
    tagged_by TEXT NOT NULL DEFAULT 'auto',
    verified_by TEXT,
    classification_at_tag TEXT NOT NULL DEFAULT 'UNCLASSIFIED',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_cagtag_source ON cag_data_tags(source_type, source_id);
CREATE INDEX IF NOT EXISTS idx_cagtag_cat ON cag_data_tags(category);

-- Aggregation rules (loaded from YAML + SCGs)
CREATE TABLE IF NOT EXISTS cag_rules (
    id TEXT PRIMARY KEY,
    rule_type TEXT NOT NULL
        CHECK(rule_type IN ('universal', 'org', 'scg')),
    name TEXT NOT NULL,
    description TEXT,
    severity TEXT NOT NULL
        CHECK(severity IN ('LOW', 'MEDIUM', 'HIGH', 'CRITICAL')),
    trigger_categories TEXT NOT NULL,
    trigger_logic TEXT NOT NULL,
    resulting_classification TEXT NOT NULL,
    action TEXT NOT NULL
        CHECK(action IN ('alert', 'review_required', 'block_and_alert',
              'quarantine')),
    remediation TEXT,
    scg_program_id TEXT,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_cagrule_type ON cag_rules(rule_type);
CREATE INDEX IF NOT EXISTS idx_cagrule_severity ON cag_rules(severity);
CREATE INDEX IF NOT EXISTS idx_cagrule_active ON cag_rules(is_active);

-- CAG alerts (triggered aggregation detections)
CREATE TABLE IF NOT EXISTS cag_alerts (
    id TEXT PRIMARY KEY,
    proposal_id TEXT REFERENCES proposals(id),
    rule_id TEXT NOT NULL REFERENCES cag_rules(id),
    severity TEXT NOT NULL
        CHECK(severity IN ('LOW', 'MEDIUM', 'HIGH', 'CRITICAL')),
    status TEXT NOT NULL DEFAULT 'open'
        CHECK(status IN ('open', 'acknowledged', 'resolved', 'overridden',
              'quarantined', 'false_positive')),
    categories_triggered TEXT NOT NULL,
    source_elements TEXT NOT NULL,
    proximity_score REAL,
    resulting_classification TEXT NOT NULL,
    remediation_suggestion TEXT,
    resolved_by TEXT,
    resolved_at TEXT,
    resolution_notes TEXT,
    override_justification TEXT,
    override_approved_by TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_cagalert_prop ON cag_alerts(proposal_id);
CREATE INDEX IF NOT EXISTS idx_cagalert_status ON cag_alerts(status);
CREATE INDEX IF NOT EXISTS idx_cagalert_severity ON cag_alerts(severity);

-- Cross-proposal exposure register
CREATE TABLE IF NOT EXISTS cag_exposure_register (
    id TEXT PRIMARY KEY,
    capability_group TEXT NOT NULL,
    proposal_id TEXT NOT NULL REFERENCES proposals(id),
    categories_exposed TEXT NOT NULL,
    audience TEXT,
    exposure_date TEXT NOT NULL,
    classification_at_exposure TEXT NOT NULL DEFAULT 'UNCLASSIFIED',
    cumulative_categories TEXT,
    cumulative_classification TEXT,
    alert_generated INTEGER DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_cagexpose_cap ON cag_exposure_register(capability_group);
CREATE INDEX IF NOT EXISTS idx_cagexpose_prop ON cag_exposure_register(proposal_id);

-- SCG programs and rules
CREATE TABLE IF NOT EXISTS scg_programs (
    id TEXT PRIMARY KEY,
    program_name TEXT NOT NULL,
    scg_document_id TEXT,
    classification_guide_date TEXT,
    classifying_authority TEXT,
    declassification_instructions TEXT,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS scg_rules (
    id TEXT PRIMARY KEY,
    program_id TEXT NOT NULL REFERENCES scg_programs(id),
    scg_section TEXT,
    description TEXT NOT NULL,
    trigger_categories TEXT NOT NULL,
    trigger_keywords TEXT,
    resulting_classification TEXT NOT NULL,
    caveats TEXT,
    declassification TEXT,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_scgrule_prog ON scg_rules(program_id);

-- Shredded requirements (deep multi-section extraction)
CREATE TABLE IF NOT EXISTS shredded_requirements (
    id TEXT PRIMARY KEY,
    proposal_id TEXT NOT NULL REFERENCES proposals(id),
    requirement_id TEXT NOT NULL,
    requirement_text TEXT NOT NULL,
    obligation_level TEXT NOT NULL DEFAULT 'unknown'
        CHECK(obligation_level IN ('shall', 'must', 'will',
              'should', 'may', 'unknown')),
    source_section TEXT NOT NULL
        CHECK(source_section IN ('section_c', 'section_f',
              'section_h', 'section_j', 'section_l',
              'section_m', 'other')),
    cross_references TEXT,
    compliance_status TEXT NOT NULL DEFAULT 'not_addressed'
        CHECK(compliance_status IN ('not_addressed',
              'partially_addressed', 'fully_addressed',
              'not_applicable')),
    mapped_section_id TEXT,
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_shreq_prop ON shredded_requirements(proposal_id);
CREATE INDEX IF NOT EXISTS idx_shreq_source ON shredded_requirements(source_section);
CREATE INDEX IF NOT EXISTS idx_shreq_obligation ON shredded_requirements(obligation_level);
CREATE INDEX IF NOT EXISTS idx_shreq_status ON shredded_requirements(compliance_status);

-- ============================================================
-- CAPTURE MANAGEMENT
-- ============================================================

-- Win themes per opportunity
CREATE TABLE IF NOT EXISTS win_themes (
    id TEXT PRIMARY KEY,
    opportunity_id TEXT REFERENCES opportunities(id),
    proposal_id TEXT REFERENCES proposals(id),
    theme_text TEXT NOT NULL,
    supporting_evidence TEXT,
    discriminator_type TEXT
        CHECK(discriminator_type IN ('technical', 'management', 'cost',
              'past_performance', 'personnel', 'innovation', 'risk')),
    strength_rating REAL,
    usage_sections TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_wintheme_opp ON win_themes(opportunity_id);

-- Teaming partners
CREATE TABLE IF NOT EXISTS teaming_partners (
    id TEXT PRIMARY KEY,
    company_name TEXT NOT NULL,
    cage_code TEXT,
    duns_number TEXT,
    naics_codes TEXT,
    capabilities TEXT,
    set_aside_status TEXT,
    clearance_level TEXT,
    contract_vehicles TEXT,
    past_collaborations TEXT,
    contact_name TEXT,
    contact_email TEXT,
    relationship_score REAL,
    notes TEXT,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_team_active ON teaming_partners(is_active);

-- Customer intelligence profiles
CREATE TABLE IF NOT EXISTS customer_profiles (
    id TEXT PRIMARY KEY,
    agency TEXT NOT NULL,
    sub_agency TEXT,
    office TEXT,
    mission_statement TEXT,
    strategic_priorities TEXT,
    budget_trends TEXT,
    key_personnel TEXT,
    procurement_history TEXT,
    preferred_approaches TEXT,
    pain_points TEXT,
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_custprof_agency ON customer_profiles(agency);

-- Black hat (competitor) analyses
CREATE TABLE IF NOT EXISTS black_hat_analyses (
    id TEXT PRIMARY KEY,
    opportunity_id TEXT NOT NULL REFERENCES opportunities(id),
    competitor_name TEXT NOT NULL,
    competitor_strengths TEXT,
    competitor_weaknesses TEXT,
    likely_approach TEXT,
    likely_win_themes TEXT,
    likely_teaming TEXT,
    price_estimate TEXT,
    counter_strategies TEXT,
    risk_to_us TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_blackhat_opp ON black_hat_analyses(opportunity_id);

-- ============================================================
-- COMPETITIVE INTELLIGENCE
-- ============================================================

-- Competitor registry
CREATE TABLE IF NOT EXISTS competitors (
    id TEXT PRIMARY KEY,
    company_name TEXT NOT NULL,
    cage_code TEXT,
    duns_number TEXT,
    website TEXT,
    naics_codes TEXT,
    capabilities TEXT,
    contract_vehicles TEXT,
    key_personnel TEXT,
    revenue_estimate TEXT,
    employee_count INTEGER,
    clearance_level TEXT,
    set_aside_status TEXT,
    strengths TEXT,
    weaknesses TEXT,
    notes TEXT,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_competitor_active ON competitors(is_active);

-- Competitor win tracking (from FPDS)
CREATE TABLE IF NOT EXISTS competitor_wins (
    id TEXT PRIMARY KEY,
    competitor_id TEXT REFERENCES competitors(id),
    competitor_name TEXT NOT NULL,
    contract_number TEXT,
    agency TEXT NOT NULL,
    award_date TEXT,
    award_amount REAL,
    naics_code TEXT,
    description TEXT,
    contract_type TEXT,
    set_aside_type TEXT,
    fpds_id TEXT,
    source TEXT NOT NULL DEFAULT 'fpds',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_compwin_comp ON competitor_wins(competitor_id);
CREATE INDEX IF NOT EXISTS idx_compwin_agency ON competitor_wins(agency);
CREATE INDEX IF NOT EXISTS idx_compwin_naics ON competitor_wins(naics_code);

-- Pricing benchmarks (from FPDS analysis)
CREATE TABLE IF NOT EXISTS pricing_benchmarks (
    id TEXT PRIMARY KEY,
    naics_code TEXT NOT NULL,
    agency TEXT,
    contract_type TEXT,
    labor_category TEXT,
    average_rate REAL,
    median_rate REAL,
    percentile_25 REAL,
    percentile_75 REAL,
    sample_size INTEGER,
    data_period TEXT,
    source TEXT NOT NULL DEFAULT 'fpds',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_pricebench_naics ON pricing_benchmarks(naics_code);

-- ============================================================
-- LEARNING & DEBRIEFS
-- ============================================================

-- Post-submission debriefs
CREATE TABLE IF NOT EXISTS debriefs (
    id TEXT PRIMARY KEY,
    proposal_id TEXT NOT NULL REFERENCES proposals(id),
    opportunity_id TEXT NOT NULL REFERENCES opportunities(id),
    result TEXT NOT NULL CHECK(result IN ('win', 'loss')),
    evaluator_strengths TEXT,
    evaluator_weaknesses TEXT,
    evaluator_deficiencies TEXT,
    evaluated_price REAL,
    winning_price REAL,
    winning_contractor TEXT,
    lessons_learned TEXT,
    kb_updates_made TEXT,
    debrief_date TEXT,
    captured_by TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_debrief_prop ON debriefs(proposal_id);
CREATE INDEX IF NOT EXISTS idx_debrief_result ON debriefs(result);

-- Win/loss pattern analysis
CREATE TABLE IF NOT EXISTS win_loss_patterns (
    id TEXT PRIMARY KEY,
    pattern_type TEXT NOT NULL
        CHECK(pattern_type IN ('win_theme', 'approach', 'pricing',
              'teaming', 'personnel', 'format')),
    pattern_description TEXT NOT NULL,
    associated_outcomes TEXT,
    confidence REAL,
    sample_size INTEGER,
    recommendation TEXT,
    analyzed_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ============================================================
-- SYSTEM TABLES
-- ============================================================

-- Audit trail (append-only)
CREATE TABLE IF NOT EXISTS audit_trail (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT NOT NULL,
    actor TEXT,
    action TEXT NOT NULL,
    entity_type TEXT,
    entity_id TEXT,
    details TEXT,
    ip_address TEXT,
    session_id TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_audit_event ON audit_trail(event_type);
CREATE INDEX IF NOT EXISTS idx_audit_entity ON audit_trail(entity_type, entity_id);
CREATE INDEX IF NOT EXISTS idx_audit_time ON audit_trail(created_at);

-- Acronym registry
CREATE TABLE IF NOT EXISTS acronyms (
    id TEXT PRIMARY KEY,
    acronym TEXT NOT NULL UNIQUE,
    expansion TEXT NOT NULL,
    domain TEXT,
    usage_count INTEGER DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_acronym_name ON acronyms(acronym);

-- Document templates
CREATE TABLE IF NOT EXISTS templates (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    template_type TEXT NOT NULL
        CHECK(template_type IN ('proposal', 'volume', 'section',
              'executive_summary', 'letter', 'form')),
    agency TEXT,
    format_rules TEXT,
    content_template TEXT,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ============================================================
-- PHASE 36: EVOLUTIONARY INTELLIGENCE
-- ============================================================

-- Genome version tracking (D209 — semver + SHA-256)
CREATE TABLE IF NOT EXISTS genome_versions (
    id TEXT PRIMARY KEY,
    version TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    genome_data TEXT NOT NULL,
    change_type TEXT NOT NULL DEFAULT 'patch'
        CHECK(change_type IN ('major', 'minor', 'patch')),
    change_summary TEXT,
    parent_version TEXT,
    created_by TEXT NOT NULL DEFAULT 'system',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_genome_version ON genome_versions(version);

-- Child capabilities tracking
CREATE TABLE IF NOT EXISTS child_capabilities (
    id TEXT PRIMARY KEY,
    capability_name TEXT NOT NULL,
    capability_type TEXT NOT NULL DEFAULT 'tool',
    status TEXT NOT NULL DEFAULT 'active'
        CHECK(status IN ('active', 'disabled', 'deprecated', 'staging', 'evaluating')),
    source TEXT NOT NULL DEFAULT 'parent'
        CHECK(source IN ('parent', 'learned', 'marketplace', 'evolved', 'manual')),
    version TEXT,
    metadata TEXT,
    learned_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_childcap_status ON child_capabilities(status);

-- Learned behaviors reported to parent
CREATE TABLE IF NOT EXISTS learned_behaviors (
    id TEXT PRIMARY KEY,
    behavior_type TEXT NOT NULL
        CHECK(behavior_type IN ('optimization', 'error_recovery', 'compliance_shortcut',
              'performance_tuning', 'security_pattern', 'workflow_improvement',
              'configuration', 'other')),
    description TEXT NOT NULL,
    evidence TEXT,
    metrics_before TEXT,
    metrics_after TEXT,
    reported_to_parent INTEGER DEFAULT 0,
    reported_at TEXT,
    evaluation_status TEXT DEFAULT 'pending'
        CHECK(evaluation_status IN ('pending', 'accepted', 'rejected', 'deferred')),
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_learnedbeh_type ON learned_behaviors(behavior_type);
CREATE INDEX IF NOT EXISTS idx_learnedbeh_status ON learned_behaviors(evaluation_status);

-- ============================================================
-- PHASE 37: AI SECURITY (MITRE ATLAS)
-- ============================================================

-- Prompt injection detection log (append-only per D6)
CREATE TABLE IF NOT EXISTS prompt_injection_log (
    id TEXT PRIMARY KEY,
    project_id TEXT,
    user_id TEXT,
    source TEXT NOT NULL DEFAULT 'unknown',
    text_hash TEXT NOT NULL,
    detected INTEGER NOT NULL DEFAULT 0,
    confidence REAL NOT NULL DEFAULT 0.0,
    action TEXT NOT NULL DEFAULT 'allow'
        CHECK(action IN ('block', 'flag', 'warn', 'allow')),
    finding_count INTEGER NOT NULL DEFAULT 0,
    findings_json TEXT,
    classification TEXT NOT NULL DEFAULT 'CUI // SP-PROPIN',
    scanned_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_pi_project ON prompt_injection_log(project_id);
CREATE INDEX IF NOT EXISTS idx_pi_action ON prompt_injection_log(action);
CREATE INDEX IF NOT EXISTS idx_pi_time ON prompt_injection_log(scanned_at);

-- AI telemetry log (append-only per D6, D218 — SHA-256 hashing)
CREATE TABLE IF NOT EXISTS ai_telemetry (
    id TEXT PRIMARY KEY,
    project_id TEXT,
    user_id TEXT,
    agent_id TEXT,
    model_id TEXT NOT NULL,
    provider TEXT NOT NULL,
    function TEXT,
    prompt_hash TEXT NOT NULL,
    response_hash TEXT,
    input_tokens INTEGER DEFAULT 0,
    output_tokens INTEGER DEFAULT 0,
    thinking_tokens INTEGER DEFAULT 0,
    latency_ms REAL DEFAULT 0.0,
    cost_usd REAL DEFAULT 0.0,
    classification TEXT NOT NULL DEFAULT 'CUI // SP-PROPIN',
    api_key_source TEXT DEFAULT 'system',
    injection_scan_result TEXT,
    logged_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_aitelemetry_project ON ai_telemetry(project_id);
CREATE INDEX IF NOT EXISTS idx_aitelemetry_model ON ai_telemetry(model_id);
CREATE INDEX IF NOT EXISTS idx_aitelemetry_time ON ai_telemetry(logged_at);

-- AI Bill of Materials (AI BOM)
CREATE TABLE IF NOT EXISTS ai_bom (
    id TEXT PRIMARY KEY,
    project_id TEXT,
    component_type TEXT NOT NULL
        CHECK(component_type IN ('model', 'library', 'service', 'framework', 'dataset')),
    component_name TEXT NOT NULL,
    version TEXT NOT NULL DEFAULT 'unknown',
    provider TEXT,
    license TEXT,
    risk_level TEXT NOT NULL DEFAULT 'medium'
        CHECK(risk_level IN ('critical', 'high', 'medium', 'low')),
    classification TEXT NOT NULL DEFAULT 'CUI // SP-PROPIN',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_aibom_project ON ai_bom(project_id);
CREATE INDEX IF NOT EXISTS idx_aibom_risk ON ai_bom(risk_level);

-- ============================================================
-- PHASE 38: CLOUD-AGNOSTIC / LLM MULTI-PROVIDER
-- ============================================================

-- Cloud provider status tracking
CREATE TABLE IF NOT EXISTS cloud_provider_status (
    id TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    service TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'unknown'
        CHECK(status IN ('healthy', 'degraded', 'unavailable', 'unknown')),
    region TEXT,
    last_check_at TEXT,
    details TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_cloudstatus_provider ON cloud_provider_status(provider);
"""


def init_db(db_path=None):
    """Initialize the GovProposal database."""
    path = db_path or str(DB_PATH)
    db_dir = Path(path).parent
    db_dir.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")

    conn.executescript(SCHEMA_SQL)
    conn.commit()

    # Count tables
    cursor = conn.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='table'"
    )
    table_count = cursor.fetchone()[0]

    # Count indexes
    cursor = conn.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='index' "
        "AND name NOT LIKE 'sqlite_%'"
    )
    index_count = cursor.fetchone()[0]

    conn.close()

    return {
        "status": "initialized",
        "db_path": str(path),
        "tables": table_count,
        "indexes": index_count,
        "initialized_at": datetime.now(timezone.utc).isoformat(),
    }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Initialize GovProposal database")
    parser.add_argument("--json", action="store_true", help="JSON output")
    parser.add_argument("--db-path", help="Override database path")
    args = parser.parse_args()

    result = init_db(db_path=args.db_path)

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"GovProposal database initialized:")
        print(f"  Path:    {result['db_path']}")
        print(f"  Tables:  {result['tables']}")
        print(f"  Indexes: {result['indexes']}")
        print(f"  Time:    {result['initialized_at']}")
