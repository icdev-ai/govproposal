#!/usr/bin/env python3
# CUI // SP-PROPIN
# Controlled by: GovProposal Portal
# CUI Category: PROPIN
# Distribution: D
# POC: GovProposal System Administrator
"""Past Performance library manager with relevance scoring.

Manages past performance records and provides 5-dimension relevance scoring
for proposal inclusion: scope_similarity (0.30), agency_match (0.20),
size_proximity (0.15), recency (0.15), rating_quality (0.20).

Usage:
    python tools/knowledge/past_performance.py --add --contract-name "Cloud Migration" --agency "DoD" --scope "..." --json
    python tools/knowledge/past_performance.py --search --query "FedRAMP ATO" [--naics 541512] [--agency "DoD"]
    python tools/knowledge/past_performance.py --get --id PP-abc123def456
    python tools/knowledge/past_performance.py --list [--agency "DoD"] [--rating exceptional] [--limit 20]
    python tools/knowledge/past_performance.py --narrative --id PP-abc123def456 [--requirements "cloud, FedRAMP"]
    python tools/knowledge/past_performance.py --summary --json
"""

import json
import math
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

# Relevance scoring weights (sum = 1.0)
RELEVANCE_WEIGHTS = {
    "scope_similarity": 0.30,
    "agency_match": 0.20,
    "size_proximity": 0.15,
    "recency": 0.15,
    "rating_quality": 0.20,
}

# CPARS rating ordinal mapping
CPARS_RATING_SCORES = {
    "exceptional": 1.0,
    "very_good": 0.8,
    "satisfactory": 0.6,
    "marginal": 0.3,
    "unsatisfactory": 0.1,
}

# Valid roles matching DB CHECK constraint
VALID_ROLES = ("prime", "subcontractor", "joint_venture", "teaming")

# Valid CPARS ratings
VALID_RATINGS = tuple(CPARS_RATING_SCORES.keys())


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _pp_id():
    """Generate a Past Performance ID: PP- followed by 12 hex characters."""
    return "PP-" + secrets.token_hex(6)


def _now():
    """Return current UTC timestamp as ISO-8601 string."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _get_db(db_path=None):
    """Open a database connection with WAL mode and foreign keys enabled.

    Args:
        db_path: Optional path override. Falls back to DB_PATH.

    Returns:
        sqlite3.Connection with row_factory set to sqlite3.Row.
    """
    path = str(db_path or DB_PATH)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _audit(conn, event_type, action, entity_type=None, entity_id=None, details=None):
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
            "past_performance",
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


def _tokenize(text):
    """Simple whitespace + punctuation tokenizer.

    Args:
        text: Input string.

    Returns:
        list of lowercase token strings.
    """
    if not text:
        return []
    text = text.lower()
    text = re.sub(r"[^\w\s]", " ", text)
    return [t for t in text.split() if len(t) > 1]


def _term_overlap_score(query_tokens, doc_tokens):
    """Compute a normalized term overlap score between query and document.

    Args:
        query_tokens: list of query tokens.
        doc_tokens: list of document tokens.

    Returns:
        float between 0.0 and 1.0.
    """
    if not query_tokens or not doc_tokens:
        return 0.0
    query_set = set(query_tokens)
    doc_set = set(doc_tokens)
    overlap = len(query_set & doc_set)
    # Jaccard-like overlap normalized by query size
    return overlap / len(query_set)


def _parse_date(date_str):
    """Parse a date string into a datetime object, handling common formats.

    Args:
        date_str: Date string (ISO-8601 or YYYY-MM-DD).

    Returns:
        datetime object, or None if parsing fails.
    """
    if not date_str:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            continue
    return None


def _recency_score(end_date_str):
    """Score a past performance record by recency.

    More recent = higher score. Uses exponential decay with a half-life
    of 3 years (1095 days).

    Args:
        end_date_str: Period of performance end date string.

    Returns:
        float between 0.0 and 1.0.
    """
    end_date = _parse_date(end_date_str)
    if end_date is None:
        return 0.3  # Default score for missing dates
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    days_ago = (now - end_date).days
    if days_ago < 0:
        return 1.0  # Still active
    half_life = 1095  # 3 years in days
    return math.pow(2, -(days_ago / half_life))


def _size_proximity_score(contract_value, target_value=None):
    """Score similarity in contract size.

    If no target value is provided, uses a moderate default score.
    Uses logarithmic ratio to handle wide value ranges.

    Args:
        contract_value: Actual contract value.
        target_value: Target/expected contract value.

    Returns:
        float between 0.0 and 1.0.
    """
    if contract_value is None or contract_value <= 0:
        return 0.3  # Default for missing values
    if target_value is None or target_value <= 0:
        return 0.5  # No target to compare against

    ratio = math.log10(max(contract_value, 1)) / math.log10(max(target_value, 1))
    # Score peaks at ratio=1.0, decays as ratio diverges
    return max(0.0, 1.0 - abs(1.0 - ratio) * 0.5)


# ---------------------------------------------------------------------------
# Core Functions
# ---------------------------------------------------------------------------

def add_performance(contract_name, agency, scope_description, role="prime",
                    db_path=None, **kwargs):
    """Add a past performance record.

    Args:
        contract_name: Name of the contract.
        agency: Contracting agency.
        scope_description: Description of scope/work performed.
        role: Role on contract (prime, subcontractor, joint_venture, teaming).
        db_path: Optional database path override.
        **kwargs: Additional fields matching past_performances table columns:
            contract_number, sub_agency, contract_type, contract_value,
            period_of_performance_start, period_of_performance_end,
            naics_code, set_aside, prime_contractor, technical_approach,
            key_accomplishments, metrics_achieved, cpars_rating,
            cpars_narrative, relevance_tags, contact_name, contact_title,
            contact_email, contact_phone.

    Returns:
        dict with the created record fields.

    Raises:
        ValueError: If role or cpars_rating is invalid.
    """
    if role not in VALID_ROLES:
        raise ValueError(
            f"Invalid role '{role}'. Must be one of: {', '.join(VALID_ROLES)}"
        )

    cpars_rating = kwargs.get("cpars_rating")
    if cpars_rating and cpars_rating not in VALID_RATINGS:
        raise ValueError(
            f"Invalid cpars_rating '{cpars_rating}'. "
            f"Must be one of: {', '.join(VALID_RATINGS)}"
        )

    pp_id = _pp_id()
    now = _now()

    # Map kwargs to DB columns
    allowed_kwargs = {
        "contract_number", "sub_agency", "contract_type", "contract_value",
        "period_of_performance_start", "period_of_performance_end",
        "naics_code", "set_aside", "prime_contractor", "technical_approach",
        "key_accomplishments", "metrics_achieved", "cpars_rating",
        "cpars_narrative", "relevance_tags", "contact_name", "contact_title",
        "contact_email", "contact_phone",
    }

    # Build column/value lists
    columns = ["id", "contract_name", "agency", "scope_description", "role",
               "is_active", "created_at", "updated_at"]
    values = [pp_id, contract_name, agency, scope_description, role, 1, now, now]

    for key, value in kwargs.items():
        if key in allowed_kwargs and value is not None:
            columns.append(key)
            if key == "relevance_tags" and isinstance(value, (list, tuple)):
                values.append(json.dumps(list(value)))
            else:
                values.append(value)

    placeholders = ", ".join(["?"] * len(columns))
    col_names = ", ".join(columns)

    conn = _get_db(db_path)
    try:
        conn.execute(
            f"INSERT INTO past_performances ({col_names}) VALUES ({placeholders})",
            values,
        )
        _audit(conn, "pp.add", f"Added past performance: {contract_name}",
               "past_performance", pp_id,
               {"agency": agency, "role": role})
        conn.commit()

        # Return the created record
        row = conn.execute(
            "SELECT * FROM past_performances WHERE id = ?", (pp_id,)
        ).fetchone()
        return _row_to_dict(row)
    finally:
        conn.close()


def get_performance(pp_id, db_path=None):
    """Get a single past performance record by ID.

    Args:
        pp_id: The past performance ID.
        db_path: Optional database path override.

    Returns:
        dict with record fields, or None if not found.
    """
    conn = _get_db(db_path)
    try:
        row = conn.execute(
            "SELECT * FROM past_performances WHERE id = ?", (pp_id,)
        ).fetchone()
        return _row_to_dict(row)
    finally:
        conn.close()


def list_performances(agency=None, rating=None, limit=20, db_path=None):
    """List past performance records with optional filters.

    Args:
        agency: Optional filter by agency name (case-insensitive LIKE match).
        rating: Optional filter by CPARS rating.
        limit: Maximum records to return (default 20).
        db_path: Optional database path override.

    Returns:
        list of dicts, each representing a past performance record.
    """
    conn = _get_db(db_path)
    try:
        conditions = ["is_active = 1"]
        params = []

        if agency:
            conditions.append("agency LIKE ?")
            params.append(f"%{agency}%")

        if rating:
            if rating not in VALID_RATINGS:
                raise ValueError(
                    f"Invalid rating '{rating}'. "
                    f"Must be one of: {', '.join(VALID_RATINGS)}"
                )
            conditions.append("cpars_rating = ?")
            params.append(rating)

        where = " AND ".join(conditions)
        params.append(limit)

        rows = conn.execute(
            f"SELECT * FROM past_performances WHERE {where} "
            f"ORDER BY updated_at DESC LIMIT ?",
            params,
        ).fetchall()
        return [_row_to_dict(r) for r in rows]
    finally:
        conn.close()


def search_relevant(query, naics_code=None, agency=None, limit=5,
                    target_value=None, db_path=None):
    """Search for relevant past performance using 5-dimension relevance scoring.

    Scoring dimensions:
        - scope_similarity (0.30): Term overlap between query and scope
        - agency_match (0.20): Whether the agency matches
        - size_proximity (0.15): Contract value similarity
        - recency (0.15): How recently the contract ended
        - rating_quality (0.20): CPARS rating quality

    Args:
        query: Search query describing target scope/requirements.
        naics_code: Optional NAICS code to boost matching records.
        agency: Optional target agency to boost matching records.
        limit: Maximum results to return (default 5).
        target_value: Optional target contract value for size comparison.
        db_path: Optional database path override.

    Returns:
        list of dicts with record fields plus 'relevance_score' and
        'score_breakdown' keys, sorted by relevance descending.
    """
    conn = _get_db(db_path)
    try:
        rows = conn.execute(
            "SELECT * FROM past_performances WHERE is_active = 1 "
            "ORDER BY updated_at DESC",
        ).fetchall()

        if not rows:
            return []

        query_tokens = _tokenize(query)
        scored = []

        for row in rows:
            record = _row_to_dict(row)

            # 1. Scope similarity (term overlap with query)
            scope_text = f"{record.get('scope_description', '')} " \
                         f"{record.get('technical_approach', '')} " \
                         f"{record.get('key_accomplishments', '')}"
            scope_tokens = _tokenize(scope_text)
            scope_score = _term_overlap_score(query_tokens, scope_tokens)

            # Boost if NAICS matches
            if naics_code and record.get("naics_code") == naics_code:
                scope_score = min(1.0, scope_score + 0.2)

            # 2. Agency match
            agency_score = 0.0
            if agency:
                record_agency = (record.get("agency") or "").lower()
                target_agency = agency.lower()
                if record_agency == target_agency:
                    agency_score = 1.0
                elif target_agency in record_agency or record_agency in target_agency:
                    agency_score = 0.7
                # Check sub_agency too
                sub = (record.get("sub_agency") or "").lower()
                if sub and (target_agency in sub or sub in target_agency):
                    agency_score = max(agency_score, 0.5)
            else:
                agency_score = 0.5  # Neutral when no target agency specified

            # 3. Size proximity
            size_score = _size_proximity_score(
                record.get("contract_value"), target_value
            )

            # 4. Recency
            rec_score = _recency_score(
                record.get("period_of_performance_end")
            )

            # 5. Rating quality
            rating = record.get("cpars_rating")
            rating_score = CPARS_RATING_SCORES.get(rating, 0.4)

            # Weighted combination
            breakdown = {
                "scope_similarity": round(scope_score, 4),
                "agency_match": round(agency_score, 4),
                "size_proximity": round(size_score, 4),
                "recency": round(rec_score, 4),
                "rating_quality": round(rating_score, 4),
            }

            total = sum(
                RELEVANCE_WEIGHTS[dim] * breakdown[dim]
                for dim in RELEVANCE_WEIGHTS
            )

            record["relevance_score"] = round(total, 4)
            record["score_breakdown"] = breakdown
            scored.append(record)

        # Sort by relevance score descending
        scored.sort(key=lambda x: x["relevance_score"], reverse=True)
        return scored[:limit]
    finally:
        conn.close()


def generate_narrative(pp_id, target_requirements=None, db_path=None):
    """Generate a tailored narrative for proposal inclusion.

    Produces a template-based draft that highlights the record's
    relevance to target requirements.

    Args:
        pp_id: The past performance ID.
        target_requirements: Optional comma-separated requirements
            to emphasize in the narrative.
        db_path: Optional database path override.

    Returns:
        dict with 'narrative' text and metadata.

    Raises:
        ValueError: If record not found.
    """
    conn = _get_db(db_path)
    try:
        row = conn.execute(
            "SELECT * FROM past_performances WHERE id = ? AND is_active = 1",
            (pp_id,),
        ).fetchone()
        if row is None:
            raise ValueError(f"Past performance not found or inactive: {pp_id}")

        record = _row_to_dict(row)

        # Build narrative sections
        sections = []

        # Header
        role_label = {
            "prime": "Prime Contractor",
            "subcontractor": "Subcontractor",
            "joint_venture": "Joint Venture Partner",
            "teaming": "Teaming Partner",
        }.get(record.get("role"), "Contractor")

        sections.append(
            f"## {record['contract_name']}\n\n"
            f"**Agency:** {record['agency']}"
            f"{(' / ' + record['sub_agency']) if record.get('sub_agency') else ''}\n"
            f"**Role:** {role_label}\n"
            f"**Contract Number:** {record.get('contract_number') or 'N/A'}\n"
            f"**Contract Value:** ${record.get('contract_value', 0):,.0f}\n"
            f"**Period of Performance:** "
            f"{record.get('period_of_performance_start', 'N/A')} to "
            f"{record.get('period_of_performance_end', 'N/A')}\n"
            f"**NAICS Code:** {record.get('naics_code') or 'N/A'}\n"
        )

        # Scope
        if record.get("scope_description"):
            sections.append(
                f"### Scope of Work\n\n{record['scope_description']}\n"
            )

        # Technical approach
        if record.get("technical_approach"):
            sections.append(
                f"### Technical Approach\n\n{record['technical_approach']}\n"
            )

        # Key accomplishments
        if record.get("key_accomplishments"):
            sections.append(
                f"### Key Accomplishments\n\n{record['key_accomplishments']}\n"
            )

        # Metrics
        if record.get("metrics_achieved"):
            sections.append(
                f"### Metrics Achieved\n\n{record['metrics_achieved']}\n"
            )

        # CPARS
        if record.get("cpars_rating"):
            rating_display = record["cpars_rating"].replace("_", " ").title()
            sections.append(
                f"### Contractor Performance Assessment\n\n"
                f"**Overall Rating:** {rating_display}\n"
            )
            if record.get("cpars_narrative"):
                sections.append(f"{record['cpars_narrative']}\n")

        # Relevance to target requirements
        if target_requirements:
            req_list = [r.strip() for r in target_requirements.split(",")
                        if r.strip()]
            if req_list:
                sections.append(
                    f"### Relevance to Current Requirement\n\n"
                    f"This past performance demonstrates direct experience in the "
                    f"following areas relevant to the current requirement:\n"
                )
                for req in req_list:
                    sections.append(f"- **{req}**")
                sections.append("")

        # Contact reference
        if record.get("contact_name"):
            sections.append(
                f"### Contract Reference\n\n"
                f"**Name:** {record['contact_name']}\n"
                f"**Title:** {record.get('contact_title') or 'N/A'}\n"
                f"**Email:** {record.get('contact_email') or 'N/A'}\n"
                f"**Phone:** {record.get('contact_phone') or 'N/A'}\n"
            )

        narrative = "\n".join(sections)

        _audit(conn, "pp.narrative",
               f"Generated narrative for: {record['contract_name']}",
               "past_performance", pp_id,
               {"target_requirements": target_requirements})
        conn.commit()

        return {
            "pp_id": pp_id,
            "contract_name": record["contract_name"],
            "narrative": narrative,
            "word_count": len(narrative.split()),
            "generated_at": _now(),
        }
    finally:
        conn.close()


def get_relevance_summary(db_path=None):
    """Get summary statistics for the past performance library.

    Returns counts by agency, CPARS rating distribution, and
    recency distribution.

    Args:
        db_path: Optional database path override.

    Returns:
        dict with summary statistics.
    """
    conn = _get_db(db_path)
    try:
        # Total active records
        total = conn.execute(
            "SELECT COUNT(*) as cnt FROM past_performances WHERE is_active = 1"
        ).fetchone()["cnt"]

        # By agency
        agency_rows = conn.execute(
            "SELECT agency, COUNT(*) as cnt FROM past_performances "
            "WHERE is_active = 1 GROUP BY agency ORDER BY cnt DESC"
        ).fetchall()
        by_agency = {r["agency"]: r["cnt"] for r in agency_rows}

        # By rating
        rating_rows = conn.execute(
            "SELECT cpars_rating, COUNT(*) as cnt FROM past_performances "
            "WHERE is_active = 1 AND cpars_rating IS NOT NULL "
            "GROUP BY cpars_rating ORDER BY cnt DESC"
        ).fetchall()
        by_rating = {r["cpars_rating"]: r["cnt"] for r in rating_rows}

        # By role
        role_rows = conn.execute(
            "SELECT role, COUNT(*) as cnt FROM past_performances "
            "WHERE is_active = 1 GROUP BY role ORDER BY cnt DESC"
        ).fetchall()
        by_role = {r["role"]: r["cnt"] for r in role_rows}

        # Recency: how many within 1yr, 3yr, 5yr, older
        now = datetime.now(timezone.utc)
        all_rows = conn.execute(
            "SELECT period_of_performance_end FROM past_performances "
            "WHERE is_active = 1"
        ).fetchall()

        recency = {"within_1yr": 0, "within_3yr": 0, "within_5yr": 0,
                    "older": 0, "no_date": 0}
        for r in all_rows:
            end = _parse_date(r["period_of_performance_end"])
            if end is None:
                recency["no_date"] += 1
            else:
                days = (now.replace(tzinfo=None) - end).days
                if days < 365:
                    recency["within_1yr"] += 1
                elif days < 1095:
                    recency["within_3yr"] += 1
                elif days < 1825:
                    recency["within_5yr"] += 1
                else:
                    recency["older"] += 1

        # Total contract value
        value_row = conn.execute(
            "SELECT SUM(contract_value) as total_value, "
            "AVG(contract_value) as avg_value "
            "FROM past_performances "
            "WHERE is_active = 1 AND contract_value IS NOT NULL"
        ).fetchone()

        return {
            "total_records": total,
            "by_agency": by_agency,
            "by_rating": by_rating,
            "by_role": by_role,
            "recency_distribution": recency,
            "total_contract_value": round(value_row["total_value"] or 0, 2),
            "average_contract_value": round(value_row["avg_value"] or 0, 2),
            "generated_at": _now(),
        }
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_parser():
    """Build the argument parser for the CLI."""
    parser = argparse.ArgumentParser(
        description="GovProposal Past Performance Manager",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  %(prog)s --add --contract-name 'Cloud Migration' --agency 'DoD' "
            "--scope 'Migrated 200+ apps...' --json\n"
            "  %(prog)s --search --query 'FedRAMP ATO cloud' --agency 'DHS' --json\n"
            "  %(prog)s --get --id PP-abc123def456 --json\n"
            "  %(prog)s --list --agency 'DoD' --rating exceptional --json\n"
            "  %(prog)s --narrative --id PP-abc123def456 --requirements 'cloud, FedRAMP'\n"
            "  %(prog)s --summary --json\n"
        ),
    )

    # Action group
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--add", action="store_true",
                        help="Add a past performance record")
    action.add_argument("--search", action="store_true",
                        help="Search with 5-dimension relevance scoring")
    action.add_argument("--get", action="store_true",
                        help="Get a record by ID")
    action.add_argument("--list", action="store_true",
                        help="List records with filters")
    action.add_argument("--narrative", action="store_true",
                        help="Generate proposal narrative")
    action.add_argument("--summary", action="store_true",
                        help="Show library summary statistics")

    # Record fields
    parser.add_argument("--id", help="Past performance ID")
    parser.add_argument("--contract-name", help="Contract name")
    parser.add_argument("--contract-number", help="Contract number")
    parser.add_argument("--agency", help="Contracting agency")
    parser.add_argument("--sub-agency", help="Sub-agency")
    parser.add_argument("--scope", help="Scope description")
    parser.add_argument("--role", choices=VALID_ROLES, default="prime",
                        help="Role on contract (default: prime)")
    parser.add_argument("--contract-type", help="Contract type (e.g. FFP, T&M)")
    parser.add_argument("--contract-value", type=float, help="Contract value ($)")
    parser.add_argument("--pop-start", help="Period of performance start (YYYY-MM-DD)")
    parser.add_argument("--pop-end", help="Period of performance end (YYYY-MM-DD)")
    parser.add_argument("--naics", help="NAICS code")
    parser.add_argument("--rating", choices=VALID_RATINGS, help="CPARS rating")
    parser.add_argument("--technical-approach", help="Technical approach description")
    parser.add_argument("--accomplishments", help="Key accomplishments")
    parser.add_argument("--metrics", help="Metrics achieved")

    # Search/filter args
    parser.add_argument("--query", help="Search query")
    parser.add_argument("--requirements", help="Target requirements for narrative")
    parser.add_argument("--target-value", type=float,
                        help="Target contract value for size matching")
    parser.add_argument("--limit", type=int, default=20,
                        help="Max results (default: 20)")

    # Output
    parser.add_argument("--json", action="store_true", help="JSON output")
    parser.add_argument("--db-path", help="Override database path")

    return parser


def main():
    """CLI entry point."""
    parser = _build_parser()
    args = parser.parse_args()
    db = args.db_path

    try:
        if args.add:
            if not args.contract_name:
                parser.error("--add requires --contract-name")
            if not args.agency:
                parser.error("--add requires --agency")
            if not args.scope:
                parser.error("--add requires --scope")

            kwargs = {}
            if args.contract_number:
                kwargs["contract_number"] = args.contract_number
            if args.sub_agency:
                kwargs["sub_agency"] = args.sub_agency
            if args.contract_type:
                kwargs["contract_type"] = args.contract_type
            if args.contract_value is not None:
                kwargs["contract_value"] = args.contract_value
            if args.pop_start:
                kwargs["period_of_performance_start"] = args.pop_start
            if args.pop_end:
                kwargs["period_of_performance_end"] = args.pop_end
            if args.naics:
                kwargs["naics_code"] = args.naics
            if args.rating:
                kwargs["cpars_rating"] = args.rating
            if args.technical_approach:
                kwargs["technical_approach"] = args.technical_approach
            if args.accomplishments:
                kwargs["key_accomplishments"] = args.accomplishments
            if args.metrics:
                kwargs["metrics_achieved"] = args.metrics

            result = add_performance(
                contract_name=args.contract_name,
                agency=args.agency,
                scope_description=args.scope,
                role=args.role,
                db_path=db,
                **kwargs,
            )

        elif args.search:
            if not args.query:
                parser.error("--search requires --query")
            result = search_relevant(
                query=args.query,
                naics_code=args.naics,
                agency=args.agency,
                limit=args.limit,
                target_value=args.target_value,
                db_path=db,
            )

        elif args.get:
            if not args.id:
                parser.error("--get requires --id")
            result = get_performance(args.id, db_path=db)
            if result is None:
                result = {"error": f"Record not found: {args.id}"}

        elif args.list:
            result = list_performances(
                agency=args.agency,
                rating=args.rating,
                limit=args.limit,
                db_path=db,
            )

        elif args.narrative:
            if not args.id:
                parser.error("--narrative requires --id")
            result = generate_narrative(
                pp_id=args.id,
                target_requirements=args.requirements,
                db_path=db,
            )

        elif args.summary:
            result = get_relevance_summary(db_path=db)

        # Output
        if args.json:
            print(json.dumps(result, indent=2, default=str))
        else:
            if isinstance(result, list):
                print(f"Found {len(result)} records:")
                for i, rec in enumerate(result, 1):
                    score = rec.get("relevance_score", "")
                    score_str = f" (relevance: {score:.4f})" if score else ""
                    print(f"  {i}. [{rec.get('id')}] {rec.get('contract_name')} "
                          f"— {rec.get('agency')}{score_str}")
                    breakdown = rec.get("score_breakdown")
                    if breakdown:
                        parts = [f"{k}={v:.2f}" for k, v in breakdown.items()]
                        print(f"     {', '.join(parts)}")
            elif isinstance(result, dict):
                if "narrative" in result:
                    print(result["narrative"])
                else:
                    for key, value in result.items():
                        if isinstance(value, dict):
                            print(f"  {key}:")
                            for k2, v2 in value.items():
                                print(f"    {k2}: {v2}")
                        else:
                            print(f"  {key}: {value}")
            else:
                print(result)

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
    import argparse
    main()
