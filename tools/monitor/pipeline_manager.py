#!/usr/bin/env python3
# CUI // SP-PROPIN
# Controlled by: GovProposal Portal
# CUI Category: PROPIN
# Distribution: D
# POC: GovProposal System Administrator
"""Pipeline Manager — Tracks opportunities through the Shipley lifecycle.

Manages pipeline stage transitions, enforces gate conditions,
and provides status dashboards.

Pipeline stages (14):
    discovered → qualified → capture_started → bid_decision →
    draft_rfp → proposal_team → outline → pink_review →
    red_review → gold_review → white_review → final_production →
    submitted → awarded | lost | no_bid

Usage:
    python tools/monitor/pipeline_manager.py --status --json
    python tools/monitor/pipeline_manager.py --advance <opp_id> --to <stage> --json
    python tools/monitor/pipeline_manager.py --upcoming --days 30 --json
"""

import argparse
import json
import os
import sqlite3
import sys
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent
DB_PATH = Path(os.environ.get(
    "GOVPROPOSAL_DB_PATH", str(BASE_DIR / "data" / "govproposal.db")
))

VALID_STAGES = [
    "discovered", "qualifying", "go_decision", "capture",
    "drafting", "pink_review", "red_review", "gold_review",
    "white_review", "production", "submitted",
    "awarded", "lost", "no_bid", "archived"
]

# Stage transitions: from → allowed_to
TRANSITIONS = {
    "discovered": ["qualifying", "no_bid"],
    "qualifying": ["go_decision", "no_bid"],
    "go_decision": ["capture", "no_bid"],
    "capture": ["drafting", "no_bid"],
    "drafting": ["pink_review"],
    "pink_review": ["red_review", "drafting"],  # Can loop back
    "red_review": ["gold_review", "drafting"],
    "gold_review": ["white_review", "red_review"],
    "white_review": ["production", "gold_review"],
    "production": ["submitted"],
    "submitted": ["awarded", "lost"],
}


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _get_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def pipeline_status():
    """Get full pipeline status overview."""
    conn = _get_db()
    try:
        # Stage counts
        stages = {}
        rows = conn.execute(
            "SELECT status, COUNT(*) as cnt FROM opportunities GROUP BY status"
        ).fetchall()
        for r in rows:
            stages[r["status"]] = r["cnt"]

        # Active proposals
        active_props = conn.execute(
            """SELECT p.id, p.title, p.status, p.cag_status, p.due_date,
                      o.agency, o.title as opp_title
               FROM proposals p
               LEFT JOIN opportunities o ON p.opportunity_id = o.id
               WHERE p.status NOT IN ('submitted', 'awarded', 'lost')
               ORDER BY p.due_date ASC"""
        ).fetchall()

        # Open CAG alerts
        cag_count = conn.execute(
            "SELECT COUNT(*) as cnt FROM cag_alerts WHERE status = 'open'"
        ).fetchone()

        # Upcoming deadlines (next 30 days)
        cutoff = (datetime.now(timezone.utc) + timedelta(days=30)).strftime("%Y-%m-%d")
        upcoming = conn.execute(
            """SELECT id, title, agency, response_deadline, status
               FROM opportunities
               WHERE response_deadline <= ? AND response_deadline >= date('now')
                 AND status NOT IN ('no_bid', 'submitted', 'awarded', 'lost')
               ORDER BY response_deadline ASC""",
            (cutoff,)
        ).fetchall()

        return {
            "status": "success",
            "pipeline_stages": stages,
            "total_opportunities": sum(stages.values()),
            "active_proposals": [dict(p) for p in active_props],
            "open_cag_alerts": cag_count["cnt"] if cag_count else 0,
            "upcoming_deadlines": [dict(u) for u in upcoming],
            "timestamp": _now()
        }
    finally:
        conn.close()


def advance_stage(opp_id, to_stage, notes=None):
    """Advance an opportunity to a new pipeline stage."""
    if to_stage not in VALID_STAGES:
        return {"status": "error", "message": f"Invalid stage: {to_stage}"}

    conn = _get_db()
    try:
        opp = conn.execute(
            "SELECT * FROM opportunities WHERE id = ?", (opp_id,)
        ).fetchone()
        if not opp:
            return {"status": "error", "message": f"Opportunity {opp_id} not found"}

        current = opp["status"]
        allowed = TRANSITIONS.get(current, [])
        if to_stage not in allowed:
            return {
                "status": "error",
                "message": f"Cannot transition from '{current}' to '{to_stage}'",
                "allowed_transitions": allowed
            }

        # Record stage transition
        stage_id = str(uuid.uuid4())[:12]
        conn.execute(
            """INSERT INTO pipeline_stages (id, opportunity_id, stage, entered_at, notes)
               VALUES (?, ?, ?, ?, ?)""",
            (stage_id, opp_id, to_stage, _now(), notes)
        )

        # Update opportunity status
        conn.execute(
            "UPDATE opportunities SET status = ?, updated_at = ? WHERE id = ?",
            (to_stage, _now(), opp_id)
        )

        # Write audit trail entry
        conn.execute(
            """INSERT INTO audit_trail (event_type, entity_type, entity_id,
                                        action, details, actor, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            ("stage_transition", "opportunity", opp_id,
             f"advanced from {current} to {to_stage}",
             json.dumps({"from": current, "to": to_stage, "notes": notes}),
             "pipeline_manager", _now())
        )

        conn.commit()
        return {
            "status": "success",
            "opportunity_id": opp_id,
            "previous_stage": current,
            "new_stage": to_stage,
            "stage_record_id": stage_id
        }
    finally:
        conn.close()


def upcoming_deadlines(days=30):
    """List opportunities with deadlines in the next N days."""
    conn = _get_db()
    try:
        cutoff = (datetime.now(timezone.utc) + timedelta(days=days)).strftime("%Y-%m-%d")
        rows = conn.execute(
            """SELECT o.id, o.title, o.agency, o.response_deadline, o.status,
                      o.fit_score, o.naics_code,
                      p.id as proposal_id, p.status as proposal_status
               FROM opportunities o
               LEFT JOIN proposals p ON o.id = p.opportunity_id
               WHERE o.response_deadline <= ? AND o.response_deadline >= date('now')
                 AND o.status NOT IN ('no_bid', 'awarded', 'lost')
               ORDER BY o.response_deadline ASC""",
            (cutoff,)
        ).fetchall()

        return {
            "status": "success",
            "days_ahead": days,
            "count": len(rows),
            "upcoming": [dict(r) for r in rows]
        }
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(description="GovProposal Pipeline Manager")
    parser.add_argument("--status", action="store_true", help="Show pipeline status")
    parser.add_argument("--advance", metavar="OPP_ID", help="Advance opportunity to new stage")
    parser.add_argument("--to", metavar="STAGE", help="Target stage for advancement")
    parser.add_argument("--notes", help="Notes for stage transition")
    parser.add_argument("--upcoming", action="store_true", help="Show upcoming deadlines")
    parser.add_argument("--days", type=int, default=30, help="Days ahead for deadlines")
    parser.add_argument("--json", action="store_true", help="JSON output")
    args = parser.parse_args()

    if args.status:
        result = pipeline_status()
    elif args.advance:
        if not args.to:
            result = {"status": "error", "message": "--to <stage> required with --advance"}
        else:
            result = advance_stage(args.advance, args.to, args.notes)
    elif args.upcoming:
        result = upcoming_deadlines(args.days)
    else:
        parser.print_help()
        return

    if args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
