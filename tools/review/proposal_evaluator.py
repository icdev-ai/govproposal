#!/usr/bin/env python3
# CUI // SP-PROPIN
# Controlled by: GovProposal Portal
# CUI Category: PROPIN
# Distribution: D
# POC: GovProposal System Administrator
"""AI Proposal Self-Scoring Evaluator — simulates government evaluation BEFORE
submission using DoD Source Selection (FAR 15.305) rating methodology.

Loads Section M evaluation criteria, proposal sections, compliance matrix, win
themes, shredded requirements, and past performance data; then scores each
evaluation factor 1-5 using the FAR adjectival rating scale.  Identifies
strengths, weaknesses, risks, and discriminators exactly as a government
Source Selection Evaluation Board (SSEB) would.

Rating scale (FAR 15.305):
  5 - Outstanding : Exceeds requirements, no weaknesses, significant strengths
  4 - Good        : Exceeds some requirements, few minor weaknesses, strengths
  3 - Acceptable  : Meets requirements, weaknesses don't outweigh, adequate
  2 - Marginal    : Fails some requirements, weaknesses impair, risk concerns
  1 - Unacceptable: Fails requirements, significant weaknesses, high risk

Usage:
    python tools/review/proposal_evaluator.py --evaluate --proposal-id PROP-123 --json
    python tools/review/proposal_evaluator.py --score-section --proposal-id PROP-123 --section 1.1 --json
    python tools/review/proposal_evaluator.py --compliance-gaps --proposal-id PROP-123 --json
    python tools/review/proposal_evaluator.py --strengths-weaknesses --proposal-id PROP-123 --json
    python tools/review/proposal_evaluator.py --competitive-position --proposal-id PROP-123 --json
    python tools/review/proposal_evaluator.py --improvement-roadmap --proposal-id PROP-123 --json
    python tools/review/proposal_evaluator.py --history --proposal-id PROP-123 --json
    python tools/review/proposal_evaluator.py --batch --status draft --json
"""

import json
import math
import os
import re
import secrets
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent
DB_PATH = Path(os.environ.get(
    "GOVPROPOSAL_DB_PATH", str(BASE_DIR / "data" / "govproposal.db")
))

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

RATING_SCALE = {
    5: "outstanding",
    4: "good",
    3: "acceptable",
    2: "marginal",
    1: "unacceptable",
}

DEFAULT_EVAL_FACTORS = {
    "technical_approach": 0.40,
    "management_approach": 0.25,
    "past_performance": 0.20,
    "cost_realism": 0.15,
}

# Patterns that indicate vague, non-committal language an evaluator would penalise
VAGUE_PATTERNS = [
    r"\bwill ensure\b", r"\bas needed\b", r"\bmay include\b",
    r"\bvarious\b", r"\betc\.?\b", r"\bappropriate\b",
    r"\badequate\b", r"\bas applicable\b", r"\bas required\b",
    r"\btbd\b", r"\bto be determined\b", r"\bas necessary\b",
    r"\bgenerally\b", r"\btypically\b", r"\bsufficient\b",
]

# Patterns that indicate strong, evaluator-favoured evidence language
STRONG_PATTERNS = [
    r"\d+%",                           # quantified metrics
    r"\$[\d,]+",                        # dollar amounts
    r"\d+\s*(?:days?|months?|years?)",  # specific timelines
    r"(?:SLA|KPI|OLA)\b",              # performance references
    r"(?:ISO|CMMI|ITIL|PMP|CISSP)\b",  # methodology/cert references
    r"CPARS\s+(?:Exceptional|Very\s+Good)", # past performance ratings
    r"(?:PP|KB)-[A-Fa-f0-9]+",         # KB / PP cross-references
    r"\b(?:patented|proprietary|award[- ]winning)\b",
    r"\b\d{1,2}/\d{1,2}/\d{2,4}\b",   # specific dates
]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _eval_id():
    """Generate an evaluation ID: EVAL- followed by 12 hex characters."""
    return "EVAL-" + secrets.token_hex(6)


def _now():
    """Return current UTC timestamp as ISO-8601 string."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _get_db(db_path=None):
    """Open a database connection with WAL mode and foreign keys enabled."""
    path = str(db_path or DB_PATH)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _audit(conn, event_type, action, entity_type=None, entity_id=None,
           details=None):
    """Write an append-only audit trail record."""
    conn.execute(
        "INSERT INTO audit_trail (event_type, actor, action, entity_type, "
        "entity_id, details, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (event_type, "proposal_evaluator", action, entity_type, entity_id,
         json.dumps(details) if details else None, _now()),
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


def _count_pattern_matches(text, patterns):
    """Count total regex matches from a list of patterns against text."""
    total = 0
    for pat in patterns:
        total += len(re.findall(pat, text, re.IGNORECASE))
    return total


def _score_to_rating(score):
    """Map a numeric score (1-5) to an adjectival rating string."""
    rounded = max(1, min(5, round(score)))
    return RATING_SCALE.get(rounded, "unacceptable")


def _clamp(value, lo=1.0, hi=5.0):
    """Clamp a value between lo and hi."""
    return max(lo, min(hi, value))


# ---------------------------------------------------------------------------
# Data loaders
# ---------------------------------------------------------------------------

def _load_proposal(conn, proposal_id):
    """Load proposal row or raise ValueError."""
    row = conn.execute(
        "SELECT * FROM proposals WHERE id = ?", (proposal_id,)
    ).fetchone()
    if row is None:
        raise ValueError(f"Proposal not found: {proposal_id}")
    return _row_to_dict(row)


def _load_sections(conn, proposal_id):
    """Load all sections for a proposal, ordered by volume and number."""
    rows = conn.execute(
        "SELECT * FROM proposal_sections WHERE proposal_id = ? "
        "ORDER BY volume, section_number", (proposal_id,)
    ).fetchall()
    return [_row_to_dict(r) for r in rows]


def _load_compliance(conn, proposal_id):
    """Load compliance matrix entries for a proposal."""
    rows = conn.execute(
        "SELECT * FROM compliance_matrices WHERE proposal_id = ?",
        (proposal_id,)
    ).fetchall()
    return [_row_to_dict(r) for r in rows]


def _load_requirements(conn, proposal_id):
    """Load shredded requirements for a proposal."""
    rows = conn.execute(
        "SELECT * FROM shredded_requirements WHERE proposal_id = ?",
        (proposal_id,)
    ).fetchall()
    return [_row_to_dict(r) for r in rows]


def _load_win_themes(conn, proposal_id, opportunity_id=None):
    """Load win themes for a proposal (or its opportunity)."""
    rows = conn.execute(
        "SELECT * FROM win_themes WHERE proposal_id = ? OR opportunity_id = ?",
        (proposal_id, opportunity_id)
    ).fetchall()
    return [_row_to_dict(r) for r in rows]


def _load_past_performances(conn, proposal_id=None):
    """Load past performance records.  Checks proposal-linked first, falls
    back to all records in the knowledge base."""
    if proposal_id:
        rows = conn.execute(
            "SELECT * FROM past_performances WHERE proposal_id = ?",
            (proposal_id,)
        ).fetchall()
        if rows:
            return [_row_to_dict(r) for r in rows]
    # Fallback: all past performances (KB-level)
    rows = conn.execute(
        "SELECT * FROM past_performances ORDER BY contract_value DESC LIMIT 20"
    ).fetchall()
    return [_row_to_dict(r) for r in rows]


def _get_eval_factors(proposal):
    """Extract evaluation factors + weights from section_m_parsed, or return
    the DoD default factors if none defined."""
    m_data = _parse_json_field(proposal.get("section_m_parsed"))
    if not m_data:
        return DEFAULT_EVAL_FACTORS

    # section_m_parsed may be a list of factor dicts or a dict with
    # evaluation_factors key
    factors = {}
    if isinstance(m_data, dict):
        ef = m_data.get("evaluation_factors") or m_data.get("factors")
        if isinstance(ef, list):
            m_data = ef
        elif isinstance(ef, dict):
            return ef  # already factor_name: weight

    if isinstance(m_data, list):
        total_weight = 0.0
        for item in m_data:
            if isinstance(item, dict):
                name = item.get("factor", item.get("name", ""))
                weight = item.get("weight", 0.0)
                if isinstance(weight, str):
                    # parse percentage strings like "40%"
                    weight = float(weight.strip("%")) / 100.0
                if name:
                    key = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
                    factors[key] = float(weight) if weight else 0.0
                    total_weight += factors[key]
            elif isinstance(item, str):
                key = re.sub(r"[^a-z0-9]+", "_", item.lower()).strip("_")
                factors[key] = 0.0

        # If weights don't sum to ~1.0, normalise them
        if factors and total_weight > 0 and abs(total_weight - 1.0) > 0.05:
            for k in factors:
                factors[k] = factors[k] / total_weight
        elif factors and total_weight == 0:
            even = 1.0 / len(factors)
            for k in factors:
                factors[k] = even

    return factors if factors else DEFAULT_EVAL_FACTORS


# ---------------------------------------------------------------------------
# Section-level scoring
# ---------------------------------------------------------------------------

def _score_content_quality(content, word_count, page_count, page_limit):
    """Evaluate raw content quality on a 1-5 scale.

    Sub-dimensions:
      - Word count adequacy (vs page limit heuristic: ~250 words/page)
      - Specificity (strong patterns vs vague patterns ratio)
      - Evidence density (quantified claims, cross-refs)
    """
    if not content or not content.strip():
        return 1.0, {"word_count": 0, "specificity": 0, "evidence": 0}

    text = content.strip()
    wc = word_count or len(text.split())

    # Word count adequacy -------------------------------------------------
    expected_words = 250  # default per-page heuristic
    if page_limit and page_limit > 0:
        expected_words = int(page_limit * 250)
    utilisation = wc / max(expected_words, 1)

    if utilisation >= 0.85:
        wc_score = 5.0
    elif utilisation >= 0.65:
        wc_score = 4.0
    elif utilisation >= 0.40:
        wc_score = 3.0
    elif utilisation >= 0.20:
        wc_score = 2.0
    else:
        wc_score = 1.0

    # Penalise over-limit
    if page_limit and page_count and page_count > page_limit:
        wc_score = max(1.0, wc_score - 1.5)

    # Specificity ----------------------------------------------------------
    strong_count = _count_pattern_matches(text, STRONG_PATTERNS)
    vague_count = _count_pattern_matches(text, VAGUE_PATTERNS)
    per_1k = (wc / 1000.0) if wc > 0 else 1.0

    strong_density = strong_count / max(per_1k, 0.1)
    vague_density = vague_count / max(per_1k, 0.1)
    net_specificity = strong_density - vague_density

    if net_specificity >= 6.0:
        spec_score = 5.0
    elif net_specificity >= 3.0:
        spec_score = 4.0
    elif net_specificity >= 0.5:
        spec_score = 3.0
    elif net_specificity >= -1.0:
        spec_score = 2.0
    else:
        spec_score = 1.0

    # Evidence density -----------------------------------------------------
    evidence_per_1k = strong_count / max(per_1k, 0.1)
    if evidence_per_1k >= 8.0:
        ev_score = 5.0
    elif evidence_per_1k >= 4.0:
        ev_score = 4.0
    elif evidence_per_1k >= 2.0:
        ev_score = 3.0
    elif evidence_per_1k >= 0.5:
        ev_score = 2.0
    else:
        ev_score = 1.0

    # Weighted composite
    composite = (wc_score * 0.30) + (spec_score * 0.40) + (ev_score * 0.30)
    detail = {
        "word_count": wc,
        "expected_words": expected_words,
        "utilisation_pct": round(utilisation * 100, 1),
        "strong_indicators": strong_count,
        "vague_indicators": vague_count,
        "specificity_score": round(spec_score, 2),
        "evidence_score": round(ev_score, 2),
        "word_count_score": round(wc_score, 2),
    }
    return round(_clamp(composite), 2), detail


def score_section(proposal_id, section_number, db_path=None):
    """Score an individual proposal section.

    Analyses word count vs limit, requirement coverage, keyword relevance,
    evidence presence, and vague language detection.

    Returns:
        dict with section_number, score, rating, strengths, weaknesses,
        improvement_suggestions.
    """
    conn = _get_db(db_path)
    try:
        proposal = _load_proposal(conn, proposal_id)
        row = conn.execute(
            "SELECT * FROM proposal_sections "
            "WHERE proposal_id = ? AND section_number = ?",
            (proposal_id, section_number)
        ).fetchone()
        if row is None:
            raise ValueError(
                f"Section {section_number} not found for {proposal_id}"
            )
        section = _row_to_dict(row)
        content = section.get("content") or ""
        wc = section.get("word_count") or 0
        pc = section.get("page_count") or 0
        pl = section.get("page_limit")

        quality_score, quality_detail = _score_content_quality(
            content, wc, pc, pl
        )

        # Requirement coverage for this section
        cm_rows = conn.execute(
            "SELECT * FROM compliance_matrices "
            "WHERE proposal_id = ? AND section_number = ?",
            (proposal_id, section_number)
        ).fetchall()
        cm_list = [_row_to_dict(r) for r in cm_rows]

        if cm_list:
            fully = sum(1 for c in cm_list
                        if c.get("compliance_status") == "fully_addressed")
            partial = sum(1 for c in cm_list
                          if c.get("compliance_status") == "partially_addressed")
            coverage = (fully + partial * 0.5) / len(cm_list)
        else:
            coverage = 0.5  # neutral when no matrix data

        # Win theme presence
        themes = _load_win_themes(conn, proposal_id,
                                  proposal.get("opportunity_id"))
        theme_hits = 0
        content_lower = content.lower()
        for t in themes:
            words = [w for w in (t.get("theme_text") or "").lower().split()
                     if len(w) > 4][:5]
            if words and sum(1 for w in words if w in content_lower) >= 2:
                theme_hits += 1
        theme_coverage = (theme_hits / max(len(themes), 1)) if themes else 0.5

        # Combine into section score (1-5)
        coverage_score = _clamp(1.0 + coverage * 4.0)
        theme_score = _clamp(1.0 + theme_coverage * 4.0)
        section_score = round(
            quality_score * 0.50 +
            coverage_score * 0.30 +
            theme_score * 0.20, 2
        )

        # Identify strengths / weaknesses / suggestions
        strengths = []
        weaknesses = []
        suggestions = []

        if quality_detail["strong_indicators"] >= 5:
            strengths.append("Strong use of quantified evidence and metrics")
        if coverage >= 0.9:
            strengths.append("Excellent requirement coverage (>90%)")
        if theme_hits >= 2:
            strengths.append(f"Win themes well-integrated ({theme_hits} themes referenced)")

        if quality_detail["vague_indicators"] >= 3:
            weaknesses.append(
                f"Vague language detected ({quality_detail['vague_indicators']} instances) "
                "- replace with specific commitments"
            )
            suggestions.append(
                "Replace 'will ensure', 'as needed', 'appropriate' with "
                "concrete metrics, dates, and named approaches."
            )
        if quality_detail.get("utilisation_pct", 0) < 50:
            weaknesses.append(
                f"Under-utilised page allocation ({quality_detail['utilisation_pct']:.0f}% of available space)"
            )
            suggestions.append(
                "Expand content with additional evidence, graphics references, "
                "and detailed methodology descriptions."
            )
        if pl and pc and pc > pl:
            weaknesses.append(
                f"Exceeds page limit ({pc} pages vs {pl} allowed)"
            )
            suggestions.append(
                "Edit for conciseness.  Prioritise evaluation factor "
                "language and remove boilerplate."
            )
        if coverage < 0.5 and cm_list:
            weaknesses.append(
                f"Low requirement coverage ({coverage:.0%}) - "
                f"{sum(1 for c in cm_list if c.get('compliance_status') == 'not_addressed')} "
                "requirements not addressed"
            )
            suggestions.append(
                "Cross-reference the compliance matrix and add responsive "
                "content for each unaddressed requirement."
            )
        if quality_detail["strong_indicators"] < 2:
            weaknesses.append(
                "Lacks quantified evidence - add specific metrics, dates, "
                "and past performance citations"
            )
            suggestions.append(
                "Include at least 3-5 proof points per page: SLA metrics, "
                "CPARS ratings, dollar values, timeline achievements."
            )
        if theme_hits == 0 and themes:
            weaknesses.append("No win themes referenced in this section")
            suggestions.append(
                "Weave at least one win theme into the section narrative "
                "with supporting evidence."
            )

        return {
            "proposal_id": proposal_id,
            "section_number": section_number,
            "section_title": section.get("section_title"),
            "volume": section.get("volume"),
            "score": round(section_score, 2),
            "rating": _score_to_rating(section_score),
            "quality_detail": quality_detail,
            "requirement_coverage_pct": round(coverage * 100, 1),
            "theme_coverage_pct": round(theme_coverage * 100, 1),
            "strengths": strengths,
            "weaknesses": weaknesses,
            "improvement_suggestions": suggestions,
        }
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Compliance gap analysis
# ---------------------------------------------------------------------------

def compliance_gap_analysis(proposal_id, db_path=None):
    """Detailed compliance gap analysis by evaluation factor.

    For each requirement in the compliance matrix:
      - Check if the mapped section exists and has content
      - Keyword-match requirement_text against section content
      - Score: fully_addressed / partially_addressed / not_addressed

    Returns:
        dict with total_reqs, coverage_pct, gaps_by_factor,
        critical_gaps (shall/must unaddressed).
    """
    conn = _get_db(db_path)
    try:
        proposal = _load_proposal(conn, proposal_id)
        cm_rows = _load_compliance(conn, proposal_id)
        sections = _load_sections(conn, proposal_id)
        requirements = _load_requirements(conn, proposal_id)

        if not cm_rows:
            return {
                "proposal_id": proposal_id,
                "total_requirements": 0,
                "coverage_pct": 0.0,
                "message": "No compliance matrix entries.  Run compliance_matrix.py --generate first.",
            }

        # Build section content index
        section_content = {}
        for s in sections:
            sn = s.get("section_number")
            if sn:
                section_content[sn] = (s.get("content") or "").lower()

        # Build obligation map from shredded requirements
        obligation_map = {}
        for req in requirements:
            obligation_map[req.get("requirement_id")] = req.get(
                "obligation_level", "unknown"
            )

        results = []
        gaps_by_factor = defaultdict(list)
        critical_gaps = []
        total = len(cm_rows)
        fully = 0
        partial = 0

        for cm in cm_rows:
            req_text = (cm.get("requirement_text") or "").lower()
            sec_num = cm.get("section_number")
            source = cm.get("source", "other")
            req_id = cm.get("requirement_id", "")
            obligation = obligation_map.get(req_id, "unknown")

            # Determine actual coverage by checking section content
            if sec_num and sec_num in section_content:
                sec_content = section_content[sec_num]
                # Extract keywords from requirement, check overlap
                req_words = set(re.findall(r"[a-z]{4,}", req_text))
                req_words -= {"shall", "must", "will", "should",
                              "contractor", "offeror", "government",
                              "provide", "include", "ensure"}
                if req_words:
                    matched = sum(1 for w in req_words if w in sec_content)
                    match_ratio = matched / len(req_words)
                else:
                    match_ratio = 0.0

                if match_ratio >= 0.5:
                    status = "fully_addressed"
                    fully += 1
                elif match_ratio >= 0.2:
                    status = "partially_addressed"
                    partial += 1
                else:
                    status = "not_addressed"
            else:
                status = "not_addressed"
                match_ratio = 0.0

            entry = {
                "requirement_id": req_id,
                "requirement_text": cm.get("requirement_text", "")[:200],
                "source": source,
                "section_number": sec_num,
                "obligation_level": obligation,
                "assessed_status": status,
                "match_ratio": round(match_ratio, 3),
            }
            results.append(entry)

            if status != "fully_addressed":
                factor_key = source.replace("section_", "")
                gaps_by_factor[factor_key].append(entry)

            if status == "not_addressed" and obligation in ("shall", "must"):
                critical_gaps.append(entry)

        applicable = total
        coverage = 0.0
        if applicable > 0:
            coverage = round(
                (fully + partial * 0.5) / applicable * 100, 1
            )

        return {
            "proposal_id": proposal_id,
            "total_requirements": total,
            "fully_addressed": fully,
            "partially_addressed": partial,
            "not_addressed": total - fully - partial,
            "coverage_pct": coverage,
            "gaps_by_factor": dict(gaps_by_factor),
            "critical_gaps": critical_gaps,
            "critical_gap_count": len(critical_gaps),
            "details": results,
            "assessed_at": _now(),
        }
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Strength / weakness / risk analysis
# ---------------------------------------------------------------------------

def strength_weakness_analysis(proposal_id, db_path=None):
    """Identify strengths, weaknesses, and risks across the entire proposal
    as a government SSEB would.

    Returns:
        dict with strengths, weaknesses, risks, net_assessment.
    """
    conn = _get_db(db_path)
    try:
        proposal = _load_proposal(conn, proposal_id)
        sections = _load_sections(conn, proposal_id)
        themes = _load_win_themes(conn, proposal_id,
                                  proposal.get("opportunity_id"))
        pp_records = _load_past_performances(conn, proposal_id)
        cm_rows = _load_compliance(conn, proposal_id)

        strengths = []
        weaknesses = []
        risks = []

        all_content = ""
        total_strong = 0
        total_vague = 0
        sections_over_limit = 0
        sections_under_utilised = 0
        total_sections = len(sections)

        for section in sections:
            content = section.get("content") or ""
            all_content += " " + content
            wc = section.get("word_count") or len(content.split())
            pl = section.get("page_limit")
            pc = section.get("page_count") or 0

            strong = _count_pattern_matches(content, STRONG_PATTERNS)
            vague = _count_pattern_matches(content, VAGUE_PATTERNS)
            total_strong += strong
            total_vague += vague

            if pl and pc > pl:
                sections_over_limit += 1
            if pl and pl > 0:
                expected = int(pl * 250)
                if wc < expected * 0.4:
                    sections_under_utilised += 1

        # -- Strengths --
        if total_strong >= 20:
            strengths.append({
                "category": "evidence",
                "text": f"Strong evidence base with {total_strong} quantified proof points across the proposal",
                "impact": "high",
            })

        # Past performance strengths
        exceptional_pp = [p for p in pp_records
                          if p.get("cpars_rating") in ("exceptional", "very_good")]
        if len(exceptional_pp) >= 2:
            strengths.append({
                "category": "past_performance",
                "text": f"{len(exceptional_pp)} contracts with Exceptional/Very Good CPARS ratings",
                "impact": "high",
            })

        # Win themes
        if len(themes) >= 3:
            strengths.append({
                "category": "discriminator",
                "text": f"{len(themes)} defined win themes/discriminators provide competitive differentiation",
                "impact": "medium",
            })

        # Compliance coverage
        if cm_rows:
            addressed = sum(1 for c in cm_rows
                            if c.get("compliance_status") == "fully_addressed")
            cm_coverage = addressed / len(cm_rows) if cm_rows else 0
            if cm_coverage >= 0.85:
                strengths.append({
                    "category": "compliance",
                    "text": f"Compliance matrix {cm_coverage:.0%} addressed - strong requirement coverage",
                    "impact": "high",
                })

        # Innovation / named methodologies
        content_lower = all_content.lower()
        methodology_hits = len(re.findall(
            r"\b(?:agile|scrum|kanban|devops|devsecops|itil|cmmi|lean|six sigma"
            r"|togaf|safe|pmbok)\b",
            content_lower
        ))
        if methodology_hits >= 3:
            strengths.append({
                "category": "technical",
                "text": f"Named methodologies referenced ({methodology_hits} instances) demonstrate mature processes",
                "impact": "medium",
            })

        # Personnel / named staff
        named_staff = len(re.findall(
            r"\b(?:key personnel|program manager|technical lead|project manager"
            r"|subject matter expert|SME)\b",
            content_lower
        ))
        if named_staff >= 2:
            strengths.append({
                "category": "management",
                "text": "Named key personnel demonstrate staffing readiness",
                "impact": "medium",
            })

        # -- Weaknesses --
        if total_vague >= 10:
            weaknesses.append({
                "category": "specificity",
                "text": f"Excessive vague language ({total_vague} instances of 'will ensure', 'as needed', etc.)",
                "impact": "high",
                "sections_affected": "multiple",
            })

        if sections_over_limit > 0:
            weaknesses.append({
                "category": "compliance",
                "text": f"{sections_over_limit} section(s) exceed page limits - evaluator may stop reading at limit",
                "impact": "high",
                "sections_affected": str(sections_over_limit),
            })

        if sections_under_utilised > 0:
            weaknesses.append({
                "category": "completeness",
                "text": f"{sections_under_utilised} section(s) under-utilise available page allocation (<40%)",
                "impact": "medium",
                "sections_affected": str(sections_under_utilised),
            })

        not_addressed = sum(1 for c in cm_rows
                            if c.get("compliance_status") == "not_addressed")
        if not_addressed > 0:
            weaknesses.append({
                "category": "compliance",
                "text": f"{not_addressed} compliance matrix requirement(s) not addressed",
                "impact": "high" if not_addressed > 3 else "medium",
                "sections_affected": "compliance_matrix",
            })

        if not themes:
            weaknesses.append({
                "category": "persuasiveness",
                "text": "No win themes defined - proposal lacks differentiation strategy",
                "impact": "high",
                "sections_affected": "all",
            })

        if total_strong < 5 and total_sections > 0:
            weaknesses.append({
                "category": "evidence",
                "text": "Insufficient proof points - government evaluators expect quantified evidence on every page",
                "impact": "high",
                "sections_affected": "multiple",
            })

        unsatisfactory_pp = [p for p in pp_records
                             if p.get("cpars_rating") in ("marginal", "unsatisfactory")]
        if unsatisfactory_pp:
            weaknesses.append({
                "category": "past_performance",
                "text": f"{len(unsatisfactory_pp)} past performance records with Marginal/Unsatisfactory ratings",
                "impact": "high",
                "sections_affected": "past_performance",
            })

        # -- Risks --
        # Schedule risk indicators
        schedule_words = len(re.findall(
            r"\b(?:aggressive|ambitious|accelerat|fast[- ]track|challenging timeline)\b",
            content_lower
        ))
        if schedule_words >= 2:
            risks.append({
                "category": "schedule",
                "text": "Aggressive schedule language detected - evaluator may flag as schedule risk",
                "likelihood": "medium",
                "impact": "medium",
            })

        # Staffing risk
        tbd_staff = len(re.findall(r"\b(?:tbd|to be (?:determined|hired|named))\b",
                                   content_lower))
        if tbd_staff >= 1:
            risks.append({
                "category": "staffing",
                "text": f"TBD personnel references ({tbd_staff}) - evaluator will question staffing readiness",
                "likelihood": "high",
                "impact": "medium",
            })

        # Technology maturity risk
        immature_tech = len(re.findall(
            r"\b(?:prototype|beta|proof of concept|poc|experimental|emerging)\b",
            content_lower
        ))
        if immature_tech >= 2:
            risks.append({
                "category": "technical",
                "text": "References to immature/prototype technology may concern risk-averse evaluators",
                "likelihood": "medium",
                "impact": "medium",
            })

        # Unsubstantiated claims
        superlative_claims = len(re.findall(
            r"\b(?:best[- ]in[- ]class|world[- ]class|unmatched|unparalleled|"
            r"industry[- ]leading|cutting[- ]edge)\b",
            content_lower
        ))
        if superlative_claims >= 3:
            risks.append({
                "category": "credibility",
                "text": f"Excessive superlatives ({superlative_claims}) without supporting evidence reduce credibility",
                "likelihood": "high",
                "impact": "medium",
            })

        if not pp_records:
            risks.append({
                "category": "past_performance",
                "text": "No past performance records available - evaluator will assign 'neutral' confidence at best",
                "likelihood": "high",
                "impact": "high",
            })

        # Net assessment
        s_score = len([s for s in strengths if s["impact"] == "high"]) * 2 + len(strengths)
        w_score = len([w for w in weaknesses if w["impact"] == "high"]) * 2 + len(weaknesses)
        r_score = len([r for r in risks if r.get("impact") == "high"]) * 2 + len(risks)

        net = s_score - w_score - (r_score * 0.5)
        if net >= 6:
            assessment = "strong"
        elif net >= 2:
            assessment = "competitive"
        elif net >= -2:
            assessment = "average"
        else:
            assessment = "weak"

        return {
            "proposal_id": proposal_id,
            "strengths": strengths,
            "weaknesses": weaknesses,
            "risks": risks,
            "strength_count": len(strengths),
            "weakness_count": len(weaknesses),
            "risk_count": len(risks),
            "net_assessment": assessment,
            "net_score": round(net, 1),
            "assessed_at": _now(),
        }
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Competitive position estimate
# ---------------------------------------------------------------------------

def competitive_position(proposal_id, db_path=None):
    """Estimate competitive position relative to typical competitor proposals.

    Factors: compliance coverage, past performance strength, technical
    innovation, evidence density, win theme differentiation.

    Returns:
        dict with position_estimate, confidence, factors.
    """
    conn = _get_db(db_path)
    try:
        proposal = _load_proposal(conn, proposal_id)
        sections = _load_sections(conn, proposal_id)
        cm_rows = _load_compliance(conn, proposal_id)
        themes = _load_win_themes(conn, proposal_id,
                                  proposal.get("opportunity_id"))
        pp_records = _load_past_performances(conn, proposal_id)

        factors = {}

        # 1. Compliance coverage (0-100)
        if cm_rows:
            addressed = sum(1 for c in cm_rows
                            if c.get("compliance_status") in (
                                "fully_addressed", "partially_addressed"))
            factors["compliance_coverage"] = round(
                addressed / len(cm_rows) * 100, 1
            )
        else:
            factors["compliance_coverage"] = 50.0

        # 2. Past performance strength (0-100)
        if pp_records:
            rating_scores = {
                "exceptional": 100, "very_good": 85, "satisfactory": 60,
                "marginal": 30, "unsatisfactory": 10
            }
            pp_scores = [rating_scores.get(p.get("cpars_rating"), 50)
                         for p in pp_records]
            factors["past_performance"] = round(
                sum(pp_scores) / len(pp_scores), 1
            )
        else:
            factors["past_performance"] = 40.0  # neutral/unknown

        # 3. Technical innovation (0-100)
        all_content = " ".join(
            (s.get("content") or "") for s in sections
        ).lower()
        innovation_hits = _count_pattern_matches(all_content, [
            r"\b(?:innovative|patent|proprietary|novel|unique approach)\b",
            r"\b(?:machine learning|artificial intelligence|automation)\b",
            r"\b(?:devops|devsecops|ci/cd|continuous)\b",
        ])
        factors["technical_innovation"] = round(
            min(innovation_hits * 12.0, 100.0), 1
        )

        # 4. Evidence density (0-100)
        total_wc = sum(s.get("word_count") or 0 for s in sections) or 1
        total_strong = _count_pattern_matches(all_content, STRONG_PATTERNS)
        evidence_per_page = total_strong / max(total_wc / 250, 1)
        factors["evidence_density"] = round(
            min(evidence_per_page * 20.0, 100.0), 1
        )

        # 5. Win theme differentiation (0-100)
        factors["win_theme_strength"] = round(
            min(len(themes) * 25.0, 100.0), 1
        )

        # Weighted composite
        weights = {
            "compliance_coverage": 0.30,
            "past_performance": 0.25,
            "technical_innovation": 0.15,
            "evidence_density": 0.15,
            "win_theme_strength": 0.15,
        }
        composite = sum(factors[k] * weights[k] for k in weights)

        if composite >= 80:
            position = "leader"
        elif composite >= 60:
            position = "competitive"
        elif composite >= 40:
            position = "trailing"
        else:
            position = "weak"

        # Confidence based on data completeness
        data_completeness = sum([
            1 if cm_rows else 0,
            1 if pp_records else 0,
            1 if sections else 0,
            1 if themes else 0,
        ]) / 4.0
        confidence = round(data_completeness * 0.85, 2)

        return {
            "proposal_id": proposal_id,
            "position_estimate": position,
            "composite_score": round(composite, 1),
            "confidence": confidence,
            "factors": factors,
            "factor_weights": weights,
            "assessed_at": _now(),
        }
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Improvement roadmap
# ---------------------------------------------------------------------------

def improvement_roadmap(proposal_id, db_path=None):
    """Generate a prioritised list of improvements ranked by
    evaluation_factor_weight * gap_size.

    Returns:
        dict with improvements list, each containing priority, section,
        issue, action, impact_estimate.
    """
    conn = _get_db(db_path)
    try:
        proposal = _load_proposal(conn, proposal_id)
        eval_factors = _get_eval_factors(proposal)
        sections = _load_sections(conn, proposal_id)
        cm_rows = _load_compliance(conn, proposal_id)
        themes = _load_win_themes(conn, proposal_id,
                                  proposal.get("opportunity_id"))

        improvements = []

        # 1. Unaddressed compliance requirements (highest impact)
        not_addressed = [c for c in cm_rows
                         if c.get("compliance_status") == "not_addressed"]
        for cm in not_addressed[:10]:
            # Estimate factor weight
            source = cm.get("source", "other")
            factor_weight = 0.25
            if source == "section_m":
                factor_weight = 0.40
            elif source == "section_l":
                factor_weight = 0.30

            improvements.append({
                "issue": f"Unaddressed requirement: {(cm.get('requirement_text') or '')[:100]}",
                "section": cm.get("section_number") or "unmapped",
                "action": "Draft responsive content addressing this requirement with specific evidence",
                "impact_estimate": round(factor_weight * 1.0, 2),
                "effort": "medium",
                "category": "compliance",
            })

        # 2. Sections with vague language
        for section in sections:
            content = section.get("content") or ""
            vague_count = _count_pattern_matches(content, VAGUE_PATTERNS)
            if vague_count >= 3:
                improvements.append({
                    "issue": f"Section {section['section_number']}: {vague_count} vague language instances",
                    "section": section["section_number"],
                    "action": "Replace vague phrases with quantified commitments and specific methodologies",
                    "impact_estimate": 0.30,
                    "effort": "low",
                    "category": "quality",
                })

        # 3. Sections over page limit
        for section in sections:
            pl = section.get("page_limit")
            pc = section.get("page_count") or 0
            if pl and pc > pl:
                improvements.append({
                    "issue": f"Section {section['section_number']}: exceeds page limit ({pc}/{pl} pages)",
                    "section": section["section_number"],
                    "action": "Edit for conciseness; remove boilerplate, consolidate redundant paragraphs",
                    "impact_estimate": 0.50,
                    "effort": "medium",
                    "category": "compliance",
                })

        # 4. Sections lacking evidence
        for section in sections:
            content = section.get("content") or ""
            wc = section.get("word_count") or 0
            if wc > 100:
                strong = _count_pattern_matches(content, STRONG_PATTERNS)
                per_page = strong / max(wc / 250, 1)
                if per_page < 1.5:
                    improvements.append({
                        "issue": f"Section {section['section_number']}: low evidence density ({strong} proof points)",
                        "section": section["section_number"],
                        "action": "Add quantified metrics, past performance citations, SLA commitments, and named tools",
                        "impact_estimate": 0.35,
                        "effort": "medium",
                        "category": "evidence",
                    })

        # 5. Missing win themes
        if not themes:
            improvements.append({
                "issue": "No win themes defined for this proposal",
                "section": "all",
                "action": "Define 3-5 win themes with supporting evidence and weave into all major sections",
                "impact_estimate": 0.45,
                "effort": "high",
                "category": "strategy",
            })

        # 6. Sections with minimal content
        for section in sections:
            wc = section.get("word_count") or 0
            pl = section.get("page_limit")
            if pl and pl > 0 and wc < int(pl * 250 * 0.3):
                improvements.append({
                    "issue": f"Section {section['section_number']}: minimal content ({wc} words vs {int(pl * 250)} expected)",
                    "section": section["section_number"],
                    "action": "Develop full content with technical approach, methodology, and evidence",
                    "impact_estimate": 0.40,
                    "effort": "high",
                    "category": "completeness",
                })

        # Sort by impact estimate descending
        improvements.sort(key=lambda x: x["impact_estimate"], reverse=True)

        # Assign priority numbers
        for i, imp in enumerate(improvements):
            imp["priority"] = i + 1

        return {
            "proposal_id": proposal_id,
            "improvement_count": len(improvements),
            "improvements": improvements,
            "generated_at": _now(),
        }
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Evaluation history
# ---------------------------------------------------------------------------

def evaluation_history(proposal_id, db_path=None):
    """Get all evaluations for a proposal over time.

    Returns:
        list of evaluation summary dicts.
    """
    conn = _get_db(db_path)
    try:
        rows = conn.execute(
            "SELECT * FROM proposal_evaluations "
            "WHERE proposal_id = ? ORDER BY created_at DESC",
            (proposal_id,)
        ).fetchall()
        results = []
        for r in rows:
            d = _row_to_dict(r)
            for field in ("strengths", "weaknesses", "risks",
                          "discriminators", "evaluation_criteria",
                          "section_scores"):
                d[field] = _parse_json_field(d.get(field))
            results.append(d)
        return results
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Main self-score evaluation
# ---------------------------------------------------------------------------

def self_score(proposal_id, db_path=None):
    """Full government-style self-scoring evaluation.

    Loads Section M evaluation criteria, analyses each factor, computes
    weighted scores, identifies strengths/weaknesses/risks/discriminators,
    and stores the result in proposal_evaluations.

    Returns:
        Full evaluation dict with scores, ratings, and recommendation.
    """
    conn = _get_db(db_path)
    try:
        proposal = _load_proposal(conn, proposal_id)
        sections = _load_sections(conn, proposal_id)
        cm_rows = _load_compliance(conn, proposal_id)
        requirements = _load_requirements(conn, proposal_id)
        themes = _load_win_themes(conn, proposal_id,
                                  proposal.get("opportunity_id"))
        pp_records = _load_past_performances(conn, proposal_id)
        eval_factors = _get_eval_factors(proposal)

        if not sections:
            raise ValueError(
                f"No sections found for proposal {proposal_id}. "
                "Cannot evaluate an empty proposal."
            )

        # Build section index by volume
        sections_by_volume = defaultdict(list)
        for s in sections:
            vol = (s.get("volume") or "technical").lower()
            sections_by_volume[vol].append(s)

        # Score each evaluation factor
        factor_scores = {}
        all_strengths = []
        all_weaknesses = []
        all_risks = []
        all_discriminators = []
        section_scores = {}

        for factor_name, factor_weight in eval_factors.items():
            # Map factor to relevant volume(s)
            factor_lower = factor_name.lower()
            if "technical" in factor_lower:
                relevant_vols = ["technical"]
            elif "management" in factor_lower:
                relevant_vols = ["management"]
            elif "past_performance" in factor_lower or "experience" in factor_lower:
                relevant_vols = ["past_performance"]
            elif "cost" in factor_lower or "price" in factor_lower:
                relevant_vols = ["cost"]
            else:
                relevant_vols = list(sections_by_volume.keys())

            # Gather sections for this factor
            factor_sections = []
            for vol in relevant_vols:
                factor_sections.extend(sections_by_volume.get(vol, []))
            if not factor_sections:
                factor_sections = sections  # fall back to all

            # --- Sub-score 1: Compliance coverage for this factor ---
            factor_cm = [c for c in cm_rows
                         if c.get("volume") in relevant_vols
                         or c.get("source") == f"section_{factor_lower[:1]}"]
            if not factor_cm:
                factor_cm = cm_rows  # fall back

            if factor_cm:
                fully = sum(1 for c in factor_cm
                            if c.get("compliance_status") == "fully_addressed")
                partial = sum(1 for c in factor_cm
                              if c.get("compliance_status") == "partially_addressed")
                cm_pct = (fully + partial * 0.5) / len(factor_cm)
            else:
                cm_pct = 0.5

            compliance_score = _clamp(1.0 + cm_pct * 4.0)

            # --- Sub-score 2: Content quality ---
            quality_scores = []
            for sec in factor_sections:
                q_score, _ = _score_content_quality(
                    sec.get("content"), sec.get("word_count"),
                    sec.get("page_count"), sec.get("page_limit"),
                )
                quality_scores.append(q_score)
                sec_num = sec.get("section_number")
                if sec_num and sec_num not in section_scores:
                    section_scores[sec_num] = {
                        "section_number": sec_num,
                        "section_title": sec.get("section_title"),
                        "volume": sec.get("volume"),
                        "quality_score": q_score,
                    }

            avg_quality = (
                sum(quality_scores) / len(quality_scores)
                if quality_scores else 2.5
            )

            # --- Sub-score 3: Win theme integration ---
            all_content = " ".join(
                (s.get("content") or "") for s in factor_sections
            ).lower()
            theme_hits = 0
            for t in themes:
                words = [w for w in (t.get("theme_text") or "").lower().split()
                         if len(w) > 4][:5]
                if words and sum(1 for w in words if w in all_content) >= 2:
                    theme_hits += 1
            theme_pct = theme_hits / max(len(themes), 1) if themes else 0.3
            theme_score = _clamp(1.0 + theme_pct * 4.0)

            # --- Sub-score 4: Past performance relevance ---
            pp_score = 3.0  # default neutral
            if "past_performance" in factor_lower or "experience" in factor_lower:
                if pp_records:
                    rating_map = {
                        "exceptional": 5.0, "very_good": 4.5,
                        "satisfactory": 3.0, "marginal": 1.5,
                        "unsatisfactory": 1.0,
                    }
                    pp_vals = [rating_map.get(p.get("cpars_rating"), 3.0)
                               for p in pp_records]
                    pp_score = sum(pp_vals) / len(pp_vals)
                else:
                    pp_score = 2.0  # no PP = weak

            # --- Combine sub-scores for this factor ---
            if "past_performance" in factor_lower:
                factor_score = (
                    pp_score * 0.50 +
                    compliance_score * 0.20 +
                    avg_quality * 0.20 +
                    theme_score * 0.10
                )
            elif "cost" in factor_lower:
                # Cost realism scored more on compliance + content quality
                factor_score = (
                    compliance_score * 0.40 +
                    avg_quality * 0.40 +
                    theme_score * 0.20
                )
            else:
                # Technical / management factors
                factor_score = (
                    avg_quality * 0.35 +
                    compliance_score * 0.30 +
                    theme_score * 0.15 +
                    pp_score * 0.05 +
                    # Bonus for evidence density
                    min(_count_pattern_matches(all_content, STRONG_PATTERNS) / 10.0, 1.0) * 0.75
                )
                factor_score = _clamp(factor_score)

            factor_score = round(_clamp(factor_score), 2)
            factor_scores[factor_name] = {
                "score": factor_score,
                "rating": _score_to_rating(factor_score),
                "weight": factor_weight,
                "compliance_coverage_pct": round(cm_pct * 100, 1),
                "content_quality_avg": round(avg_quality, 2),
                "theme_integration_pct": round(theme_pct * 100, 1),
            }

            # Factor-level strengths / weaknesses
            if factor_score >= 4.5:
                all_strengths.append(
                    f"{factor_name}: Outstanding — exceeds requirements with "
                    "significant strengths and very low risk"
                )
            elif factor_score >= 3.5:
                all_strengths.append(
                    f"{factor_name}: Good — exceeds some requirements with strengths"
                )

            if factor_score < 2.5:
                all_weaknesses.append(
                    f"{factor_name}: Marginal/Unacceptable — fails to meet "
                    "some requirements, significant weaknesses"
                )
            elif factor_score < 3.0:
                all_weaknesses.append(
                    f"{factor_name}: Borderline acceptable — weaknesses need "
                    "attention before submission"
                )

            # Risks
            vague = _count_pattern_matches(all_content, VAGUE_PATTERNS)
            if vague >= 5:
                all_risks.append(
                    f"{factor_name}: {vague} vague language instances may "
                    "trigger evaluator concerns"
                )

        # Discriminators from win themes
        for t in themes:
            disc = t.get("discriminator_type")
            evidence = t.get("supporting_evidence") or t.get("theme_text", "")
            if disc:
                all_discriminators.append(
                    f"[{disc}] {evidence[:120]}"
                )

        # Calculate weighted overall score
        overall_score = 0.0
        total_weight = 0.0
        for fname, fdata in factor_scores.items():
            overall_score += fdata["score"] * fdata["weight"]
            total_weight += fdata["weight"]
        if total_weight > 0:
            overall_score = overall_score / total_weight
        overall_score = round(_clamp(overall_score), 2)
        overall_rating = _score_to_rating(overall_score)

        # Map named volume scores
        vol_scores = {"technical": None, "management": None,
                      "past_performance": None, "cost": None}
        for fname, fdata in factor_scores.items():
            fl = fname.lower()
            if "technical" in fl:
                vol_scores["technical"] = fdata["score"]
            elif "management" in fl:
                vol_scores["management"] = fdata["score"]
            elif "past_performance" in fl or "experience" in fl:
                vol_scores["past_performance"] = fdata["score"]
            elif "cost" in fl or "price" in fl:
                vol_scores["cost"] = fdata["score"]

        # Recommendation
        if overall_score >= 4.0:
            recommendation = "submit"
        elif overall_score >= 3.0:
            recommendation = "revise"
        elif overall_score >= 2.0:
            recommendation = "needs_review"
        else:
            recommendation = "no_bid"

        # Confidence based on data available
        data_signals = sum([
            1 if sections else 0,
            1 if cm_rows else 0,
            1 if themes else 0,
            1 if pp_records else 0,
            1 if requirements else 0,
        ])
        confidence = round(min(data_signals / 5.0, 1.0) * 0.90, 2)

        # Store evaluation
        eval_id = _eval_id()
        now = _now()
        conn.execute(
            "INSERT INTO proposal_evaluations "
            "(id, proposal_id, evaluation_type, overall_score, overall_rating, "
            " technical_score, management_score, past_performance_score, "
            " cost_score, strengths, weaknesses, risks, discriminators, "
            " evaluation_criteria, section_scores, recommendation, "
            " confidence, evaluator, classification, created_at) "
            "VALUES (?, ?, 'self_score', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, "
            "'ai_evaluator', 'CUI // SP-PROPIN', ?)",
            (
                eval_id, proposal_id,
                overall_score, overall_rating,
                vol_scores.get("technical"),
                vol_scores.get("management"),
                vol_scores.get("past_performance"),
                vol_scores.get("cost"),
                json.dumps(all_strengths[:20]),
                json.dumps(all_weaknesses[:20]),
                json.dumps(all_risks[:20]),
                json.dumps(all_discriminators[:10]),
                json.dumps(factor_scores),
                json.dumps(section_scores),
                recommendation,
                confidence,
                now,
            ),
        )

        _audit(
            conn, "evaluation.self_score",
            f"Self-score evaluation for {proposal_id}: "
            f"{overall_rating} ({overall_score}/5.0) -> {recommendation}",
            "proposal_evaluations", eval_id,
            {"overall_score": overall_score, "rating": overall_rating,
             "recommendation": recommendation, "confidence": confidence},
        )
        conn.commit()

        return {
            "evaluation_id": eval_id,
            "proposal_id": proposal_id,
            "evaluation_type": "self_score",
            "overall_score": overall_score,
            "overall_rating": overall_rating,
            "recommendation": recommendation,
            "confidence": confidence,
            "factor_scores": factor_scores,
            "section_scores": section_scores,
            "technical_score": vol_scores.get("technical"),
            "management_score": vol_scores.get("management"),
            "past_performance_score": vol_scores.get("past_performance"),
            "cost_score": vol_scores.get("cost"),
            "strengths": all_strengths[:20],
            "weaknesses": all_weaknesses[:20],
            "risks": all_risks[:20],
            "discriminators": all_discriminators[:10],
            "evaluated_at": now,
        }
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Batch evaluation
# ---------------------------------------------------------------------------

def batch_evaluate(status="draft", db_path=None):
    """Evaluate all proposals at a given status.

    Returns:
        dict with evaluated proposals summary.
    """
    conn = _get_db(db_path)
    try:
        rows = conn.execute(
            "SELECT id, title, status FROM proposals WHERE status = ?",
            (status,)
        ).fetchall()
        proposals = [_row_to_dict(r) for r in rows]
    finally:
        conn.close()

    results = []
    errors = []
    for prop in proposals:
        try:
            result = self_score(prop["id"], db_path=db_path)
            results.append({
                "proposal_id": prop["id"],
                "title": prop["title"],
                "overall_score": result["overall_score"],
                "overall_rating": result["overall_rating"],
                "recommendation": result["recommendation"],
            })
        except (ValueError, sqlite3.Error) as exc:
            errors.append({
                "proposal_id": prop["id"],
                "title": prop["title"],
                "error": str(exc),
            })

    return {
        "status_filter": status,
        "total_found": len(proposals),
        "evaluated": len(results),
        "errors": len(errors),
        "results": results,
        "error_details": errors,
        "evaluated_at": _now(),
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_parser():
    """Build argument parser."""
    import argparse
    parser = argparse.ArgumentParser(
        description="AI Proposal Self-Scoring Evaluator (FAR 15.305)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  %(prog)s --evaluate --proposal-id PROP-123 --json\n"
            "  %(prog)s --score-section --proposal-id PROP-123 "
            "--section 1.1 --json\n"
            "  %(prog)s --compliance-gaps --proposal-id PROP-123 --json\n"
            "  %(prog)s --strengths-weaknesses --proposal-id PROP-123 --json\n"
            "  %(prog)s --competitive-position --proposal-id PROP-123 --json\n"
            "  %(prog)s --improvement-roadmap --proposal-id PROP-123 --json\n"
            "  %(prog)s --history --proposal-id PROP-123 --json\n"
            "  %(prog)s --batch --status draft --json\n"
        ),
    )

    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--evaluate", action="store_true",
                        help="Run full self-score evaluation")
    action.add_argument("--score-section", action="store_true",
                        help="Score a single section")
    action.add_argument("--compliance-gaps", action="store_true",
                        help="Compliance gap analysis")
    action.add_argument("--strengths-weaknesses", action="store_true",
                        help="Strength/weakness/risk analysis")
    action.add_argument("--competitive-position", action="store_true",
                        help="Competitive position estimate")
    action.add_argument("--improvement-roadmap", action="store_true",
                        help="Prioritised improvement roadmap")
    action.add_argument("--history", action="store_true",
                        help="Evaluation history")
    action.add_argument("--batch", action="store_true",
                        help="Batch evaluate proposals at a status")

    parser.add_argument("--proposal-id", help="Proposal ID")
    parser.add_argument("--section", help="Section number (for --score-section)")
    parser.add_argument("--status", default="draft",
                        help="Status filter for --batch (default: draft)")
    parser.add_argument("--json", action="store_true", help="JSON output")
    parser.add_argument("--db-path", help="Override database path")

    return parser


def main():
    """CLI entry point."""
    parser = _build_parser()
    args = parser.parse_args()
    db = args.db_path

    try:
        if args.batch:
            result = batch_evaluate(status=args.status, db_path=db)
        else:
            if not args.proposal_id:
                parser.error("--proposal-id is required")

            if args.evaluate:
                result = self_score(args.proposal_id, db_path=db)
            elif args.score_section:
                if not args.section:
                    parser.error("--score-section requires --section")
                result = score_section(
                    args.proposal_id, args.section, db_path=db
                )
            elif args.compliance_gaps:
                result = compliance_gap_analysis(
                    args.proposal_id, db_path=db
                )
            elif args.strengths_weaknesses:
                result = strength_weakness_analysis(
                    args.proposal_id, db_path=db
                )
            elif args.competitive_position:
                result = competitive_position(
                    args.proposal_id, db_path=db
                )
            elif args.improvement_roadmap:
                result = improvement_roadmap(
                    args.proposal_id, db_path=db
                )
            elif args.history:
                result = evaluation_history(
                    args.proposal_id, db_path=db
                )
            else:
                parser.print_help()
                sys.exit(1)

        # Output
        if args.json:
            print(json.dumps(result, indent=2, default=str))
        else:
            _print_human(result, args)

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


def _print_human(result, args):
    """Print human-readable output."""
    if isinstance(result, list):
        # History
        print(f"Found {len(result)} evaluation(s):")
        for ev in result:
            score = ev.get("overall_score", "?")
            rating = ev.get("overall_rating", "?")
            rec = ev.get("recommendation", "?")
            ts = ev.get("created_at", "?")
            print(f"  [{ev.get('evaluation_type')}] "
                  f"{score}/5.0 {rating} -> {rec}  ({ts})")
        return

    if "error" in result:
        print(f"ERROR: {result['error']}", file=sys.stderr)
        sys.exit(1)

    if args.evaluate:
        print(f"{'=' * 60}")
        print(f"  SELF-SCORE EVALUATION: {result.get('proposal_id')}")
        print(f"{'=' * 60}")
        print(f"  Overall Score : {result['overall_score']}/5.0")
        print(f"  Rating        : {result['overall_rating'].upper()}")
        print(f"  Recommendation: {result['recommendation'].upper()}")
        print(f"  Confidence    : {result['confidence']:.0%}")
        print()
        print("  Factor Scores:")
        for fname, fdata in result.get("factor_scores", {}).items():
            print(f"    {fname:30s} {fdata['score']}/5.0 "
                  f"({fdata['rating']}) [weight: {fdata['weight']:.0%}]")
        print()
        if result.get("strengths"):
            print(f"  Strengths ({len(result['strengths'])}):")
            for s in result["strengths"][:5]:
                print(f"    + {s}")
        if result.get("weaknesses"):
            print(f"  Weaknesses ({len(result['weaknesses'])}):")
            for w in result["weaknesses"][:5]:
                print(f"    - {w}")
        if result.get("risks"):
            print(f"  Risks ({len(result['risks'])}):")
            for r in result["risks"][:5]:
                print(f"    ! {r}")

    elif args.score_section:
        sec = result.get("section_number", "?")
        print(f"Section {sec}: {result.get('score')}/5.0 "
              f"({result.get('rating')})")
        if result.get("strengths"):
            for s in result["strengths"]:
                print(f"  + {s}")
        if result.get("weaknesses"):
            for w in result["weaknesses"]:
                print(f"  - {w}")
        if result.get("improvement_suggestions"):
            print("  Suggestions:")
            for s in result["improvement_suggestions"]:
                print(f"    -> {s}")

    elif args.compliance_gaps:
        print(f"Compliance Coverage: {result.get('coverage_pct', 0)}%")
        print(f"  Total requirements: {result.get('total_requirements', 0)}")
        print(f"  Fully addressed:    {result.get('fully_addressed', 0)}")
        print(f"  Partially:          {result.get('partially_addressed', 0)}")
        print(f"  Not addressed:      {result.get('not_addressed', 0)}")
        cg = result.get("critical_gaps", [])
        if cg:
            print(f"\n  CRITICAL GAPS ({len(cg)} shall/must unaddressed):")
            for g in cg[:10]:
                print(f"    [{g.get('obligation_level')}] "
                      f"{g.get('requirement_text', '')[:80]}")

    elif args.strengths_weaknesses:
        print(f"Net Assessment: {result.get('net_assessment', '?').upper()} "
              f"(score: {result.get('net_score', 0)})")
        for s in result.get("strengths", []):
            print(f"  + [{s['impact']}] {s['text']}")
        for w in result.get("weaknesses", []):
            print(f"  - [{w['impact']}] {w['text']}")
        for r in result.get("risks", []):
            print(f"  ! [{r.get('likelihood', '?')}] {r['text']}")

    elif args.competitive_position:
        print(f"Position: {result.get('position_estimate', '?').upper()} "
              f"(score: {result.get('composite_score', 0)}/100, "
              f"confidence: {result.get('confidence', 0):.0%})")
        for k, v in result.get("factors", {}).items():
            print(f"  {k:30s} {v:.1f}/100")

    elif args.improvement_roadmap:
        imps = result.get("improvements", [])
        print(f"Improvement Roadmap ({len(imps)} items):")
        for imp in imps[:15]:
            print(f"  #{imp['priority']} [{imp['category']}] "
                  f"(impact: {imp['impact_estimate']}, effort: {imp['effort']})")
            print(f"     {imp['issue'][:80]}")
            print(f"     -> {imp['action'][:80]}")

    elif args.batch:
        print(f"Batch Evaluation ({result.get('status_filter', '?')}): "
              f"{result.get('evaluated', 0)}/{result.get('total_found', 0)} "
              f"evaluated")
        for r in result.get("results", []):
            print(f"  {r['proposal_id']}: {r['overall_score']}/5.0 "
                  f"{r['overall_rating']} -> {r['recommendation']}")
        if result.get("error_details"):
            print(f"\n  Errors ({result['errors']}):")
            for e in result["error_details"]:
                print(f"    {e['proposal_id']}: {e['error']}")

    else:
        print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
