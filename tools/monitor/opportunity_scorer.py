#!/usr/bin/env python3
# CUI // SP-PROPIN
# Controlled by: GovProposal Portal
# CUI Category: PROPIN
# Distribution: D
# POC: GovProposal System Administrator
"""Opportunity qualification and scoring engine.

Provides automated fit scoring (0-100) and 7-dimension Go/No-Go
qualification scoring for government contract opportunities. Scoring
is driven by configuration in args/scoring_config.yaml and evaluated
against KB entries, past performances, competitor intelligence,
and personnel records in the database.

Scoring Dimensions (7, weights sum to 1.0):
    1. customer_relationship (0.20) — Past agency work, incumbent status
    2. technical_fit         (0.20) — KB capabilities vs requirements
    3. past_performance      (0.15) — Relevant CPARS-rated contracts
    4. competitive_position  (0.15) — Competitor wins for same agency/NAICS
    5. vehicle_access        (0.10) — Contract vehicle eligibility
    6. clearance_compliance  (0.10) — Clearance requirements vs personnel
    7. strategic_value       (0.10) — Contract value and strategic alignment

Decision Thresholds:
    >= 0.75  Strong Go
    0.55-0.75  Conditional Go (teaming or mitigation needed)
    < 0.55   No Bid

Usage:
    # Score a single opportunity (fit + qualification)
    python tools/monitor/opportunity_scorer.py --score --opp-id OPP-abc123 --json

    # Batch score all unscored opportunities
    python tools/monitor/opportunity_scorer.py --score-all --json

    # Generate Go/No-Go recommendation
    python tools/monitor/opportunity_scorer.py --go-no-go --opp-id OPP-abc123 --json

    # Retrieve existing scorecard
    python tools/monitor/opportunity_scorer.py --scorecard --opp-id OPP-abc123 --json
"""

import argparse
import hashlib
import json
import os
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Graceful optional imports
# ---------------------------------------------------------------------------
try:
    import yaml
except ImportError:
    yaml = None

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent.parent
DB_PATH = Path(os.environ.get(
    "GOVPROPOSAL_DB_PATH", str(BASE_DIR / "data" / "govproposal.db")
))
CONFIG_PATH = BASE_DIR / "args" / "proposal_config.yaml"
SCORING_CONFIG_PATH = BASE_DIR / "args" / "scoring_config.yaml"

# ---------------------------------------------------------------------------
# Default scoring weights (used when YAML config unavailable)
# ---------------------------------------------------------------------------
DEFAULT_DIMENSIONS = {
    "customer_relationship": {"weight": 0.20},
    "technical_fit": {"weight": 0.20},
    "past_performance": {"weight": 0.15},
    "competitive_position": {"weight": 0.15},
    "vehicle_access": {"weight": 0.10},
    "clearance_compliance": {"weight": 0.10},
    "strategic_value": {"weight": 0.10},
}

DEFAULT_THRESHOLDS = {
    "strong_go": 0.75,
    "conditional_go": 0.55,
    "no_bid": 0.55,
}

DEFAULT_FIT_WEIGHTS = {
    "naics_match_weight": 0.25,
    "agency_match_weight": 0.20,
    "set_aside_match_weight": 0.15,
    "keyword_match_weight": 0.20,
    "contract_size_match_weight": 0.10,
    "clearance_match_weight": 0.10,
}

DEFAULT_BOOST_KEYWORDS = [
    "cloud migration", "devsecops", "zero trust", "artificial intelligence",
    "cybersecurity", "data analytics", "software development", "agile",
    "digital transformation", "it modernization",
]

DEFAULT_PENALTY_KEYWORDS = [
    "construction", "janitorial", "food service", "medical supplies",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_db(db_path=None):
    """Return a sqlite3 connection with WAL mode and foreign keys enabled."""
    path = str(db_path or DB_PATH)
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    return conn


def _now():
    """Return current UTC timestamp as ISO-8601 string."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _score_id():
    """Generate a unique score ID: SCR- + 12 hex chars."""
    raw = hashlib.sha256(os.urandom(32)).hexdigest()[:12]
    return f"SCR-{raw}"


def _audit(conn, event_type, action, entity_type=None, entity_id=None,
           details=None, actor="opportunity_scorer"):
    """Write an append-only audit trail entry."""
    conn.execute(
        "INSERT INTO audit_trail (event_type, actor, action, entity_type, "
        "entity_id, details, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (event_type, actor, action, entity_type, entity_id,
         json.dumps(details) if isinstance(details, dict) else details,
         _now()),
    )


def _load_scoring_config():
    """Load scoring_config.yaml; returns dict or empty dict on failure."""
    if yaml is None:
        return {}
    if not SCORING_CONFIG_PATH.exists():
        return {}
    try:
        with open(SCORING_CONFIG_PATH, "r", encoding="utf-8") as fh:
            return yaml.safe_load(fh) or {}
    except Exception:
        return {}


def _load_proposal_config():
    """Load proposal_config.yaml; returns dict or empty dict on failure."""
    if yaml is None:
        return {}
    if not CONFIG_PATH.exists():
        return {}
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
            return yaml.safe_load(fh) or {}
    except Exception:
        return {}


def _get_dimensions(config):
    """Extract dimension definitions from scoring config."""
    qual = config.get("qualification", {})
    dims = qual.get("dimensions", DEFAULT_DIMENSIONS)
    return dims


def _get_thresholds(config):
    """Extract decision thresholds from scoring config."""
    qual = config.get("qualification", {})
    return qual.get("thresholds", DEFAULT_THRESHOLDS)


def _get_fit_config(config):
    """Extract fit scoring weights and keyword lists."""
    fit = config.get("fit_scoring", DEFAULT_FIT_WEIGHTS)
    boosts = fit.get("boost_keywords", DEFAULT_BOOST_KEYWORDS)
    penalties = fit.get("penalty_keywords", DEFAULT_PENALTY_KEYWORDS)
    return fit, boosts, penalties


def _text_lower(val):
    """Safely lowercase a value that may be None."""
    return (val or "").lower()


def _keyword_overlap(text, keywords):
    """Count how many keywords from the list appear in the text.

    Returns (match_count, total_keywords).
    """
    if not text or not keywords:
        return 0, max(len(keywords) if keywords else 0, 1)
    text_lower = text.lower()
    matches = sum(1 for kw in keywords if kw.lower() in text_lower)
    return matches, len(keywords)


# ---------------------------------------------------------------------------
# Fit scoring (automated, fast, pre-qualification)
# ---------------------------------------------------------------------------

def score_fit(opp_id, db_path=None):
    """Automated fit scoring (0-100) for an opportunity.

    Evaluates the opportunity against organizational capabilities
    stored in the knowledge base, past performances, and resumes.
    The fit score is a lightweight pre-qualification check run
    before the full 7-dimension qualification scoring.

    Scoring factors (from scoring_config.yaml):
        - NAICS match (0.25): Do we have KB entries / past work in this NAICS?
        - Agency match (0.20): Have we worked with this agency before?
        - Set-aside match (0.15): Are we eligible for the set-aside type?
        - Keyword match (0.20): Does the description match our capabilities?
        - Contract size match (0.10): Is the value in our sweet spot?
        - Clearance match (0.10): Do we have cleared personnel?

    Args:
        opp_id: The opportunity ID (OPP-xxxx format).
        db_path: Override database path.

    Returns:
        dict with keys: opp_id, fit_score, breakdown, scored_at.
    """
    config = _load_scoring_config()
    fit_cfg, boost_kw, penalty_kw = _get_fit_config(config)

    conn = _get_db(db_path)
    try:
        opp = conn.execute(
            "SELECT * FROM opportunities WHERE id = ?", (opp_id,)
        ).fetchone()
        if not opp:
            return {"status": "error", "error": f"Opportunity {opp_id} not found"}

        opp = dict(opp)
        breakdown = {}

        # --- 1. NAICS match ---
        naics_score = 0.0
        opp_naics = opp.get("naics_code") or ""
        if opp_naics:
            # Check KB entries with matching NAICS
            kb_match = conn.execute(
                "SELECT COUNT(*) as cnt FROM kb_entries "
                "WHERE is_active = 1 AND naics_codes LIKE ?",
                (f"%{opp_naics}%",),
            ).fetchone()["cnt"]
            # Check past performances with matching NAICS
            pp_match = conn.execute(
                "SELECT COUNT(*) as cnt FROM past_performances "
                "WHERE is_active = 1 AND naics_code = ?",
                (opp_naics,),
            ).fetchone()["cnt"]
            if pp_match >= 2:
                naics_score = 1.0
            elif pp_match == 1:
                naics_score = 0.8
            elif kb_match >= 3:
                naics_score = 0.7
            elif kb_match >= 1:
                naics_score = 0.5
            else:
                naics_score = 0.1
        breakdown["naics_match"] = round(naics_score, 2)

        # --- 2. Agency match ---
        agency_score = 0.0
        opp_agency = _text_lower(opp.get("agency"))
        if opp_agency:
            pp_agency = conn.execute(
                "SELECT COUNT(*) as cnt FROM past_performances "
                "WHERE is_active = 1 AND LOWER(agency) LIKE ?",
                (f"%{opp_agency[:20]}%",),
            ).fetchone()["cnt"]
            if pp_agency >= 3:
                agency_score = 1.0
            elif pp_agency >= 1:
                agency_score = 0.7
            else:
                # Check customer profiles
                cp = conn.execute(
                    "SELECT COUNT(*) as cnt FROM customer_profiles "
                    "WHERE LOWER(agency) LIKE ?",
                    (f"%{opp_agency[:20]}%",),
                ).fetchone()["cnt"]
                agency_score = 0.3 if cp > 0 else 0.1
        breakdown["agency_match"] = round(agency_score, 2)

        # --- 3. Set-aside match ---
        sa_score = 0.5  # Default: full and open (neutral)
        opp_sa = _text_lower(opp.get("set_aside_type"))
        if opp_sa and opp_sa not in ("total", "none", ""):
            # Check if we have past performance under this set-aside
            pp_sa = conn.execute(
                "SELECT COUNT(*) as cnt FROM past_performances "
                "WHERE is_active = 1 AND LOWER(set_aside) LIKE ?",
                (f"%{opp_sa[:10]}%",),
            ).fetchone()["cnt"]
            if pp_sa >= 1:
                sa_score = 1.0
            else:
                # Check teaming partners
                team_sa = conn.execute(
                    "SELECT COUNT(*) as cnt FROM teaming_partners "
                    "WHERE is_active = 1 AND LOWER(set_aside_status) LIKE ?",
                    (f"%{opp_sa[:10]}%",),
                ).fetchone()["cnt"]
                sa_score = 0.6 if team_sa > 0 else 0.2
        breakdown["set_aside_match"] = round(sa_score, 2)

        # --- 4. Keyword match ---
        kw_score = 0.5  # Default neutral
        desc = _text_lower(opp.get("description") or opp.get("title") or "")
        if desc:
            boost_hits, boost_total = _keyword_overlap(desc, boost_kw)
            penalty_hits, _ = _keyword_overlap(desc, penalty_kw)

            # Also check KB keyword overlap
            kb_keywords = conn.execute(
                "SELECT keywords FROM kb_entries "
                "WHERE is_active = 1 AND keywords IS NOT NULL "
                "LIMIT 50",
            ).fetchall()
            all_kb_kw = set()
            for row in kb_keywords:
                for kw in (row["keywords"] or "").split(","):
                    kw = kw.strip().lower()
                    if kw:
                        all_kb_kw.add(kw)

            kb_hits = sum(1 for kw in all_kb_kw if kw in desc)

            if boost_hits >= 3 and penalty_hits == 0:
                kw_score = 1.0
            elif boost_hits >= 2:
                kw_score = 0.8
            elif boost_hits >= 1:
                kw_score = 0.6
            elif penalty_hits >= 2:
                kw_score = 0.1
            elif penalty_hits >= 1:
                kw_score = 0.3

            # KB keyword bonus
            if kb_hits >= 5:
                kw_score = min(1.0, kw_score + 0.2)
            elif kb_hits >= 2:
                kw_score = min(1.0, kw_score + 0.1)

        breakdown["keyword_match"] = round(kw_score, 2)

        # --- 5. Contract size match ---
        size_score = 0.5  # Default neutral
        est_low = opp.get("estimated_value_low")
        est_high = opp.get("estimated_value_high")
        if est_low or est_high:
            value = est_high or est_low or 0
            if 1_000_000 <= value <= 50_000_000:
                size_score = 1.0  # Sweet spot
            elif 500_000 <= value < 1_000_000:
                size_score = 0.7
            elif 50_000_000 < value <= 100_000_000:
                size_score = 0.6
            elif value > 100_000_000:
                size_score = 0.4  # Possible but risky
            else:
                size_score = 0.3  # Too small
        breakdown["contract_size_match"] = round(size_score, 2)

        # --- 6. Clearance match ---
        cl_score = 0.5  # Default neutral
        desc_full = _text_lower(
            (opp.get("description") or "") + " " + (opp.get("title") or "")
        )
        clearance_needed = False
        for term in ["top secret", "ts/sci", "secret clearance",
                     "security clearance", "ts clearance"]:
            if term in desc_full:
                clearance_needed = True
                break

        if clearance_needed:
            cleared_count = conn.execute(
                "SELECT COUNT(*) as cnt FROM resumes "
                "WHERE is_active = 1 AND clearance_level IN "
                "('secret', 'top_secret', 'ts_sci', 'ts_sci_poly') "
                "AND clearance_status = 'active'",
            ).fetchone()["cnt"]
            if cleared_count >= 10:
                cl_score = 1.0
            elif cleared_count >= 5:
                cl_score = 0.7
            elif cleared_count >= 1:
                cl_score = 0.4
            else:
                cl_score = 0.1
        else:
            cl_score = 0.8  # No clearance needed is favorable
        breakdown["clearance_match"] = round(cl_score, 2)

        # --- Weighted total ---
        weights = {
            "naics_match": fit_cfg.get("naics_match_weight", 0.25),
            "agency_match": fit_cfg.get("agency_match_weight", 0.20),
            "set_aside_match": fit_cfg.get("set_aside_match_weight", 0.15),
            "keyword_match": fit_cfg.get("keyword_match_weight", 0.20),
            "contract_size_match": fit_cfg.get(
                "contract_size_match_weight", 0.10),
            "clearance_match": fit_cfg.get("clearance_match_weight", 0.10),
        }
        raw_score = sum(
            breakdown[dim] * weights.get(dim, 0)
            for dim in breakdown
        )
        fit_score = round(raw_score * 100, 1)

        # --- Persist ---
        conn.execute(
            "UPDATE opportunities SET fit_score = ?, updated_at = ? "
            "WHERE id = ?",
            (fit_score, _now(), opp_id),
        )
        _audit(
            conn, "opportunity.scored", f"Fit scored: {fit_score}",
            "opportunity", opp_id,
            {"fit_score": fit_score, "breakdown": breakdown},
        )
        conn.commit()

        return {
            "status": "success",
            "opp_id": opp_id,
            "fit_score": fit_score,
            "breakdown": breakdown,
            "weights": weights,
            "scored_at": _now(),
        }
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Qualification scoring (7-dimension Go/No-Go)
# ---------------------------------------------------------------------------

def _score_customer_relationship(opp, conn, dim_cfg):
    """Score customer_relationship dimension (0.0-1.0)."""
    agency = _text_lower(opp.get("agency"))
    if not agency:
        return 0.1, "No agency specified", None

    # Check past performances with this agency
    pp_rows = conn.execute(
        "SELECT id, contract_name, role, cpars_rating, "
        "period_of_performance_end FROM past_performances "
        "WHERE is_active = 1 AND LOWER(agency) LIKE ? "
        "ORDER BY period_of_performance_end DESC",
        (f"%{agency[:20]}%",),
    ).fetchall()

    if not pp_rows:
        return 0.1, "No prior relationship with agency", None

    scoring = dim_cfg.get("scoring", {})
    evidence = [dict(r)["contract_name"] for r in pp_rows[:5]]

    best_role = None
    for pp in pp_rows:
        role = (pp["role"] or "").lower()
        if role == "prime":
            best_role = "prime"
            break
        elif role in ("subcontractor", "joint_venture", "teaming"):
            best_role = role

    # Check recency
    most_recent = pp_rows[0]
    end_date = most_recent["period_of_performance_end"] or ""
    is_recent = False
    try:
        end_dt = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
        age_years = (datetime.now(timezone.utc) - end_dt).days / 365.25
        is_recent = age_years <= 3
    except (ValueError, TypeError):
        pass

    if best_role == "prime" and is_recent:
        score = scoring.get("incumbent_prime", 1.0)
        rationale = "Incumbent prime contractor with recent work"
    elif best_role == "prime":
        score = scoring.get("prior_work_older", 0.5)
        rationale = "Former prime contractor"
    elif best_role and is_recent:
        score = scoring.get("incumbent_sub", 0.8)
        rationale = f"Recent subcontractor/teaming relationship"
    elif best_role:
        score = scoring.get("prior_work_older", 0.5)
        rationale = "Prior subcontractor relationship"
    else:
        score = scoring.get("prior_work_recent", 0.7) if is_recent else 0.5
        rationale = "Prior work with agency"

    return score, rationale, json.dumps(evidence)


def _score_technical_fit(opp, conn, dim_cfg):
    """Score technical_fit dimension (0.0-1.0)."""
    desc = _text_lower(
        (opp.get("description") or "") + " " + (opp.get("title") or "")
    )
    if not desc:
        return 0.3, "No description available for analysis", None

    scoring = dim_cfg.get("scoring", {})

    # Extract meaningful words from description (> 3 chars, alpha-only)
    desc_words = set(
        w for w in re.findall(r'[a-z]+', desc)
        if len(w) > 3
    )

    # Check KB capability entries for keyword overlap
    kb_rows = conn.execute(
        "SELECT id, title, keywords, content FROM kb_entries "
        "WHERE is_active = 1 AND entry_type IN "
        "('capability', 'solution_architecture', 'methodology', "
        "'domain_expertise', 'tool_technology') "
        "LIMIT 100",
    ).fetchall()

    total_kb = max(len(kb_rows), 1)
    matching_kb = 0
    evidence_items = []

    for kb in kb_rows:
        kb_text = _text_lower(
            (kb["title"] or "") + " " +
            (kb["keywords"] or "") + " " +
            (kb["content"] or "")[:500]
        )
        kb_words = set(
            w for w in re.findall(r'[a-z]+', kb_text)
            if len(w) > 3
        )
        overlap = desc_words & kb_words
        if len(overlap) >= 3:
            matching_kb += 1
            evidence_items.append(kb["title"])

    coverage = matching_kb / total_kb if total_kb > 0 else 0

    if coverage >= 0.6:
        score = scoring.get("full_coverage", 1.0)
        rationale = f"Strong coverage: {matching_kb}/{total_kb} KB entries match"
    elif coverage >= 0.4:
        score = scoring.get("strong_coverage", 0.8)
        rationale = f"Good coverage: {matching_kb}/{total_kb} KB entries match"
    elif coverage >= 0.2:
        score = scoring.get("moderate_coverage", 0.6)
        rationale = f"Moderate coverage: {matching_kb}/{total_kb} KB entries match"
    elif coverage >= 0.1:
        score = scoring.get("partial_coverage", 0.3)
        rationale = f"Partial coverage: {matching_kb}/{total_kb} KB entries match"
    else:
        score = scoring.get("weak_coverage", 0.1)
        rationale = f"Weak coverage: {matching_kb}/{total_kb} KB entries match"

    return score, rationale, json.dumps(evidence_items[:10])


def _score_past_performance(opp, conn, dim_cfg):
    """Score past_performance dimension (0.0-1.0)."""
    agency = _text_lower(opp.get("agency"))
    naics = opp.get("naics_code") or ""
    scoring = dim_cfg.get("scoring", {})

    # Find relevant past performances (agency or NAICS match)
    clauses = []
    params = []
    if agency:
        clauses.append("LOWER(agency) LIKE ?")
        params.append(f"%{agency[:20]}%")
    if naics:
        clauses.append("naics_code = ?")
        params.append(naics)

    if not clauses:
        return 0.2, "Cannot evaluate without agency or NAICS", None

    where = " OR ".join(clauses)
    pp_rows = conn.execute(
        f"SELECT id, contract_name, cpars_rating, contract_value "
        f"FROM past_performances "
        f"WHERE is_active = 1 AND ({where}) "
        f"ORDER BY period_of_performance_end DESC",
        params,
    ).fetchall()

    if not pp_rows:
        return scoring.get("no_relevant_pp", 0.2), \
            "No relevant past performance", None

    evidence_items = []
    ratings = []
    for pp in pp_rows:
        evidence_items.append(
            f"{pp['contract_name']} ({pp['cpars_rating'] or 'unrated'})"
        )
        if pp["cpars_rating"]:
            ratings.append(pp["cpars_rating"])

    # Score based on best CPARS rating
    rating_order = ["exceptional", "very_good", "satisfactory",
                    "marginal", "unsatisfactory"]
    best_rating = None
    for r in rating_order:
        if r in ratings:
            best_rating = r
            break

    if best_rating == "exceptional":
        score = scoring.get("exceptional_relevant", 1.0)
        rationale = f"Exceptional CPARS on relevant work ({len(pp_rows)} contracts)"
    elif best_rating == "very_good":
        score = scoring.get("very_good_relevant", 0.8)
        rationale = f"Very Good CPARS on relevant work ({len(pp_rows)} contracts)"
    elif best_rating == "satisfactory":
        score = scoring.get("satisfactory_relevant", 0.6)
        rationale = f"Satisfactory CPARS on relevant work ({len(pp_rows)} contracts)"
    elif best_rating in ("marginal", "unsatisfactory"):
        score = scoring.get("mixed_ratings", 0.4)
        rationale = f"Mixed CPARS ratings ({best_rating})"
    else:
        score = 0.5
        rationale = f"Relevant contracts found but no CPARS ({len(pp_rows)})"

    return score, rationale, json.dumps(evidence_items[:5])


def _score_competitive_position(opp, conn, dim_cfg):
    """Score competitive_position dimension (0.0-1.0)."""
    agency = _text_lower(opp.get("agency"))
    naics = opp.get("naics_code") or ""
    scoring = dim_cfg.get("scoring", {})

    # Check competitor wins in this space
    clauses = []
    params = []
    if agency:
        clauses.append("LOWER(agency) LIKE ?")
        params.append(f"%{agency[:20]}%")
    if naics:
        clauses.append("naics_code = ?")
        params.append(naics)

    competitor_count = 0
    if clauses:
        where = " OR ".join(clauses)
        competitor_count = conn.execute(
            f"SELECT COUNT(DISTINCT competitor_name) as cnt "
            f"FROM competitor_wins WHERE {where}",
            params,
        ).fetchone()["cnt"]

    if competitor_count == 0:
        score = scoring.get("strong_position", 1.0)
        rationale = "No known competitor wins in this space"
    elif competitor_count <= 2:
        score = scoring.get("moderate_position", 0.7)
        rationale = f"{competitor_count} known competitor(s)"
    elif competitor_count <= 5:
        score = scoring.get("crowded_field", 0.4)
        rationale = f"Crowded field: {competitor_count} competitors"
    else:
        score = scoring.get("disadvantaged", 0.2)
        rationale = f"Highly competitive: {competitor_count} known competitors"

    evidence = json.dumps({"competitor_count": competitor_count})
    return score, rationale, evidence


def _score_vehicle_access(opp, conn, dim_cfg):
    """Score vehicle_access dimension (0.0-1.0)."""
    scoring = dim_cfg.get("scoring", {})
    desc = _text_lower(
        (opp.get("description") or "") + " " +
        (opp.get("set_aside_type") or "") + " " +
        (opp.get("title") or "")
    )

    # Look for vehicle mentions in description
    vehicle_terms = [
        "gwac", "bpa", "idiq", "gsa schedule", "seaport",
        "alliant", "encore", "oasis", "8(a) stars", "cio-cs",
    ]
    vehicle_mentioned = any(v in desc for v in vehicle_terms)

    if not vehicle_mentioned:
        return scoring.get("full_and_open", 0.5), \
            "No specific vehicle requirement detected (likely full and open)", \
            None

    # Check if we have matching vehicle access in teaming partners
    team_with_vehicle = conn.execute(
        "SELECT COUNT(*) as cnt FROM teaming_partners "
        "WHERE is_active = 1 AND contract_vehicles IS NOT NULL "
        "AND contract_vehicles != ''",
    ).fetchone()["cnt"]

    if team_with_vehicle > 0:
        return scoring.get("can_team_for_vehicle", 0.6), \
            "Teaming partner may have vehicle access", \
            json.dumps({"team_partners_with_vehicles": team_with_vehicle})

    return scoring.get("no_vehicle_access", 0.1), \
        "Specific vehicle required but no access identified", None


def _score_clearance_compliance(opp, conn, dim_cfg):
    """Score clearance_compliance dimension (0.0-1.0)."""
    scoring = dim_cfg.get("scoring", {})
    desc = _text_lower(
        (opp.get("description") or "") + " " + (opp.get("title") or "")
    )

    # Detect clearance requirements
    required_level = None
    if "ts/sci" in desc or "ts_sci" in desc:
        required_level = "ts_sci"
    elif "top secret" in desc:
        required_level = "top_secret"
    elif "secret" in desc and "clearance" in desc:
        required_level = "secret"
    elif "public trust" in desc:
        required_level = "public_trust"

    if not required_level:
        return scoring.get("fully_cleared", 1.0), \
            "No specific clearance requirement detected", None

    # Map acceptable clearance levels (higher clears lower)
    level_hierarchy = {
        "public_trust": ["public_trust", "secret", "top_secret",
                         "ts_sci", "ts_sci_poly"],
        "secret": ["secret", "top_secret", "ts_sci", "ts_sci_poly"],
        "top_secret": ["top_secret", "ts_sci", "ts_sci_poly"],
        "ts_sci": ["ts_sci", "ts_sci_poly"],
    }
    acceptable = level_hierarchy.get(required_level, [required_level])
    placeholders = ",".join("?" for _ in acceptable)

    cleared = conn.execute(
        f"SELECT COUNT(*) as cnt FROM resumes "
        f"WHERE is_active = 1 AND clearance_level IN ({placeholders}) "
        f"AND clearance_status = 'active'",
        acceptable,
    ).fetchone()["cnt"]

    evidence = json.dumps({
        "required_level": required_level,
        "cleared_personnel": cleared,
    })

    if cleared >= 10:
        return scoring.get("fully_cleared", 1.0), \
            f"Fully cleared: {cleared} personnel with {required_level}+", \
            evidence
    elif cleared >= 5:
        return scoring.get("mostly_cleared", 0.7), \
            f"Mostly cleared: {cleared} personnel available", evidence
    elif cleared >= 1:
        return scoring.get("partially_cleared", 0.4), \
            f"Partially cleared: only {cleared} personnel", evidence
    else:
        return scoring.get("insufficient", 0.1), \
            f"No personnel with required {required_level} clearance", evidence


def _score_strategic_value(opp, conn, dim_cfg):
    """Score strategic_value dimension (0.0-1.0)."""
    scoring = dim_cfg.get("scoring", {})
    est_low = opp.get("estimated_value_low") or 0
    est_high = opp.get("estimated_value_high") or 0
    value = max(est_low, est_high)

    if value >= 50_000_000:
        score = scoring.get("transformational", 1.0)
        rationale = f"Transformational: ${value:,.0f} TCV"
    elif value >= 10_000_000:
        score = scoring.get("significant", 0.8)
        rationale = f"Significant: ${value:,.0f} TCV"
    elif value >= 1_000_000:
        score = scoring.get("moderate", 0.5)
        rationale = f"Moderate: ${value:,.0f} TCV"
    elif value > 0:
        score = scoring.get("limited", 0.3)
        rationale = f"Limited: ${value:,.0f} TCV"
    else:
        # No value estimate; check agency for strategic relevance
        agency = _text_lower(opp.get("agency"))
        strategic_agencies = [
            "department of defense", "defense", "army", "navy",
            "air force", "cyber command", "intelligence",
        ]
        if any(sa in agency for sa in strategic_agencies):
            score = 0.6
            rationale = "Strategic DoD/IC agency (value unknown)"
        else:
            score = 0.4
            rationale = "Contract value unknown"

    return score, rationale, json.dumps({"estimated_value": value})


# Dimension scoring dispatch
DIMENSION_SCORERS = {
    "customer_relationship": _score_customer_relationship,
    "technical_fit": _score_technical_fit,
    "past_performance": _score_past_performance,
    "competitive_position": _score_competitive_position,
    "vehicle_access": _score_vehicle_access,
    "clearance_compliance": _score_clearance_compliance,
    "strategic_value": _score_strategic_value,
}


def score_qualification(opp_id, dimensions=None, db_path=None):
    """Run full 7-dimension Go/No-Go qualification scoring.

    Each dimension is scored 0.0-1.0 and stored in the
    opportunity_scores table. Returns the weighted overall score
    and a recommendation.

    Args:
        opp_id: Opportunity ID.
        dimensions: List of dimension names to score (default: all 7).
        db_path: Override database path.

    Returns:
        dict with keys: opp_id, overall_score, recommendation,
        dimension_scores, thresholds, scored_at.
    """
    config = _load_scoring_config()
    dim_defs = _get_dimensions(config)
    thresholds = _get_thresholds(config)

    conn = _get_db(db_path)
    try:
        opp = conn.execute(
            "SELECT * FROM opportunities WHERE id = ?", (opp_id,)
        ).fetchone()
        if not opp:
            return {"status": "error", "error": f"Opportunity {opp_id} not found"}
        opp = dict(opp)

        dims_to_score = dimensions or list(DIMENSION_SCORERS.keys())
        dimension_scores = {}
        now = _now()

        for dim_name in dims_to_score:
            scorer_fn = DIMENSION_SCORERS.get(dim_name)
            if not scorer_fn:
                continue

            dim_cfg = dim_defs.get(dim_name, {})
            score_val, rationale, evidence = scorer_fn(opp, conn, dim_cfg)
            score_val = max(0.0, min(1.0, score_val))

            dimension_scores[dim_name] = {
                "score": round(score_val, 2),
                "weight": dim_cfg.get("weight",
                                      DEFAULT_DIMENSIONS.get(dim_name, {})
                                      .get("weight", 0)),
                "rationale": rationale,
            }

            # Persist individual dimension score
            conn.execute(
                "INSERT INTO opportunity_scores "
                "(id, opportunity_id, dimension, score, rationale, "
                "evidence, scored_by, scored_at) "
                "VALUES (?, ?, ?, ?, ?, ?, 'opportunity_scorer', ?)",
                (_score_id(), opp_id, dim_name, score_val,
                 rationale, evidence, now),
            )

        # Weighted overall
        overall = sum(
            ds["score"] * ds["weight"]
            for ds in dimension_scores.values()
        )
        overall = round(overall, 3)

        # Determine recommendation
        strong_go_threshold = thresholds.get("strong_go", 0.75)
        cond_go_threshold = thresholds.get("conditional_go", 0.55)

        if overall >= strong_go_threshold:
            recommendation = "strong_go"
        elif overall >= cond_go_threshold:
            recommendation = "conditional_go"
        else:
            recommendation = "no_bid"

        # Persist qualification score on opportunity
        conn.execute(
            "UPDATE opportunities SET qualification_score = ?, "
            "updated_at = ? WHERE id = ?",
            (overall, now, opp_id),
        )

        _audit(
            conn, "opportunity.qualified",
            f"Qualification scored: {overall:.3f} ({recommendation})",
            "opportunity", opp_id,
            {"overall_score": overall, "recommendation": recommendation,
             "dimensions": {
                 k: v["score"] for k, v in dimension_scores.items()
             }},
        )
        conn.commit()

        return {
            "status": "success",
            "opp_id": opp_id,
            "overall_score": overall,
            "recommendation": recommendation,
            "dimension_scores": dimension_scores,
            "thresholds": thresholds,
            "scored_at": now,
        }
    finally:
        conn.close()


def score_all_new(db_path=None):
    """Batch score all unscored opportunities (fit + qualification).

    Finds all opportunities with status='discovered' and no fit_score,
    runs both fit scoring and qualification scoring on each.

    Args:
        db_path: Override database path.

    Returns:
        dict with keys: status, scored_count, errors.
    """
    conn = _get_db(db_path)
    try:
        rows = conn.execute(
            "SELECT id FROM opportunities "
            "WHERE fit_score IS NULL "
            "ORDER BY discovered_at DESC",
        ).fetchall()
    finally:
        conn.close()

    scored = 0
    errors = []
    for row in rows:
        oid = row["id"]
        try:
            fit_result = score_fit(oid, db_path=db_path)
            if fit_result.get("status") != "success":
                errors.append(f"{oid}: fit error: {fit_result.get('error')}")
                continue

            qual_result = score_qualification(oid, db_path=db_path)
            if qual_result.get("status") != "success":
                errors.append(f"{oid}: qual error: {qual_result.get('error')}")
                continue

            scored += 1
        except Exception as exc:
            errors.append(f"{oid}: {exc}")

    return {
        "status": "success" if not errors else "partial",
        "total_unscored": len(rows),
        "scored_count": scored,
        "errors": errors if errors else None,
        "scored_at": _now(),
    }


def go_no_go(opp_id, db_path=None):
    """Generate a full Go/No-Go recommendation with scorecard.

    Runs fit scoring (if not already done), qualification scoring,
    and returns a complete decision package.

    Args:
        opp_id: Opportunity ID.
        db_path: Override database path.

    Returns:
        dict with fit_score, qualification, recommendation,
        strengths, weaknesses, risk_factors.
    """
    # Ensure fit score exists
    conn = _get_db(db_path)
    try:
        opp = conn.execute(
            "SELECT id, title, agency, naics_code, fit_score, "
            "qualification_score, response_deadline "
            "FROM opportunities WHERE id = ?", (opp_id,)
        ).fetchone()
        if not opp:
            return {"status": "error", "error": f"Opportunity {opp_id} not found"}
        opp = dict(opp)
    finally:
        conn.close()

    # Run fit scoring if not already done
    if opp.get("fit_score") is None:
        fit_result = score_fit(opp_id, db_path=db_path)
    else:
        fit_result = {"fit_score": opp["fit_score"]}

    # Run full qualification
    qual_result = score_qualification(opp_id, db_path=db_path)
    if qual_result.get("status") != "success":
        return qual_result

    # Identify strengths and weaknesses from dimension scores
    dim_scores = qual_result.get("dimension_scores", {})
    strengths = []
    weaknesses = []
    risk_factors = []

    for dim_name, dim_data in dim_scores.items():
        score = dim_data["score"]
        label = dim_name.replace("_", " ").title()
        if score >= 0.7:
            strengths.append(f"{label}: {dim_data['rationale']}")
        elif score <= 0.3:
            weaknesses.append(f"{label}: {dim_data['rationale']}")
            risk_factors.append(
                f"Low {label.lower()} score ({score:.2f}) may require "
                f"mitigation"
            )

    # Check deadline risk
    deadline = opp.get("response_deadline")
    if deadline:
        try:
            dl = datetime.fromisoformat(
                deadline.replace("Z", "+00:00")
            )
            days_until = (dl - datetime.now(timezone.utc)).days
            if days_until < 14:
                risk_factors.append(
                    f"Tight deadline: only {days_until} days remaining"
                )
            elif days_until < 30:
                risk_factors.append(
                    f"Moderate timeline pressure: {days_until} days"
                )
        except (ValueError, TypeError):
            pass

    recommendation = qual_result.get("recommendation", "no_bid")
    overall = qual_result.get("overall_score", 0)

    return {
        "status": "success",
        "opp_id": opp_id,
        "title": opp.get("title"),
        "agency": opp.get("agency"),
        "fit_score": fit_result.get("fit_score"),
        "qualification_score": overall,
        "recommendation": recommendation,
        "recommendation_label": {
            "strong_go": "STRONG GO",
            "conditional_go": "CONDITIONAL GO",
            "no_bid": "NO BID",
        }.get(recommendation, recommendation.upper()),
        "dimension_scores": dim_scores,
        "strengths": strengths,
        "weaknesses": weaknesses,
        "risk_factors": risk_factors,
        "thresholds": qual_result.get("thresholds"),
        "scored_at": _now(),
    }


def get_scorecard(opp_id, db_path=None):
    """Retrieve the existing scorecard for an opportunity.

    Returns the most recent scores from opportunity_scores,
    plus the opportunity's current fit_score and qualification_score.

    Args:
        opp_id: Opportunity ID.
        db_path: Override database path.

    Returns:
        dict with opp_id, fit_score, qualification_score,
        dimension_scores, go_decision, or None if not found.
    """
    conn = _get_db(db_path)
    try:
        opp = conn.execute(
            "SELECT id, title, agency, naics_code, fit_score, "
            "qualification_score, go_decision, go_decision_rationale, "
            "go_decision_by, go_decision_at, status "
            "FROM opportunities WHERE id = ?", (opp_id,)
        ).fetchone()

        if not opp:
            return None

        result = dict(opp)

        # Fetch most recent scores per dimension
        scores = conn.execute(
            "SELECT dimension, score, rationale, evidence, scored_by, "
            "scored_at FROM opportunity_scores "
            "WHERE opportunity_id = ? "
            "ORDER BY scored_at DESC",
            (opp_id,),
        ).fetchall()

        # Deduplicate: keep only the most recent per dimension
        seen = set()
        dim_scores = {}
        for s in scores:
            dim = s["dimension"]
            if dim not in seen:
                seen.add(dim)
                dim_scores[dim] = {
                    "score": s["score"],
                    "rationale": s["rationale"],
                    "evidence": s["evidence"],
                    "scored_by": s["scored_by"],
                    "scored_at": s["scored_at"],
                }

        result["dimension_scores"] = dim_scores
        return result
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _format_scorecard(card):
    """Format a scorecard dict for human-readable display."""
    lines = []
    lines.append(f"Opportunity: {card.get('title', card.get('opp_id'))}")
    lines.append("=" * 60)
    lines.append(f"  ID:               {card.get('id', card.get('opp_id'))}")
    lines.append(f"  Agency:           {card.get('agency', 'N/A')}")
    lines.append(f"  Status:           {card.get('status', 'N/A')}")
    lines.append(f"  Fit Score:        {card.get('fit_score', '--')}")
    lines.append(
        f"  Qual Score:       {card.get('qualification_score', '--')}")
    lines.append(f"  Go Decision:      {card.get('go_decision', '--')}")

    dim_scores = card.get("dimension_scores", {})
    if dim_scores:
        lines.append("")
        lines.append("  Dimension Scores:")
        lines.append(f"  {'Dimension':<25} {'Score':>6}  Rationale")
        lines.append("  " + "-" * 70)
        for dim, data in dim_scores.items():
            score_val = data.get("score", 0)
            rationale = data.get("rationale", "")[:45]
            label = dim.replace("_", " ").title()
            lines.append(f"  {label:<25} {score_val:>5.2f}  {rationale}")

    return "\n".join(lines)


def main():
    """CLI entry point for the opportunity scoring engine."""
    parser = argparse.ArgumentParser(
        description="Opportunity Qualification & Scoring Engine — "
                    "7-dimension Go/No-Go scoring for government opportunities",
    )

    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--score", action="store_true",
        help="Score a single opportunity (fit + qualification)",
    )
    group.add_argument(
        "--score-all", action="store_true",
        help="Batch score all unscored opportunities",
    )
    group.add_argument(
        "--go-no-go", action="store_true",
        help="Generate full Go/No-Go recommendation",
    )
    group.add_argument(
        "--scorecard", action="store_true",
        help="Retrieve existing scorecard",
    )

    parser.add_argument("--opp-id", help="Opportunity ID (required for "
                                         "--score, --go-no-go, --scorecard)")
    parser.add_argument("--json", action="store_true", help="JSON output")
    parser.add_argument("--db-path", help="Override database path")

    args = parser.parse_args()

    # -------------------------------------------------------------------
    if args.score:
        if not args.opp_id:
            print("Error: --score requires --opp-id", file=sys.stderr)
            sys.exit(1)
        fit = score_fit(args.opp_id, db_path=args.db_path)
        qual = score_qualification(args.opp_id, db_path=args.db_path)
        result = {"fit": fit, "qualification": qual}
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(f"Fit Score: {fit.get('fit_score', '--')}")
            print(f"Qualification: {qual.get('overall_score', '--')} "
                  f"({qual.get('recommendation', '--')})")
            dim_scores = qual.get("dimension_scores", {})
            for dim, data in dim_scores.items():
                label = dim.replace("_", " ").title()
                print(f"  {label}: {data['score']:.2f} — {data['rationale']}")

    # -------------------------------------------------------------------
    elif args.score_all:
        result = score_all_new(db_path=args.db_path)
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print("Batch Scoring Results")
            print("=" * 40)
            print(f"  Unscored:    {result['total_unscored']}")
            print(f"  Scored:      {result['scored_count']}")
            if result.get("errors"):
                print(f"  Errors:      {len(result['errors'])}")
                for e in result["errors"]:
                    print(f"    - {e}")

    # -------------------------------------------------------------------
    elif args.go_no_go:
        if not args.opp_id:
            print("Error: --go-no-go requires --opp-id", file=sys.stderr)
            sys.exit(1)
        result = go_no_go(args.opp_id, db_path=args.db_path)
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            if result.get("status") != "success":
                print(f"Error: {result.get('error')}")
                sys.exit(1)
            print(f"Go/No-Go: {result['title']}")
            print("=" * 60)
            print(f"  Recommendation:   {result['recommendation_label']}")
            print(f"  Fit Score:        {result.get('fit_score', '--')}")
            print(f"  Qual Score:       {result['qualification_score']:.3f}")
            print()
            if result.get("strengths"):
                print("  Strengths:")
                for s in result["strengths"]:
                    print(f"    + {s}")
            if result.get("weaknesses"):
                print("  Weaknesses:")
                for w in result["weaknesses"]:
                    print(f"    - {w}")
            if result.get("risk_factors"):
                print("  Risk Factors:")
                for r in result["risk_factors"]:
                    print(f"    ! {r}")
            print()
            dim_scores = result.get("dimension_scores", {})
            if dim_scores:
                print(f"  {'Dimension':<25} {'Score':>6} {'Weight':>6}")
                print("  " + "-" * 40)
                for dim, data in dim_scores.items():
                    label = dim.replace("_", " ").title()
                    print(f"  {label:<25} {data['score']:>5.2f} "
                          f"{data['weight']:>5.2f}")

    # -------------------------------------------------------------------
    elif args.scorecard:
        if not args.opp_id:
            print("Error: --scorecard requires --opp-id", file=sys.stderr)
            sys.exit(1)
        card = get_scorecard(args.opp_id, db_path=args.db_path)
        if args.json:
            print(json.dumps(card, indent=2, default=str))
        else:
            if card is None:
                print(f"No scorecard found for {args.opp_id}")
                sys.exit(1)
            print(_format_scorecard(card))


if __name__ == "__main__":
    main()
