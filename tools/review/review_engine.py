#!/usr/bin/env python3
# CUI // SP-PROPIN
# Controlled by: GovProposal Portal
# CUI Category: PROPIN
# Distribution: D
# POC: GovProposal System Administrator
"""Unified Review Engine supporting Pink/Red/Gold/White team reviews.

Loads review criteria from args/review_config.yaml, evaluates proposal
sections against those criteria, computes weighted per-section and overall
scores, and stores results in the proposal_reviews table with R/Y/G
(Red/Yellow/Green) traffic-light indicators.

Review types:
  - Pink:  Compliance — section presence, instruction coverage, page limits,
           formatting, required attachments.
  - Red:   Responsiveness — evaluation factor coverage, evidence backing,
           discriminators, strengths/weaknesses.
  - Gold:  Win Theme — theme consistency, customer focus, storytelling
           quality, graphics support, executive summary.
  - White: Final QC — cross-references, acronyms, classification markings,
           CAG clearance, file packaging.

Usage:
    python tools/review/review_engine.py --review --proposal-id PROP-001 --review-type pink --json
    python tools/review/review_engine.py --get --proposal-id PROP-001 --json
    python tools/review/review_engine.py --get --proposal-id PROP-001 --review-type red --json
    python tools/review/review_engine.py --summary --proposal-id PROP-001 --json
    python tools/review/review_engine.py --deficiencies --proposal-id PROP-001 --json
"""

import json
import os
import re
import secrets
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent
DB_PATH = Path(os.environ.get(
    "GOVPROPOSAL_DB_PATH", str(BASE_DIR / "data" / "govproposal.db")
))
REVIEW_CONFIG_PATH = BASE_DIR / "args" / "review_config.yaml"

# Optional YAML import
try:
    import yaml
except ImportError:
    yaml = None

# Valid review types matching the CHECK constraint on proposal_reviews
VALID_REVIEW_TYPES = ("pink", "red", "gold", "white")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _rv_id():
    """Generate a review ID: RV- followed by 12 hex characters."""
    return "RV-" + secrets.token_hex(6)


def _now():
    """Return current UTC timestamp as ISO-8601 string."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _get_db(db_path=None):
    """Open a database connection with WAL mode and foreign keys enabled.

    Args:
        db_path: Optional path override.  Falls back to DB_PATH.

    Returns:
        sqlite3.Connection with row_factory set to sqlite3.Row.
    """
    path = str(db_path or DB_PATH)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _audit(conn, event_type, action, entity_type=None, entity_id=None,
           details=None):
    """Write an append-only audit trail record.

    Args:
        conn: Active database connection.
        event_type: Category of event.
        action: Human-readable description.
        entity_type: Type of entity affected.
        entity_id: ID of the affected entity.
        details: Optional JSON-serializable details dict.
    """
    conn.execute(
        "INSERT INTO audit_trail (event_type, actor, action, entity_type, "
        "entity_id, details, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            event_type,
            "review_engine",
            action,
            entity_type,
            entity_id,
            json.dumps(details) if details else None,
            _now(),
        ),
    )


def _row_to_dict(row):
    """Convert a sqlite3.Row to a plain dict."""
    if row is None:
        return None
    return dict(row)


def _parse_json_field(value):
    """Safely parse a JSON string field."""
    if value is None:
        return None
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return value


def _load_review_config():
    """Load review criteria from args/review_config.yaml.

    Returns a dict keyed by review type ('pink_team', 'red_team', etc.)
    with criteria lists and thresholds.  Falls back to built-in defaults
    if YAML is unavailable or the file is missing.
    """
    if yaml and REVIEW_CONFIG_PATH.exists():
        with open(REVIEW_CONFIG_PATH, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}

    # Built-in fallback (minimal)
    return {
        "pink_team": {
            "description": "Verify every Section L instruction is addressed",
            "criteria": [
                {"id": "section_coverage", "label": "All required sections present", "weight": 0.30},
                {"id": "instruction_compliance", "label": "Each instruction addressed", "weight": 0.30},
                {"id": "page_limits", "label": "Page limits respected", "weight": 0.15},
                {"id": "format_compliance", "label": "Font, margins, spacing", "weight": 0.15},
                {"id": "required_attachments", "label": "Attachments included", "weight": 0.10},
            ],
            "pass_threshold": 0.90,
            "scoring": {"green": 0.90, "yellow": 0.70, "red": 0.70},
        },
        "red_team": {
            "description": "Evaluate against Section M evaluation criteria",
            "criteria": [
                {"id": "eval_factor_coverage", "label": "Eval factors addressed", "weight": 0.25},
                {"id": "strengths_articulated", "label": "Strengths tied to eval criteria", "weight": 0.20},
                {"id": "weaknesses_mitigated", "label": "Weaknesses preemptively addressed", "weight": 0.15},
                {"id": "proof_points", "label": "Evidence backing claims", "weight": 0.20},
                {"id": "discriminators_clear", "label": "Differentiators clear", "weight": 0.20},
            ],
            "pass_threshold": 0.80,
        },
        "gold_team": {
            "description": "Evaluate win theme integration and persuasiveness",
            "criteria": [
                {"id": "theme_consistency", "label": "Win themes throughout", "weight": 0.25},
                {"id": "customer_focus", "label": "Customer mission centered", "weight": 0.25},
                {"id": "storytelling", "label": "Compelling narrative", "weight": 0.20},
                {"id": "graphics_support", "label": "Graphics reinforce messages", "weight": 0.15},
                {"id": "executive_summary", "label": "Exec summary captures themes", "weight": 0.15},
            ],
            "pass_threshold": 0.75,
        },
        "white_team": {
            "description": "Final quality check before submission",
            "criteria": [
                {"id": "cross_references", "label": "All cross-refs resolve", "weight": 0.20},
                {"id": "acronyms", "label": "Acronym list complete", "weight": 0.10},
                {"id": "consistency", "label": "Consistent terminology", "weight": 0.15},
                {"id": "classification_markings", "label": "Markings on all pages", "weight": 0.20},
                {"id": "cag_clearance", "label": "CAG scan passes", "weight": 0.20},
                {"id": "file_packaging", "label": "File names, sizes, volumes", "weight": 0.15},
            ],
            "pass_threshold": 0.95,
        },
    }


def _traffic_light(score, config):
    """Convert a score to R/Y/G traffic light.

    Args:
        score: float between 0.0 and 1.0.
        config: Review type config dict with optional 'scoring' thresholds.

    Returns:
        'green', 'yellow', or 'red'.
    """
    scoring = config.get("scoring", {})
    green_threshold = scoring.get("green", config.get("pass_threshold", 0.80))
    yellow_threshold = scoring.get("yellow", green_threshold - 0.15)
    if score >= green_threshold:
        return "green"
    elif score >= yellow_threshold:
        return "yellow"
    return "red"


# ---------------------------------------------------------------------------
# Review evaluators (per review type)
# ---------------------------------------------------------------------------

def _evaluate_pink(section, proposal, compliance_rows):
    """Evaluate Pink Team criteria for a single section.

    Pink: compliance-focused — section presence, instruction coverage,
    page limits, formatting.

    Args:
        section: dict of proposal_sections row.
        proposal: dict of proposals row.
        compliance_rows: list of compliance_matrices dicts for this proposal.

    Returns:
        dict mapping criterion_id -> score (0.0-1.0).
    """
    scores = {}

    # section_coverage: section exists and has content
    has_content = bool(section.get("content") and
                       len(section["content"].strip()) > 50)
    scores["section_coverage"] = 1.0 if has_content else 0.0

    # instruction_compliance: check compliance matrix for this section
    section_num = section.get("section_number") or ""
    matched = [c for c in compliance_rows
               if c.get("section_number") == section_num]
    if matched:
        addressed = sum(
            1 for c in matched
            if c.get("compliance_status") in (
                "fully_addressed", "partially_addressed"
            )
        )
        scores["instruction_compliance"] = (
            addressed / max(len(matched), 1)
        )
    else:
        scores["instruction_compliance"] = 0.5  # no matrix data

    # page_limits
    page_limit = section.get("page_limit")
    page_count = section.get("page_count") or 0
    if page_limit and page_limit > 0:
        if page_count <= page_limit:
            scores["page_limits"] = 1.0
        else:
            over_pct = (page_count - page_limit) / page_limit
            scores["page_limits"] = max(1.0 - over_pct, 0.0)
    else:
        scores["page_limits"] = 1.0  # no limit defined

    # format_compliance (heuristic: check word count is reasonable)
    wc = section.get("word_count") or 0
    scores["format_compliance"] = 1.0 if wc > 0 else 0.3

    # required_attachments (checked at proposal level, not per-section)
    scores["required_attachments"] = 1.0

    return scores


def _evaluate_red(section, proposal, win_themes):
    """Evaluate Red Team criteria for a single section.

    Red: responsiveness — evaluation factor coverage, evidence backing,
    discriminators.

    Args:
        section: dict of proposal_sections row.
        proposal: dict of proposals row.
        win_themes: list of win_themes dicts.

    Returns:
        dict mapping criterion_id -> score (0.0-1.0).
    """
    scores = {}
    content = (section.get("content") or "").lower()
    content_len = len(content)

    # eval_factor_coverage: check if section M parsed factors are addressed
    section_m = _parse_json_field(proposal.get("section_m_parsed")) or []
    if section_m and isinstance(section_m, list):
        addressed = sum(
            1 for factor in section_m
            if isinstance(factor, str) and factor.lower()[:30] in content
        )
        scores["eval_factor_coverage"] = (
            addressed / max(len(section_m), 1)
        )
    else:
        scores["eval_factor_coverage"] = 0.5

    # strengths_articulated: look for strength-indicating language
    strength_indicators = [
        "strength", "advantage", "proven", "demonstrated",
        "successfully", "exceeded", "exceptional",
    ]
    found = sum(1 for kw in strength_indicators if kw in content)
    scores["strengths_articulated"] = min(found / 3.0, 1.0)

    # weaknesses_mitigated: look for mitigation language
    mitigation_indicators = [
        "mitigat", "address", "overcom", "resolv", "risk reduction",
        "contingency", "backup plan",
    ]
    found = sum(1 for kw in mitigation_indicators if kw in content)
    scores["weaknesses_mitigated"] = min(found / 2.0, 1.0)

    # proof_points: check for evidence references (KB, PP, metrics)
    kb_refs = len(re.findall(r"KB-[a-f0-9]+", content, re.IGNORECASE))
    pp_refs = len(re.findall(r"PP-[a-f0-9]+", content, re.IGNORECASE))
    metric_refs = len(re.findall(r"\d+%|\$[\d,]+|SLA|KPI", content))
    total_evidence = kb_refs + pp_refs + metric_refs
    scores["proof_points"] = min(total_evidence / 3.0, 1.0)

    # discriminators_clear: check for differentiating language
    diff_indicators = [
        "unique", "differentiator", "only provider", "unlike",
        "competitive advantage", "proprietary", "innovative",
    ]
    found = sum(1 for kw in diff_indicators if kw in content)
    scores["discriminators_clear"] = min(found / 2.0, 1.0)

    return scores


def _evaluate_gold(section, proposal, win_themes):
    """Evaluate Gold Team criteria for a single section.

    Gold: persuasiveness — win theme integration, customer focus,
    storytelling.

    Args:
        section: dict of proposal_sections row.
        proposal: dict of proposals row.
        win_themes: list of win_themes dicts.

    Returns:
        dict mapping criterion_id -> score (0.0-1.0).
    """
    scores = {}
    content = (section.get("content") or "").lower()

    # theme_consistency: check how many win themes are referenced
    theme_hits = 0
    for theme in win_themes:
        theme_text = (theme.get("theme_text") or "").lower()
        # Check if key phrases from the theme appear in content
        theme_words = [w for w in theme_text.split() if len(w) > 5][:5]
        if sum(1 for w in theme_words if w in content) >= 2:
            theme_hits += 1
    total_themes = max(len(win_themes), 1)
    scores["theme_consistency"] = min(theme_hits / total_themes, 1.0)

    # customer_focus: customer-centric language
    customer_indicators = [
        "your mission", "your requirement", "agency's",
        "customer", "stakeholder", "mission success",
        "operational need", "your team",
    ]
    found = sum(1 for kw in customer_indicators if kw in content)
    scores["customer_focus"] = min(found / 3.0, 1.0)

    # storytelling: narrative flow indicators
    story_indicators = [
        "for example", "as demonstrated", "consider",
        "imagine", "result was", "outcome", "impact",
        "success story", "case study", "scenario",
    ]
    found = sum(1 for kw in story_indicators if kw in content)
    scores["storytelling"] = min(found / 3.0, 1.0)

    # graphics_support: check for figure/table references
    fig_refs = len(re.findall(
        r"figure\s+\d+|table\s+\d+|exhibit\s+\d+|graphic",
        content,
    ))
    scores["graphics_support"] = min(fig_refs / 2.0, 1.0)

    # executive_summary: if this IS the exec summary section
    vol = (section.get("volume") or "").lower()
    sec_title = (section.get("section_title") or "").lower()
    if "executive" in vol or "executive" in sec_title:
        # Should contain theme references
        scores["executive_summary"] = scores["theme_consistency"]
    else:
        scores["executive_summary"] = 0.7  # neutral for non-exec sections

    return scores


def _evaluate_white(section, proposal, cag_alerts, acronym_list):
    """Evaluate White Team criteria for a single section.

    White: final QC — cross-references, acronyms, classification markings,
    CAG clearance, file packaging.

    Args:
        section: dict of proposal_sections row.
        proposal: dict of proposals row.
        cag_alerts: list of open CAG alerts for this proposal.
        acronym_list: set of known acronyms from the acronyms table.

    Returns:
        dict mapping criterion_id -> score (0.0-1.0).
    """
    scores = {}
    content = (section.get("content") or "")

    # cross_references: find "Section X.X" references and check they exist
    xrefs = re.findall(r"[Ss]ection\s+(\d+(?:\.\d+)*)", content)
    if xrefs:
        # We can't fully validate without all sections, so score based
        # on reference format quality
        scores["cross_references"] = 0.8
    else:
        scores["cross_references"] = 1.0  # no cross-refs = no broken refs

    # acronyms: find uppercase acronyms, check for first-use expansion
    found_acronyms = set(re.findall(r"\b[A-Z]{2,6}\b", content))
    # Common non-acronyms to exclude
    non_acronyms = {"THE", "AND", "FOR", "NOT", "BUT", "ALL", "HAS", "WAS",
                    "ARE", "CAN", "OUR", "HIS", "HER", "ITS", "MAY", "USE"}
    found_acronyms -= non_acronyms
    if found_acronyms:
        # Check how many have expansions in the acronym list
        if acronym_list:
            expanded = found_acronyms & acronym_list
            scores["acronyms"] = len(expanded) / max(len(found_acronyms), 1)
        else:
            scores["acronyms"] = 0.5  # no list to check against
    else:
        scores["acronyms"] = 1.0

    # consistency: check for basic terminology consistency issues
    # (heuristic: consistent use of "shall" vs "will", "Contractor" vs "we")
    has_shall = "shall" in content.lower()
    has_will = "will" in content.lower()
    if has_shall and has_will:
        scores["consistency"] = 0.7  # mixed usage
    else:
        scores["consistency"] = 1.0

    # classification_markings
    marking = proposal.get("classification") or "CUI // SP-PROPIN"
    has_marking = marking.lower() in content.lower() or "cui" in content.lower()
    scores["classification_markings"] = 1.0 if has_marking else 0.0

    # cag_clearance
    open_alerts = [a for a in cag_alerts
                   if a.get("status") in ("open", "quarantined")]
    if open_alerts:
        scores["cag_clearance"] = 0.0
    else:
        scores["cag_clearance"] = 1.0

    # file_packaging
    status = section.get("status") or "outline"
    scores["file_packaging"] = 1.0 if status == "final" else 0.5

    return scores


# ---------------------------------------------------------------------------
# Core Functions
# ---------------------------------------------------------------------------

def run_review(proposal_id, review_type, db_path=None):
    """Execute an automated proposal review.

    Loads criteria from args/review_config.yaml, evaluates each section
    against the criteria for the given review type, computes weighted
    per-section and overall scores, and stores results in proposal_reviews.

    Args:
        proposal_id: Proposal ID to review.
        review_type: One of 'pink', 'red', 'gold', 'white'.
        db_path: Optional database path override.

    Returns:
        dict with overall_score, pass_threshold, result (pass/fail),
        section_scores (list), strengths, weaknesses, deficiencies.

    Raises:
        ValueError: If proposal not found or invalid review type.
    """
    if review_type not in VALID_REVIEW_TYPES:
        raise ValueError(
            f"Invalid review_type '{review_type}'. "
            f"Must be one of: {', '.join(VALID_REVIEW_TYPES)}"
        )

    config = _load_review_config()
    type_key = f"{review_type}_team"
    review_cfg = config.get(type_key, {})
    criteria = review_cfg.get("criteria", [])
    pass_threshold = review_cfg.get("pass_threshold", 0.80)

    conn = _get_db(db_path)
    try:
        # Load proposal
        prop_row = conn.execute(
            "SELECT * FROM proposals WHERE id = ?", (proposal_id,)
        ).fetchone()
        if prop_row is None:
            raise ValueError(f"Proposal not found: {proposal_id}")
        proposal = _row_to_dict(prop_row)

        # Load sections
        sec_rows = conn.execute(
            "SELECT * FROM proposal_sections WHERE proposal_id = ? "
            "ORDER BY volume, section_number",
            (proposal_id,),
        ).fetchall()
        sections = [_row_to_dict(s) for s in sec_rows]
        if not sections:
            raise ValueError(f"No sections found for proposal {proposal_id}")

        # Load supporting data based on review type
        compliance_rows = []
        win_themes = []
        cag_alerts = []
        acronym_set = set()

        if review_type == "pink":
            cm_rows = conn.execute(
                "SELECT * FROM compliance_matrices WHERE proposal_id = ?",
                (proposal_id,),
            ).fetchall()
            compliance_rows = [_row_to_dict(r) for r in cm_rows]

        elif review_type in ("red", "gold"):
            opp_id = proposal.get("opportunity_id")
            wt_rows = conn.execute(
                "SELECT * FROM win_themes WHERE proposal_id = ? "
                "OR opportunity_id = ?",
                (proposal_id, opp_id),
            ).fetchall()
            win_themes = [_row_to_dict(r) for r in wt_rows]

        elif review_type == "white":
            alert_rows = conn.execute(
                "SELECT * FROM cag_alerts WHERE proposal_id = ?",
                (proposal_id,),
            ).fetchall()
            cag_alerts = [_row_to_dict(r) for r in alert_rows]
            acr_rows = conn.execute(
                "SELECT acronym FROM acronyms"
            ).fetchall()
            acronym_set = {r["acronym"].upper() for r in acr_rows}

        # Evaluate each section
        section_results = []
        all_strengths = []
        all_weaknesses = []
        all_deficiencies = []

        for section in sections:
            if review_type == "pink":
                crit_scores = _evaluate_pink(
                    section, proposal, compliance_rows
                )
            elif review_type == "red":
                crit_scores = _evaluate_red(section, proposal, win_themes)
            elif review_type == "gold":
                crit_scores = _evaluate_gold(section, proposal, win_themes)
            else:  # white
                crit_scores = _evaluate_white(
                    section, proposal, cag_alerts, acronym_set
                )

            # Compute weighted score for this section
            weighted_sum = 0.0
            total_weight = 0.0
            crit_details = []
            for c in criteria:
                cid = c.get("id", "")
                weight = c.get("weight", 0.0)
                score = crit_scores.get(cid, 0.5)
                weighted_sum += score * weight
                total_weight += weight
                light = _traffic_light(score, review_cfg)
                crit_details.append({
                    "criterion_id": cid,
                    "label": c.get("label", cid),
                    "weight": weight,
                    "score": round(score, 3),
                    "traffic_light": light,
                })

                # Categorize strengths / weaknesses / deficiencies
                if score >= 0.85:
                    all_strengths.append(
                        f"{section['section_number']} - "
                        f"{c.get('label', cid)}: {score:.0%}"
                    )
                elif score < 0.50:
                    fail_cond = c.get("fail_condition")
                    if fail_cond:
                        all_deficiencies.append(
                            f"{section['section_number']} - "
                            f"{c.get('label', cid)}: {fail_cond}"
                        )
                    else:
                        all_weaknesses.append(
                            f"{section['section_number']} - "
                            f"{c.get('label', cid)}: {score:.0%}"
                        )
                elif score < 0.70:
                    all_weaknesses.append(
                        f"{section['section_number']} - "
                        f"{c.get('label', cid)}: {score:.0%}"
                    )

            sec_score = (
                weighted_sum / total_weight if total_weight > 0 else 0.0
            )
            sec_light = _traffic_light(sec_score, review_cfg)

            section_results.append({
                "section_id": section["id"],
                "volume": section["volume"],
                "section_number": section["section_number"],
                "section_title": section["section_title"],
                "section_score": round(sec_score, 3),
                "traffic_light": sec_light,
                "criteria_scores": crit_details,
            })

        # Compute overall score (average of section scores)
        if section_results:
            overall_score = sum(
                s["section_score"] for s in section_results
            ) / len(section_results)
        else:
            overall_score = 0.0
        overall_score = round(overall_score, 3)
        overall_light = _traffic_light(overall_score, review_cfg)
        passed = overall_score >= pass_threshold

        # Store review record
        now = _now()
        review_id = _rv_id()
        conn.execute(
            "INSERT INTO proposal_reviews "
            "(id, proposal_id, review_type, overall_score, "
            " criteria_scores, strengths, weaknesses, deficiencies, "
            " recommendations, reviewer, review_status, reviewed_at, "
            " created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'completed', ?, ?)",
            (
                review_id, proposal_id, review_type, overall_score,
                json.dumps(section_results),
                json.dumps(all_strengths[:20]),
                json.dumps(all_weaknesses[:20]),
                json.dumps(all_deficiencies[:20]),
                json.dumps(_generate_recommendations(
                    review_type, all_deficiencies, all_weaknesses
                )),
                "review_engine",
                now, now,
            ),
        )

        _audit(conn, f"review.{review_type}",
               f"{review_type.title()} team review for {proposal_id}: "
               f"{'PASS' if passed else 'FAIL'} ({overall_score:.1%})",
               "proposal_reviews", review_id,
               {"overall_score": overall_score, "passed": passed,
                "sections_reviewed": len(section_results)})
        conn.commit()

        return {
            "review_id": review_id,
            "proposal_id": proposal_id,
            "review_type": review_type,
            "overall_score": overall_score,
            "overall_traffic_light": overall_light,
            "pass_threshold": pass_threshold,
            "result": "PASS" if passed else "FAIL",
            "sections_reviewed": len(section_results),
            "section_scores": section_results,
            "strengths": all_strengths[:20],
            "weaknesses": all_weaknesses[:20],
            "deficiencies": all_deficiencies[:20],
            "reviewed_at": now,
        }
    finally:
        conn.close()


def _generate_recommendations(review_type, deficiencies, weaknesses):
    """Generate actionable recommendations based on findings.

    Args:
        review_type: Type of review conducted.
        deficiencies: List of deficiency strings.
        weaknesses: List of weakness strings.

    Returns:
        list of recommendation strings.
    """
    recs = []

    if review_type == "pink":
        if any("section" in d.lower() for d in deficiencies):
            recs.append(
                "Missing required sections must be added before "
                "advancing to Red Team review."
            )
        if any("page" in d.lower() for d in deficiencies):
            recs.append(
                "Sections exceeding page limits need immediate editing "
                "to comply with solicitation instructions."
            )
        if any("instruction" in w.lower() for w in weaknesses):
            recs.append(
                "Review compliance matrix to ensure all Section L "
                "instructions have corresponding content."
            )

    elif review_type == "red":
        if any("eval" in d.lower() for d in deficiencies):
            recs.append(
                "Critical: One or more evaluation factors are not "
                "explicitly addressed. Map each factor to specific "
                "proposal content."
            )
        if any("evidence" in w.lower() or "proof" in w.lower()
               for w in weaknesses):
            recs.append(
                "Add specific past performance references, metrics, "
                "and case studies to support claims."
            )

    elif review_type == "gold":
        if any("theme" in w.lower() for w in weaknesses):
            recs.append(
                "Win themes are not consistently woven through sections. "
                "Each major section should reinforce at least one theme."
            )
        if any("customer" in w.lower() for w in weaknesses):
            recs.append(
                "Shift language from contractor-centric to "
                "customer-mission-centric."
            )

    elif review_type == "white":
        if any("cag" in d.lower() for d in deficiencies):
            recs.append(
                "CRITICAL: CAG alerts must be resolved before submission. "
                "Review with Security Officer."
            )
        if any("marking" in d.lower() for d in deficiencies):
            recs.append(
                "Classification markings missing on one or more sections. "
                "Apply CUI markings to all pages."
            )
        if any("acronym" in w.lower() for w in weaknesses):
            recs.append(
                "Update acronym list and ensure first-use expansion "
                "in all sections."
            )

    if not recs:
        recs.append(
            f"Address all {len(deficiencies)} deficiencies and "
            f"{len(weaknesses)} weaknesses identified in this review."
        )

    return recs


def get_review(proposal_id, review_type=None, db_path=None):
    """Retrieve review results for a proposal.

    Args:
        proposal_id: Proposal ID.
        review_type: Optional filter by review type.
        db_path: Optional database path override.

    Returns:
        list of review dicts.
    """
    conn = _get_db(db_path)
    try:
        if review_type:
            if review_type not in VALID_REVIEW_TYPES:
                raise ValueError(
                    f"Invalid review_type '{review_type}'. "
                    f"Must be one of: {', '.join(VALID_REVIEW_TYPES)}"
                )
            rows = conn.execute(
                "SELECT * FROM proposal_reviews "
                "WHERE proposal_id = ? AND review_type = ? "
                "ORDER BY reviewed_at DESC",
                (proposal_id, review_type),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM proposal_reviews "
                "WHERE proposal_id = ? ORDER BY reviewed_at DESC",
                (proposal_id,),
            ).fetchall()

        results = []
        for r in rows:
            d = _row_to_dict(r)
            for field in ("criteria_scores", "strengths", "weaknesses",
                          "deficiencies", "recommendations"):
                d[field] = _parse_json_field(d.get(field))
            results.append(d)
        return results
    finally:
        conn.close()


def get_review_summary(proposal_id, db_path=None):
    """Get a summary of all review types for a proposal.

    Returns the most recent review of each type with overall score and
    pass/fail status.

    Args:
        proposal_id: Proposal ID.
        db_path: Optional database path override.

    Returns:
        dict with per-type summary and overall readiness assessment.
    """
    config = _load_review_config()
    conn = _get_db(db_path)
    try:
        reviews_by_type = {}
        for rt in VALID_REVIEW_TYPES:
            row = conn.execute(
                "SELECT * FROM proposal_reviews "
                "WHERE proposal_id = ? AND review_type = ? "
                "ORDER BY reviewed_at DESC LIMIT 1",
                (proposal_id, rt),
            ).fetchone()
            if row:
                d = _row_to_dict(row)
                type_key = f"{rt}_team"
                threshold = config.get(type_key, {}).get(
                    "pass_threshold", 0.80
                )
                score = d.get("overall_score") or 0.0
                reviews_by_type[rt] = {
                    "review_id": d["id"],
                    "overall_score": score,
                    "pass_threshold": threshold,
                    "result": "PASS" if score >= threshold else "FAIL",
                    "reviewed_at": d.get("reviewed_at"),
                    "deficiency_count": len(
                        _parse_json_field(d.get("deficiencies")) or []
                    ),
                }
            else:
                reviews_by_type[rt] = {
                    "review_id": None,
                    "overall_score": None,
                    "result": "NOT_REVIEWED",
                    "reviewed_at": None,
                }

        # Overall readiness
        completed = [v for v in reviews_by_type.values()
                     if v["result"] != "NOT_REVIEWED"]
        passed = [v for v in completed if v["result"] == "PASS"]
        total_deficiencies = sum(
            v.get("deficiency_count", 0) for v in completed
        )

        readiness = "NOT_STARTED"
        if len(completed) == 4 and len(passed) == 4:
            readiness = "READY_FOR_SUBMISSION"
        elif len(completed) == 4:
            readiness = "REVIEWS_COMPLETE_WITH_ISSUES"
        elif completed:
            readiness = "IN_PROGRESS"

        return {
            "proposal_id": proposal_id,
            "reviews": reviews_by_type,
            "reviews_completed": len(completed),
            "reviews_passed": len(passed),
            "total_deficiencies": total_deficiencies,
            "readiness": readiness,
        }
    finally:
        conn.close()


def list_deficiencies(proposal_id, db_path=None):
    """List all deficiencies across all review types for a proposal.

    Args:
        proposal_id: Proposal ID.
        db_path: Optional database path override.

    Returns:
        list of deficiency dicts with review_type, text, and severity.
    """
    conn = _get_db(db_path)
    try:
        rows = conn.execute(
            "SELECT review_type, deficiencies, weaknesses, reviewed_at "
            "FROM proposal_reviews WHERE proposal_id = ? "
            "ORDER BY reviewed_at DESC",
            (proposal_id,),
        ).fetchall()

        all_deficiencies = []
        for r in rows:
            rt = r["review_type"]
            defs = _parse_json_field(r["deficiencies"]) or []
            for d in defs:
                all_deficiencies.append({
                    "review_type": rt,
                    "severity": "DEFICIENCY",
                    "text": d,
                    "reviewed_at": r["reviewed_at"],
                })
            weaks = _parse_json_field(r["weaknesses"]) or []
            for w in weaks:
                all_deficiencies.append({
                    "review_type": rt,
                    "severity": "WEAKNESS",
                    "text": w,
                    "reviewed_at": r["reviewed_at"],
                })

        # Sort: deficiencies first, then by review pipeline order
        type_order = {"pink": 0, "red": 1, "gold": 2, "white": 3}
        sev_order = {"DEFICIENCY": 0, "WEAKNESS": 1}
        all_deficiencies.sort(key=lambda x: (
            sev_order.get(x["severity"], 1),
            type_order.get(x["review_type"], 4),
        ))

        return all_deficiencies
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_parser():
    """Build argument parser for the CLI."""
    import argparse
    parser = argparse.ArgumentParser(
        description="GovProposal Review Engine",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  %(prog)s --review --proposal-id PROP-001 "
            "--review-type pink --json\n"
            "  %(prog)s --get --proposal-id PROP-001 --json\n"
            "  %(prog)s --summary --proposal-id PROP-001 --json\n"
            "  %(prog)s --deficiencies --proposal-id PROP-001 --json\n"
        ),
    )

    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--review", action="store_true",
                        help="Run a review")
    action.add_argument("--get", action="store_true",
                        help="Retrieve review results")
    action.add_argument("--summary", action="store_true",
                        help="Review summary across all types")
    action.add_argument("--deficiencies", action="store_true",
                        help="List all deficiencies")

    parser.add_argument("--proposal-id", help="Proposal ID")
    parser.add_argument("--review-type",
                        choices=VALID_REVIEW_TYPES,
                        help="Review type (pink/red/gold/white)")
    parser.add_argument("--json", action="store_true", help="JSON output")
    parser.add_argument("--db-path", help="Override database path")

    return parser


def main():
    """CLI entry point."""
    parser = _build_parser()
    args = parser.parse_args()
    db = args.db_path

    try:
        if not args.proposal_id:
            parser.error("--proposal-id is required")

        if args.review:
            if not args.review_type:
                parser.error("--review requires --review-type")
            result = run_review(
                args.proposal_id, args.review_type, db_path=db
            )

        elif args.get:
            result = get_review(
                args.proposal_id,
                review_type=args.review_type,
                db_path=db,
            )

        elif args.summary:
            result = get_review_summary(args.proposal_id, db_path=db)

        elif args.deficiencies:
            result = list_deficiencies(args.proposal_id, db_path=db)

        # Output
        if args.json:
            print(json.dumps(result, indent=2, default=str))
        else:
            if isinstance(result, list):
                print(f"Found {len(result)} item(s):")
                for item in result:
                    if "review_type" in item and "severity" in item:
                        print(f"  [{item['review_type'].upper()}] "
                              f"{item['severity']}: {item['text']}")
                    elif "review_type" in item:
                        score = item.get("overall_score", "?")
                        print(f"  [{item['review_type'].upper()}] "
                              f"Score: {score}")
                    else:
                        print(f"  {item}")
            elif isinstance(result, dict):
                for key, value in result.items():
                    if isinstance(value, (list, dict)):
                        if key == "section_scores":
                            print(f"  {key}: ({len(value)} sections)")
                        else:
                            print(f"  {key}: "
                                  f"{json.dumps(value, default=str)}")
                    else:
                        print(f"  {key}: {value}")

    except ValueError as exc:
        if args.json:
            print(json.dumps({"error": str(exc)}, indent=2))
        else:
            print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
    except sqlite3.Error as exc:
        if args.json:
            print(json.dumps({"error": f"Database error: {exc}"}, indent=2))
        else:
            print(f"Database error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
