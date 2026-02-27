#!/usr/bin/env python3
# CUI // SP-PROPIN
# Controlled by: GovProposal Portal
# CUI Category: PROPIN
# Distribution: D
# POC: GovProposal System Administrator
"""Knowledge Base CRUD manager for GovProposal.

Manages knowledge base entries: capabilities, boilerplate, case studies,
win themes, solution architectures, methodologies, certifications,
tool/technology profiles, domain expertise, corporate overviews,
and management approaches.

Usage:
    python tools/knowledge/kb_manager.py --add --type capability --title "Cloud Migration" --content "..."
    python tools/knowledge/kb_manager.py --update --id KB-abc123def456 --title "Updated Title"
    python tools/knowledge/kb_manager.py --get --id KB-abc123def456
    python tools/knowledge/kb_manager.py --list [--type boilerplate] [--limit 20]
    python tools/knowledge/kb_manager.py --delete --id KB-abc123def456
    python tools/knowledge/kb_manager.py --import --text "Raw boilerplate text..." [--type boilerplate]
    python tools/knowledge/kb_manager.py --record-usage --id KB-abc123def456 [--proposal-id PROP-001]
    python tools/knowledge/kb_manager.py --json
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

# Valid entry types matching the CHECK constraint in kb_entries table
VALID_ENTRY_TYPES = (
    "capability", "boilerplate", "case_study", "win_theme",
    "solution_architecture", "methodology", "certification",
    "tool_technology", "domain_expertise", "corporate_overview",
    "management_approach",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _kb_id():
    """Generate a KB entry ID: KB- followed by 12 hex characters."""
    return "KB-" + secrets.token_hex(6)


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
        event_type: Category of event (e.g. 'kb.add', 'kb.update').
        action: Human-readable description of the action.
        entity_type: Type of entity affected (e.g. 'kb_entry').
        entity_id: ID of the affected entity.
        details: Optional JSON-serializable details dict.
    """
    conn.execute(
        "INSERT INTO audit_trail (event_type, actor, action, entity_type, "
        "entity_id, details, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            event_type,
            "kb_manager",
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
    """Safely parse a JSON string field, returning the parsed value or the
    original string if parsing fails.

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


def _serialize_list(value):
    """Serialize a list or string to a JSON array string for storage.

    Args:
        value: A list, comma-separated string, or None.

    Returns:
        JSON array string, or None.
    """
    if value is None:
        return None
    if isinstance(value, str):
        value = [v.strip() for v in value.split(",") if v.strip()]
    if isinstance(value, (list, tuple)):
        return json.dumps(list(value))
    return json.dumps([str(value)])


# ---------------------------------------------------------------------------
# Core CRUD Functions
# ---------------------------------------------------------------------------

def add_entry(entry_type, title, content, tags=None, naics_codes=None,
              agencies=None, db_path=None):
    """Add a new knowledge base entry.

    Args:
        entry_type: One of VALID_ENTRY_TYPES.
        title: Short descriptive title.
        content: Full text content of the entry.
        tags: Optional list or comma-separated string of tags.
        naics_codes: Optional list or comma-separated NAICS codes.
        agencies: Optional list or comma-separated agency names.
        db_path: Optional database path override.

    Returns:
        dict with the created entry fields.

    Raises:
        ValueError: If entry_type is not valid.
    """
    if entry_type not in VALID_ENTRY_TYPES:
        raise ValueError(
            f"Invalid entry_type '{entry_type}'. "
            f"Must be one of: {', '.join(VALID_ENTRY_TYPES)}"
        )

    entry_id = _kb_id()
    now = _now()
    tags_json = _serialize_list(tags)
    naics_json = _serialize_list(naics_codes)
    agencies_json = _serialize_list(agencies)

    conn = _get_db(db_path)
    try:
        conn.execute(
            "INSERT INTO kb_entries "
            "(id, entry_type, title, content, tags, naics_codes, agencies, "
            " version, is_active, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, 1, 1, ?, ?)",
            (entry_id, entry_type, title, content, tags_json, naics_json,
             agencies_json, now, now),
        )
        _audit(conn, "kb.add", f"Added KB entry: {title}",
               "kb_entry", entry_id, {"entry_type": entry_type})
        conn.commit()

        entry = {
            "id": entry_id,
            "entry_type": entry_type,
            "title": title,
            "content": content,
            "tags": _parse_json_field(tags_json),
            "naics_codes": _parse_json_field(naics_json),
            "agencies": _parse_json_field(agencies_json),
            "version": 1,
            "is_active": 1,
            "usage_count": 0,
            "created_at": now,
            "updated_at": now,
        }
        return entry
    finally:
        conn.close()


def update_entry(entry_id, updates, db_path=None):
    """Update an existing knowledge base entry.

    Increments the version number automatically. Only fields present
    in the updates dict are modified.

    Args:
        entry_id: The KB entry ID (e.g. 'KB-abc123def456').
        updates: dict of field names to new values. Supported fields:
            title, content, tags, naics_codes, agencies, keywords,
            quality_score, win_rate.
        db_path: Optional database path override.

    Returns:
        dict with updated entry fields.

    Raises:
        ValueError: If entry not found or no valid update fields provided.
    """
    allowed_fields = {
        "title", "content", "tags", "naics_codes", "agencies",
        "keywords", "quality_score", "win_rate",
    }
    list_fields = {"tags", "naics_codes", "agencies"}

    filtered = {}
    for key, value in updates.items():
        if key in allowed_fields:
            if key in list_fields:
                filtered[key] = _serialize_list(value)
            else:
                filtered[key] = value

    if not filtered:
        raise ValueError(
            f"No valid update fields provided. "
            f"Allowed: {', '.join(sorted(allowed_fields))}"
        )

    conn = _get_db(db_path)
    try:
        # Verify entry exists and is active
        row = conn.execute(
            "SELECT * FROM kb_entries WHERE id = ? AND is_active = 1",
            (entry_id,),
        ).fetchone()
        if row is None:
            raise ValueError(f"KB entry not found or inactive: {entry_id}")

        now = _now()
        current_version = row["version"]
        new_version = current_version + 1

        set_clauses = []
        params = []
        for field, value in filtered.items():
            set_clauses.append(f"{field} = ?")
            params.append(value)

        set_clauses.append("version = ?")
        params.append(new_version)
        set_clauses.append("updated_at = ?")
        params.append(now)
        params.append(entry_id)

        sql = f"UPDATE kb_entries SET {', '.join(set_clauses)} WHERE id = ?"
        conn.execute(sql, params)

        _audit(conn, "kb.update", f"Updated KB entry: {entry_id}",
               "kb_entry", entry_id,
               {"fields": list(filtered.keys()), "new_version": new_version})
        conn.commit()

        return _row_to_dict(conn.execute(
            "SELECT * FROM kb_entries WHERE id = ?", (entry_id,)
        ).fetchone())
    finally:
        conn.close()


def get_entry(entry_id, db_path=None):
    """Get a single knowledge base entry by ID.

    Args:
        entry_id: The KB entry ID.
        db_path: Optional database path override.

    Returns:
        dict with entry fields, or None if not found.
    """
    conn = _get_db(db_path)
    try:
        row = conn.execute(
            "SELECT * FROM kb_entries WHERE id = ?", (entry_id,)
        ).fetchone()
        return _row_to_dict(row)
    finally:
        conn.close()


def list_entries(entry_type=None, limit=50, db_path=None):
    """List knowledge base entries with optional type filter.

    Args:
        entry_type: Optional filter by entry type.
        limit: Maximum number of entries to return (default 50).
        db_path: Optional database path override.

    Returns:
        list of dicts, each representing a KB entry.

    Raises:
        ValueError: If entry_type is provided but not valid.
    """
    if entry_type is not None and entry_type not in VALID_ENTRY_TYPES:
        raise ValueError(
            f"Invalid entry_type '{entry_type}'. "
            f"Must be one of: {', '.join(VALID_ENTRY_TYPES)}"
        )

    conn = _get_db(db_path)
    try:
        if entry_type:
            rows = conn.execute(
                "SELECT * FROM kb_entries WHERE is_active = 1 AND entry_type = ? "
                "ORDER BY updated_at DESC LIMIT ?",
                (entry_type, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM kb_entries WHERE is_active = 1 "
                "ORDER BY updated_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [_row_to_dict(r) for r in rows]
    finally:
        conn.close()


def delete_entry(entry_id, db_path=None):
    """Soft-delete a knowledge base entry (set is_active=0).

    Args:
        entry_id: The KB entry ID.
        db_path: Optional database path override.

    Returns:
        dict with status and entry_id.

    Raises:
        ValueError: If entry not found.
    """
    conn = _get_db(db_path)
    try:
        row = conn.execute(
            "SELECT id, title FROM kb_entries WHERE id = ? AND is_active = 1",
            (entry_id,),
        ).fetchone()
        if row is None:
            raise ValueError(f"KB entry not found or already deleted: {entry_id}")

        now = _now()
        conn.execute(
            "UPDATE kb_entries SET is_active = 0, updated_at = ? WHERE id = ?",
            (now, entry_id),
        )
        _audit(conn, "kb.delete", f"Soft-deleted KB entry: {row['title']}",
               "kb_entry", entry_id)
        conn.commit()

        return {"status": "deleted", "id": entry_id, "deleted_at": now}
    finally:
        conn.close()


def record_usage(entry_id, proposal_id=None, db_path=None):
    """Record usage of a KB entry, incrementing its usage_count.

    Args:
        entry_id: The KB entry ID.
        proposal_id: Optional proposal ID where this entry was used.
        db_path: Optional database path override.

    Returns:
        dict with updated usage_count and last_used_at.

    Raises:
        ValueError: If entry not found.
    """
    conn = _get_db(db_path)
    try:
        row = conn.execute(
            "SELECT id, usage_count FROM kb_entries WHERE id = ? AND is_active = 1",
            (entry_id,),
        ).fetchone()
        if row is None:
            raise ValueError(f"KB entry not found or inactive: {entry_id}")

        now = _now()
        new_count = (row["usage_count"] or 0) + 1

        conn.execute(
            "UPDATE kb_entries SET usage_count = ?, last_used_at = ?, "
            "last_used_in = ? WHERE id = ?",
            (new_count, now, proposal_id, entry_id),
        )
        _audit(conn, "kb.usage", f"Recorded usage of KB entry: {entry_id}",
               "kb_entry", entry_id,
               {"proposal_id": proposal_id, "new_count": new_count})
        conn.commit()

        return {
            "id": entry_id,
            "usage_count": new_count,
            "last_used_at": now,
            "last_used_in": proposal_id,
        }
    finally:
        conn.close()


def import_from_text(text, entry_type="boilerplate", title=None, db_path=None):
    """Create a KB entry from raw text.

    If no title is provided, uses the first 80 characters of the text.

    Args:
        text: The raw text content.
        entry_type: Entry type (default 'boilerplate').
        title: Optional title; auto-generated from text if not provided.
        db_path: Optional database path override.

    Returns:
        dict with the created entry fields.
    """
    if not text or not text.strip():
        raise ValueError("Text content cannot be empty")

    if title is None:
        # Use first line or first 80 chars as title
        first_line = text.strip().split("\n")[0].strip()
        title = first_line[:80] + ("..." if len(first_line) > 80 else "")

    return add_entry(
        entry_type=entry_type,
        title=title,
        content=text.strip(),
        db_path=db_path,
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_parser():
    """Build the argument parser for the CLI."""
    parser = argparse.ArgumentParser(
        description="GovProposal Knowledge Base Manager",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  %(prog)s --add --type capability --title 'Cloud Migration' "
            "--content 'We provide...' --json\n"
            "  %(prog)s --list --type boilerplate --limit 20 --json\n"
            "  %(prog)s --get --id KB-abc123def456 --json\n"
            "  %(prog)s --update --id KB-abc123def456 --title 'New Title'\n"
            "  %(prog)s --delete --id KB-abc123def456\n"
            "  %(prog)s --import --text 'Raw text...' --type boilerplate\n"
            "  %(prog)s --record-usage --id KB-abc123def456 --proposal-id PROP-001\n"
        ),
    )

    # Action group (mutually exclusive)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--add", action="store_true", help="Add a new KB entry")
    action.add_argument("--update", action="store_true", help="Update a KB entry")
    action.add_argument("--get", action="store_true", help="Get a KB entry by ID")
    action.add_argument("--list", action="store_true", help="List KB entries")
    action.add_argument("--delete", action="store_true", help="Soft-delete a KB entry")
    action.add_argument("--import", dest="import_text", action="store_true",
                        help="Import from raw text")
    action.add_argument("--record-usage", action="store_true",
                        help="Record usage of a KB entry")

    # Common args
    parser.add_argument("--id", help="KB entry ID")
    parser.add_argument("--type", dest="entry_type", choices=VALID_ENTRY_TYPES,
                        help="Entry type")
    parser.add_argument("--title", help="Entry title")
    parser.add_argument("--content", help="Entry content text")
    parser.add_argument("--text", help="Raw text for --import")
    parser.add_argument("--tags", help="Comma-separated tags")
    parser.add_argument("--naics-codes", help="Comma-separated NAICS codes")
    parser.add_argument("--agencies", help="Comma-separated agency names")
    parser.add_argument("--proposal-id", help="Proposal ID for usage recording")
    parser.add_argument("--limit", type=int, default=50,
                        help="Max entries for --list (default: 50)")
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
            if not args.entry_type:
                parser.error("--add requires --type")
            if not args.title:
                parser.error("--add requires --title")
            if not args.content:
                parser.error("--add requires --content")
            result = add_entry(
                entry_type=args.entry_type,
                title=args.title,
                content=args.content,
                tags=args.tags,
                naics_codes=args.naics_codes,
                agencies=args.agencies,
                db_path=db,
            )

        elif args.update:
            if not args.id:
                parser.error("--update requires --id")
            updates = {}
            if args.title:
                updates["title"] = args.title
            if args.content:
                updates["content"] = args.content
            if args.tags:
                updates["tags"] = args.tags
            if args.naics_codes:
                updates["naics_codes"] = args.naics_codes
            if args.agencies:
                updates["agencies"] = args.agencies
            if not updates:
                parser.error("--update requires at least one field to update")
            result = update_entry(args.id, updates, db_path=db)

        elif args.get:
            if not args.id:
                parser.error("--get requires --id")
            result = get_entry(args.id, db_path=db)
            if result is None:
                result = {"error": f"Entry not found: {args.id}"}

        elif args.list:
            result = list_entries(
                entry_type=args.entry_type,
                limit=args.limit,
                db_path=db,
            )

        elif args.delete:
            if not args.id:
                parser.error("--delete requires --id")
            result = delete_entry(args.id, db_path=db)

        elif args.import_text:
            text = args.text or args.content
            if not text:
                parser.error("--import requires --text or --content")
            result = import_from_text(
                text=text,
                entry_type=args.entry_type or "boilerplate",
                title=args.title,
                db_path=db,
            )

        elif args.record_usage:
            if not args.id:
                parser.error("--record-usage requires --id")
            result = record_usage(
                entry_id=args.id,
                proposal_id=args.proposal_id,
                db_path=db,
            )

        # Output
        if args.json:
            print(json.dumps(result, indent=2, default=str))
        else:
            if isinstance(result, list):
                print(f"Found {len(result)} entries:")
                for entry in result:
                    print(f"  [{entry.get('id')}] {entry.get('entry_type')}: "
                          f"{entry.get('title')}")
            elif isinstance(result, dict):
                for key, value in result.items():
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
