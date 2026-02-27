#!/usr/bin/env python3
# CUI // SP-PROPIN
# Controlled by: GovProposal Portal
# CUI Category: PROPIN
# Distribution: D
# POC: GovProposal System Administrator
"""Post-submission debrief capture and knowledge management.

Records win/loss debrief data from government evaluator feedback,
extracts structured lessons learned, and updates the knowledge base
to improve future proposal quality.

Usage:
    python tools/learning/debrief_capture.py --capture --proposal-id PROP-001 --result win --json
    python tools/learning/debrief_capture.py --get --proposal-id PROP-001 --json
    python tools/learning/debrief_capture.py --list [--result win] [--limit 20] --json
    python tools/learning/debrief_capture.py --lessons --debrief-id debrief-abc123 --json
    python tools/learning/debrief_capture.py --update-kb --debrief-id debrief-abc123 --json
"""

import json
import os
import secrets
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent
DB_PATH = Path(os.environ.get(
    "GOVPROPOSAL_DB_PATH", str(BASE_DIR / "data" / "govproposal.db")
))

# Optional imports
try:
    import yaml  # noqa: F401
except ImportError:
    yaml = None

try:
    import requests  # noqa: F401
except ImportError:
    requests = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _debrief_id():
    """Generate a debrief ID: debrief- followed by 12 hex characters."""
    return "debrief-" + secrets.token_hex(6)


def _pattern_id():
    """Generate a win/loss pattern ID."""
    return "WLP-" + secrets.token_hex(6)


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


def _audit(conn, event_type, action, entity_type=None, entity_id=None,
           details=None):
    """Write an append-only audit trail record.

    Args:
        conn: Active database connection.
        event_type: Category of event (e.g. 'debrief.capture').
        action: Human-readable description of the action.
        entity_type: Type of entity affected.
        entity_id: ID of the affected entity.
        details: Optional JSON-serializable details dict.
    """
    conn.execute(
        "INSERT INTO audit_trail (event_type, actor, action, entity_type, "
        "entity_id, details, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            event_type,
            "debrief_capture",
            action,
            entity_type,
            entity_id,
            json.dumps(details) if details else None,
            _now(),
        ),
    )


def _row_to_dict(row):
    """Convert a sqlite3.Row to a plain dict.

    Args:
        row: sqlite3.Row object.

    Returns:
        dict with column names as keys, or None if row is None.
    """
    if row is None:
        return None
    return dict(row)


def _parse_json_field(value):
    """Safely parse a JSON string field.

    Args:
        value: String that may be JSON, or None.

    Returns:
        Parsed JSON value, original string, or None.
    """
    if value is None:
        return None
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return value


# ---------------------------------------------------------------------------
# Core Functions
# ---------------------------------------------------------------------------

def capture_debrief(proposal_id, result, db_path=None, **kwargs):
    """Record debrief data from post-submission evaluator feedback.

    Stores evaluator feedback in the debriefs table, updates the opportunity
    status to 'awarded' or 'lost', and updates the proposal result field.

    Args:
        proposal_id: The proposal ID to record the debrief against.
        result: 'win' or 'loss'.
        db_path: Optional database path override.
        **kwargs: Additional debrief fields:
            evaluator_strengths: Text of evaluator-identified strengths.
            evaluator_weaknesses: Text of evaluator-identified weaknesses.
            evaluator_deficiencies: Text of evaluator-identified deficiencies.
            evaluated_price: Our evaluated price amount.
            winning_price: The winning bid price amount.
            winning_contractor: Name of the winning contractor.
            lessons_learned: Free-text lessons learned narrative.
            debrief_date: Date of debrief (ISO format).
            captured_by: Person capturing the debrief.

    Returns:
        dict with the created debrief record.

    Raises:
        ValueError: If result is not 'win' or 'loss', or proposal not found.
    """
    if result not in ("win", "loss"):
        raise ValueError(f"Result must be 'win' or 'loss', got: {result}")

    conn = _get_db(db_path)
    try:
        # Verify proposal exists and get opportunity_id
        prop_row = conn.execute(
            "SELECT id, opportunity_id FROM proposals WHERE id = ?",
            (proposal_id,),
        ).fetchone()
        if prop_row is None:
            raise ValueError(f"Proposal not found: {proposal_id}")

        opportunity_id = prop_row["opportunity_id"]
        debrief = _debrief_id()
        now = _now()

        conn.execute(
            "INSERT INTO debriefs "
            "(id, proposal_id, opportunity_id, result, evaluator_strengths, "
            "evaluator_weaknesses, evaluator_deficiencies, evaluated_price, "
            "winning_price, winning_contractor, lessons_learned, debrief_date, "
            "captured_by, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                debrief,
                proposal_id,
                opportunity_id,
                result,
                kwargs.get("evaluator_strengths"),
                kwargs.get("evaluator_weaknesses"),
                kwargs.get("evaluator_deficiencies"),
                kwargs.get("evaluated_price"),
                kwargs.get("winning_price"),
                kwargs.get("winning_contractor"),
                kwargs.get("lessons_learned"),
                kwargs.get("debrief_date", now[:10]),
                kwargs.get("captured_by"),
                now,
            ),
        )

        # Update opportunity status
        new_status = "awarded" if result == "win" else "lost"
        conn.execute(
            "UPDATE opportunities SET status = ?, updated_at = ? "
            "WHERE id = ?",
            (new_status, now, opportunity_id),
        )

        # Update proposal result
        conn.execute(
            "UPDATE proposals SET result = ?, updated_at = ? WHERE id = ?",
            (result, now, proposal_id),
        )

        _audit(
            conn, "debrief.capture",
            f"Captured {result} debrief for proposal {proposal_id}",
            "debrief", debrief,
            {"proposal_id": proposal_id, "result": result},
        )
        conn.commit()

        return {
            "id": debrief,
            "proposal_id": proposal_id,
            "opportunity_id": opportunity_id,
            "result": result,
            "evaluator_strengths": kwargs.get("evaluator_strengths"),
            "evaluator_weaknesses": kwargs.get("evaluator_weaknesses"),
            "evaluator_deficiencies": kwargs.get("evaluator_deficiencies"),
            "evaluated_price": kwargs.get("evaluated_price"),
            "winning_price": kwargs.get("winning_price"),
            "winning_contractor": kwargs.get("winning_contractor"),
            "lessons_learned": kwargs.get("lessons_learned"),
            "debrief_date": kwargs.get("debrief_date", now[:10]),
            "captured_by": kwargs.get("captured_by"),
            "created_at": now,
        }
    finally:
        conn.close()


def get_debrief(proposal_id=None, debrief_id=None, db_path=None):
    """Retrieve a debrief by proposal ID or debrief ID.

    Args:
        proposal_id: Look up debrief by proposal ID.
        debrief_id: Look up debrief by debrief ID.
        db_path: Optional database path override.

    Returns:
        dict with debrief fields, or None if not found.

    Raises:
        ValueError: If neither proposal_id nor debrief_id is provided.
    """
    if not proposal_id and not debrief_id:
        raise ValueError("Must provide either --proposal-id or --debrief-id")

    conn = _get_db(db_path)
    try:
        if debrief_id:
            row = conn.execute(
                "SELECT * FROM debriefs WHERE id = ?", (debrief_id,)
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT * FROM debriefs WHERE proposal_id = ? "
                "ORDER BY created_at DESC LIMIT 1",
                (proposal_id,),
            ).fetchone()
        return _row_to_dict(row)
    finally:
        conn.close()


def list_debriefs(result=None, limit=20, db_path=None):
    """List debriefs with optional win/loss filter.

    Args:
        result: Optional filter: 'win' or 'loss'.
        limit: Maximum number of debriefs to return (default 20).
        db_path: Optional database path override.

    Returns:
        list of dicts, each representing a debrief record.
    """
    conn = _get_db(db_path)
    try:
        if result:
            rows = conn.execute(
                "SELECT d.*, p.title AS proposal_title, o.agency "
                "FROM debriefs d "
                "LEFT JOIN proposals p ON d.proposal_id = p.id "
                "LEFT JOIN opportunities o ON d.opportunity_id = o.id "
                "WHERE d.result = ? "
                "ORDER BY d.created_at DESC LIMIT ?",
                (result, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT d.*, p.title AS proposal_title, o.agency "
                "FROM debriefs d "
                "LEFT JOIN proposals p ON d.proposal_id = p.id "
                "LEFT JOIN opportunities o ON d.opportunity_id = o.id "
                "ORDER BY d.created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [_row_to_dict(r) for r in rows]
    finally:
        conn.close()


def extract_lessons(debrief_id, db_path=None):
    """Parse lessons learned from a debrief into structured patterns.

    Identifies four pattern categories from the debrief data:
    - what_worked: Strengths that contributed to positive evaluation.
    - what_failed: Weaknesses and deficiencies that hurt the evaluation.
    - pricing_insight: Pricing-related observations from win/loss data.
    - process_improvement: Process and approach recommendations.

    Stores extracted patterns in the win_loss_patterns table.

    Args:
        debrief_id: The debrief ID to extract lessons from.
        db_path: Optional database path override.

    Returns:
        dict with extracted patterns grouped by category.

    Raises:
        ValueError: If debrief not found.
    """
    conn = _get_db(db_path)
    try:
        row = conn.execute(
            "SELECT * FROM debriefs WHERE id = ?", (debrief_id,)
        ).fetchone()
        if row is None:
            raise ValueError(f"Debrief not found: {debrief_id}")

        debrief = _row_to_dict(row)
        patterns = {
            "what_worked": [],
            "what_failed": [],
            "pricing_insight": [],
            "process_improvement": [],
        }
        now = _now()

        # Extract what worked from evaluator strengths
        if debrief.get("evaluator_strengths"):
            pattern_id = _pattern_id()
            desc = debrief["evaluator_strengths"]
            patterns["what_worked"].append(desc)
            conn.execute(
                "INSERT INTO win_loss_patterns "
                "(id, pattern_type, pattern_description, associated_outcomes, "
                "confidence, sample_size, recommendation, analyzed_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    pattern_id, "approach", desc,
                    json.dumps({"result": debrief["result"],
                                "debrief_id": debrief_id}),
                    1.0, 1,
                    "Replicate this approach in future proposals"
                    if debrief["result"] == "win"
                    else "Strengthen this area despite evaluator recognition",
                    now,
                ),
            )

        # Extract what failed from weaknesses and deficiencies
        for field in ("evaluator_weaknesses", "evaluator_deficiencies"):
            if debrief.get(field):
                pattern_id = _pattern_id()
                desc = debrief[field]
                patterns["what_failed"].append(desc)
                conn.execute(
                    "INSERT INTO win_loss_patterns "
                    "(id, pattern_type, pattern_description, "
                    "associated_outcomes, confidence, sample_size, "
                    "recommendation, analyzed_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        pattern_id, "approach", desc,
                        json.dumps({"result": debrief["result"],
                                    "debrief_id": debrief_id,
                                    "source": field}),
                        1.0, 1,
                        f"Address {field.replace('evaluator_', '')} "
                        f"in future proposals",
                        now,
                    ),
                )

        # Extract pricing insight
        evaluated = debrief.get("evaluated_price")
        winning = debrief.get("winning_price")
        if evaluated or winning:
            pattern_id = _pattern_id()
            parts = []
            if evaluated:
                parts.append(f"Our evaluated price: ${evaluated:,.2f}")
            if winning:
                parts.append(f"Winning price: ${winning:,.2f}")
            if evaluated and winning and winning > 0:
                ratio = evaluated / winning
                parts.append(f"Price ratio (ours/winner): {ratio:.2f}")
            desc = "; ".join(parts)
            patterns["pricing_insight"].append(desc)
            conn.execute(
                "INSERT INTO win_loss_patterns "
                "(id, pattern_type, pattern_description, "
                "associated_outcomes, confidence, sample_size, "
                "recommendation, analyzed_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    pattern_id, "pricing", desc,
                    json.dumps({"result": debrief["result"],
                                "debrief_id": debrief_id,
                                "evaluated_price": evaluated,
                                "winning_price": winning}),
                    1.0, 1,
                    "Adjust pricing strategy based on competitive data",
                    now,
                ),
            )

        # Extract process improvements from lessons learned
        if debrief.get("lessons_learned"):
            pattern_id = _pattern_id()
            desc = debrief["lessons_learned"]
            patterns["process_improvement"].append(desc)
            conn.execute(
                "INSERT INTO win_loss_patterns "
                "(id, pattern_type, pattern_description, "
                "associated_outcomes, confidence, sample_size, "
                "recommendation, analyzed_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    pattern_id, "approach", desc,
                    json.dumps({"result": debrief["result"],
                                "debrief_id": debrief_id,
                                "source": "lessons_learned"}),
                    1.0, 1,
                    "Incorporate lesson into process checklist",
                    now,
                ),
            )

        _audit(
            conn, "debrief.lessons",
            f"Extracted lessons from debrief {debrief_id}",
            "debrief", debrief_id,
            {"pattern_count": sum(len(v) for v in patterns.values())},
        )
        conn.commit()

        return {
            "debrief_id": debrief_id,
            "result": debrief["result"],
            "patterns": patterns,
            "total_patterns": sum(len(v) for v in patterns.values()),
            "extracted_at": now,
        }
    finally:
        conn.close()


def update_kb_from_debrief(debrief_id, db_path=None):
    """Update knowledge base entries based on debrief results.

    If win: boosts quality_score and win_rate of KB entries used in the
    winning proposal. If loss: flags weak content for revision by
    reducing quality_score.

    Args:
        debrief_id: The debrief ID to process.
        db_path: Optional database path override.

    Returns:
        dict with summary of KB updates made.

    Raises:
        ValueError: If debrief not found.
    """
    conn = _get_db(db_path)
    try:
        row = conn.execute(
            "SELECT * FROM debriefs WHERE id = ?", (debrief_id,)
        ).fetchone()
        if row is None:
            raise ValueError(f"Debrief not found: {debrief_id}")

        debrief = _row_to_dict(row)
        proposal_id = debrief["proposal_id"]
        result = debrief["result"]
        now = _now()
        updates = {"boosted": [], "flagged": [], "unchanged": []}

        # Find KB entries referenced in proposal sections
        sections = conn.execute(
            "SELECT id, kb_sources FROM proposal_sections "
            "WHERE proposal_id = ? AND kb_sources IS NOT NULL",
            (proposal_id,),
        ).fetchall()

        kb_entry_ids = set()
        for section in sections:
            sources = _parse_json_field(section["kb_sources"])
            if isinstance(sources, list):
                kb_entry_ids.update(sources)
            elif isinstance(sources, str) and sources:
                kb_entry_ids.add(sources)

        for kb_id in kb_entry_ids:
            kb_row = conn.execute(
                "SELECT id, quality_score, win_rate, usage_count "
                "FROM kb_entries WHERE id = ? AND is_active = 1",
                (kb_id,),
            ).fetchone()
            if kb_row is None:
                updates["unchanged"].append(kb_id)
                continue

            current_quality = kb_row["quality_score"] or 0.5
            current_win_rate = kb_row["win_rate"] or 0.0
            usage_count = kb_row["usage_count"] or 1

            if result == "win":
                # Boost quality score (capped at 1.0)
                new_quality = min(1.0, current_quality + 0.1)
                # Update win rate as running average
                new_win_rate = (
                    (current_win_rate * (usage_count - 1) + 1.0)
                    / usage_count
                )
                updates["boosted"].append(kb_id)
            else:
                # Reduce quality score (floored at 0.0)
                new_quality = max(0.0, current_quality - 0.05)
                # Update win rate as running average
                new_win_rate = (
                    (current_win_rate * (usage_count - 1))
                    / usage_count
                )
                updates["flagged"].append(kb_id)

            conn.execute(
                "UPDATE kb_entries SET quality_score = ?, win_rate = ?, "
                "updated_at = ? WHERE id = ?",
                (round(new_quality, 3), round(new_win_rate, 3), now, kb_id),
            )

        # Record what updates were made in the debrief
        conn.execute(
            "UPDATE debriefs SET kb_updates_made = ? WHERE id = ?",
            (json.dumps(updates), debrief_id),
        )

        _audit(
            conn, "debrief.kb_update",
            f"Updated KB from {result} debrief {debrief_id}",
            "debrief", debrief_id,
            {
                "boosted": len(updates["boosted"]),
                "flagged": len(updates["flagged"]),
                "unchanged": len(updates["unchanged"]),
            },
        )
        conn.commit()

        return {
            "debrief_id": debrief_id,
            "result": result,
            "proposal_id": proposal_id,
            "kb_entries_boosted": updates["boosted"],
            "kb_entries_flagged": updates["flagged"],
            "kb_entries_unchanged": updates["unchanged"],
            "total_updated": len(updates["boosted"]) + len(updates["flagged"]),
            "updated_at": now,
        }
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_parser():
    """Build the argument parser for the CLI."""
    parser = argparse.ArgumentParser(
        description="GovProposal Post-Submission Debrief Capture",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  %(prog)s --capture --proposal-id PROP-001 --result win --json\n"
            "  %(prog)s --get --proposal-id PROP-001 --json\n"
            "  %(prog)s --list --result loss --limit 10 --json\n"
            "  %(prog)s --lessons --debrief-id debrief-abc123 --json\n"
            "  %(prog)s --update-kb --debrief-id debrief-abc123 --json\n"
        ),
    )

    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--capture", action="store_true",
                        help="Capture a new debrief")
    action.add_argument("--get", action="store_true",
                        help="Retrieve a debrief")
    action.add_argument("--list", action="store_true",
                        help="List debriefs")
    action.add_argument("--lessons", action="store_true",
                        help="Extract lessons from a debrief")
    action.add_argument("--update-kb", action="store_true",
                        help="Update KB from debrief results")

    parser.add_argument("--proposal-id", help="Proposal ID")
    parser.add_argument("--debrief-id", help="Debrief ID")
    parser.add_argument("--result", choices=("win", "loss"),
                        help="Win or loss result")
    parser.add_argument("--evaluator-strengths",
                        help="Evaluator-identified strengths")
    parser.add_argument("--evaluator-weaknesses",
                        help="Evaluator-identified weaknesses")
    parser.add_argument("--evaluator-deficiencies",
                        help="Evaluator-identified deficiencies")
    parser.add_argument("--evaluated-price", type=float,
                        help="Our evaluated price")
    parser.add_argument("--winning-price", type=float,
                        help="Winning bid price")
    parser.add_argument("--winning-contractor",
                        help="Name of the winning contractor")
    parser.add_argument("--lessons-learned",
                        help="Free-text lessons learned")
    parser.add_argument("--limit", type=int, default=20,
                        help="Max entries for --list (default: 20)")
    parser.add_argument("--json", action="store_true", help="JSON output")
    parser.add_argument("--db-path", help="Override database path")

    return parser


def main():
    """CLI entry point."""
    parser = _build_parser()
    args = parser.parse_args()
    db = args.db_path

    try:
        if args.capture:
            if not args.proposal_id:
                parser.error("--capture requires --proposal-id")
            if not args.result:
                parser.error("--capture requires --result")
            kwargs = {}
            if args.evaluator_strengths:
                kwargs["evaluator_strengths"] = args.evaluator_strengths
            if args.evaluator_weaknesses:
                kwargs["evaluator_weaknesses"] = args.evaluator_weaknesses
            if args.evaluator_deficiencies:
                kwargs["evaluator_deficiencies"] = args.evaluator_deficiencies
            if args.evaluated_price is not None:
                kwargs["evaluated_price"] = args.evaluated_price
            if args.winning_price is not None:
                kwargs["winning_price"] = args.winning_price
            if args.winning_contractor:
                kwargs["winning_contractor"] = args.winning_contractor
            if args.lessons_learned:
                kwargs["lessons_learned"] = args.lessons_learned
            result = capture_debrief(
                proposal_id=args.proposal_id,
                result=args.result,
                db_path=db,
                **kwargs,
            )

        elif args.get:
            result = get_debrief(
                proposal_id=args.proposal_id,
                debrief_id=args.debrief_id,
                db_path=db,
            )
            if result is None:
                result = {"error": "Debrief not found"}

        elif args.list:
            result = list_debriefs(
                result=args.result,
                limit=args.limit,
                db_path=db,
            )

        elif args.lessons:
            if not args.debrief_id:
                parser.error("--lessons requires --debrief-id")
            result = extract_lessons(args.debrief_id, db_path=db)

        elif args.update_kb:
            if not args.debrief_id:
                parser.error("--update-kb requires --debrief-id")
            result = update_kb_from_debrief(args.debrief_id, db_path=db)

        # Output
        if args.json:
            print(json.dumps(result, indent=2, default=str))
        else:
            if isinstance(result, list):
                print(f"Found {len(result)} debriefs:")
                for d in result:
                    print(f"  [{d.get('id')}] {d.get('result')}: "
                          f"{d.get('proposal_title', d.get('proposal_id'))}")
            elif isinstance(result, dict):
                for key, value in result.items():
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
    import argparse
    main()
