#!/usr/bin/env python3
# CUI // SP-PROPIN
# Controlled by: GovProposal Portal
# CUI Category: PROPIN
# Distribution: D
# POC: GovProposal System Administrator
"""Cross-Reference and Acronym Validator for GovProposal.

Validates internal cross-references, acronym usage, compliance matrix
references, and figure/table references across proposal sections.

Usage:
    python tools/production/cross_ref_validator.py --validate --proposal-id "PROP-123" --json
    python tools/production/cross_ref_validator.py --cross-refs --proposal-id "PROP-123" --json
    python tools/production/cross_ref_validator.py --acronyms --proposal-id "PROP-123" --json
    python tools/production/cross_ref_validator.py --acronym-list --proposal-id "PROP-123" --json
    python tools/production/cross_ref_validator.py --compliance-refs --proposal-id "PROP-123" --json
    python tools/production/cross_ref_validator.py --figures-tables --proposal-id "PROP-123" --json
    python tools/production/cross_ref_validator.py --add-acronym --acronym "CDRL" --expansion "Contract Data Requirements List" [--domain "contracting"] --json
    python tools/production/cross_ref_validator.py --list-acronyms [--domain "contracting"] --json
"""

import argparse
import json
import os
import re
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

# ---------------------------------------------------------------------------
# Common words to exclude from acronym detection (2-3 letter uppercase words
# that are not acronyms in government proposals)
# ---------------------------------------------------------------------------
COMMON_WORDS = frozenset({
    "IT", "US", "AM", "PM", "OR", "AN", "AS", "AT", "BE", "BY", "DO", "GO",
    "IF", "IN", "IS", "ME", "MY", "NO", "OF", "ON", "SO", "TO", "UP", "WE",
    "OK", "HE", "II", "OH", "OX", "OW", "ALL", "AND", "ARE", "BUT", "CAN",
    "DID", "FOR", "GET", "HAS", "HAD", "HER", "HIM", "HIS", "HOW", "ITS",
    "LET", "MAY", "NEW", "NOT", "NOW", "OLD", "OUR", "OUT", "OWN", "PUT",
    "RUN", "SAY", "SHE", "THE", "TOO", "TWO", "USE", "WAS", "WAY", "WHO",
    "WHY", "YES", "YET", "YOU", "SET", "SEE", "SAW", "TOP", "END",
})

# ---------------------------------------------------------------------------
# Cross-reference regex patterns for government proposals
# ---------------------------------------------------------------------------
# Section references: "See Section 3.2", "refer to Section 3.2.1", etc.
RE_SECTION_REF = re.compile(
    r'(?:see|See|SEE|refer\s+to|Refer\s+to|per|Per|PER|'
    r'described\s+in|Described\s+in|in\s+accordance\s+with|'
    r'In\s+accordance\s+with|as\s+(?:defined|specified|detailed|outlined)\s+in|'
    r'As\s+(?:defined|specified|detailed|outlined)\s+in|'
    r'referenced\s+in|Referenced\s+in|pursuant\s+to|Pursuant\s+to)'
    r'\s+[Ss]ection\s+([\d]+(?:\.[\d]+)*)',
    re.IGNORECASE,
)

# Table references: "Table 1", "Table 3-2"
RE_TABLE_REF = re.compile(r'\b[Tt]able\s+(\d+(?:[-.]\d+)?)\b')

# Figure references: "Figure 1", "Figure 3-2"
RE_FIGURE_REF = re.compile(r'\b[Ff]igure\s+(\d+(?:[-.]\d+)?)\b')

# Appendix references: "Appendix A", "Appendix B-1"
RE_APPENDIX_REF = re.compile(r'\b[Aa]ppendix\s+([A-Z](?:[-.]\d+)?)\b')

# Volume references: "Volume I", "Volume II", "Volume 1"
RE_VOLUME_REF = re.compile(
    r'\b[Vv]olume\s+(I{1,3}V?|VI{0,3}|[1-5])\b'
)

# Table/Figure definitions: "Table 1:", "Table 1.", "Figure 1:"
RE_TABLE_DEF = re.compile(r'\b[Tt]able\s+(\d+(?:[-.]\d+)?)\s*[:.]\s')
RE_FIGURE_DEF = re.compile(r'\b[Ff]igure\s+(\d+(?:[-.]\d+)?)\s*[:.]\s')

# Acronym detection: 2-8 uppercase letters
RE_ACRONYM = re.compile(r'\b([A-Z]{2,8})\b')

# Acronym definition pattern: "Full Name (ACRO)"
RE_ACRONYM_DEF = re.compile(
    r'([A-Z][a-z]+(?:\s+(?:and\s+)?[A-Za-z]+)*)\s*\(([A-Z]{2,8})\)'
)


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
            "cross_ref_validator",
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


def _acr_id():
    """Generate an acronym ID: ACR- followed by 12 hex characters."""
    return "ACR-" + secrets.token_hex(6)


def _get_sections(conn, proposal_id):
    """Fetch all proposal sections for a given proposal."""
    rows = conn.execute(
        "SELECT id, proposal_id, volume, section_number, section_title, "
        "content, content_html FROM proposal_sections "
        "WHERE proposal_id = ? ORDER BY volume, section_number",
        (proposal_id,),
    ).fetchall()
    return [_row_to_dict(r) for r in rows]


# ---------------------------------------------------------------------------
# 1. Cross-Reference Validation
# ---------------------------------------------------------------------------

def validate_cross_references(proposal_id, db_path=None):
    """Find and validate all section cross-references within a proposal.

    Scans section content for patterns like "See Section 3.2",
    "refer to Section 3.2.1", "per Section 4", "in accordance with
    Section 5.1", plus Table/Figure/Appendix/Volume references.

    Returns:
        dict with total_refs, valid_refs, broken_refs list.
    """
    conn = _get_db(db_path)
    try:
        sections = _get_sections(conn, proposal_id)
        if not sections:
            return {"error": f"No sections found for proposal '{proposal_id}'"}

        # Build lookup of existing section numbers
        existing_sections = {s["section_number"] for s in sections if s["section_number"]}

        all_refs = []
        broken_refs = []

        for section in sections:
            content = section.get("content") or section.get("content_html") or ""
            src = section["section_number"]

            # Section references
            for match in RE_SECTION_REF.finditer(content):
                ref_num = match.group(1)
                ref_entry = {
                    "source_section": src,
                    "reference": f"Section {ref_num}",
                    "type": "section",
                    "target": ref_num,
                }
                all_refs.append(ref_entry)
                if ref_num not in existing_sections:
                    ref_entry["issue"] = f"Section {ref_num} does not exist"
                    broken_refs.append(ref_entry)

            # Table references
            for match in RE_TABLE_REF.finditer(content):
                ref_num = match.group(1)
                ref_entry = {
                    "source_section": src,
                    "reference": f"Table {ref_num}",
                    "type": "table",
                    "target": ref_num,
                }
                all_refs.append(ref_entry)

            # Figure references
            for match in RE_FIGURE_REF.finditer(content):
                ref_num = match.group(1)
                ref_entry = {
                    "source_section": src,
                    "reference": f"Figure {ref_num}",
                    "type": "figure",
                    "target": ref_num,
                }
                all_refs.append(ref_entry)

            # Appendix references
            for match in RE_APPENDIX_REF.finditer(content):
                ref_id = match.group(1)
                ref_entry = {
                    "source_section": src,
                    "reference": f"Appendix {ref_id}",
                    "type": "appendix",
                    "target": ref_id,
                }
                all_refs.append(ref_entry)

            # Volume references
            for match in RE_VOLUME_REF.finditer(content):
                ref_id = match.group(1)
                ref_entry = {
                    "source_section": src,
                    "reference": f"Volume {ref_id}",
                    "type": "volume",
                    "target": ref_id,
                }
                all_refs.append(ref_entry)

        valid_count = len(all_refs) - len(broken_refs)

        _audit(conn, "validation.cross_refs",
               f"Cross-reference validation: {len(all_refs)} total, {len(broken_refs)} broken",
               "proposal", proposal_id,
               {"total": len(all_refs), "broken": len(broken_refs)})
        conn.commit()

        return {
            "proposal_id": proposal_id,
            "total_refs": len(all_refs),
            "valid_refs": valid_count,
            "broken_refs": broken_refs,
            "broken_count": len(broken_refs),
            "validated_at": _now(),
        }
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 2. Acronym Validation
# ---------------------------------------------------------------------------

def validate_acronyms(proposal_id, db_path=None):
    """Validate acronym usage across all proposal sections.

    Detects:
      - Undefined acronyms (used but not in acronyms table)
      - First-use violations (acronym used before definition in text)
      - Defined-but-unused acronyms (in table but never referenced)
      - Auto-adds newly defined acronyms from inline definitions

    Returns:
        dict with total_acronyms, defined, undefined, first_use_violations.
    """
    conn = _get_db(db_path)
    try:
        sections = _get_sections(conn, proposal_id)
        if not sections:
            return {"error": f"No sections found for proposal '{proposal_id}'"}

        # Load known acronyms from DB
        known_rows = conn.execute(
            "SELECT acronym, expansion, domain FROM acronyms"
        ).fetchall()
        known_acronyms = {r["acronym"]: r["expansion"] for r in known_rows}

        # Track acronym usage across sections
        acronym_usage = defaultdict(list)     # acronym -> [section_numbers]
        first_occurrence = {}                  # acronym -> section_number
        inline_definitions = {}                # acronym -> expansion (from text)
        first_use_violations = []
        auto_added = []

        for section in sections:
            content = section.get("content") or section.get("content_html") or ""
            sec_num = section["section_number"]

            # Detect inline definitions: "Full Name (ACRO)"
            for match in RE_ACRONYM_DEF.finditer(content):
                expansion = match.group(1).strip()
                acronym = match.group(2)
                if acronym not in COMMON_WORDS:
                    inline_definitions[acronym] = expansion
                    if acronym not in first_occurrence:
                        first_occurrence[acronym] = sec_num

            # Detect all acronym usages
            for match in RE_ACRONYM.finditer(content):
                acronym = match.group(1)
                if acronym in COMMON_WORDS:
                    continue
                acronym_usage[acronym].append(sec_num)
                if acronym not in first_occurrence:
                    first_occurrence[acronym] = sec_num

        # Auto-add inline definitions to DB
        for acronym, expansion in inline_definitions.items():
            if acronym not in known_acronyms:
                try:
                    conn.execute(
                        "INSERT INTO acronyms (id, acronym, expansion, usage_count, created_at) "
                        "VALUES (?, ?, ?, ?, ?)",
                        (_acr_id(), acronym, expansion, len(acronym_usage.get(acronym, [])), _now()),
                    )
                    known_acronyms[acronym] = expansion
                    auto_added.append({"acronym": acronym, "expansion": expansion})
                except sqlite3.IntegrityError:
                    pass  # Already exists (race condition)

        # Update usage counts for known acronyms
        for acronym, sections_used in acronym_usage.items():
            if acronym in known_acronyms:
                conn.execute(
                    "UPDATE acronyms SET usage_count = ? WHERE acronym = ?",
                    (len(sections_used), acronym),
                )

        # Classify results
        all_used = set(acronym_usage.keys())
        defined = all_used & set(known_acronyms.keys())
        undefined = all_used - set(known_acronyms.keys())

        # Check first-use violations: acronym used before its inline definition
        for acronym in all_used:
            if acronym in inline_definitions:
                def_section = None
                # Find the section where the definition pattern appears
                for section in sections:
                    content = section.get("content") or ""
                    if RE_ACRONYM_DEF.search(content) and acronym in content:
                        for m in RE_ACRONYM_DEF.finditer(content):
                            if m.group(2) == acronym:
                                def_section = section["section_number"]
                                break
                    if def_section:
                        break
                # Check if acronym is used in earlier sections without definition
                if def_section and acronym_usage[acronym]:
                    early_uses = [s for s in acronym_usage[acronym] if s < def_section]
                    if early_uses:
                        first_use_violations.append({
                            "acronym": acronym,
                            "section": early_uses[0],
                            "defined_in": def_section,
                            "issue": f"'{acronym}' used in section {early_uses[0]} before definition in section {def_section}",
                        })
            elif acronym not in known_acronyms:
                # Undefined acronym with no inline definition
                first_use_violations.append({
                    "acronym": acronym,
                    "section": first_occurrence.get(acronym, "unknown"),
                    "issue": f"'{acronym}' used without definition",
                })

        # Defined in DB but never used in proposal
        db_only = set(known_acronyms.keys()) - all_used
        unused_acronyms = [{"acronym": a, "expansion": known_acronyms[a]} for a in sorted(db_only)]

        _audit(conn, "validation.acronyms",
               f"Acronym validation: {len(all_used)} used, {len(undefined)} undefined",
               "proposal", proposal_id,
               {"total": len(all_used), "defined": len(defined),
                "undefined": len(undefined), "auto_added": len(auto_added)})
        conn.commit()

        return {
            "proposal_id": proposal_id,
            "total_acronyms": len(all_used),
            "defined": len(defined),
            "undefined": len(undefined),
            "undefined_list": sorted(undefined),
            "first_use_violations": first_use_violations,
            "violation_count": len(first_use_violations),
            "auto_added": auto_added,
            "unused_in_proposal": unused_acronyms[:20],
            "validated_at": _now(),
        }
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 3. Generate Acronym List (Appendix)
# ---------------------------------------------------------------------------

def generate_acronym_list(proposal_id, db_path=None):
    """Generate a sorted acronym appendix for the proposal.

    Collects all acronyms used in the proposal with their expansions
    and the sections where they appear, formatted for appendix inclusion.

    Returns:
        dict with acronyms list and count.
    """
    conn = _get_db(db_path)
    try:
        sections = _get_sections(conn, proposal_id)
        if not sections:
            return {"error": f"No sections found for proposal '{proposal_id}'"}

        # Load known acronyms
        known_rows = conn.execute(
            "SELECT acronym, expansion, domain FROM acronyms"
        ).fetchall()
        known_acronyms = {r["acronym"]: {"expansion": r["expansion"], "domain": r["domain"]}
                          for r in known_rows}

        # Scan sections for acronym usage
        acronym_sections = defaultdict(set)
        for section in sections:
            content = section.get("content") or section.get("content_html") or ""
            sec_num = section["section_number"]
            for match in RE_ACRONYM.finditer(content):
                acronym = match.group(1)
                if acronym not in COMMON_WORDS:
                    acronym_sections[acronym].add(sec_num)

        # Also pick up inline definitions
        for section in sections:
            content = section.get("content") or ""
            for match in RE_ACRONYM_DEF.finditer(content):
                expansion = match.group(1).strip()
                acronym = match.group(2)
                if acronym not in COMMON_WORDS and acronym not in known_acronyms:
                    known_acronyms[acronym] = {"expansion": expansion, "domain": None}

        # Build appendix list
        acronym_list = []
        for acronym in sorted(acronym_sections.keys()):
            info = known_acronyms.get(acronym, {})
            expansion = info.get("expansion", "UNDEFINED")
            used_in = sorted(acronym_sections[acronym])
            acronym_list.append({
                "acronym": acronym,
                "expansion": expansion,
                "domain": info.get("domain"),
                "sections_used": used_in,
            })

        return {
            "proposal_id": proposal_id,
            "acronyms": acronym_list,
            "count": len(acronym_list),
            "generated_at": _now(),
        }
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 4. Compliance Matrix Reference Validation
# ---------------------------------------------------------------------------

def validate_compliance_refs(proposal_id, db_path=None):
    """Validate compliance matrix references point to existing sections.

    For each compliance_matrix entry with a section_number, verifies:
      - The section exists in proposal_sections
      - The section content contains keywords from the requirement text

    Returns:
        dict with total_mappings, verified, unverified, missing_sections.
    """
    conn = _get_db(db_path)
    try:
        # Load compliance matrix entries that have section mappings
        matrix_rows = conn.execute(
            "SELECT id, requirement_id, requirement_text, volume, section_number "
            "FROM compliance_matrices WHERE proposal_id = ? "
            "AND section_number IS NOT NULL AND section_number != ''",
            (proposal_id,),
        ).fetchall()

        if not matrix_rows:
            return {
                "proposal_id": proposal_id,
                "total_mappings": 0,
                "message": "No compliance matrix entries with section mappings found",
            }

        # Build section lookup
        sections = _get_sections(conn, proposal_id)
        section_map = {}
        for s in sections:
            section_map[s["section_number"]] = s

        verified = []
        unverified = []
        missing_sections = []

        for mrow in matrix_rows:
            mdict = _row_to_dict(mrow)
            sec_num = mdict["section_number"]
            req_text = mdict.get("requirement_text") or ""

            if sec_num not in section_map:
                missing_sections.append({
                    "matrix_id": mdict["id"],
                    "requirement_id": mdict["requirement_id"],
                    "section_number": sec_num,
                    "issue": f"Section {sec_num} does not exist",
                })
                continue

            # Basic keyword matching to check if section addresses the requirement
            section_content = (section_map[sec_num].get("content") or "").lower()
            req_keywords = set(re.findall(r'[a-zA-Z]{4,}', req_text.lower()))
            # Remove stopwords
            stopwords = {"shall", "must", "should", "will", "that", "this",
                         "with", "from", "have", "been", "being", "contractor",
                         "offeror", "government", "provide", "include", "ensure"}
            req_keywords -= stopwords

            if not req_keywords:
                verified.append({
                    "matrix_id": mdict["id"],
                    "requirement_id": mdict["requirement_id"],
                    "section_number": sec_num,
                    "keyword_match": True,
                    "match_score": 1.0,
                })
                continue

            matched = sum(1 for kw in req_keywords if kw in section_content)
            score = matched / len(req_keywords) if req_keywords else 0.0

            entry = {
                "matrix_id": mdict["id"],
                "requirement_id": mdict["requirement_id"],
                "section_number": sec_num,
                "keyword_match": score >= 0.2,
                "match_score": round(score, 3),
            }

            if score >= 0.2:
                verified.append(entry)
            else:
                entry["issue"] = (
                    f"Section {sec_num} may not address requirement "
                    f"(keyword match: {round(score * 100)}%)"
                )
                unverified.append(entry)

        _audit(conn, "validation.compliance_refs",
               f"Compliance ref validation: {len(verified)} verified, "
               f"{len(unverified)} unverified, {len(missing_sections)} missing",
               "proposal", proposal_id,
               {"verified": len(verified), "unverified": len(unverified),
                "missing": len(missing_sections)})
        conn.commit()

        return {
            "proposal_id": proposal_id,
            "total_mappings": len(matrix_rows),
            "verified": len(verified),
            "unverified": len(unverified),
            "missing_sections": missing_sections,
            "unverified_details": unverified,
            "verified_details": verified,
            "validated_at": _now(),
        }
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 5. Figure and Table Validation
# ---------------------------------------------------------------------------

def validate_figures_tables(proposal_id, db_path=None):
    """Validate figure and table references against definitions.

    Scans for "Figure X" / "Table X" references and "Figure X:" / "Table X:"
    definitions.  Cross-checks that every reference has a definition and
    every definition is referenced at least once.

    Returns:
        dict with figures and tables sub-dicts containing defined, referenced,
        orphaned, and missing counts.
    """
    conn = _get_db(db_path)
    try:
        sections = _get_sections(conn, proposal_id)
        if not sections:
            return {"error": f"No sections found for proposal '{proposal_id}'"}

        figure_refs = set()
        figure_defs = set()
        table_refs = set()
        table_defs = set()

        for section in sections:
            content = section.get("content") or section.get("content_html") or ""

            # Collect figure references and definitions
            for match in RE_FIGURE_REF.finditer(content):
                figure_refs.add(match.group(1))
            for match in RE_FIGURE_DEF.finditer(content):
                figure_defs.add(match.group(1))

            # Collect table references and definitions
            for match in RE_TABLE_REF.finditer(content):
                table_refs.add(match.group(1))
            for match in RE_TABLE_DEF.finditer(content):
                table_defs.add(match.group(1))

        # Figures: orphaned = defined but never referenced; missing = referenced but not defined
        fig_orphaned = sorted(figure_defs - figure_refs)
        fig_missing = sorted(figure_refs - figure_defs)

        # Tables: same logic
        tbl_orphaned = sorted(table_defs - table_refs)
        tbl_missing = sorted(table_refs - table_defs)

        figures_result = {
            "defined": len(figure_defs),
            "referenced": len(figure_refs),
            "orphaned": fig_orphaned,
            "orphaned_count": len(fig_orphaned),
            "missing": fig_missing,
            "missing_count": len(fig_missing),
        }

        tables_result = {
            "defined": len(table_defs),
            "referenced": len(table_refs),
            "orphaned": tbl_orphaned,
            "orphaned_count": len(tbl_orphaned),
            "missing": tbl_missing,
            "missing_count": len(tbl_missing),
        }

        total_issues = (len(fig_orphaned) + len(fig_missing) +
                        len(tbl_orphaned) + len(tbl_missing))

        _audit(conn, "validation.figures_tables",
               f"Figure/table validation: {total_issues} issues",
               "proposal", proposal_id,
               {"fig_orphaned": len(fig_orphaned), "fig_missing": len(fig_missing),
                "tbl_orphaned": len(tbl_orphaned), "tbl_missing": len(tbl_missing)})
        conn.commit()

        return {
            "proposal_id": proposal_id,
            "figures": figures_result,
            "tables": tables_result,
            "total_issues": total_issues,
            "validated_at": _now(),
        }
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 6. Full Validation (Aggregate)
# ---------------------------------------------------------------------------

def full_validation(proposal_id, db_path=None):
    """Run all validators and return an aggregated report.

    Executes: cross-references, acronyms, compliance refs, figures/tables.

    Returns:
        dict with passed bool, individual results, and summary.
    """
    cross_refs = validate_cross_references(proposal_id, db_path)
    acronyms_result = validate_acronyms(proposal_id, db_path)
    compliance = validate_compliance_refs(proposal_id, db_path)
    figs_tables = validate_figures_tables(proposal_id, db_path)

    # Aggregate issue counts by severity
    errors = 0
    warnings = 0
    info_count = 0

    # Broken cross-references are errors
    errors += cross_refs.get("broken_count", 0)

    # Undefined acronyms are warnings; first-use violations are warnings
    warnings += len(acronyms_result.get("undefined_list", []))
    warnings += acronyms_result.get("violation_count", 0)

    # Missing compliance sections are errors; unverified are warnings
    errors += len(compliance.get("missing_sections", []))
    warnings += len(compliance.get("unverified_details", []))

    # Missing figures/tables are errors; orphaned are info
    errors += figs_tables.get("figures", {}).get("missing_count", 0)
    errors += figs_tables.get("tables", {}).get("missing_count", 0)
    info_count += figs_tables.get("figures", {}).get("orphaned_count", 0)
    info_count += figs_tables.get("tables", {}).get("orphaned_count", 0)

    total_issues = errors + warnings + info_count
    passed = errors == 0

    return {
        "proposal_id": proposal_id,
        "passed": passed,
        "cross_refs": cross_refs,
        "acronyms": acronyms_result,
        "compliance": compliance,
        "figures_tables": figs_tables,
        "summary": {
            "total_issues": total_issues,
            "errors": errors,
            "warnings": warnings,
            "info": info_count,
        },
        "validated_at": _now(),
    }


# ---------------------------------------------------------------------------
# 7. Add Acronym
# ---------------------------------------------------------------------------

def add_acronym(acronym, expansion, domain=None, db_path=None):
    """Manually add an acronym to the database.

    Args:
        acronym: The acronym (e.g. "CDRL").
        expansion: The full expansion (e.g. "Contract Data Requirements List").
        domain: Optional domain category (e.g. "contracting").

    Returns:
        dict with the created acronym entry.
    """
    conn = _get_db(db_path)
    try:
        acr_id = _acr_id()
        try:
            conn.execute(
                "INSERT INTO acronyms (id, acronym, expansion, domain, usage_count, created_at) "
                "VALUES (?, ?, ?, ?, 0, ?)",
                (acr_id, acronym.upper(), expansion, domain, _now()),
            )
        except sqlite3.IntegrityError:
            return {"error": f"Acronym '{acronym.upper()}' already exists"}

        _audit(conn, "acronym.added",
               f"Added acronym: {acronym.upper()} = {expansion}",
               "acronym", acr_id,
               {"acronym": acronym.upper(), "expansion": expansion, "domain": domain})
        conn.commit()

        return {
            "id": acr_id,
            "acronym": acronym.upper(),
            "expansion": expansion,
            "domain": domain,
            "added": True,
        }
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 8. List Acronyms
# ---------------------------------------------------------------------------

def list_acronyms(domain=None, db_path=None):
    """List all known acronyms, optionally filtered by domain.

    Args:
        domain: Optional domain filter.

    Returns:
        dict with acronyms list and count.
    """
    conn = _get_db(db_path)
    try:
        if domain:
            rows = conn.execute(
                "SELECT id, acronym, expansion, domain, usage_count, created_at "
                "FROM acronyms WHERE domain = ? ORDER BY acronym",
                (domain,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, acronym, expansion, domain, usage_count, created_at "
                "FROM acronyms ORDER BY acronym"
            ).fetchall()

        entries = [_row_to_dict(r) for r in rows]

        return {
            "acronyms": entries,
            "count": len(entries),
            "domain_filter": domain,
        }
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Cross-Reference and Acronym Validator for GovProposal."
    )
    parser.add_argument("--validate", action="store_true",
                        help="Run full validation (all checks)")
    parser.add_argument("--cross-refs", action="store_true",
                        help="Validate section cross-references")
    parser.add_argument("--acronyms", action="store_true",
                        help="Validate acronym usage")
    parser.add_argument("--acronym-list", action="store_true",
                        help="Generate acronym appendix list")
    parser.add_argument("--compliance-refs", action="store_true",
                        help="Validate compliance matrix section references")
    parser.add_argument("--figures-tables", action="store_true",
                        help="Validate figure and table references")
    parser.add_argument("--add-acronym", action="store_true",
                        help="Add an acronym to the database")
    parser.add_argument("--list-acronyms", action="store_true",
                        help="List all known acronyms")
    parser.add_argument("--proposal-id", help="Proposal ID")
    parser.add_argument("--acronym", help="Acronym text (for --add-acronym)")
    parser.add_argument("--expansion", help="Acronym expansion (for --add-acronym)")
    parser.add_argument("--domain", help="Domain filter or category")
    parser.add_argument("--db-path", help="Optional database path override")
    parser.add_argument("--json", action="store_true", help="JSON output")
    args = parser.parse_args()

    db_path = args.db_path if args.db_path else None
    result = {}

    if args.add_acronym:
        if not args.acronym or not args.expansion:
            parser.error("--add-acronym requires --acronym and --expansion")
        result = add_acronym(args.acronym, args.expansion, args.domain, db_path)
    elif args.list_acronyms:
        result = list_acronyms(args.domain, db_path)
    elif args.validate:
        if not args.proposal_id:
            parser.error("--validate requires --proposal-id")
        result = full_validation(args.proposal_id, db_path)
    elif args.cross_refs:
        if not args.proposal_id:
            parser.error("--cross-refs requires --proposal-id")
        result = validate_cross_references(args.proposal_id, db_path)
    elif args.acronyms:
        if not args.proposal_id:
            parser.error("--acronyms requires --proposal-id")
        result = validate_acronyms(args.proposal_id, db_path)
    elif args.acronym_list:
        if not args.proposal_id:
            parser.error("--acronym-list requires --proposal-id")
        result = generate_acronym_list(args.proposal_id, db_path)
    elif args.compliance_refs:
        if not args.proposal_id:
            parser.error("--compliance-refs requires --proposal-id")
        result = validate_compliance_refs(args.proposal_id, db_path)
    elif args.figures_tables:
        if not args.proposal_id:
            parser.error("--figures-tables requires --proposal-id")
        result = validate_figures_tables(args.proposal_id, db_path)
    else:
        parser.print_help()
        sys.exit(1)

    if args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        if "error" in result:
            print(f"ERROR: {result['error']}", file=sys.stderr)
            sys.exit(1)
        elif "passed" in result:
            # Full validation summary
            status = "PASSED" if result["passed"] else "FAILED"
            s = result["summary"]
            print(f"Cross-Reference Validation: {status}")
            print(f"  Errors:   {s['errors']}")
            print(f"  Warnings: {s['warnings']}")
            print(f"  Info:     {s['info']}")
            if result.get("cross_refs", {}).get("broken_refs"):
                print(f"\nBroken Section References:")
                for br in result["cross_refs"]["broken_refs"][:10]:
                    print(f"  [{br['source_section']}] {br['reference']} -- {br['issue']}")
            if result.get("acronyms", {}).get("undefined_list"):
                print(f"\nUndefined Acronyms: {', '.join(result['acronyms']['undefined_list'][:15])}")
            if result.get("compliance", {}).get("missing_sections"):
                print(f"\nMissing Compliance Sections:")
                for ms in result["compliance"]["missing_sections"][:10]:
                    print(f"  [{ms['requirement_id']}] -> Section {ms['section_number']}")
        elif "total_refs" in result:
            print(f"Cross-References: {result['total_refs']} total, "
                  f"{result['valid_refs']} valid, {result['broken_count']} broken")
            for br in result.get("broken_refs", [])[:10]:
                print(f"  [{br['source_section']}] {br['reference']} -- {br['issue']}")
        elif "total_acronyms" in result:
            print(f"Acronyms: {result['total_acronyms']} used, "
                  f"{result['defined']} defined, {result['undefined']} undefined")
            if result.get("undefined_list"):
                print(f"  Undefined: {', '.join(result['undefined_list'][:15])}")
            if result.get("first_use_violations"):
                print(f"  Violations: {result['violation_count']}")
                for v in result["first_use_violations"][:10]:
                    print(f"    {v['issue']}")
        elif "acronyms" in result and "count" in result:
            if result.get("generated_at"):
                # Acronym list (appendix)
                print(f"Acronym List ({result['count']} entries):")
                for a in result["acronyms"]:
                    secs = ", ".join(a["sections_used"][:5])
                    print(f"  {a['acronym']:12s} {a['expansion']}")
                    if a["sections_used"]:
                        print(f"               Used in: {secs}")
            else:
                # List acronyms
                print(f"Known Acronyms ({result['count']}):")
                for a in result["acronyms"]:
                    domain_str = f" [{a['domain']}]" if a.get("domain") else ""
                    print(f"  {a['acronym']:12s} {a['expansion']}{domain_str}")
        elif "total_mappings" in result:
            print(f"Compliance Refs: {result['total_mappings']} mappings, "
                  f"{result.get('verified', 0)} verified, "
                  f"{result.get('unverified', 0)} unverified")
            if result.get("missing_sections"):
                print(f"  Missing sections: {len(result['missing_sections'])}")
                for ms in result["missing_sections"][:10]:
                    print(f"    [{ms['requirement_id']}] -> Section {ms['section_number']}")
        elif "figures" in result and "tables" in result:
            f = result["figures"]
            t = result["tables"]
            print(f"Figures: {f['defined']} defined, {f['referenced']} referenced, "
                  f"{f['orphaned_count']} orphaned, {f['missing_count']} missing")
            print(f"Tables:  {t['defined']} defined, {t['referenced']} referenced, "
                  f"{t['orphaned_count']} orphaned, {t['missing_count']} missing")
        elif "added" in result:
            print(f"Added: {result['acronym']} = {result['expansion']}")
        else:
            print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
