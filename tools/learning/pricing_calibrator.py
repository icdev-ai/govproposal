#!/usr/bin/env python3
# CUI // SP-PROPIN
# Controlled by: GovProposal Portal
# CUI Category: PROPIN
# Distribution: D
# POC: GovProposal System Administrator
"""Pricing analysis and calibration from FPDS award data and debriefs.

Calibrates pricing benchmarks by NAICS code, agency, and labor category
using historical FPDS contract award data and internal debrief records.
Provides price-to-win estimates and flags outlier rates.

Usage:
    python tools/learning/pricing_calibrator.py --calibrate [--naics 541512] [--agency "DoD"] --json
    python tools/learning/pricing_calibrator.py --benchmarks [--naics 541512] [--labor-category "Sr Engineer"] --json
    python tools/learning/pricing_calibrator.py --price-to-win --opp-id OPP-001 --json
    python tools/learning/pricing_calibrator.py --compare --proposal-id PROP-001 --json
    python tools/learning/pricing_calibrator.py --report --json
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

def _bench_id():
    """Generate a pricing benchmark ID."""
    return "PB-" + secrets.token_hex(6)


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
            "pricing_calibrator",
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


def _percentile(sorted_values, pct):
    """Calculate the pth percentile from a sorted list of values.

    Args:
        sorted_values: Pre-sorted list of numeric values.
        pct: Percentile as a decimal (e.g. 0.25 for 25th percentile).

    Returns:
        Interpolated percentile value, or 0.0 if list is empty.
    """
    if not sorted_values:
        return 0.0
    n = len(sorted_values)
    if n == 1:
        return sorted_values[0]
    k = pct * (n - 1)
    f = int(k)
    c = f + 1
    if c >= n:
        return sorted_values[-1]
    d = k - f
    return sorted_values[f] + d * (sorted_values[c] - sorted_values[f])


def _median(values):
    """Calculate the median of a list of values.

    Args:
        values: List of numeric values.

    Returns:
        Median value, or 0.0 if list is empty.
    """
    if not values:
        return 0.0
    s = sorted(values)
    n = len(s)
    mid = n // 2
    if n % 2 == 0:
        return (s[mid - 1] + s[mid]) / 2
    return s[mid]


# ---------------------------------------------------------------------------
# Core Functions
# ---------------------------------------------------------------------------

def calibrate(naics_code=None, agency=None, db_path=None):
    """Analyze FPDS data and debrief pricing to calibrate benchmarks.

    Calculates average_rate, median_rate, percentile_25, and percentile_75
    per labor_category and naics_code from competitor wins and debrief data.
    Stores results in the pricing_benchmarks table.

    Args:
        naics_code: Optional NAICS code filter.
        agency: Optional agency name filter.
        db_path: Optional database path override.

    Returns:
        dict with calibration results and benchmark counts.
    """
    conn = _get_db(db_path)
    try:
        now = _now()
        benchmarks_created = 0

        # --- Source 1: Competitor wins (FPDS data) ---
        cw_query = (
            "SELECT naics_code, agency, award_amount, contract_type "
            "FROM competitor_wins WHERE award_amount IS NOT NULL "
        )
        cw_params = []
        if naics_code:
            cw_query += "AND naics_code = ? "
            cw_params.append(naics_code)
        if agency:
            cw_query += "AND agency = ? "
            cw_params.append(agency)

        cw_rows = conn.execute(cw_query, cw_params).fetchall()

        # Group award amounts by NAICS
        naics_amounts = {}
        for r in cw_rows:
            nc = r["naics_code"] or "unknown"
            naics_amounts.setdefault(nc, []).append(r["award_amount"])

        for nc, amounts in naics_amounts.items():
            if not amounts:
                continue
            s = sorted(amounts)
            bench_id = _bench_id()
            avg = round(_safe_divide(sum(s), len(s)), 2)
            med = round(_median(s), 2)
            p25 = round(_percentile(s, 0.25), 2)
            p75 = round(_percentile(s, 0.75), 2)

            conn.execute(
                "INSERT INTO pricing_benchmarks "
                "(id, naics_code, agency, contract_type, labor_category, "
                "average_rate, median_rate, percentile_25, percentile_75, "
                "sample_size, data_period, source, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (bench_id, nc, agency, None, "contract_total",
                 avg, med, p25, p75, len(s), now[:4], "fpds", now),
            )
            benchmarks_created += 1

        # --- Source 2: Debrief pricing data ---
        db_query = (
            "SELECT d.evaluated_price, d.winning_price, d.result, "
            "o.naics_code, o.agency "
            "FROM debriefs d "
            "LEFT JOIN opportunities o ON d.opportunity_id = o.id "
            "WHERE (d.evaluated_price IS NOT NULL "
            "OR d.winning_price IS NOT NULL) "
        )
        db_params = []
        if naics_code:
            db_query += "AND o.naics_code = ? "
            db_params.append(naics_code)
        if agency:
            db_query += "AND o.agency = ? "
            db_params.append(agency)

        db_rows = conn.execute(db_query, db_params).fetchall()

        # Group debrief winning prices by NAICS for benchmarking
        debrief_naics = {}
        for r in db_rows:
            nc = r["naics_code"] or "unknown"
            price = r["winning_price"] or r["evaluated_price"]
            if price:
                debrief_naics.setdefault(nc, []).append(price)

        for nc, prices in debrief_naics.items():
            if not prices:
                continue
            s = sorted(prices)
            bench_id = _bench_id()
            avg = round(_safe_divide(sum(s), len(s)), 2)
            med = round(_median(s), 2)
            p25 = round(_percentile(s, 0.25), 2)
            p75 = round(_percentile(s, 0.75), 2)

            conn.execute(
                "INSERT INTO pricing_benchmarks "
                "(id, naics_code, agency, contract_type, labor_category, "
                "average_rate, median_rate, percentile_25, percentile_75, "
                "sample_size, data_period, source, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (bench_id, nc, agency, None, "debrief_price",
                 avg, med, p25, p75, len(s), now[:4], "debrief", now),
            )
            benchmarks_created += 1

        _audit(
            conn, "pricing.calibrate",
            f"Calibrated {benchmarks_created} pricing benchmarks",
            details={
                "naics_code": naics_code,
                "agency": agency,
                "fpds_records": len(cw_rows),
                "debrief_records": len(db_rows),
                "benchmarks_created": benchmarks_created,
            },
        )
        conn.commit()

        return {
            "status": "calibrated",
            "benchmarks_created": benchmarks_created,
            "fpds_records_analyzed": len(cw_rows),
            "debrief_records_analyzed": len(db_rows),
            "filters": {"naics_code": naics_code, "agency": agency},
            "calibrated_at": now,
        }
    finally:
        conn.close()


def get_benchmarks(naics_code=None, agency=None, labor_category=None,
                   db_path=None):
    """Retrieve pricing benchmarks from the database.

    Args:
        naics_code: Optional NAICS code filter.
        agency: Optional agency name filter.
        labor_category: Optional labor category filter.
        db_path: Optional database path override.

    Returns:
        list of dicts with benchmark records.
    """
    conn = _get_db(db_path)
    try:
        query = "SELECT * FROM pricing_benchmarks WHERE 1=1 "
        params = []

        if naics_code:
            query += "AND naics_code = ? "
            params.append(naics_code)
        if agency:
            query += "AND agency = ? "
            params.append(agency)
        if labor_category:
            query += "AND labor_category = ? "
            params.append(labor_category)

        query += "ORDER BY created_at DESC LIMIT 50"
        rows = conn.execute(query, params).fetchall()
        return [_row_to_dict(r) for r in rows]
    finally:
        conn.close()


def price_to_win(opp_id, db_path=None):
    """Estimate the competitive price range for an opportunity.

    Combines FPDS historical data, competitor win prices, our pricing
    history, and market trends to estimate the price-to-win range.

    Args:
        opp_id: The opportunity ID to estimate pricing for.
        db_path: Optional database path override.

    Returns:
        dict with price-to-win estimate including low/mid/high ranges.

    Raises:
        ValueError: If opportunity not found.
    """
    conn = _get_db(db_path)
    try:
        opp_row = conn.execute(
            "SELECT * FROM opportunities WHERE id = ?", (opp_id,)
        ).fetchone()
        if opp_row is None:
            raise ValueError(f"Opportunity not found: {opp_id}")

        opp = _row_to_dict(opp_row)
        naics = opp.get("naics_code")
        ag = opp.get("agency")

        data_points = []

        # Source 1: Pricing benchmarks for this NAICS
        benchmarks = conn.execute(
            "SELECT average_rate, median_rate, percentile_25, percentile_75 "
            "FROM pricing_benchmarks WHERE naics_code = ? "
            "ORDER BY created_at DESC LIMIT 10",
            (naics,),
        ).fetchall()

        for b in benchmarks:
            if b["median_rate"]:
                data_points.append(b["median_rate"])

        # Source 2: Competitor wins in this NAICS/agency space
        cw_query = (
            "SELECT award_amount FROM competitor_wins "
            "WHERE award_amount IS NOT NULL "
        )
        cw_params = []
        if naics:
            cw_query += "AND naics_code = ? "
            cw_params.append(naics)
        if ag:
            cw_query += "AND agency = ? "
            cw_params.append(ag)
        cw_query += "ORDER BY award_date DESC LIMIT 20"

        cw_rows = conn.execute(cw_query, cw_params).fetchall()
        for r in cw_rows:
            data_points.append(r["award_amount"])

        # Source 3: Our historical debrief winning prices
        db_rows = conn.execute(
            "SELECT d.winning_price FROM debriefs d "
            "LEFT JOIN opportunities o ON d.opportunity_id = o.id "
            "WHERE d.winning_price IS NOT NULL AND o.naics_code = ? "
            "ORDER BY d.created_at DESC LIMIT 10",
            (naics,),
        ).fetchall()
        for r in db_rows:
            data_points.append(r["winning_price"])

        if not data_points:
            # Fall back to opportunity estimated value
            low = opp.get("estimated_value_low")
            high = opp.get("estimated_value_high")
            if low and high:
                return {
                    "opportunity_id": opp_id,
                    "status": "estimate_from_opportunity",
                    "price_low": round(low, 2),
                    "price_mid": round((low + high) / 2, 2),
                    "price_high": round(high, 2),
                    "confidence": "low",
                    "data_sources": 0,
                    "note": "No historical data; using opportunity value range",
                }
            return {
                "opportunity_id": opp_id,
                "status": "insufficient_data",
                "message": "No pricing data available for estimation",
            }

        s = sorted(data_points)
        p25 = _percentile(s, 0.25)
        p50 = _percentile(s, 0.50)
        p75 = _percentile(s, 0.75)

        confidence = "low"
        if len(data_points) >= 10:
            confidence = "high"
        elif len(data_points) >= 5:
            confidence = "medium"

        return {
            "opportunity_id": opp_id,
            "agency": ag,
            "naics_code": naics,
            "price_low": round(p25, 2),
            "price_mid": round(p50, 2),
            "price_high": round(p75, 2),
            "price_recommended": round(p50 * 0.98, 2),
            "confidence": confidence,
            "data_sources": len(data_points),
            "methodology": (
                "Combined FPDS benchmarks, competitor wins, "
                "and debrief data; recommended price is 2% below median"
            ),
        }
    finally:
        conn.close()


def compare_pricing(proposal_id, db_path=None):
    """Compare proposed pricing against benchmarks.

    Flags rates that exceed the 75th percentile (too high) or fall
    below the 25th percentile (too low) of market benchmarks.

    Args:
        proposal_id: The proposal ID to compare.
        db_path: Optional database path override.

    Returns:
        dict with pricing comparison and flagged outliers.

    Raises:
        ValueError: If proposal not found.
    """
    conn = _get_db(db_path)
    try:
        prop_row = conn.execute(
            "SELECT p.*, o.naics_code, o.agency "
            "FROM proposals p "
            "LEFT JOIN opportunities o ON p.opportunity_id = o.id "
            "WHERE p.id = ?",
            (proposal_id,),
        ).fetchone()
        if prop_row is None:
            raise ValueError(f"Proposal not found: {proposal_id}")

        prop = _row_to_dict(prop_row)
        naics = prop.get("naics_code")

        # Get benchmarks for this NAICS
        benchmarks = conn.execute(
            "SELECT * FROM pricing_benchmarks WHERE naics_code = ? "
            "ORDER BY created_at DESC LIMIT 5",
            (naics,),
        ).fetchall()

        if not benchmarks:
            return {
                "proposal_id": proposal_id,
                "status": "no_benchmarks",
                "message": (
                    f"No pricing benchmarks found for NAICS {naics}. "
                    f"Run --calibrate first."
                ),
            }

        # Use most recent benchmark
        bench = _row_to_dict(benchmarks[0])
        p25 = bench.get("percentile_25", 0)
        p75 = bench.get("percentile_75", 0)
        median = bench.get("median_rate", 0)
        avg = bench.get("average_rate", 0)

        # Check debrief prices for this proposal
        debrief = conn.execute(
            "SELECT evaluated_price, winning_price FROM debriefs "
            "WHERE proposal_id = ? ORDER BY created_at DESC LIMIT 1",
            (proposal_id,),
        ).fetchone()

        our_price = debrief["evaluated_price"] if debrief else None
        flags = []

        if our_price and p75 and our_price > p75:
            flags.append({
                "type": "too_high",
                "severity": "warning",
                "message": (
                    f"Our price (${our_price:,.2f}) exceeds 75th percentile "
                    f"(${p75:,.2f})"
                ),
                "recommendation": (
                    f"Consider reducing to at or below ${p75:,.2f}"
                ),
            })
        elif our_price and p25 and our_price < p25:
            flags.append({
                "type": "too_low",
                "severity": "info",
                "message": (
                    f"Our price (${our_price:,.2f}) is below 25th percentile "
                    f"(${p25:,.2f})"
                ),
                "recommendation": (
                    "Low price may raise realism concerns; ensure "
                    "cost volume supports proposed rates"
                ),
            })
        elif our_price:
            flags.append({
                "type": "within_range",
                "severity": "ok",
                "message": (
                    f"Our price (${our_price:,.2f}) is within the competitive "
                    f"range (${p25:,.2f} - ${p75:,.2f})"
                ),
            })

        return {
            "proposal_id": proposal_id,
            "naics_code": naics,
            "our_price": our_price,
            "benchmark": {
                "average": avg,
                "median": median,
                "percentile_25": p25,
                "percentile_75": p75,
                "sample_size": bench.get("sample_size"),
                "source": bench.get("source"),
            },
            "flags": flags,
            "assessment": (
                "competitive" if not any(
                    f["severity"] == "warning" for f in flags
                ) else "needs_review"
            ),
        }
    finally:
        conn.close()


def get_pricing_report(db_path=None):
    """Generate a summary report of pricing benchmarks and trends.

    Args:
        db_path: Optional database path override.

    Returns:
        dict with pricing benchmarks summary, trends, and recommendations.
    """
    conn = _get_db(db_path)
    try:
        now = _now()

        # Overall benchmark stats
        total_benchmarks = conn.execute(
            "SELECT COUNT(*) as cnt FROM pricing_benchmarks"
        ).fetchone()["cnt"]

        # Benchmarks by NAICS
        naics_stats = conn.execute(
            "SELECT naics_code, COUNT(*) as cnt, "
            "AVG(average_rate) as avg_rate, "
            "AVG(median_rate) as med_rate, "
            "SUM(sample_size) as total_samples "
            "FROM pricing_benchmarks "
            "GROUP BY naics_code "
            "ORDER BY total_samples DESC "
            "LIMIT 20"
        ).fetchall()

        # Benchmarks by source
        source_stats = conn.execute(
            "SELECT source, COUNT(*) as cnt, "
            "AVG(sample_size) as avg_samples "
            "FROM pricing_benchmarks "
            "GROUP BY source"
        ).fetchall()

        # Recent debrief price comparison
        recent_debriefs = conn.execute(
            "SELECT d.result, d.evaluated_price, d.winning_price, "
            "o.naics_code "
            "FROM debriefs d "
            "LEFT JOIN opportunities o ON d.opportunity_id = o.id "
            "WHERE d.evaluated_price IS NOT NULL "
            "ORDER BY d.created_at DESC LIMIT 20"
        ).fetchall()

        price_gaps = []
        for d in recent_debriefs:
            if d["evaluated_price"] and d["winning_price"]:
                gap = d["evaluated_price"] - d["winning_price"]
                gap_pct = _safe_divide(gap, d["winning_price"]) * 100
                price_gaps.append({
                    "result": d["result"],
                    "gap": round(gap, 2),
                    "gap_pct": round(gap_pct, 1),
                    "naics_code": d["naics_code"],
                })

        avg_gap = _safe_divide(
            sum(p["gap_pct"] for p in price_gaps),
            len(price_gaps),
        ) if price_gaps else 0.0

        recommendations = []
        if avg_gap > 5:
            recommendations.append(
                "Pricing runs 5%+ above competitors on average; "
                "review rate structure and indirect rates"
            )
        elif avg_gap < -5:
            recommendations.append(
                "Pricing runs 5%+ below competitors; ensure "
                "cost realism is defensible"
            )
        else:
            recommendations.append(
                "Pricing is generally competitive; maintain current approach"
            )

        if total_benchmarks < 5:
            recommendations.append(
                "Limited benchmark data; run --calibrate with FPDS data "
                "to build a stronger pricing baseline"
            )

        return {
            "report_date": now,
            "total_benchmarks": total_benchmarks,
            "by_naics": [_row_to_dict(r) for r in naics_stats],
            "by_source": [_row_to_dict(r) for r in source_stats],
            "recent_price_gaps": price_gaps[:10],
            "average_price_gap_pct": round(avg_gap, 1),
            "recommendations": recommendations,
        }
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_parser():
    """Build the argument parser for the CLI."""
    parser = argparse.ArgumentParser(
        description="GovProposal Pricing Calibrator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  %(prog)s --calibrate --naics 541512 --json\n"
            "  %(prog)s --benchmarks --naics 541512 --json\n"
            "  %(prog)s --price-to-win --opp-id OPP-001 --json\n"
            "  %(prog)s --compare --proposal-id PROP-001 --json\n"
            "  %(prog)s --report --json\n"
        ),
    )

    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--calibrate", action="store_true",
                        help="Calibrate pricing benchmarks from data")
    action.add_argument("--benchmarks", action="store_true",
                        help="Retrieve pricing benchmarks")
    action.add_argument("--price-to-win", action="store_true",
                        help="Estimate competitive price for an opportunity")
    action.add_argument("--compare", action="store_true",
                        help="Compare proposal pricing against benchmarks")
    action.add_argument("--report", action="store_true",
                        help="Pricing summary report")

    parser.add_argument("--opp-id", help="Opportunity ID")
    parser.add_argument("--proposal-id", help="Proposal ID")
    parser.add_argument("--naics", help="NAICS code filter")
    parser.add_argument("--agency", help="Agency name filter")
    parser.add_argument("--labor-category", help="Labor category filter")
    parser.add_argument("--json", action="store_true", help="JSON output")
    parser.add_argument("--db-path", help="Override database path")

    return parser


def main():
    """CLI entry point."""
    parser = _build_parser()
    args = parser.parse_args()
    db = args.db_path

    try:
        if args.calibrate:
            result = calibrate(
                naics_code=args.naics,
                agency=args.agency,
                db_path=db,
            )

        elif args.benchmarks:
            result = get_benchmarks(
                naics_code=args.naics,
                agency=args.agency,
                labor_category=args.labor_category,
                db_path=db,
            )

        elif args.price_to_win:
            if not args.opp_id:
                parser.error("--price-to-win requires --opp-id")
            result = price_to_win(opp_id=args.opp_id, db_path=db)

        elif args.compare:
            if not args.proposal_id:
                parser.error("--compare requires --proposal-id")
            result = compare_pricing(
                proposal_id=args.proposal_id,
                db_path=db,
            )

        elif args.report:
            result = get_pricing_report(db_path=db)

        # Output
        if args.json:
            print(json.dumps(result, indent=2, default=str))
        else:
            if isinstance(result, list):
                print(f"Found {len(result)} benchmarks:")
                for b in result:
                    print(
                        f"  [{b.get('id')}] NAICS {b.get('naics_code')}: "
                        f"avg=${b.get('average_rate', 0):,.2f} "
                        f"med=${b.get('median_rate', 0):,.2f}"
                    )
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
