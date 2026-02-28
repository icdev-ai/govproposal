#!/usr/bin/env python3
# CUI // SP-PROPIN
# Controlled by: GovProposal Portal
# CUI Category: PROPIN
# Distribution: D
# POC: GovProposal System Administrator
"""Document Template Engine — Manage and apply proposal formatting templates.

Creates, manages, and applies document templates for government proposals.
Supports agency-specific formatting rules (fonts, margins, spacing, headers),
Jinja2 template rendering with {{variable}} fallback, page estimation,
and a default seed library of standard government proposal formats.

Usage:
    python tools/production/template_engine.py --list [--type proposal] [--agency "DoD"] --json
    python tools/production/template_engine.py --get --template-id "TMPL-abc" --json
    python tools/production/template_engine.py --get --name "dod_standard" --json
    python tools/production/template_engine.py --create --name "custom" --type proposal --content-file /path/to/template.txt [--agency "DIA"] --json
    python tools/production/template_engine.py --apply --proposal-id "PROP-123" [--template dod_standard] --json
    python tools/production/template_engine.py --render --template-id "TMPL-abc" --variables '{"title": "My Proposal"}' --json
    python tools/production/template_engine.py --seed --json
    python tools/production/template_engine.py --estimate-pages --content "..." --rules '{"font_size": 12, "margins": {"top": 1}}' --json
"""

import argparse
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

try:
    import jinja2
except ImportError:
    jinja2 = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _tmpl_id():
    """Generate a template ID: TMPL- followed by 12 hex characters."""
    return "TMPL-" + secrets.token_hex(6)


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
            "template_engine",
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


def _ensure_columns(conn):
    """Add classification and updated_at columns if missing (migration-safe)."""
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(templates)")}
    if "classification" not in cols:
        conn.execute(
            "ALTER TABLE templates ADD COLUMN classification TEXT "
            "DEFAULT 'CUI // SP-PROPIN'"
        )
    if "updated_at" not in cols:
        conn.execute(
            "ALTER TABLE templates ADD COLUMN updated_at TEXT"
        )
    # Ensure name has UNIQUE-like behavior via code (cannot ALTER existing constraint)
    conn.commit()


# ---------------------------------------------------------------------------
# Core functions
# ---------------------------------------------------------------------------

def list_templates(template_type=None, agency=None, db_path=None):
    """List available templates, optionally filtered by type or agency.

    Args:
        template_type: Filter by template_type (proposal, volume, section, etc.).
        agency: Filter by agency name (case-insensitive LIKE match).
        db_path: Optional database path override.

    Returns:
        dict with templates list and count.
    """
    conn = _get_db(db_path)
    _ensure_columns(conn)
    try:
        query = "SELECT * FROM templates WHERE is_active = 1"
        params = []
        if template_type:
            query += " AND template_type = ?"
            params.append(template_type)
        if agency:
            query += " AND agency LIKE ?"
            params.append(f"%{agency}%")
        query += " ORDER BY template_type, name"
        rows = conn.execute(query, params).fetchall()
        templates = []
        for r in rows:
            t = _row_to_dict(r)
            t["format_rules"] = _parse_json_field(t.get("format_rules"))
            templates.append(t)
        return {"templates": templates, "count": len(templates)}
    finally:
        conn.close()


def get_template(template_id=None, name=None, db_path=None):
    """Get a specific template by ID or name.

    Args:
        template_id: Template ID (TMPL-...).
        name: Template name (unique lookup).
        db_path: Optional database path override.

    Returns:
        dict with template data, or error if not found.
    """
    if not template_id and not name:
        return {"error": "Either --template-id or --name is required"}
    conn = _get_db(db_path)
    _ensure_columns(conn)
    try:
        if template_id:
            row = conn.execute(
                "SELECT * FROM templates WHERE id = ?", (template_id,)
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT * FROM templates WHERE name = ?", (name,)
            ).fetchone()
        if row is None:
            lookup = template_id or name
            return {"error": f"Template not found: {lookup}"}
        t = _row_to_dict(row)
        t["format_rules"] = _parse_json_field(t.get("format_rules"))
        return {"template": t}
    finally:
        conn.close()


def create_template(name, template_type, content_template, agency=None,
                    format_rules=None, db_path=None):
    """Create a new document template.

    Args:
        name: Unique template name.
        template_type: One of proposal, volume, section, executive_summary,
                       letter, form.
        content_template: Template content string with {{variable}} placeholders.
        agency: Optional agency association.
        format_rules: Optional dict of formatting rules (font, margins, etc.).
        db_path: Optional database path override.

    Returns:
        dict with created template data.
    """
    valid_types = (
        "proposal", "volume", "section", "executive_summary", "letter", "form"
    )
    if template_type not in valid_types:
        return {"error": f"Invalid template_type: {template_type}. "
                         f"Must be one of: {', '.join(valid_types)}"}

    conn = _get_db(db_path)
    _ensure_columns(conn)
    try:
        # Check for duplicate name
        existing = conn.execute(
            "SELECT id FROM templates WHERE name = ?", (name,)
        ).fetchone()
        if existing:
            return {"error": f"Template with name '{name}' already exists "
                             f"(id: {existing['id']})"}

        tid = _tmpl_id()
        now = _now()
        rules_json = json.dumps(format_rules) if format_rules else None
        conn.execute(
            "INSERT INTO templates (id, name, template_type, agency, "
            "format_rules, content_template, is_active, classification, "
            "created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?, ?)",
            (tid, name, template_type, agency, rules_json, content_template,
             "CUI // SP-PROPIN", now, now),
        )
        _audit(conn, "template.created", f"Created template '{name}'",
               entity_type="template", entity_id=tid,
               details={"template_type": template_type, "agency": agency})
        conn.commit()

        return {
            "created": True,
            "template": {
                "id": tid,
                "name": name,
                "template_type": template_type,
                "agency": agency,
                "format_rules": format_rules,
                "content_template": content_template,
                "is_active": 1,
                "classification": "CUI // SP-PROPIN",
                "created_at": now,
                "updated_at": now,
            },
        }
    finally:
        conn.close()


def update_template(template_id, updates, db_path=None):
    """Update template fields.

    Args:
        template_id: Template ID to update.
        updates: dict of field names to new values.  Allowed fields:
                 name, template_type, agency, format_rules, content_template,
                 is_active, classification.
        db_path: Optional database path override.

    Returns:
        dict with updated template data.
    """
    allowed = {
        "name", "template_type", "agency", "format_rules",
        "content_template", "is_active", "classification",
    }
    filtered = {k: v for k, v in updates.items() if k in allowed}
    if not filtered:
        return {"error": f"No valid fields to update. Allowed: {sorted(allowed)}"}

    conn = _get_db(db_path)
    _ensure_columns(conn)
    try:
        existing = conn.execute(
            "SELECT * FROM templates WHERE id = ?", (template_id,)
        ).fetchone()
        if existing is None:
            return {"error": f"Template not found: {template_id}"}

        # Serialize format_rules if present
        if "format_rules" in filtered and isinstance(filtered["format_rules"], dict):
            filtered["format_rules"] = json.dumps(filtered["format_rules"])

        # Build UPDATE
        set_clauses = [f"{k} = ?" for k in filtered]
        set_clauses.append("updated_at = ?")
        values = list(filtered.values())
        now = _now()
        values.append(now)
        values.append(template_id)

        conn.execute(
            f"UPDATE templates SET {', '.join(set_clauses)} WHERE id = ?",
            values,
        )
        _audit(conn, "template.updated",
               f"Updated template '{template_id}' fields: {list(filtered.keys())}",
               entity_type="template", entity_id=template_id,
               details={"fields_changed": list(filtered.keys())})
        conn.commit()

        # Re-fetch
        row = conn.execute(
            "SELECT * FROM templates WHERE id = ?", (template_id,)
        ).fetchone()
        t = _row_to_dict(row)
        t["format_rules"] = _parse_json_field(t.get("format_rules"))
        return {"updated": True, "template": t}
    finally:
        conn.close()


def render_section(template_id, variables, db_path=None):
    """Render a single template with the given variables.

    Uses Jinja2 if available, otherwise falls back to simple regex
    {{variable}} replacement.

    Args:
        template_id: Template ID to render.
        variables: dict of variable names to values.
        db_path: Optional database path override.

    Returns:
        dict with rendered content.
    """
    conn = _get_db(db_path)
    _ensure_columns(conn)
    try:
        row = conn.execute(
            "SELECT * FROM templates WHERE id = ?", (template_id,)
        ).fetchone()
        if row is None:
            return {"error": f"Template not found: {template_id}"}

        tmpl_data = _row_to_dict(row)
        raw = tmpl_data.get("content_template") or ""

        rendered = _render_content(raw, variables)

        return {
            "rendered": True,
            "template_id": template_id,
            "template_name": tmpl_data["name"],
            "content": rendered,
            "variables_used": list(variables.keys()),
            "engine": "jinja2" if jinja2 else "regex",
        }
    finally:
        conn.close()


def _render_content(template_str, variables):
    """Render a template string with variables using Jinja2 or regex fallback."""
    if not template_str:
        return ""
    if jinja2:
        env = jinja2.Environment(
            undefined=jinja2.Undefined,
            autoescape=False,
        )
        tmpl = env.from_string(template_str)
        return tmpl.render(**variables)
    else:
        # Simple regex {{var}} replacement
        def _replace(match):
            key = match.group(1).strip()
            return str(variables.get(key, match.group(0)))
        return re.sub(r"\{\{(\s*\w+\s*)\}\}", _replace, template_str)


def apply_template(proposal_id, template_name=None, db_path=None):
    """Apply a template to a proposal, formatting all its sections.

    If no template_name is given, auto-detects by matching the proposal's
    opportunity agency against available templates.

    Args:
        proposal_id: Proposal ID to format.
        template_name: Optional template name override.
        db_path: Optional database path override.

    Returns:
        dict with application results.
    """
    conn = _get_db(db_path)
    _ensure_columns(conn)
    try:
        # Load proposal
        prop_row = conn.execute(
            "SELECT * FROM proposals WHERE id = ?", (proposal_id,)
        ).fetchone()
        if prop_row is None:
            return {"error": f"Proposal not found: {proposal_id}"}
        proposal = _row_to_dict(prop_row)

        # Load opportunity for agency info
        opp = None
        if proposal.get("opportunity_id"):
            opp_row = conn.execute(
                "SELECT * FROM opportunities WHERE id = ?",
                (proposal["opportunity_id"],),
            ).fetchone()
            if opp_row:
                opp = _row_to_dict(opp_row)

        agency = opp["agency"] if opp else None
        solicitation_number = opp.get("solicitation_number", "") if opp else ""

        # Resolve template
        tmpl = None
        if template_name:
            tmpl_row = conn.execute(
                "SELECT * FROM templates WHERE name = ? AND is_active = 1",
                (template_name,),
            ).fetchone()
            if tmpl_row:
                tmpl = _row_to_dict(tmpl_row)
        if tmpl is None and agency:
            # Auto-detect: look for agency-matching template
            tmpl_row = conn.execute(
                "SELECT * FROM templates WHERE agency LIKE ? AND is_active = 1 "
                "AND template_type = 'proposal' ORDER BY created_at DESC LIMIT 1",
                (f"%{agency}%",),
            ).fetchone()
            if tmpl_row:
                tmpl = _row_to_dict(tmpl_row)
        if tmpl is None:
            # Fall back to any active proposal template
            tmpl_row = conn.execute(
                "SELECT * FROM templates WHERE template_type = 'proposal' "
                "AND is_active = 1 ORDER BY created_at DESC LIMIT 1",
            ).fetchone()
            if tmpl_row:
                tmpl = _row_to_dict(tmpl_row)
        if tmpl is None:
            return {"error": "No active template found. Run --seed first."}

        format_rules = _parse_json_field(tmpl.get("format_rules")) or {}
        content_tmpl = tmpl.get("content_template") or ""

        # Load sections
        sections = conn.execute(
            "SELECT * FROM proposal_sections WHERE proposal_id = ? "
            "ORDER BY volume, section_number",
            (proposal_id,),
        ).fetchall()
        sections = [_row_to_dict(r) for r in sections]

        sections_formatted = 0
        for sec in sections:
            # Build variable context for this section
            variables = {
                "proposal_title": proposal.get("title", ""),
                "agency": agency or "",
                "solicitation_number": solicitation_number,
                "date": _now()[:10],
                "classification": proposal.get("classification",
                                               "CUI // SP-PROPIN"),
                "volume_name": sec.get("volume", ""),
                "section_number": sec.get("section_number", ""),
                "section_title": sec.get("section_title", ""),
                "content": sec.get("content", ""),
            }

            # Render content through template if template has content
            if content_tmpl:
                rendered = _render_content(content_tmpl, variables)
                # Only update content if template actually produced output
                if rendered.strip() and rendered.strip() != content_tmpl.strip():
                    sec["content"] = rendered

            # Estimate word/page counts based on format_rules
            text = sec.get("content") or ""
            word_count = len(text.split())
            page_count = _estimate_page_count(text, format_rules)

            # Update section in DB
            conn.execute(
                "UPDATE proposal_sections SET word_count = ?, page_count = ?, "
                "updated_at = ? WHERE id = ?",
                (word_count, round(page_count, 2), _now(), sec["id"]),
            )
            sections_formatted += 1

        _audit(conn, "template.applied",
               f"Applied template '{tmpl['name']}' to proposal '{proposal_id}'",
               entity_type="proposal", entity_id=proposal_id,
               details={
                   "template_id": tmpl["id"],
                   "template_name": tmpl["name"],
                   "sections_formatted": sections_formatted,
                   "format_rules": format_rules,
               })
        conn.commit()

        return {
            "applied": True,
            "template_name": tmpl["name"],
            "template_id": tmpl["id"],
            "proposal_id": proposal_id,
            "sections_formatted": sections_formatted,
            "format_rules_applied": format_rules,
        }
    finally:
        conn.close()


def estimate_pages(content, format_rules, db_path=None):
    """Estimate page count from content and format rules.

    Calculates words per page based on font size, margins, and line spacing,
    then divides total word count by words per page.

    Args:
        content: Text content to estimate.
        format_rules: dict with font_size, margins, line_spacing, etc.
        db_path: Unused, present for API consistency.

    Returns:
        dict with word_count, estimated_pages, words_per_page, and rules used.
    """
    if not content:
        return {
            "word_count": 0,
            "estimated_pages": 0.0,
            "words_per_page": 0,
            "format_rules_used": format_rules or {},
        }

    rules = format_rules or {}
    word_count = len(content.split())
    wpp = _words_per_page(rules)
    pages = word_count / wpp if wpp > 0 else 0.0

    return {
        "word_count": word_count,
        "estimated_pages": round(pages, 2),
        "words_per_page": wpp,
        "format_rules_used": rules,
    }


def _estimate_page_count(text, format_rules):
    """Internal helper: estimate pages from text and rules."""
    if not text:
        return 0.0
    word_count = len(text.split())
    wpp = _words_per_page(format_rules)
    if wpp <= 0:
        return 0.0
    return word_count / wpp


def _words_per_page(rules):
    """Calculate approximate words per page from format rules.

    Standard 8.5 x 11 inch page. Default assumptions:
      - 12pt font ~ 250 words/page single-spaced with 1-inch margins
      - Adjust for font size, margins, and line spacing.
    """
    font_size = rules.get("font_size", 12)
    margins = rules.get("margins", {})
    top = margins.get("top", 1.0)
    bottom = margins.get("bottom", 1.0)
    left = margins.get("left", 1.0)
    right = margins.get("right", 1.0)
    line_spacing = rules.get("line_spacing", 1.0)

    # Usable area (inches)
    usable_width = max(8.5 - left - right, 1.0)
    usable_height = max(11.0 - top - bottom, 1.0)

    # Characters per line: ~10 chars per inch at 12pt, scale by font ratio
    chars_per_inch = 10.0 * (12.0 / max(font_size, 6))
    chars_per_line = usable_width * chars_per_inch

    # Lines per page: ~6 lines per inch at 12pt single-spaced
    lines_per_inch = 6.0 * (12.0 / max(font_size, 6)) / max(line_spacing, 0.5)
    lines_per_page = usable_height * lines_per_inch

    # Average word length ~5 chars + 1 space = 6 chars
    words_per_line = max(chars_per_line / 6.0, 1)
    words_per_page = int(words_per_line * lines_per_page)

    return max(words_per_page, 50)  # Floor at 50 to avoid division issues


def seed_default_templates(db_path=None):
    """Seed the standard government proposal templates.

    Creates 6 default templates:
      - dod_standard: DoD standard proposal format
      - gsa_schedule: GSA Schedule format
      - civilian_standard: Civilian agency standard
      - sbir_phase1: SBIR Phase I format
      - sbir_phase2: SBIR Phase II format
      - letter_proposal: Short-form letter proposal

    Returns:
        dict with seeded template names and counts.
    """
    defaults = [
        {
            "name": "dod_standard",
            "template_type": "proposal",
            "agency": "DoD",
            "format_rules": {
                "font": "Times New Roman",
                "font_size": 12,
                "margins": {"top": 1, "bottom": 1, "left": 1, "right": 1},
                "line_spacing": 1.15,
                "page_limit": None,
                "header": "CUI // SP-PROPIN",
                "footer": "Page {{page}} of {{total_pages}}",
            },
            "content_template": (
                "{{classification}}\n\n"
                "{{proposal_title}}\n"
                "Solicitation: {{solicitation_number}}\n"
                "Agency: {{agency}}\n"
                "Date: {{date}}\n\n"
                "Volume: {{volume_name}}\n"
                "Section {{section_number}}: {{section_title}}\n\n"
                "{{content}}\n\n"
                "{{classification}}"
            ),
        },
        {
            "name": "gsa_schedule",
            "template_type": "proposal",
            "agency": "GSA",
            "format_rules": {
                "font": "Arial",
                "font_size": 11,
                "margins": {"top": 1, "bottom": 1, "left": 1, "right": 1},
                "line_spacing": 1.0,
                "page_limit": None,
                "header": "GSA Schedule Proposal",
                "footer": "Page {{page}} of {{total_pages}}",
            },
            "content_template": (
                "{{proposal_title}}\n"
                "GSA Schedule Proposal\n"
                "Solicitation: {{solicitation_number}}\n"
                "Date: {{date}}\n\n"
                "{{section_number}} {{section_title}}\n\n"
                "{{content}}"
            ),
        },
        {
            "name": "civilian_standard",
            "template_type": "proposal",
            "agency": None,
            "format_rules": {
                "font": "Times New Roman",
                "font_size": 12,
                "margins": {"top": 1, "bottom": 1, "left": 1, "right": 1},
                "line_spacing": 1.15,
                "page_limit": None,
                "header": "{{classification}}",
                "footer": "Page {{page}} of {{total_pages}}",
            },
            "content_template": (
                "{{classification}}\n\n"
                "{{proposal_title}}\n"
                "Solicitation: {{solicitation_number}}\n"
                "Submitted to: {{agency}}\n"
                "Date: {{date}}\n\n"
                "{{volume_name}} - Section {{section_number}}: "
                "{{section_title}}\n\n"
                "{{content}}\n\n"
                "{{classification}}"
            ),
        },
        {
            "name": "sbir_phase1",
            "template_type": "proposal",
            "agency": None,
            "format_rules": {
                "font": "Times New Roman",
                "font_size": 11,
                "margins": {"top": 1, "bottom": 1, "left": 1, "right": 1},
                "line_spacing": 1.0,
                "page_limit": 25,
                "header": "SBIR Phase I Proposal",
                "footer": "Page {{page}} of {{total_pages}} (Limit: 25)",
            },
            "content_template": (
                "SBIR Phase I Proposal\n"
                "Topic: {{solicitation_number}}\n"
                "{{proposal_title}}\n"
                "Date: {{date}}\n\n"
                "{{section_number}}. {{section_title}}\n\n"
                "{{content}}"
            ),
        },
        {
            "name": "sbir_phase2",
            "template_type": "proposal",
            "agency": None,
            "format_rules": {
                "font": "Times New Roman",
                "font_size": 11,
                "margins": {"top": 1, "bottom": 1, "left": 1, "right": 1},
                "line_spacing": 1.0,
                "page_limit": 50,
                "header": "SBIR Phase II Proposal",
                "footer": "Page {{page}} of {{total_pages}} (Limit: 50)",
            },
            "content_template": (
                "SBIR Phase II Proposal\n"
                "Topic: {{solicitation_number}}\n"
                "{{proposal_title}}\n"
                "Agency: {{agency}}\n"
                "Date: {{date}}\n\n"
                "{{section_number}}. {{section_title}}\n\n"
                "{{content}}"
            ),
        },
        {
            "name": "letter_proposal",
            "template_type": "letter",
            "agency": None,
            "format_rules": {
                "font": "Times New Roman",
                "font_size": 12,
                "margins": {"top": 1.25, "bottom": 1.25,
                             "left": 1.25, "right": 1.25},
                "line_spacing": 1.15,
                "page_limit": 10,
                "header": "",
                "footer": "Page {{page}} of {{total_pages}}",
            },
            "content_template": (
                "{{date}}\n\n"
                "Re: {{solicitation_number}} - {{proposal_title}}\n\n"
                "Dear Contracting Officer,\n\n"
                "{{content}}\n\n"
                "Respectfully submitted,\n"
                "[Authorized Representative]"
            ),
        },
    ]

    conn = _get_db(db_path)
    _ensure_columns(conn)
    try:
        seeded = []
        skipped = []
        for d in defaults:
            existing = conn.execute(
                "SELECT id FROM templates WHERE name = ?", (d["name"],)
            ).fetchone()
            if existing:
                skipped.append(d["name"])
                continue
            tid = _tmpl_id()
            now = _now()
            conn.execute(
                "INSERT INTO templates (id, name, template_type, agency, "
                "format_rules, content_template, is_active, classification, "
                "created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?, ?)",
                (
                    tid, d["name"], d["template_type"], d["agency"],
                    json.dumps(d["format_rules"]), d["content_template"],
                    "CUI // SP-PROPIN", now, now,
                ),
            )
            seeded.append(d["name"])

        if seeded:
            _audit(conn, "template.seeded",
                   f"Seeded {len(seeded)} default templates",
                   entity_type="template", entity_id=None,
                   details={"seeded": seeded, "skipped": skipped})
        conn.commit()

        return {
            "seeded": seeded,
            "skipped": skipped,
            "total_seeded": len(seeded),
            "total_skipped": len(skipped),
        }
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Document Template Engine — manage and apply proposal "
                    "formatting templates."
    )
    parser.add_argument("--json", action="store_true",
                        help="Output as JSON")
    parser.add_argument("--db-path", help="Override database path")

    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--list", action="store_true",
                       help="List available templates")
    group.add_argument("--get", action="store_true",
                       help="Get a specific template")
    group.add_argument("--create", action="store_true",
                       help="Create a new template")
    group.add_argument("--apply", action="store_true",
                       help="Apply template to a proposal")
    group.add_argument("--render", action="store_true",
                       help="Render a template with variables")
    group.add_argument("--seed", action="store_true",
                       help="Seed default templates")
    group.add_argument("--estimate-pages", action="store_true",
                       help="Estimate page count from content and rules")
    group.add_argument("--update", action="store_true",
                       help="Update an existing template")

    # Filters
    parser.add_argument("--type", dest="template_type",
                        help="Filter by template type")
    parser.add_argument("--agency", help="Filter by agency")

    # Get/render/update identifiers
    parser.add_argument("--template-id", help="Template ID")
    parser.add_argument("--name", help="Template name")

    # Create args
    parser.add_argument("--content-file", help="Path to template content file")
    parser.add_argument("--content-text",
                        help="Inline template content string")
    parser.add_argument("--format-rules",
                        help="JSON string of format rules")

    # Apply args
    parser.add_argument("--proposal-id", help="Proposal ID")
    parser.add_argument("--template", help="Template name for apply")

    # Render args
    parser.add_argument("--variables", help="JSON string of variables")

    # Estimate args
    parser.add_argument("--content", help="Content text for estimation")
    parser.add_argument("--rules", help="JSON rules for estimation")

    # Update args
    parser.add_argument("--updates", help="JSON string of field updates")

    args = parser.parse_args()
    db = args.db_path

    try:
        if args.list:
            result = list_templates(
                template_type=args.template_type, agency=args.agency,
                db_path=db,
            )

        elif args.get:
            result = get_template(
                template_id=args.template_id, name=args.name, db_path=db,
            )

        elif args.create:
            # Load content
            content = ""
            if args.content_file:
                content = Path(args.content_file).read_text(encoding="utf-8")
            elif args.content_text:
                content = args.content_text
            if not args.name:
                result = {"error": "--name is required for --create"}
            elif not args.template_type:
                result = {"error": "--type is required for --create"}
            else:
                rules = None
                if args.format_rules:
                    rules = json.loads(args.format_rules)
                result = create_template(
                    name=args.name,
                    template_type=args.template_type,
                    content_template=content,
                    agency=args.agency,
                    format_rules=rules,
                    db_path=db,
                )

        elif args.update:
            if not args.template_id:
                result = {"error": "--template-id is required for --update"}
            elif not args.updates:
                result = {"error": "--updates JSON is required for --update"}
            else:
                updates = json.loads(args.updates)
                result = update_template(
                    template_id=args.template_id, updates=updates, db_path=db,
                )

        elif args.apply:
            if not args.proposal_id:
                result = {"error": "--proposal-id is required for --apply"}
            else:
                result = apply_template(
                    proposal_id=args.proposal_id,
                    template_name=args.template,
                    db_path=db,
                )

        elif args.render:
            if not args.template_id:
                result = {"error": "--template-id is required for --render"}
            else:
                variables = {}
                if args.variables:
                    variables = json.loads(args.variables)
                result = render_section(
                    template_id=args.template_id, variables=variables,
                    db_path=db,
                )

        elif args.seed:
            result = seed_default_templates(db_path=db)

        elif args.estimate_pages:
            content = args.content or ""
            rules = {}
            if args.rules:
                rules = json.loads(args.rules)
            result = estimate_pages(content=content, format_rules=rules)

        else:
            result = {"error": "No action specified"}

    except json.JSONDecodeError as e:
        result = {"error": f"Invalid JSON input: {e}"}
    except Exception as e:
        result = {"error": str(e)}

    if args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        # Human-readable output
        if "error" in result:
            print(f"ERROR: {result['error']}", file=sys.stderr)
            sys.exit(1)
        elif "templates" in result:
            print(f"Templates ({result['count']}):")
            for t in result["templates"]:
                agency_str = f" [{t.get('agency', '')}]" if t.get("agency") else ""
                print(f"  {t['id']}  {t['name']} ({t['template_type']}){agency_str}")
        elif "template" in result:
            t = result["template"]
            print(f"Template: {t['name']}")
            print(f"  ID:   {t['id']}")
            print(f"  Type: {t['template_type']}")
            print(f"  Agency: {t.get('agency', '(none)')}")
            if t.get("format_rules"):
                print(f"  Rules: {json.dumps(t['format_rules'], indent=4)}")
        elif "applied" in result:
            print(f"Applied template '{result['template_name']}' "
                  f"to proposal '{result['proposal_id']}'")
            print(f"  Sections formatted: {result['sections_formatted']}")
        elif "rendered" in result:
            print(f"Rendered ({result['engine']} engine):")
            print(result["content"])
        elif "seeded" in result:
            print(f"Seeded {result['total_seeded']} templates: "
                  f"{', '.join(result['seeded']) or '(none)'}")
            if result["skipped"]:
                print(f"Skipped {result['total_skipped']} existing: "
                      f"{', '.join(result['skipped'])}")
        elif "word_count" in result:
            print(f"Word count: {result['word_count']}")
            print(f"Estimated pages: {result['estimated_pages']}")
            print(f"Words per page: {result['words_per_page']}")
        elif "updated" in result:
            print(f"Updated template: {result['template']['id']}")
        else:
            print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
