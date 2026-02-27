#!/usr/bin/env python3
# CUI // SP-PROPIN
# Controlled by: GovProposal Portal
# CUI Category: PROPIN
# Distribution: D
# POC: GovProposal System Administrator
"""Win/loss pattern analysis across all debriefs.

Analyzes historical debrief data to identify recurring patterns in
wins and losses, calculates win rates by agency and NAICS, extracts
pricing insights, and generates actionable recommendations for
future proposals.

Usage:
    python tools/learning/win_loss_analyzer.py --analyze --json
    python tools/learning/win_loss_analyzer.py --win-rate [--agency "DoD"] [--naics 541512] --json
    python tools/learning/win_loss_analyzer.py --top-themes [--limit 10] --json
    python tools/learning/win_loss_analyzer.py --pricing [--naics 541512] [--agency "DoD"] --json
    python tools/learning/win_loss_analyzer.py --recommend [--opp-id OPP-001] --json
    python tools/learning/win_loss_analyzer.py --report --json
"""

import json
import os
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
        event_type: Category of event.
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
            "win_loss_analyzer",
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


def _safe_divide(numerator, denominator, default=0.0):
    """Safely divide, returning default if denominator is zero."""
    if not denominator:
        return default
    return numerator / denominator


# ---------------------------------------------------------------------------
# Core Functions
# ---------------------------------------------------------------------------

def analyze_patterns(db_path=None):
    """Analyze all debriefs to identify recurring win/loss patterns.

    Groups patterns by: win_theme effectiveness, approach patterns,
    pricing patterns, teaming patterns, and personnel patterns.
    For each pattern, calculates confidence based on sample size
    and extracts a recommendation. Stores results in win_loss_patterns.

    Args:
        db_path: Optional database path override.

    Returns:
        dict with pattern analysis grouped by type.
    """
    conn = _get_db(db_path)
    try:
        debriefs = conn.execute(
            "SELECT d.*, o.agency, o.naics_code, o.set_aside_type "
            "FROM debriefs d "
            "LEFT JOIN opportunities o ON d.opportunity_id = o.id "
            "ORDER BY d.created_at DESC"
        ).fetchall()

        total = len(debriefs)
        if total == 0:
            return {
                "status": "no_data",
                "message": "No debriefs found for analysis",
                "patterns": {},
            }

        now = _now()
        wins = [_row_to_dict(d) for d in debriefs if d["result"] == "win"]
        losses = [_row_to_dict(d) for d in debriefs if d["result"] == "loss"]
        patterns = defaultdict(list)

        # --- Win theme effectiveness ---
        theme_wins = defaultdict(int)
        theme_total = defaultdict(int)
        for d in debriefs:
            prop_row = conn.execute(
                "SELECT win_themes FROM proposals WHERE id = ?",
                (d["proposal_id"],),
            ).fetchone()
            if prop_row and prop_row["win_themes"]:
                themes = _parse_json_field(prop_row["win_themes"])
                if isinstance(themes, list):
                    for theme in themes:
                        theme_total[theme] += 1
                        if d["result"] == "win":
                            theme_wins[theme] += 1

        for theme, count in theme_total.items():
            win_count = theme_wins.get(theme, 0)
            rate = _safe_divide(win_count, count)
            confidence = min(1.0, count / max(total, 1))
            pid = _pattern_id()
            rec = (
                f"Strong theme (win rate {rate:.0%}), reuse in similar bids"
                if rate >= 0.5
                else f"Weak theme (win rate {rate:.0%}), revise or retire"
            )
            patterns["win_theme"].append({
                "id": pid,
                "description": theme,
                "win_rate": round(rate, 3),
                "sample_size": count,
                "confidence": round(confidence, 3),
                "recommendation": rec,
            })
            conn.execute(
                "INSERT INTO win_loss_patterns "
                "(id, pattern_type, pattern_description, associated_outcomes, "
                "confidence, sample_size, recommendation, analyzed_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (pid, "win_theme", theme,
                 json.dumps({"win_count": win_count, "total": count}),
                 round(confidence, 3), count, rec, now),
            )

        # --- Approach patterns (from evaluator strengths/weaknesses) ---
        strength_counts = defaultdict(lambda: {"wins": 0, "losses": 0})
        for d in debriefs:
            if d["evaluator_strengths"]:
                key = d["evaluator_strengths"][:120]
                if d["result"] == "win":
                    strength_counts[key]["wins"] += 1
                else:
                    strength_counts[key]["losses"] += 1

        for desc, counts in strength_counts.items():
            sample = counts["wins"] + counts["losses"]
            rate = _safe_divide(counts["wins"], sample)
            confidence = min(1.0, sample / max(total, 1))
            pid = _pattern_id()
            rec = (
                "Consistently recognized strength, maintain and highlight"
                if rate >= 0.6
                else "Mixed results, refine approach"
            )
            patterns["approach"].append({
                "id": pid,
                "description": desc,
                "win_rate": round(rate, 3),
                "sample_size": sample,
                "confidence": round(confidence, 3),
                "recommendation": rec,
            })
            conn.execute(
                "INSERT INTO win_loss_patterns "
                "(id, pattern_type, pattern_description, associated_outcomes, "
                "confidence, sample_size, recommendation, analyzed_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (pid, "approach", desc,
                 json.dumps(counts),
                 round(confidence, 3), sample, rec, now),
            )

        # --- Pricing patterns ---
        pricing_data = []
        for d in debriefs:
            if d["evaluated_price"] and d["winning_price"]:
                pricing_data.append({
                    "result": d["result"],
                    "our_price": d["evaluated_price"],
                    "win_price": d["winning_price"],
                    "ratio": _safe_divide(
                        d["evaluated_price"], d["winning_price"], None
                    ),
                    "agency": d["agency"] if "agency" in d.keys() else None,
                })

        if pricing_data:
            ratios = [p["ratio"] for p in pricing_data if p["ratio"]]
            avg_ratio = _safe_divide(sum(ratios), len(ratios))
            win_ratios = [
                p["ratio"] for p in pricing_data
                if p["result"] == "win" and p["ratio"]
            ]
            loss_ratios = [
                p["ratio"] for p in pricing_data
                if p["result"] == "loss" and p["ratio"]
            ]
            pid = _pattern_id()
            desc = (
                f"Average price ratio (ours/winner): {avg_ratio:.2f}; "
                f"Win avg: {_safe_divide(sum(win_ratios), len(win_ratios)):.2f}; "
                f"Loss avg: {_safe_divide(sum(loss_ratios), len(loss_ratios)):.2f}"
            )
            rec = (
                "Price within 5% of estimated winning price"
                if avg_ratio <= 1.05
                else "Pricing tends to be above market; review rate structure"
            )
            patterns["pricing"].append({
                "id": pid,
                "description": desc,
                "average_ratio": round(avg_ratio, 3),
                "sample_size": len(pricing_data),
                "confidence": round(
                    min(1.0, len(pricing_data) / max(total, 1)), 3
                ),
                "recommendation": rec,
            })
            conn.execute(
                "INSERT INTO win_loss_patterns "
                "(id, pattern_type, pattern_description, associated_outcomes, "
                "confidence, sample_size, recommendation, analyzed_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (pid, "pricing", desc,
                 json.dumps({"avg_ratio": round(avg_ratio, 3),
                             "data_points": len(pricing_data)}),
                 round(min(1.0, len(pricing_data) / max(total, 1)), 3),
                 len(pricing_data), rec, now),
            )

        # --- Teaming patterns ---
        teaming_outcomes = defaultdict(lambda: {"wins": 0, "losses": 0})
        for d in debriefs:
            if d["winning_contractor"]:
                key = d["winning_contractor"]
                if d["result"] == "win":
                    teaming_outcomes[key]["wins"] += 1
                else:
                    teaming_outcomes[key]["losses"] += 1

        for contractor, counts in teaming_outcomes.items():
            if counts["losses"] > 0:
                pid = _pattern_id()
                desc = (
                    f"Frequent competitor: {contractor} "
                    f"(beat us {counts['losses']} time(s))"
                )
                patterns["teaming"].append({
                    "id": pid,
                    "description": desc,
                    "competitor": contractor,
                    "losses_to": counts["losses"],
                    "wins_against": counts["wins"],
                })
                conn.execute(
                    "INSERT INTO win_loss_patterns "
                    "(id, pattern_type, pattern_description, "
                    "associated_outcomes, confidence, sample_size, "
                    "recommendation, analyzed_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (pid, "teaming", desc,
                     json.dumps(counts),
                     round(min(1.0, (counts["wins"] + counts["losses"])
                               / max(total, 1)), 3),
                     counts["wins"] + counts["losses"],
                     f"Study {contractor} approach; consider teaming or "
                     f"differentiating more sharply",
                     now),
                )

        # --- Personnel patterns (from win themes containing personnel) ---
        personnel_mentions = {"wins": 0, "losses": 0}
        for d in debriefs:
            if d["evaluator_strengths"] and "personnel" in (
                d["evaluator_strengths"] or ""
            ).lower():
                if d["result"] == "win":
                    personnel_mentions["wins"] += 1
                else:
                    personnel_mentions["losses"] += 1

        if personnel_mentions["wins"] + personnel_mentions["losses"] > 0:
            pid = _pattern_id()
            p_total = personnel_mentions["wins"] + personnel_mentions["losses"]
            p_rate = _safe_divide(personnel_mentions["wins"], p_total)
            desc = (
                f"Personnel mentioned in evaluator strengths: "
                f"{p_total} time(s), win rate {p_rate:.0%}"
            )
            patterns["personnel"].append({
                "id": pid,
                "description": desc,
                "win_rate": round(p_rate, 3),
                "sample_size": p_total,
            })
            conn.execute(
                "INSERT INTO win_loss_patterns "
                "(id, pattern_type, pattern_description, "
                "associated_outcomes, confidence, sample_size, "
                "recommendation, analyzed_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (pid, "personnel", desc,
                 json.dumps(personnel_mentions),
                 round(min(1.0, p_total / max(total, 1)), 3),
                 p_total,
                 "Strong personnel drive wins; invest in key staff retention",
                 now),
            )

        _audit(conn, "analysis.patterns", "Analyzed win/loss patterns",
               details={"total_debriefs": total,
                        "total_patterns": sum(
                            len(v) for v in patterns.values())})
        conn.commit()

        return {
            "total_debriefs": total,
            "wins": len(wins),
            "losses": len(losses),
            "overall_win_rate": round(
                _safe_divide(len(wins), total), 3
            ),
            "patterns": {k: v for k, v in patterns.items()},
            "total_patterns": sum(len(v) for v in patterns.values()),
            "analyzed_at": now,
        }
    finally:
        conn.close()


def get_win_rate(agency=None, naics=None, time_period=None, db_path=None):
    """Calculate win rate statistics with optional filters.

    Args:
        agency: Optional agency name filter.
        naics: Optional NAICS code filter.
        time_period: Optional time period filter (e.g. '2024', '2024-Q1').
        db_path: Optional database path override.

    Returns:
        dict with win rate statistics.
    """
    conn = _get_db(db_path)
    try:
        query = (
            "SELECT d.result, o.agency, o.naics_code, d.created_at "
            "FROM debriefs d "
            "LEFT JOIN opportunities o ON d.opportunity_id = o.id "
            "WHERE 1=1 "
        )
        params = []

        if agency:
            query += "AND o.agency = ? "
            params.append(agency)
        if naics:
            query += "AND o.naics_code = ? "
            params.append(naics)
        if time_period:
            query += "AND d.created_at LIKE ? "
            params.append(f"{time_period}%")

        rows = conn.execute(query, params).fetchall()
        total = len(rows)
        wins = sum(1 for r in rows if r["result"] == "win")
        losses = total - wins

        # Breakdown by agency
        agency_stats = defaultdict(lambda: {"wins": 0, "losses": 0})
        for r in rows:
            ag = r["agency"] or "Unknown"
            if r["result"] == "win":
                agency_stats[ag]["wins"] += 1
            else:
                agency_stats[ag]["losses"] += 1

        agency_breakdown = {}
        for ag, counts in agency_stats.items():
            ag_total = counts["wins"] + counts["losses"]
            agency_breakdown[ag] = {
                "wins": counts["wins"],
                "losses": counts["losses"],
                "total": ag_total,
                "win_rate": round(_safe_divide(counts["wins"], ag_total), 3),
            }

        return {
            "total_bids": total,
            "wins": wins,
            "losses": losses,
            "win_rate": round(_safe_divide(wins, total), 3),
            "filters": {
                "agency": agency,
                "naics": naics,
                "time_period": time_period,
            },
            "by_agency": agency_breakdown,
        }
    finally:
        conn.close()


def get_top_themes(limit=10, db_path=None):
    """Get the most effective win themes based on win/loss data.

    Args:
        limit: Maximum number of themes to return (default 10).
        db_path: Optional database path override.

    Returns:
        list of dicts with theme text, win rate, and usage count.
    """
    conn = _get_db(db_path)
    try:
        rows = conn.execute(
            "SELECT pattern_description, confidence, sample_size, "
            "recommendation, analyzed_at "
            "FROM win_loss_patterns "
            "WHERE pattern_type = 'win_theme' "
            "ORDER BY confidence DESC, sample_size DESC "
            "LIMIT ?",
            (limit,),
        ).fetchall()
        return [_row_to_dict(r) for r in rows]
    finally:
        conn.close()


def get_pricing_insights(naics=None, agency=None, db_path=None):
    """Get pricing analysis from historical win/loss data.

    Compares average winning prices against our evaluated prices,
    calculates price-to-win ratios, and identifies pricing patterns.

    Args:
        naics: Optional NAICS code filter.
        agency: Optional agency name filter.
        db_path: Optional database path override.

    Returns:
        dict with pricing analysis including averages and ratios.
    """
    conn = _get_db(db_path)
    try:
        query = (
            "SELECT d.result, d.evaluated_price, d.winning_price, "
            "o.agency, o.naics_code "
            "FROM debriefs d "
            "LEFT JOIN opportunities o ON d.opportunity_id = o.id "
            "WHERE d.evaluated_price IS NOT NULL "
        )
        params = []
        if naics:
            query += "AND o.naics_code = ? "
            params.append(naics)
        if agency:
            query += "AND o.agency = ? "
            params.append(agency)

        rows = conn.execute(query, params).fetchall()
        if not rows:
            return {
                "status": "no_data",
                "message": "No pricing data available for filters",
                "filters": {"naics": naics, "agency": agency},
            }

        our_prices = [r["evaluated_price"] for r in rows
                      if r["evaluated_price"]]
        winning_prices = [r["winning_price"] for r in rows
                          if r["winning_price"]]
        ratios = [
            r["evaluated_price"] / r["winning_price"]
            for r in rows
            if r["evaluated_price"] and r["winning_price"]
            and r["winning_price"] > 0
        ]

        win_prices_on_wins = [
            r["evaluated_price"] for r in rows
            if r["result"] == "win" and r["evaluated_price"]
        ]
        win_prices_on_losses = [
            r["evaluated_price"] for r in rows
            if r["result"] == "loss" and r["evaluated_price"]
        ]

        return {
            "sample_size": len(rows),
            "our_average_price": round(
                _safe_divide(sum(our_prices), len(our_prices)), 2
            ) if our_prices else None,
            "winning_average_price": round(
                _safe_divide(sum(winning_prices), len(winning_prices)), 2
            ) if winning_prices else None,
            "average_price_ratio": round(
                _safe_divide(sum(ratios), len(ratios)), 3
            ) if ratios else None,
            "avg_price_on_wins": round(
                _safe_divide(sum(win_prices_on_wins),
                             len(win_prices_on_wins)), 2
            ) if win_prices_on_wins else None,
            "avg_price_on_losses": round(
                _safe_divide(sum(win_prices_on_losses),
                             len(win_prices_on_losses)), 2
            ) if win_prices_on_losses else None,
            "price_to_win_recommendation": (
                "Price within 0-5% of estimated winning price"
                if ratios and _safe_divide(sum(ratios), len(ratios)) <= 1.05
                else "Reduce pricing by 5-10% to be more competitive"
            ),
            "filters": {"naics": naics, "agency": agency},
        }
    finally:
        conn.close()


def generate_recommendations(opp_id=None, db_path=None):
    """Generate recommendations based on historical patterns.

    If an opportunity ID is provided, generates recommendations tailored
    to that opportunity's agency and NAICS code. Otherwise, generates
    general recommendations from all available data.

    Args:
        opp_id: Optional opportunity ID for targeted recommendations.
        db_path: Optional database path override.

    Returns:
        dict with prioritized recommendations.
    """
    conn = _get_db(db_path)
    try:
        recommendations = []
        opp = None

        if opp_id:
            opp_row = conn.execute(
                "SELECT * FROM opportunities WHERE id = ?", (opp_id,)
            ).fetchone()
            if opp_row:
                opp = _row_to_dict(opp_row)

        # Fetch recent patterns
        patterns = conn.execute(
            "SELECT * FROM win_loss_patterns "
            "ORDER BY confidence DESC, sample_size DESC "
            "LIMIT 50"
        ).fetchall()

        for p in patterns:
            pattern = _row_to_dict(p)
            priority = "medium"
            if pattern["confidence"] and pattern["confidence"] >= 0.7:
                priority = "high"
            elif pattern["confidence"] and pattern["confidence"] < 0.3:
                priority = "low"

            rec = {
                "pattern_type": pattern["pattern_type"],
                "description": pattern["pattern_description"],
                "recommendation": pattern["recommendation"],
                "confidence": pattern["confidence"],
                "priority": priority,
                "sample_size": pattern["sample_size"],
            }

            # Boost priority if pattern matches opportunity context
            if opp:
                outcomes = _parse_json_field(pattern["associated_outcomes"])
                if isinstance(outcomes, dict):
                    if outcomes.get("agency") == opp.get("agency"):
                        rec["priority"] = "high"
                        rec["context_match"] = "agency"
                    if outcomes.get("naics") == opp.get("naics_code"):
                        rec["priority"] = "high"
                        rec["context_match"] = "naics"

            recommendations.append(rec)

        # Sort by priority (high > medium > low) then confidence
        priority_order = {"high": 0, "medium": 1, "low": 2}
        recommendations.sort(
            key=lambda r: (
                priority_order.get(r["priority"], 1),
                -(r["confidence"] or 0),
            )
        )

        return {
            "opportunity_id": opp_id,
            "opportunity_context": {
                "agency": opp.get("agency") if opp else None,
                "naics": opp.get("naics_code") if opp else None,
            } if opp else None,
            "recommendations": recommendations[:20],
            "total_patterns_analyzed": len(patterns),
        }
    finally:
        conn.close()


def get_report(db_path=None):
    """Generate a full win/loss report combining all analyses.

    Includes: overall statistics, pattern summary, top themes,
    pricing insights, and prioritized recommendations.

    Args:
        db_path: Optional database path override.

    Returns:
        dict with comprehensive win/loss analysis report.
    """
    now = _now()
    win_rate = get_win_rate(db_path=db_path)
    themes = get_top_themes(limit=5, db_path=db_path)
    pricing = get_pricing_insights(db_path=db_path)
    recs = generate_recommendations(db_path=db_path)

    conn = _get_db(db_path)
    try:
        pattern_counts = conn.execute(
            "SELECT pattern_type, COUNT(*) as cnt "
            "FROM win_loss_patterns GROUP BY pattern_type"
        ).fetchall()
        pattern_summary = {r["pattern_type"]: r["cnt"] for r in pattern_counts}
    finally:
        conn.close()

    return {
        "report_date": now,
        "overall_stats": {
            "total_bids": win_rate["total_bids"],
            "wins": win_rate["wins"],
            "losses": win_rate["losses"],
            "win_rate": win_rate["win_rate"],
        },
        "by_agency": win_rate.get("by_agency", {}),
        "pattern_summary": pattern_summary,
        "top_themes": themes,
        "pricing_insights": pricing,
        "top_recommendations": (
            recs.get("recommendations", [])[:10]
        ),
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_parser():
    """Build the argument parser for the CLI."""
    parser = argparse.ArgumentParser(
        description="GovProposal Win/Loss Pattern Analyzer",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  %(prog)s --analyze --json\n"
            "  %(prog)s --win-rate --agency 'Department of Defense' --json\n"
            "  %(prog)s --top-themes --limit 5 --json\n"
            "  %(prog)s --pricing --naics 541512 --json\n"
            "  %(prog)s --recommend --opp-id OPP-001 --json\n"
            "  %(prog)s --report --json\n"
        ),
    )

    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--analyze", action="store_true",
                        help="Analyze all debriefs for patterns")
    action.add_argument("--win-rate", action="store_true",
                        help="Calculate win rate statistics")
    action.add_argument("--top-themes", action="store_true",
                        help="Get most effective win themes")
    action.add_argument("--pricing", action="store_true",
                        help="Get pricing analysis")
    action.add_argument("--recommend", action="store_true",
                        help="Generate recommendations")
    action.add_argument("--report", action="store_true",
                        help="Full win/loss report")

    parser.add_argument("--agency", help="Filter by agency name")
    parser.add_argument("--naics", help="Filter by NAICS code")
    parser.add_argument("--time-period",
                        help="Filter by time period (e.g. 2024, 2024-Q1)")
    parser.add_argument("--opp-id", help="Opportunity ID for recommendations")
    parser.add_argument("--limit", type=int, default=10,
                        help="Max results (default: 10)")
    parser.add_argument("--json", action="store_true", help="JSON output")
    parser.add_argument("--db-path", help="Override database path")

    return parser


def main():
    """CLI entry point."""
    parser = _build_parser()
    args = parser.parse_args()
    db = args.db_path

    try:
        if args.analyze:
            result = analyze_patterns(db_path=db)

        elif args.win_rate:
            result = get_win_rate(
                agency=args.agency,
                naics=args.naics,
                time_period=args.time_period,
                db_path=db,
            )

        elif args.top_themes:
            result = get_top_themes(limit=args.limit, db_path=db)

        elif args.pricing:
            result = get_pricing_insights(
                naics=args.naics,
                agency=args.agency,
                db_path=db,
            )

        elif args.recommend:
            result = generate_recommendations(
                opp_id=args.opp_id,
                db_path=db,
            )

        elif args.report:
            result = get_report(db_path=db)

        # Output
        if args.json:
            print(json.dumps(result, indent=2, default=str))
        else:
            if isinstance(result, list):
                print(f"Found {len(result)} items:")
                for item in result:
                    desc = item.get("pattern_description",
                                    item.get("description", ""))
                    print(f"  - {desc[:80]}")
            elif isinstance(result, dict):
                for key, value in result.items():
                    if isinstance(value, (dict, list)):
                        print(f"  {key}: {json.dumps(value, default=str)}")
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
    import argparse
    main()
