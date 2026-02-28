#!/usr/bin/env python3
# CUI // SP-PROPIN
# Controlled by: GovProposal Portal
# CUI Category: PROPIN
# Distribution: D
# POC: GovProposal System Administrator
"""Proposal Auto-Formatter — Formatting, page estimation, and compliance checks.

Calculates word counts, estimates page counts from format rules, checks page
limits, normalizes section numbering, and runs pre-submission formatting checks
for government proposals.

Usage:
    python tools/production/formatter.py --format --proposal-id PROP-001 --json
    python tools/production/formatter.py --check-limits --proposal-id PROP-001 --json
    python tools/production/formatter.py --word-count --proposal-id PROP-001 --json
    python tools/production/formatter.py --normalize --proposal-id PROP-001 --json
    python tools/production/formatter.py --apply-rules --proposal-id PROP-001 --rules '{"font_size": 12}' --json
    python tools/production/formatter.py --format-check --proposal-id PROP-001 --json
"""

import json
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

try:
    from docx import Document
    from docx.shared import Inches, Pt, Cm, RGBColor
    from docx.enum.text import WD_ALIGN_PARAGRAPH
except ImportError:
    Document = None

# ---------------------------------------------------------------------------
# Default government formatting rules
# ---------------------------------------------------------------------------

DEFAULT_FORMAT_RULES = {
    "body_font": "Times New Roman",
    "body_font_size": 12,
    "heading_font": "Arial",
    "heading_font_size": 14,
    "margin_top": 1.0,
    "margin_bottom": 1.0,
    "margin_left": 1.0,
    "margin_right": 1.0,
    "line_spacing": 1.15,
    "words_per_page": 250,
    "page_numbering": "Page X of Y",
    "cui_header": "CUI // SP-PROPIN",
    "cui_footer": "CUI // SP-PROPIN",
    "section_numbering_style": "decimal",
    "header_levels": 3,
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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
        (
            event_type,
            "formatter",
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


def _load_proposal(conn, proposal_id):
    """Load proposal record and raise if not found."""
    row = conn.execute(
        "SELECT * FROM proposals WHERE id = ?", (proposal_id,)
    ).fetchone()
    if row is None:
        raise ValueError(f"Proposal not found: {proposal_id}")
    return _row_to_dict(row)


def _load_sections(conn, proposal_id):
    """Load all proposal sections ordered by volume and section number."""
    rows = conn.execute(
        "SELECT * FROM proposal_sections WHERE proposal_id = ? "
        "ORDER BY volume, section_number",
        (proposal_id,),
    ).fetchall()
    return [_row_to_dict(r) for r in rows]


def _load_format_rules(conn, template_name=None):
    """Load format rules from a named template, or return defaults."""
    if template_name:
        row = conn.execute(
            "SELECT format_rules FROM templates WHERE name = ? AND is_active = 1",
            (template_name,),
        ).fetchone()
        if row and row["format_rules"]:
            parsed = _parse_json_field(row["format_rules"])
            if isinstance(parsed, dict):
                merged = dict(DEFAULT_FORMAT_RULES)
                merged.update(parsed)
                return merged
    return dict(DEFAULT_FORMAT_RULES)


def _count_words(text):
    """Count words in a text string."""
    if not text:
        return 0
    return len(text.split())


# ---------------------------------------------------------------------------
# Core functions
# ---------------------------------------------------------------------------

def estimate_pages_from_rules(word_count, format_rules=None):
    """Estimate page count from word count and format rules.

    Adjusts the base words-per-page (default 250 for 12pt TNR single-spaced,
    1-inch margins) based on font size, line spacing, and margin changes.

    Args:
        word_count: Number of words.
        format_rules: Optional dict of format rules.

    Returns:
        float: Estimated page count rounded to 1 decimal place.
    """
    if word_count <= 0:
        return 0.0
    rules = format_rules or DEFAULT_FORMAT_RULES
    base_wpp = rules.get("words_per_page", 250)
    font_size = rules.get("body_font_size", 12)
    line_spacing = rules.get("line_spacing", 1.15)
    margin_left = rules.get("margin_left", 1.0)
    margin_right = rules.get("margin_right", 1.0)
    margin_top = rules.get("margin_top", 1.0)
    margin_bottom = rules.get("margin_bottom", 1.0)

    # Scale words-per-page by font size (baseline 12pt)
    font_factor = 12.0 / max(font_size, 6)
    # Scale by line spacing (baseline 1.0)
    spacing_factor = 1.0 / max(line_spacing, 0.5)
    # Scale by usable page area (baseline 6.5" x 9" for letter with 1" margins)
    usable_width = max(8.5 - margin_left - margin_right, 1.0)
    usable_height = max(11.0 - margin_top - margin_bottom, 1.0)
    area_factor = (usable_width * usable_height) / (6.5 * 9.0)

    adjusted_wpp = base_wpp * font_factor * spacing_factor * area_factor
    adjusted_wpp = max(adjusted_wpp, 50)
    pages = word_count / adjusted_wpp
    return round(pages, 1)


def format_proposal(proposal_id, template_name=None, db_path=None):
    """Format entire proposal: calculate word counts and estimate page counts.

    Args:
        proposal_id: Proposal ID.
        template_name: Optional template name for format rules.
        db_path: Optional database path override.

    Returns:
        dict with formatted status and per-volume breakdown.
    """
    conn = _get_db(db_path)
    try:
        proposal = _load_proposal(conn, proposal_id)
        sections = _load_sections(conn, proposal_id)
        rules = _load_format_rules(conn, template_name)

        if not sections:
            return {
                "formatted": True,
                "proposal_id": proposal_id,
                "volumes": [],
                "message": "No sections found",
            }

        volumes = {}
        for sec in sections:
            content = sec.get("content") or ""
            wc = _count_words(content)
            pc = estimate_pages_from_rules(wc, rules)

            conn.execute(
                "UPDATE proposal_sections SET word_count = ?, page_count = ?, "
                "updated_at = ? WHERE id = ?",
                (wc, pc, _now(), sec["id"]),
            )

            vol = sec.get("volume", "unknown")
            if vol not in volumes:
                volumes[vol] = {"volume": vol, "sections_formatted": 0,
                                "total_words": 0, "total_pages": 0.0}
            volumes[vol]["sections_formatted"] += 1
            volumes[vol]["total_words"] += wc
            volumes[vol]["total_pages"] = round(
                volumes[vol]["total_pages"] + pc, 1)

        _audit(conn, "format.complete", f"Formatted proposal {proposal_id}",
               "proposal", proposal_id,
               {"template": template_name, "sections": len(sections)})
        conn.commit()

        return {
            "formatted": True,
            "proposal_id": proposal_id,
            "volumes": list(volumes.values()),
        }
    finally:
        conn.close()


def check_page_limits(proposal_id, db_path=None):
    """Check all sections against their page limits.

    Args:
        proposal_id: Proposal ID.
        db_path: Optional database path override.

    Returns:
        dict with compliance status and per-section breakdown.
    """
    conn = _get_db(db_path)
    try:
        _load_proposal(conn, proposal_id)
        sections = _load_sections(conn, proposal_id)
        results = []
        all_compliant = True

        for sec in sections:
            limit = sec.get("page_limit") or 0
            pages = sec.get("page_count") or 0.0
            if limit and limit > 0:
                over_by = round(max(pages - limit, 0), 1)
                status = "within_limit" if pages <= limit else "over_limit"
                if status == "over_limit":
                    all_compliant = False
                results.append({
                    "section_number": sec["section_number"],
                    "title": sec["section_title"],
                    "pages": pages,
                    "limit": limit,
                    "status": status,
                    "over_by": over_by,
                })

        return {
            "proposal_id": proposal_id,
            "compliant": all_compliant,
            "sections": results,
        }
    finally:
        conn.close()


def word_count_report(proposal_id, db_path=None):
    """Generate detailed word count report by volume and section.

    Args:
        proposal_id: Proposal ID.
        db_path: Optional database path override.

    Returns:
        dict with per-volume and per-section word/page counts.
    """
    conn = _get_db(db_path)
    try:
        _load_proposal(conn, proposal_id)
        sections = _load_sections(conn, proposal_id)

        volumes = {}
        grand_words = 0
        grand_pages = 0.0

        for sec in sections:
            vol = sec.get("volume", "unknown")
            wc = sec.get("word_count") or 0
            pc = sec.get("page_count") or 0.0
            if vol not in volumes:
                volumes[vol] = {"volume": vol, "total_words": 0,
                                "total_pages": 0.0, "sections": []}
            volumes[vol]["sections"].append({
                "number": sec["section_number"],
                "title": sec["section_title"],
                "words": wc,
                "pages": pc,
            })
            volumes[vol]["total_words"] += wc
            volumes[vol]["total_pages"] = round(
                volumes[vol]["total_pages"] + pc, 1)
            grand_words += wc
            grand_pages += pc

        return {
            "proposal_id": proposal_id,
            "volumes": list(volumes.values()),
            "grand_total_words": grand_words,
            "grand_total_pages": round(grand_pages, 1),
        }
    finally:
        conn.close()


def normalize_section_numbering(proposal_id, db_path=None):
    """Fix section numbering: resequence per volume.

    Assigns top-level numbers per volume (1.0, 2.0, ...) and subsections
    (1.1, 1.2, 2.1, ...) based on existing ordering.

    Args:
        proposal_id: Proposal ID.
        db_path: Optional database path override.

    Returns:
        dict with renumbering results.
    """
    conn = _get_db(db_path)
    try:
        _load_proposal(conn, proposal_id)
        sections = _load_sections(conn, proposal_id)

        if not sections:
            return {"proposal_id": proposal_id, "renumbered": [],
                    "total_sections": 0}

        # Group by volume
        by_volume = {}
        for sec in sections:
            vol = sec.get("volume", "unknown")
            by_volume.setdefault(vol, []).append(sec)

        renumbered = []
        for vol, vol_sections in by_volume.items():
            # Determine hierarchy from existing numbering depth
            major = 0
            minor = 0
            for sec in vol_sections:
                old_num = sec["section_number"]
                parts = str(old_num).split(".")
                depth = len(parts)
                if depth <= 1:
                    major += 1
                    minor = 0
                    new_num = f"{major}.0"
                else:
                    minor += 1
                    new_num = f"{major}.{minor}"

                if new_num != old_num:
                    renumbered.append({
                        "old": old_num,
                        "new": new_num,
                        "title": sec["section_title"],
                    })
                conn.execute(
                    "UPDATE proposal_sections SET section_number = ?, "
                    "updated_at = ? WHERE id = ?",
                    (new_num, _now(), sec["id"]),
                )

        _audit(conn, "format.normalize", f"Renumbered {len(renumbered)} sections",
               "proposal", proposal_id,
               {"renumbered_count": len(renumbered)})
        conn.commit()

        return {
            "proposal_id": proposal_id,
            "renumbered": renumbered,
            "total_sections": len(sections),
        }
    finally:
        conn.close()


def apply_format_rules(proposal_id, rules=None, db_path=None):
    """Apply specific format rules and recalculate page counts.

    Args:
        proposal_id: Proposal ID.
        rules: Optional dict overriding DEFAULT_FORMAT_RULES.
        db_path: Optional database path override.

    Returns:
        dict with applied rules and section update count.
    """
    conn = _get_db(db_path)
    try:
        _load_proposal(conn, proposal_id)
        sections = _load_sections(conn, proposal_id)

        effective_rules = dict(DEFAULT_FORMAT_RULES)
        if rules:
            effective_rules.update(rules)

        updated = 0
        for sec in sections:
            wc = sec.get("word_count") or 0
            pc = estimate_pages_from_rules(wc, effective_rules)
            conn.execute(
                "UPDATE proposal_sections SET page_count = ?, updated_at = ? "
                "WHERE id = ?",
                (pc, _now(), sec["id"]),
            )
            updated += 1

        _audit(conn, "format.apply_rules",
               f"Applied format rules to {updated} sections",
               "proposal", proposal_id,
               {"rules": effective_rules})
        conn.commit()

        return {
            "proposal_id": proposal_id,
            "applied": True,
            "rules_used": effective_rules,
            "sections_updated": updated,
        }
    finally:
        conn.close()


def format_check(proposal_id, db_path=None):
    """Pre-submission formatting check.

    Verifies:
      - All sections have content
      - Word counts are calculated (> 0)
      - Page limits are within bounds
      - Section numbering is consistent (no duplicates per volume)
      - Classification markings present in content

    Args:
        proposal_id: Proposal ID.
        db_path: Optional database path override.

    Returns:
        dict with pass/fail status, individual checks, and warnings.
    """
    conn = _get_db(db_path)
    try:
        proposal = _load_proposal(conn, proposal_id)
        sections = _load_sections(conn, proposal_id)
        checks = []
        warnings = []
        all_passed = True

        # Check 1: sections exist
        if not sections:
            checks.append({"check": "sections_exist", "status": "fail",
                           "details": "No sections found for proposal"})
            all_passed = False
        else:
            checks.append({"check": "sections_exist", "status": "pass",
                           "details": f"{len(sections)} sections found"})

        # Check 2: all sections have content
        empty = [s["section_number"] for s in sections
                 if not (s.get("content") or "").strip()]
        if empty:
            checks.append({"check": "content_present", "status": "fail",
                           "details": f"Empty sections: {', '.join(empty)}"})
            all_passed = False
        else:
            checks.append({"check": "content_present", "status": "pass",
                           "details": "All sections have content"})

        # Check 3: word counts calculated
        no_wc = [s["section_number"] for s in sections
                 if not s.get("word_count")]
        if no_wc:
            checks.append({"check": "word_counts", "status": "fail",
                           "details": f"Missing word counts: {', '.join(no_wc)}"})
            all_passed = False
        else:
            checks.append({"check": "word_counts", "status": "pass",
                           "details": "All sections have word counts"})

        # Check 4: page limits
        limit_result = check_page_limits(proposal_id, db_path)
        over = [s for s in limit_result.get("sections", [])
                if s["status"] == "over_limit"]
        if over:
            details = "; ".join(
                f"{s['section_number']} over by {s['over_by']}p" for s in over)
            checks.append({"check": "page_limits", "status": "fail",
                           "details": details})
            all_passed = False
        else:
            checks.append({"check": "page_limits", "status": "pass",
                           "details": "All sections within page limits"})

        # Check 5: no duplicate section numbers per volume
        by_volume = {}
        for sec in sections:
            vol = sec.get("volume", "unknown")
            num = sec["section_number"]
            by_volume.setdefault(vol, []).append(num)
        dupes = []
        for vol, nums in by_volume.items():
            seen = set()
            for n in nums:
                if n in seen:
                    dupes.append(f"{vol}/{n}")
                seen.add(n)
        if dupes:
            checks.append({"check": "section_numbering", "status": "fail",
                           "details": f"Duplicate numbers: {', '.join(dupes)}"})
            all_passed = False
        else:
            checks.append({"check": "section_numbering", "status": "pass",
                           "details": "No duplicate section numbers"})

        # Check 6: classification markings in content
        classification = proposal.get("classification") or "CUI"
        missing_marking = []
        for sec in sections:
            content = (sec.get("content") or "").upper()
            if classification.upper()[:3] not in content:
                missing_marking.append(sec["section_number"])
        if missing_marking:
            warnings.append(
                f"Sections without classification marking: "
                f"{', '.join(missing_marking)}")

        return {
            "proposal_id": proposal_id,
            "passed": all_passed,
            "checks": checks,
            "warnings": warnings,
        }
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    import argparse
    parser = argparse.ArgumentParser(
        description="Proposal Auto-Formatter")
    parser.add_argument("--format", action="store_true",
                        help="Format entire proposal (word counts + page estimates)")
    parser.add_argument("--check-limits", action="store_true",
                        help="Check page limits for all sections")
    parser.add_argument("--word-count", action="store_true",
                        help="Generate word count report")
    parser.add_argument("--normalize", action="store_true",
                        help="Normalize section numbering")
    parser.add_argument("--apply-rules", action="store_true",
                        help="Apply format rules and recalculate pages")
    parser.add_argument("--format-check", action="store_true",
                        help="Run pre-submission formatting check")
    parser.add_argument("--proposal-id", required=True,
                        help="Proposal ID")
    parser.add_argument("--template", default=None,
                        help="Template name for format rules")
    parser.add_argument("--rules", default=None,
                        help="JSON string of format rules to apply")
    parser.add_argument("--db-path", default=None,
                        help="Database path override")
    parser.add_argument("--json", action="store_true",
                        help="Output as JSON")
    args = parser.parse_args()

    try:
        if args.format:
            result = format_proposal(args.proposal_id, args.template,
                                     args.db_path)
        elif args.check_limits:
            result = check_page_limits(args.proposal_id, args.db_path)
        elif args.word_count:
            result = word_count_report(args.proposal_id, args.db_path)
        elif args.normalize:
            result = normalize_section_numbering(args.proposal_id, args.db_path)
        elif args.apply_rules:
            rules = json.loads(args.rules) if args.rules else None
            result = apply_format_rules(args.proposal_id, rules, args.db_path)
        elif args.format_check:
            result = format_check(args.proposal_id, args.db_path)
        else:
            parser.print_help()
            sys.exit(1)

        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(json.dumps(result, indent=2))

    except ValueError as e:
        err = {"error": str(e)}
        print(json.dumps(err, indent=2), file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        err = {"error": str(e)}
        print(json.dumps(err, indent=2), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
