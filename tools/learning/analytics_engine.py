#!/usr/bin/env python3
# CUI // SP-PROPIN
# Controlled by: GovProposal Portal
# CUI Category: PROPIN
# Distribution: D
# POC: GovProposal System Administrator
"""Unified Win-Rate Analytics Engine for GovProposal.

Correlates data across debriefs, FPDS competitor wins, and pricing
benchmarks to produce multi-dimensional win rate analytics.  Dimensions
include agency, NAICS, contract value range, set-aside type, fiscal year,
win theme effectiveness, competitor impact, and team composition.

Usage:
    python tools/learning/analytics_engine.py --report --json
    python tools/learning/analytics_engine.py --by-agency [--min-bids 2] --json
    python tools/learning/analytics_engine.py --by-naics --json
    python tools/learning/analytics_engine.py --trends --json
    python tools/learning/analytics_engine.py --price-sensitivity --json
    python tools/learning/analytics_engine.py --theme-effectiveness --json
    python tools/learning/analytics_engine.py --competitor-impact --json
    python tools/learning/analytics_engine.py --team-impact --json
"""

import json
import os
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
# Helpers
# ---------------------------------------------------------------------------

def _now():
    """Return current UTC timestamp as ISO-8601 string."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _get_db(db_path=None):
    """Open a database connection with WAL mode and foreign keys."""
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
        (
            event_type,
            "analytics_engine",
            action,
            entity_type,
            entity_id,
            json.dumps(details) if details else None,
            _now(),
        ),
    )


def _safe_divide(a, b, default=0.0):
    """Safely divide, returning default if denominator is zero."""
    if not b:
        return default
    return a / b


def _parse_json_field(value):
    """Safely parse a JSON string field."""
    if value is None:
        return None
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return value


def _value_range(amount):
    """Classify a dollar amount into a value range bucket."""
    if amount is None:
        return "unknown"
    if amount < 250_000:
        return "<250K"
    if amount < 1_000_000:
        return "250K-1M"
    if amount < 5_000_000:
        return "1M-5M"
    if amount < 25_000_000:
        return "5M-25M"
    return "25M+"


def _fiscal_year(date_str):
    """Extract US government fiscal year from a date string."""
    if not date_str:
        return "unknown"
    try:
        dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        # US fiscal year: Oct 1 - Sep 30
        return f"FY{dt.year + 1}" if dt.month >= 10 else f"FY{dt.year}"
    except (ValueError, AttributeError):
        return "unknown"


# ---------------------------------------------------------------------------
# Analytics Functions
# ---------------------------------------------------------------------------

def _load_debrief_data(conn):
    """Load enriched debrief data with opportunity and proposal fields."""
    rows = conn.execute(
        "SELECT d.*, "
        "  o.agency, o.naics_code, o.set_aside_type, o.contract_type, "
        "  o.estimated_value_low, o.estimated_value_high, "
        "  o.title AS opp_title, "
        "  p.win_themes, p.status AS prop_status "
        "FROM debriefs d "
        "LEFT JOIN opportunities o ON d.opportunity_id = o.id "
        "LEFT JOIN proposals p ON d.proposal_id = p.id "
        "ORDER BY d.created_at DESC"
    ).fetchall()
    return [dict(r) for r in rows]


def win_rate_by_agency(db_path=None, min_bids=1):
    """Calculate win rate broken down by agency.

    Args:
        db_path: Optional database path override.
        min_bids: Minimum bids to include an agency (default 1).

    Returns:
        dict with per-agency win rate and overall stats.
    """
    conn = _get_db(db_path)
    try:
        debriefs = _load_debrief_data(conn)
        if not debriefs:
            return {"status": "no_data", "agencies": []}

        agency_stats = defaultdict(lambda: {"wins": 0, "losses": 0})
        for d in debriefs:
            agency = d.get("agency") or "Unknown"
            if d["result"] == "win":
                agency_stats[agency]["wins"] += 1
            else:
                agency_stats[agency]["losses"] += 1

        results = []
        for agency, stats in sorted(agency_stats.items()):
            total = stats["wins"] + stats["losses"]
            if total < min_bids:
                continue
            results.append({
                "agency": agency,
                "wins": stats["wins"],
                "losses": stats["losses"],
                "total_bids": total,
                "win_rate": round(_safe_divide(stats["wins"], total), 3),
            })

        # Sort by win rate descending
        results.sort(key=lambda x: x["win_rate"], reverse=True)

        total_wins = sum(r["wins"] for r in results)
        total_bids = sum(r["total_bids"] for r in results)

        return {
            "overall_win_rate": round(
                _safe_divide(total_wins, total_bids), 3
            ),
            "total_bids": total_bids,
            "total_wins": total_wins,
            "agencies": results,
            "analyzed_at": _now(),
        }
    finally:
        conn.close()


def win_rate_by_naics(db_path=None):
    """Calculate win rate broken down by NAICS code.

    Args:
        db_path: Optional database path override.

    Returns:
        dict with per-NAICS win rate stats.
    """
    conn = _get_db(db_path)
    try:
        debriefs = _load_debrief_data(conn)
        if not debriefs:
            return {"status": "no_data", "naics": []}

        naics_stats = defaultdict(lambda: {"wins": 0, "losses": 0})
        for d in debriefs:
            naics = d.get("naics_code") or "Unknown"
            if d["result"] == "win":
                naics_stats[naics]["wins"] += 1
            else:
                naics_stats[naics]["losses"] += 1

        results = []
        for naics, stats in sorted(naics_stats.items()):
            total = stats["wins"] + stats["losses"]
            results.append({
                "naics_code": naics,
                "wins": stats["wins"],
                "losses": stats["losses"],
                "total_bids": total,
                "win_rate": round(_safe_divide(stats["wins"], total), 3),
            })

        results.sort(key=lambda x: x["win_rate"], reverse=True)

        return {
            "naics": results,
            "analyzed_at": _now(),
        }
    finally:
        conn.close()


def win_rate_trends(db_path=None):
    """Calculate win rate trend over time by fiscal year.

    Args:
        db_path: Optional database path override.

    Returns:
        dict with per-fiscal-year win rate trend data.
    """
    conn = _get_db(db_path)
    try:
        debriefs = _load_debrief_data(conn)
        if not debriefs:
            return {"status": "no_data", "trends": []}

        fy_stats = defaultdict(lambda: {"wins": 0, "losses": 0})
        for d in debriefs:
            fy = _fiscal_year(d.get("debrief_date") or d.get("created_at"))
            if d["result"] == "win":
                fy_stats[fy]["wins"] += 1
            else:
                fy_stats[fy]["losses"] += 1

        results = []
        for fy in sorted(fy_stats.keys()):
            stats = fy_stats[fy]
            total = stats["wins"] + stats["losses"]
            results.append({
                "fiscal_year": fy,
                "wins": stats["wins"],
                "losses": stats["losses"],
                "total_bids": total,
                "win_rate": round(_safe_divide(stats["wins"], total), 3),
            })

        # Calculate trend direction
        trend = "stable"
        if len(results) >= 2:
            recent = results[-1]["win_rate"]
            prior = results[-2]["win_rate"]
            if recent > prior + 0.05:
                trend = "improving"
            elif recent < prior - 0.05:
                trend = "declining"

        return {
            "trends": results,
            "trend_direction": trend,
            "analyzed_at": _now(),
        }
    finally:
        conn.close()


def price_sensitivity(db_path=None):
    """Analyze win rate vs price-to-market ratio.

    Examines whether winning proposals tend to be priced above or below
    the winning price to identify optimal pricing strategy.

    Args:
        db_path: Optional database path override.

    Returns:
        dict with pricing sensitivity analysis.
    """
    conn = _get_db(db_path)
    try:
        debriefs = _load_debrief_data(conn)
        priced = [
            d for d in debriefs
            if d.get("evaluated_price") and d.get("winning_price")
        ]

        if not priced:
            return {"status": "no_data", "buckets": []}

        # Calculate price ratio for each bid
        for d in priced:
            d["price_ratio"] = round(
                d["evaluated_price"] / d["winning_price"], 3
            )

        # Bucket by price ratio
        buckets = {
            "<0.90 (underpriced)": {"min": 0, "max": 0.90},
            "0.90-0.95": {"min": 0.90, "max": 0.95},
            "0.95-1.00": {"min": 0.95, "max": 1.00},
            "1.00-1.05": {"min": 1.00, "max": 1.05},
            "1.05-1.10": {"min": 1.05, "max": 1.10},
            ">1.10 (overpriced)": {"min": 1.10, "max": 999},
        }

        results = []
        for label, bounds in buckets.items():
            in_bucket = [
                d for d in priced
                if bounds["min"] <= d["price_ratio"] < bounds["max"]
            ]
            wins = sum(1 for d in in_bucket if d["result"] == "win")
            total = len(in_bucket)
            results.append({
                "bucket": label,
                "total_bids": total,
                "wins": wins,
                "win_rate": round(_safe_divide(wins, total), 3),
            })

        # Overall pricing insight
        win_ratios = [d["price_ratio"] for d in priced if d["result"] == "win"]
        loss_ratios = [d["price_ratio"] for d in priced if d["result"] == "loss"]

        return {
            "buckets": results,
            "avg_win_ratio": round(
                _safe_divide(sum(win_ratios), len(win_ratios)), 3
            ) if win_ratios else None,
            "avg_loss_ratio": round(
                _safe_divide(sum(loss_ratios), len(loss_ratios)), 3
            ) if loss_ratios else None,
            "total_priced_bids": len(priced),
            "insight": (
                "Winning bids average "
                f"{_safe_divide(sum(win_ratios), len(win_ratios)):.0%} "
                "of the winning price"
                if win_ratios else "Insufficient pricing data"
            ),
            "analyzed_at": _now(),
        }
    finally:
        conn.close()


def theme_effectiveness(db_path=None):
    """Analyze which win themes correlate with actual wins.

    Args:
        db_path: Optional database path override.

    Returns:
        dict with per-theme win rates and effectiveness ranking.
    """
    conn = _get_db(db_path)
    try:
        debriefs = _load_debrief_data(conn)
        if not debriefs:
            return {"status": "no_data", "themes": []}

        theme_stats = defaultdict(lambda: {"wins": 0, "losses": 0})
        for d in debriefs:
            themes = _parse_json_field(d.get("win_themes"))
            if not isinstance(themes, list):
                continue
            for theme in themes:
                if d["result"] == "win":
                    theme_stats[theme]["wins"] += 1
                else:
                    theme_stats[theme]["losses"] += 1

        results = []
        for theme, stats in theme_stats.items():
            total = stats["wins"] + stats["losses"]
            rate = _safe_divide(stats["wins"], total)
            results.append({
                "theme": theme,
                "wins": stats["wins"],
                "losses": stats["losses"],
                "total_uses": total,
                "win_rate": round(rate, 3),
                "effectiveness": (
                    "strong" if rate >= 0.6
                    else "moderate" if rate >= 0.4
                    else "weak"
                ),
            })

        results.sort(key=lambda x: x["win_rate"], reverse=True)

        return {
            "themes": results,
            "total_themes_tracked": len(results),
            "strong_themes": sum(
                1 for r in results if r["effectiveness"] == "strong"
            ),
            "analyzed_at": _now(),
        }
    finally:
        conn.close()


def competitor_impact(db_path=None):
    """Analyze win rate when specific competitors bid.

    Correlates debrief winning_contractor data with competitor_wins
    to show which competitors most affect our win probability.

    Args:
        db_path: Optional database path override.

    Returns:
        dict with per-competitor impact analysis.
    """
    conn = _get_db(db_path)
    try:
        debriefs = _load_debrief_data(conn)
        if not debriefs:
            return {"status": "no_data", "competitors": []}

        comp_stats = defaultdict(lambda: {"we_won": 0, "they_won": 0})
        for d in debriefs:
            winner = d.get("winning_contractor") or ""
            if not winner:
                continue
            if d["result"] == "win":
                # We won against this competitor (they bid but lost)
                comp_stats[winner]["we_won"] += 1
            else:
                # They won against us
                comp_stats[winner]["they_won"] += 1

        results = []
        for competitor, stats in comp_stats.items():
            total = stats["we_won"] + stats["they_won"]
            our_rate = _safe_divide(stats["we_won"], total)
            results.append({
                "competitor": competitor,
                "encounters": total,
                "our_wins": stats["we_won"],
                "their_wins": stats["they_won"],
                "our_win_rate_vs": round(our_rate, 3),
                "threat_level": (
                    "low" if our_rate >= 0.6
                    else "medium" if our_rate >= 0.3
                    else "high"
                ),
            })

        # Also pull competitor market presence from competitor_wins
        comp_awards = conn.execute(
            "SELECT competitor_name, COUNT(*) as total_awards, "
            "  SUM(award_amount) as total_value, "
            "  GROUP_CONCAT(DISTINCT agency) as agencies "
            "FROM competitor_wins "
            "GROUP BY competitor_name "
            "ORDER BY total_awards DESC "
            "LIMIT 20"
        ).fetchall()

        market_presence = []
        for row in comp_awards:
            r = dict(row)
            # Find matching encounter data
            encounter = next(
                (c for c in results
                 if c["competitor"].lower() == r["competitor_name"].lower()),
                None,
            )
            market_presence.append({
                "competitor": r["competitor_name"],
                "total_awards": r["total_awards"],
                "total_award_value": r["total_value"],
                "agencies": (r["agencies"] or "").split(",")[:5],
                "our_win_rate_vs": (
                    encounter["our_win_rate_vs"] if encounter else None
                ),
            })

        results.sort(key=lambda x: x["encounters"], reverse=True)

        return {
            "direct_encounters": results,
            "market_presence": market_presence,
            "total_competitors_tracked": len(results),
            "high_threat_count": sum(
                1 for r in results if r["threat_level"] == "high"
            ),
            "analyzed_at": _now(),
        }
    finally:
        conn.close()


def team_impact(db_path=None):
    """Analyze win rate by teaming partner presence.

    Examines whether proposals with specific teaming partners have
    higher or lower win rates.

    Args:
        db_path: Optional database path override.

    Returns:
        dict with per-partner win rate impact.
    """
    conn = _get_db(db_path)
    try:
        # Get proposals with their teaming data
        rows = conn.execute(
            "SELECT p.id, p.result, p.win_themes, "
            "  d.result AS debrief_result, "
            "  o.agency, o.naics_code "
            "FROM proposals p "
            "LEFT JOIN debriefs d ON d.proposal_id = p.id "
            "LEFT JOIN opportunities o ON p.opportunity_id = o.id "
            "WHERE p.result IS NOT NULL OR d.result IS NOT NULL"
        ).fetchall()

        if not rows:
            return {"status": "no_data", "partners": []}

        # Check proposal-partner associations (via capture decisions)
        partner_stats = defaultdict(lambda: {"wins": 0, "losses": 0})

        for row in rows:
            r = dict(row)
            result = r.get("debrief_result") or r.get("result")
            if not result:
                continue

            # Look for partner associations in capture_decisions
            decisions = conn.execute(
                "SELECT decision_data FROM capture_decisions "
                "WHERE opportunity_id = ("
                "  SELECT opportunity_id FROM proposals WHERE id = ?"
                ") AND decision_type = 'teaming_selection'",
                (r["id"],),
            ).fetchall()

            for dec in decisions:
                data = _parse_json_field(dec["decision_data"])
                if isinstance(data, dict):
                    partners = data.get("selected_partners", [])
                    if isinstance(partners, list):
                        for partner in partners:
                            name = (
                                partner.get("company_name")
                                if isinstance(partner, dict)
                                else str(partner)
                            )
                            if name:
                                if result == "win":
                                    partner_stats[name]["wins"] += 1
                                else:
                                    partner_stats[name]["losses"] += 1

        results = []
        for partner, stats in partner_stats.items():
            total = stats["wins"] + stats["losses"]
            results.append({
                "partner": partner,
                "proposals_together": total,
                "wins": stats["wins"],
                "losses": stats["losses"],
                "win_rate_with": round(
                    _safe_divide(stats["wins"], total), 3
                ),
            })

        results.sort(key=lambda x: x["win_rate_with"], reverse=True)

        return {
            "partners": results,
            "total_partners_tracked": len(results),
            "analyzed_at": _now(),
        }
    finally:
        conn.close()


def generate_report(db_path=None):
    """Generate comprehensive win-rate analytics report.

    Combines all analytics dimensions into a single report.

    Args:
        db_path: Optional database path override.

    Returns:
        dict with all analytics dimensions combined.
    """
    report = {
        "report_type": "win_rate_analytics",
        "generated_at": _now(),
    }

    # Collect all dimensions
    report["by_agency"] = win_rate_by_agency(db_path=db_path)
    report["by_naics"] = win_rate_by_naics(db_path=db_path)
    report["trends"] = win_rate_trends(db_path=db_path)
    report["price_sensitivity"] = price_sensitivity(db_path=db_path)
    report["theme_effectiveness"] = theme_effectiveness(db_path=db_path)
    report["competitor_impact"] = competitor_impact(db_path=db_path)
    report["team_impact"] = team_impact(db_path=db_path)

    # Overall summary
    agency_data = report["by_agency"]
    report["summary"] = {
        "overall_win_rate": agency_data.get("overall_win_rate"),
        "total_bids_analyzed": agency_data.get("total_bids", 0),
        "total_wins": agency_data.get("total_wins", 0),
        "trend": report["trends"].get("trend_direction", "unknown"),
        "top_agency": (
            agency_data["agencies"][0]["agency"]
            if agency_data.get("agencies") else None
        ),
        "strongest_theme": (
            report["theme_effectiveness"]["themes"][0]["theme"]
            if report["theme_effectiveness"].get("themes") else None
        ),
        "biggest_threat": next(
            (c["competitor"]
             for c in report["competitor_impact"].get(
                 "direct_encounters", []
             ) if c.get("threat_level") == "high"),
            None,
        ),
    }

    # Audit the report generation
    conn = _get_db(db_path)
    try:
        _audit(conn, "learning.analytics_report",
               "Generated comprehensive win-rate analytics report",
               details=report["summary"])
        conn.commit()
    finally:
        conn.close()

    return report


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_parser():
    """Build argument parser for the CLI."""
    import argparse
    parser = argparse.ArgumentParser(
        description="GovProposal Win-Rate Analytics Engine",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  %(prog)s --report --json\n"
            "  %(prog)s --by-agency --min-bids 3 --json\n"
            "  %(prog)s --by-naics --json\n"
            "  %(prog)s --trends --json\n"
            "  %(prog)s --price-sensitivity --json\n"
            "  %(prog)s --theme-effectiveness --json\n"
            "  %(prog)s --competitor-impact --json\n"
            "  %(prog)s --team-impact --json\n"
        ),
    )

    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--report", action="store_true",
                        help="Full analytics report (all dimensions)")
    action.add_argument("--by-agency", action="store_true",
                        help="Win rate by agency")
    action.add_argument("--by-naics", action="store_true",
                        help="Win rate by NAICS code")
    action.add_argument("--trends", action="store_true",
                        help="Win rate trends over time")
    action.add_argument("--price-sensitivity", action="store_true",
                        help="Win rate vs price-to-market ratio")
    action.add_argument("--theme-effectiveness", action="store_true",
                        help="Win theme effectiveness ranking")
    action.add_argument("--competitor-impact", action="store_true",
                        help="Competitor impact on win rate")
    action.add_argument("--team-impact", action="store_true",
                        help="Teaming partner impact on win rate")

    parser.add_argument("--min-bids", type=int, default=1,
                        help="Min bids to include (for --by-agency)")
    parser.add_argument("--json", action="store_true", help="JSON output")
    parser.add_argument("--db-path", help="Override database path")

    return parser


def main():
    """CLI entry point."""
    parser = _build_parser()
    args = parser.parse_args()
    db = args.db_path

    try:
        if args.report:
            result = generate_report(db_path=db)
        elif args.by_agency:
            result = win_rate_by_agency(db_path=db, min_bids=args.min_bids)
        elif args.by_naics:
            result = win_rate_by_naics(db_path=db)
        elif args.trends:
            result = win_rate_trends(db_path=db)
        elif args.price_sensitivity:
            result = price_sensitivity(db_path=db)
        elif args.theme_effectiveness:
            result = theme_effectiveness(db_path=db)
        elif args.competitor_impact:
            result = competitor_impact(db_path=db)
        elif args.team_impact:
            result = team_impact(db_path=db)

        # Output
        if args.json:
            print(json.dumps(result, indent=2, default=str))
        else:
            if isinstance(result, dict):
                for key, value in result.items():
                    if isinstance(value, (list, dict)):
                        if isinstance(value, list) and len(value) <= 20:
                            print(f"\n{key}:")
                            for item in value:
                                if isinstance(item, dict):
                                    line = ", ".join(
                                        f"{k}: {v}"
                                        for k, v in item.items()
                                    )
                                    print(f"  {line}")
                                else:
                                    print(f"  {item}")
                        else:
                            print(f"  {key}: "
                                  f"{json.dumps(value, default=str)[:200]}")
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
