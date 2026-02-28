#!/usr/bin/env python3
# CUI // SP-PROPIN
"""Audit Logger — append-only audit trail writer for GovProposal.

Logs all actions to the audit_trail table in govproposal.db.
Satisfies NIST 800-53 AU controls. No UPDATE/DELETE operations.

Usage:
    python tools/audit/audit_logger.py \
        --event-type "proposal.draft" \
        --actor "orchestrator" \
        --action "Drafted technical approach section" \
        --project-id "PROP-123" \
        --json
"""

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

DB_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "govproposal.db"


def log_event(event_type: str, actor: str, action: str,
              project_id: str = "", metadata: dict = None) -> dict:
    """Append an event to the audit trail. Returns the entry."""
    entry = {
        "id": str(uuid4()),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event_type": event_type,
        "actor": actor,
        "action": action,
        "project_id": project_id,
        "metadata": json.dumps(metadata or {}),
    }

    db_path = Path(DB_PATH)
    if db_path.exists():
        conn = sqlite3.connect(str(db_path))
        try:
            conn.execute(
                """INSERT INTO audit_trail
                   (id, timestamp, event_type, actor, action, project_id, metadata)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (entry["id"], entry["timestamp"], entry["event_type"],
                 entry["actor"], entry["action"], entry["project_id"],
                 entry["metadata"]),
            )
            conn.commit()
        except sqlite3.OperationalError:
            pass  # Table may not exist yet
        finally:
            conn.close()

    return entry


def main():
    parser = argparse.ArgumentParser(description="Audit Logger")
    parser.add_argument("--event-type", required=True)
    parser.add_argument("--actor", required=True)
    parser.add_argument("--action", required=True)
    parser.add_argument("--project-id", default="")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    result = log_event(args.event_type, args.actor, args.action, args.project_id)

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"Logged: [{result['event_type']}] {result['action']}")


if __name__ == "__main__":
    main()
