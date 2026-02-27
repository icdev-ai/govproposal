#!/usr/bin/env python3
# CUI // SP-PROPIN
# Controlled by: GovProposal Portal
# CUI Category: PROPIN
# Distribution: D
# POC: GovProposal System Administrator
"""Submission Packager — Final document assembly and packaging for GovProposal.

Assembles final proposal packages including:
  - Section status validation (all must be 'final')
  - White team QC checks
  - CAG pre-export classification guard check
  - Table of contents generation
  - Acronym list extraction and expansion
  - Cross-reference validation
  - Classification marking application
  - Per-volume file packaging with naming convention
  - Submission checklist generation

Usage:
    python tools/production/submission_packager.py --package --proposal-id PROP-001 --output /tmp/out --json
    python tools/production/submission_packager.py --validate --proposal-id PROP-001 --json
    python tools/production/submission_packager.py --acronyms --proposal-id PROP-001 --json
    python tools/production/submission_packager.py --cross-refs --proposal-id PROP-001 --json
    python tools/production/submission_packager.py --status --proposal-id PROP-001 --json
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

# Optional YAML import
try:
    import yaml  # noqa: F401
except ImportError:
    yaml = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _pkg_id():
    """Generate a package ID: PKG- followed by 12 hex characters."""
    return "PKG-" + secrets.token_hex(6)


def _acr_id():
    """Generate an acronym ID: ACR- followed by 12 hex characters."""
    return "ACR-" + secrets.token_hex(6)


def _now():
    """Return current UTC timestamp as ISO-8601 string."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _get_db(db_path=None):
    """Open a database connection with WAL mode and foreign keys enabled.

    Args:
        db_path: Optional path override.  Falls back to DB_PATH.

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
        action: Human-readable description.
        entity_type: Type of entity affected.
        entity_id: ID of the affected entity.
        details: Optional JSON-serializable details dict.
    """
    conn.execute(
        "INSERT INTO audit_trail (event_type, actor, action, entity_type, "
        "entity_id, details, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            event_type,
            "submission_packager",
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


def _safe_filename(text, max_len=50):
    """Sanitize a string for use as a filename component.

    Args:
        text: Raw string.
        max_len: Maximum length.

    Returns:
        Sanitized string with only alphanumerics, hyphens, underscores.
    """
    sanitized = re.sub(r"[^\w\-]", "_", text.strip())
    sanitized = re.sub(r"_+", "_", sanitized).strip("_")
    return sanitized[:max_len]


# ---------------------------------------------------------------------------
# Core Functions
# ---------------------------------------------------------------------------

def package_proposal(proposal_id, output_dir, db_path=None):
    """Assemble the final proposal package for submission.

    Steps:
      1. Validate all sections are 'final' status
      2. Run White team QC checks
      3. Run CAG pre-export check
      4. Generate table of contents
      5. Build acronym list from all sections
      6. Validate cross-references
      7. Apply classification markings to every page
      8. Package into per-volume files with naming convention
      9. Generate submission checklist

    Args:
        proposal_id: Proposal ID to package.
        output_dir: Directory to write package files into.
        db_path: Optional database path override.

    Returns:
        dict with package manifest: file list, sizes, compliance status,
        checklist items.

    Raises:
        ValueError: If proposal not found or pre-conditions fail.
    """
    conn = _get_db(db_path)
    try:
        proposal = _load_proposal(conn, proposal_id)
        sections = _load_sections(conn, proposal_id)
        if not sections:
            raise ValueError(
                f"No sections found for proposal {proposal_id}"
            )

        classification = proposal.get("classification") or "CUI // SP-PROPIN"
        opp_id = proposal.get("opportunity_id") or "UNKNOWN"
        sol_num = ""
        if opp_id != "UNKNOWN":
            opp_row = conn.execute(
                "SELECT solicitation_number, title FROM opportunities "
                "WHERE id = ?", (opp_id,)
            ).fetchone()
            if opp_row:
                sol_num = opp_row["solicitation_number"] or ""

        issues = []
        warnings = []
        files_written = []

        # --- Step 1: Validate all sections are 'final' ---
        non_final = [s for s in sections if s.get("status") != "final"]
        if non_final:
            non_final_ids = [
                f"{s['section_number']} ({s['status']})"
                for s in non_final
            ]
            issues.append(
                f"Non-final sections: {', '.join(non_final_ids)}"
            )

        # --- Step 2: White team QC check ---
        latest_white = conn.execute(
            "SELECT * FROM proposal_reviews "
            "WHERE proposal_id = ? AND review_type = 'white' "
            "ORDER BY reviewed_at DESC LIMIT 1",
            (proposal_id,),
        ).fetchone()
        if latest_white:
            white = _row_to_dict(latest_white)
            white_score = white.get("overall_score") or 0.0
            if white_score < 0.95:
                warnings.append(
                    f"White team score {white_score:.1%} is below 95% "
                    f"threshold. Review deficiencies before submission."
                )
            white_defs = _parse_json_field(white.get("deficiencies")) or []
            if white_defs:
                issues.append(
                    f"White team deficiencies unresolved: {len(white_defs)}"
                )
        else:
            warnings.append("No White team review found. QC not verified.")

        # --- Step 3: CAG pre-export check ---
        cag_status = proposal.get("cag_status") or "pending"
        open_alerts = conn.execute(
            "SELECT COUNT(*) as cnt FROM cag_alerts "
            "WHERE proposal_id = ? AND status IN ('open', 'quarantined')",
            (proposal_id,),
        ).fetchone()
        open_alert_count = open_alerts["cnt"] if open_alerts else 0
        if cag_status == "blocked" or cag_status == "quarantined":
            issues.append(
                f"CAG status is '{cag_status}'. Cannot export."
            )
        if open_alert_count > 0:
            issues.append(
                f"{open_alert_count} open CAG alert(s). Resolve before export."
            )

        # --- Step 4: Generate table of contents ---
        toc_entries = []
        for s in sections:
            toc_entries.append({
                "volume": s["volume"],
                "section_number": s["section_number"],
                "section_title": s["section_title"],
                "page_count": s.get("page_count") or 0,
            })

        # --- Step 5: Build acronym list ---
        acronyms_found = generate_acronym_list(
            proposal_id, db_path=db_path
        )

        # --- Step 6: Validate cross-references ---
        xref_results = check_cross_references(
            proposal_id, db_path=db_path
        )
        broken_refs = xref_results.get("broken_references", [])
        if broken_refs:
            warnings.append(
                f"{len(broken_refs)} potentially broken cross-reference(s)."
            )

        # --- Step 7 & 8: Write per-volume files ---
        out_path = Path(output_dir)
        out_path.mkdir(parents=True, exist_ok=True)

        volumes_defined = _parse_json_field(proposal.get("volumes")) or [
            "technical", "management", "past_performance", "cost"
        ]
        volume_sections = {}
        for s in sections:
            vol = s.get("volume", "technical")
            volume_sections.setdefault(vol, []).append(s)

        sol_slug = _safe_filename(sol_num) if sol_num else "proposal"

        for vol_name in volumes_defined:
            vol_secs = volume_sections.get(vol_name, [])
            if not vol_secs:
                continue

            filename = f"{sol_slug}_vol_{vol_name}.txt"
            filepath = out_path / filename

            lines = []
            lines.append(classification)
            lines.append("")
            lines.append(f"PROPOSAL: {proposal.get('title', proposal_id)}")
            lines.append(f"VOLUME: {vol_name.upper()}")
            if sol_num:
                lines.append(f"SOLICITATION: {sol_num}")
            lines.append(f"CLASSIFICATION: {classification}")
            lines.append("=" * 72)
            lines.append("")

            # Table of contents for this volume
            lines.append("TABLE OF CONTENTS")
            lines.append("-" * 40)
            for s in vol_secs:
                lines.append(
                    f"  {s['section_number']}  {s['section_title']}"
                )
            lines.append("")
            lines.append("=" * 72)

            # Section content
            for s in vol_secs:
                lines.append("")
                lines.append(classification)
                lines.append(
                    f"SECTION {s['section_number']}: "
                    f"{s['section_title'].upper()}"
                )
                lines.append("-" * 60)
                content = s.get("content") or "[CONTENT MISSING]"
                lines.append(content)
                lines.append("")
                lines.append(classification)
                lines.append("")

            # Footer
            lines.append("=" * 72)
            lines.append(classification)

            filepath.write_text("\n".join(lines), encoding="utf-8")
            file_size = filepath.stat().st_size
            files_written.append({
                "filename": filename,
                "volume": vol_name,
                "sections": len(vol_secs),
                "size_bytes": file_size,
                "path": str(filepath),
            })

        # Write acronym list file
        if acronyms_found.get("acronyms"):
            acr_filename = f"{sol_slug}_acronyms.txt"
            acr_path = out_path / acr_filename
            acr_lines = [classification, "", "ACRONYM LIST", "-" * 40]
            for a in acronyms_found["acronyms"]:
                acr_lines.append(
                    f"  {a['acronym']:12s} {a['expansion']}"
                )
            acr_lines.append("", classification)
            acr_path.write_text("\n".join(acr_lines), encoding="utf-8")
            files_written.append({
                "filename": acr_filename,
                "volume": "attachments",
                "sections": 0,
                "size_bytes": acr_path.stat().st_size,
                "path": str(acr_path),
            })

        # --- Step 9: Generate submission checklist ---
        checklist = _generate_checklist(
            proposal, sections, issues, warnings,
            files_written, latest_white is not None,
            open_alert_count, broken_refs,
        )

        # Write checklist file
        chk_filename = f"{sol_slug}_checklist.txt"
        chk_path = out_path / chk_filename
        chk_lines = [classification, "", "SUBMISSION CHECKLIST", "=" * 40]
        for item in checklist:
            status_mark = "[X]" if item["passed"] else "[ ]"
            chk_lines.append(f"  {status_mark} {item['item']}")
            if not item["passed"] and item.get("note"):
                chk_lines.append(f"       NOTE: {item['note']}")
        chk_lines.append("", classification)
        chk_path.write_text("\n".join(chk_lines), encoding="utf-8")
        files_written.append({
            "filename": chk_filename,
            "volume": "admin",
            "sections": 0,
            "size_bytes": chk_path.stat().st_size,
            "path": str(chk_path),
        })

        # Overall compliance status
        all_passed = all(item["passed"] for item in checklist)
        compliance_status = "READY" if all_passed else "NOT_READY"
        if issues:
            compliance_status = "BLOCKED"

        now = _now()
        result = {
            "proposal_id": proposal_id,
            "package_id": _pkg_id(),
            "compliance_status": compliance_status,
            "output_dir": str(out_path),
            "files": files_written,
            "total_files": len(files_written),
            "total_size_bytes": sum(f["size_bytes"] for f in files_written),
            "issues": issues,
            "warnings": warnings,
            "checklist": checklist,
            "toc": toc_entries,
            "acronym_count": len(acronyms_found.get("acronyms", [])),
            "cross_ref_issues": len(broken_refs),
            "packaged_at": now,
        }

        _audit(conn, "production.package",
               f"Packaged proposal {proposal_id}: {compliance_status}",
               "proposal", proposal_id,
               {"compliance_status": compliance_status,
                "files": len(files_written),
                "issues": len(issues)})
        conn.commit()
        return result
    finally:
        conn.close()


def _generate_checklist(proposal, sections, issues, warnings,
                        files, has_white_review, open_alerts, broken_refs):
    """Generate a submission pre-flight checklist.

    Args:
        proposal: Proposal dict.
        sections: List of section dicts.
        issues: List of blocking issue strings.
        warnings: List of warning strings.
        files: List of file dicts written.
        has_white_review: Whether White team review exists.
        open_alerts: Number of open CAG alerts.
        broken_refs: List of broken cross-references.

    Returns:
        list of checklist item dicts with 'item', 'passed', 'note'.
    """
    checklist = []

    # 1. All sections finalized
    non_final = [s for s in sections if s.get("status") != "final"]
    checklist.append({
        "item": "All sections in 'final' status",
        "passed": len(non_final) == 0,
        "note": (f"{len(non_final)} non-final section(s)"
                 if non_final else None),
    })

    # 2. White team review completed
    checklist.append({
        "item": "White team review completed",
        "passed": has_white_review,
        "note": None if has_white_review else "No White team review on file",
    })

    # 3. CAG clearance
    checklist.append({
        "item": "CAG clearance — no open alerts",
        "passed": open_alerts == 0,
        "note": (f"{open_alerts} open alert(s)"
                 if open_alerts > 0 else None),
    })

    # 4. Classification markings applied
    classification = proposal.get("classification") or ""
    has_marking = bool(classification)
    checklist.append({
        "item": "Classification markings defined",
        "passed": has_marking,
        "note": None if has_marking else "No classification marking set",
    })

    # 5. Cross-references validated
    checklist.append({
        "item": "Cross-references validated",
        "passed": len(broken_refs) == 0,
        "note": (f"{len(broken_refs)} potential issue(s)"
                 if broken_refs else None),
    })

    # 6. Volumes packaged
    checklist.append({
        "item": "Volume files generated",
        "passed": len(files) > 0,
        "note": f"{len(files)} file(s) written",
    })

    # 7. Page limits respected
    over_limit = [
        s for s in sections
        if s.get("page_limit") and s.get("page_count")
        and s["page_count"] > s["page_limit"]
    ]
    checklist.append({
        "item": "All sections within page limits",
        "passed": len(over_limit) == 0,
        "note": (f"{len(over_limit)} section(s) over limit"
                 if over_limit else None),
    })

    # 8. Proposal manager assigned
    has_pm = bool(proposal.get("assigned_pm"))
    checklist.append({
        "item": "Proposal Manager assigned",
        "passed": has_pm,
        "note": None if has_pm else "No PM assigned",
    })

    # 9. Due date set
    has_due = bool(proposal.get("due_date"))
    checklist.append({
        "item": "Submission due date set",
        "passed": has_due,
        "note": proposal.get("due_date") if has_due else "No due date",
    })

    # 10. No blocking issues
    checklist.append({
        "item": "No blocking issues",
        "passed": len(issues) == 0,
        "note": (f"{len(issues)} blocking issue(s)"
                 if issues else None),
    })

    return checklist


def validate_submission(proposal_id, db_path=None):
    """Run pre-submission validation without generating package files.

    Performs the same checks as package_proposal but does not write files.

    Args:
        proposal_id: Proposal ID to validate.
        db_path: Optional database path override.

    Returns:
        dict with validation results and checklist.

    Raises:
        ValueError: If proposal not found.
    """
    conn = _get_db(db_path)
    try:
        proposal = _load_proposal(conn, proposal_id)
        sections = _load_sections(conn, proposal_id)
        if not sections:
            raise ValueError(
                f"No sections found for proposal {proposal_id}"
            )

        issues = []
        warnings = []

        # Section status check
        non_final = [s for s in sections if s.get("status") != "final"]
        if non_final:
            issues.append(
                f"{len(non_final)} section(s) not in 'final' status"
            )

        # White team review
        latest_white = conn.execute(
            "SELECT overall_score FROM proposal_reviews "
            "WHERE proposal_id = ? AND review_type = 'white' "
            "ORDER BY reviewed_at DESC LIMIT 1",
            (proposal_id,),
        ).fetchone()
        has_white = latest_white is not None
        if not has_white:
            warnings.append("White team review not completed")

        # CAG check
        open_alerts_row = conn.execute(
            "SELECT COUNT(*) as cnt FROM cag_alerts "
            "WHERE proposal_id = ? AND status IN ('open', 'quarantined')",
            (proposal_id,),
        ).fetchone()
        open_alerts = open_alerts_row["cnt"] if open_alerts_row else 0
        if open_alerts > 0:
            issues.append(f"{open_alerts} open CAG alert(s)")

        # Cross-ref check
        xrefs = check_cross_references(proposal_id, db_path=db_path)
        broken = xrefs.get("broken_references", [])
        if broken:
            warnings.append(
                f"{len(broken)} potentially broken cross-reference(s)"
            )

        # Page limits
        over_limit = [
            s for s in sections
            if s.get("page_limit") and s.get("page_count")
            and s["page_count"] > s["page_limit"]
        ]
        if over_limit:
            issues.append(f"{len(over_limit)} section(s) over page limit")

        checklist = _generate_checklist(
            proposal, sections, issues, warnings,
            [], has_white, open_alerts, broken,
        )

        all_passed = all(item["passed"] for item in checklist)
        status = "READY" if all_passed else "NOT_READY"
        if issues:
            status = "BLOCKED"

        result = {
            "proposal_id": proposal_id,
            "validation_status": status,
            "section_count": len(sections),
            "non_final_sections": len(non_final),
            "open_cag_alerts": open_alerts,
            "cross_ref_issues": len(broken),
            "page_limit_violations": len(over_limit),
            "issues": issues,
            "warnings": warnings,
            "checklist": checklist,
        }

        _audit(conn, "production.validate",
               f"Validated proposal {proposal_id}: {status}",
               "proposal", proposal_id,
               {"status": status, "issues": len(issues)})
        conn.commit()
        return result
    finally:
        conn.close()


def generate_acronym_list(proposal_id, db_path=None):
    """Extract all acronyms from proposal sections, expand, and store.

    Scans all section content for uppercase 2-6 letter sequences,
    checks the acronyms table for known expansions, and stores any
    new discoveries.

    Args:
        proposal_id: Proposal ID to scan.
        db_path: Optional database path override.

    Returns:
        dict with acronyms list, new_count, existing_count.

    Raises:
        ValueError: If proposal not found.
    """
    conn = _get_db(db_path)
    try:
        proposal = _load_proposal(conn, proposal_id)
        sections = _load_sections(conn, proposal_id)

        # Common English words that look like acronyms
        non_acronyms = {
            "THE", "AND", "FOR", "NOT", "BUT", "ALL", "HAS", "WAS",
            "ARE", "CAN", "OUR", "HIS", "HER", "ITS", "MAY", "USE",
            "SET", "NEW", "OLD", "ONE", "TWO", "PER", "END", "ANY",
            "HOW", "WHO", "WHY", "DID", "GET", "GOT", "LET", "PUT",
            "RUN", "SAY", "SEE", "TRY", "WAY", "DAY",
        }

        # Gather all acronyms from content
        found_acronyms = set()
        for s in sections:
            content = s.get("content") or ""
            matches = re.findall(r"\b([A-Z]{2,6})\b", content)
            found_acronyms.update(matches)

        found_acronyms -= non_acronyms

        # Load existing acronyms from DB
        existing_rows = conn.execute(
            "SELECT acronym, expansion FROM acronyms"
        ).fetchall()
        existing_map = {r["acronym"]: r["expansion"] for r in existing_rows}

        acronym_list = []
        new_count = 0

        for acr in sorted(found_acronyms):
            if acr in existing_map:
                acronym_list.append({
                    "acronym": acr,
                    "expansion": existing_map[acr],
                    "status": "known",
                })
            else:
                # Store as unknown — human must provide expansion
                acr_id = _acr_id()
                conn.execute(
                    "INSERT OR IGNORE INTO acronyms "
                    "(id, acronym, expansion, domain, usage_count, "
                    " created_at) "
                    "VALUES (?, ?, ?, ?, 1, ?)",
                    (acr_id, acr, f"[EXPANSION NEEDED: {acr}]",
                     "proposal", _now()),
                )
                acronym_list.append({
                    "acronym": acr,
                    "expansion": f"[EXPANSION NEEDED: {acr}]",
                    "status": "new",
                })
                new_count += 1

        _audit(conn, "production.acronyms",
               f"Extracted {len(acronym_list)} acronyms from {proposal_id}",
               "proposal", proposal_id,
               {"total": len(acronym_list), "new": new_count})
        conn.commit()

        return {
            "proposal_id": proposal_id,
            "acronyms": acronym_list,
            "total_count": len(acronym_list),
            "known_count": len(acronym_list) - new_count,
            "new_count": new_count,
        }
    finally:
        conn.close()


def check_cross_references(proposal_id, db_path=None):
    """Find broken or potentially invalid cross-references in proposal.

    Scans section content for patterns like "Section X.X", "Table X",
    "Figure X" and validates that referenced section numbers exist in
    the proposal's section list.

    Args:
        proposal_id: Proposal ID to check.
        db_path: Optional database path override.

    Returns:
        dict with total_references, valid_references, broken_references.

    Raises:
        ValueError: If proposal not found.
    """
    conn = _get_db(db_path)
    try:
        proposal = _load_proposal(conn, proposal_id)
        sections = _load_sections(conn, proposal_id)

        # Build set of known section numbers
        known_sections = {s["section_number"] for s in sections}

        all_refs = []
        broken_refs = []
        valid_refs = []

        for s in sections:
            content = s.get("content") or ""

            # Find "Section X.X.X" references
            sec_refs = re.findall(
                r"[Ss]ection\s+(\d+(?:\.\d+)*)", content
            )
            for ref in sec_refs:
                ref_entry = {
                    "source_section": s["section_number"],
                    "reference_type": "section",
                    "reference_target": ref,
                }
                all_refs.append(ref_entry)
                if ref in known_sections:
                    valid_refs.append(ref_entry)
                else:
                    ref_entry["issue"] = (
                        f"Section {ref} referenced but not found"
                    )
                    broken_refs.append(ref_entry)

            # Find "Table X" and "Figure X" references (informational)
            table_refs = re.findall(
                r"[Tt]able\s+(\d+(?:\.\d+)?(?:-\d+)?)", content
            )
            for ref in table_refs:
                all_refs.append({
                    "source_section": s["section_number"],
                    "reference_type": "table",
                    "reference_target": f"Table {ref}",
                })

            fig_refs = re.findall(
                r"[Ff]igure\s+(\d+(?:\.\d+)?(?:-\d+)?)", content
            )
            for ref in fig_refs:
                all_refs.append({
                    "source_section": s["section_number"],
                    "reference_type": "figure",
                    "reference_target": f"Figure {ref}",
                })

        return {
            "proposal_id": proposal_id,
            "total_references": len(all_refs),
            "valid_references": len(valid_refs),
            "broken_references": broken_refs,
            "broken_count": len(broken_refs),
            "all_references": all_refs,
        }
    finally:
        conn.close()


def get_package_status(proposal_id, db_path=None):
    """Get current packaging status for a proposal.

    Aggregates section readiness, review status, and CAG clearance
    into a single status view.

    Args:
        proposal_id: Proposal ID.
        db_path: Optional database path override.

    Returns:
        dict with section_readiness, review_status, cag_status,
        and overall packaging_ready flag.

    Raises:
        ValueError: If proposal not found.
    """
    conn = _get_db(db_path)
    try:
        proposal = _load_proposal(conn, proposal_id)
        sections = _load_sections(conn, proposal_id)

        # Section readiness
        status_counts = {}
        for s in sections:
            st = s.get("status") or "outline"
            status_counts[st] = status_counts.get(st, 0) + 1
        all_final = status_counts.get("final", 0) == len(sections)

        # Review status
        reviews = {}
        for rt in ("pink", "red", "gold", "white"):
            row = conn.execute(
                "SELECT overall_score, review_status, reviewed_at "
                "FROM proposal_reviews "
                "WHERE proposal_id = ? AND review_type = ? "
                "ORDER BY reviewed_at DESC LIMIT 1",
                (proposal_id, rt),
            ).fetchone()
            if row:
                reviews[rt] = {
                    "score": row["overall_score"],
                    "status": row["review_status"],
                    "reviewed_at": row["reviewed_at"],
                }
            else:
                reviews[rt] = {"score": None, "status": "not_started"}

        # CAG status
        cag = proposal.get("cag_status") or "pending"
        open_alerts = conn.execute(
            "SELECT COUNT(*) as cnt FROM cag_alerts "
            "WHERE proposal_id = ? AND status IN ('open', 'quarantined')",
            (proposal_id,),
        ).fetchone()
        alert_count = open_alerts["cnt"] if open_alerts else 0

        # Overall readiness
        reviews_complete = all(
            v["status"] == "completed" for v in reviews.values()
        )
        cag_clear = cag in ("clear",) and alert_count == 0
        packaging_ready = all_final and reviews_complete and cag_clear

        return {
            "proposal_id": proposal_id,
            "proposal_status": proposal.get("status"),
            "section_readiness": {
                "total_sections": len(sections),
                "status_breakdown": status_counts,
                "all_final": all_final,
            },
            "review_status": reviews,
            "cag_status": {
                "status": cag,
                "open_alerts": alert_count,
                "clear": cag_clear,
            },
            "packaging_ready": packaging_ready,
        }
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_parser():
    """Build argument parser for the CLI."""
    import argparse
    parser = argparse.ArgumentParser(
        description="GovProposal Submission Packager",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  %(prog)s --package --proposal-id PROP-001 "
            "--output /tmp/out --json\n"
            "  %(prog)s --validate --proposal-id PROP-001 --json\n"
            "  %(prog)s --acronyms --proposal-id PROP-001 --json\n"
            "  %(prog)s --cross-refs --proposal-id PROP-001 --json\n"
            "  %(prog)s --status --proposal-id PROP-001 --json\n"
        ),
    )

    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--package", action="store_true",
                        help="Assemble final proposal package")
    action.add_argument("--validate", action="store_true",
                        help="Pre-submission validation only")
    action.add_argument("--acronyms", action="store_true",
                        help="Extract and list acronyms")
    action.add_argument("--cross-refs", action="store_true",
                        help="Check cross-references")
    action.add_argument("--status", action="store_true",
                        help="Get packaging status")

    parser.add_argument("--proposal-id", help="Proposal ID")
    parser.add_argument("--output", help="Output directory (for --package)")
    parser.add_argument("--json", action="store_true", help="JSON output")
    parser.add_argument("--db-path", help="Override database path")

    return parser


def main():
    """CLI entry point."""
    parser = _build_parser()
    args = parser.parse_args()
    db = args.db_path

    try:
        if not args.proposal_id:
            parser.error("--proposal-id is required")

        if args.package:
            if not args.output:
                parser.error("--package requires --output")
            result = package_proposal(
                args.proposal_id, args.output, db_path=db
            )

        elif args.validate:
            result = validate_submission(args.proposal_id, db_path=db)

        elif args.acronyms:
            result = generate_acronym_list(args.proposal_id, db_path=db)

        elif args.cross_refs:
            result = check_cross_references(args.proposal_id, db_path=db)

        elif args.status:
            result = get_package_status(args.proposal_id, db_path=db)

        # Output
        if args.json:
            print(json.dumps(result, indent=2, default=str))
        else:
            if isinstance(result, dict):
                for key, value in result.items():
                    if isinstance(value, (list, dict)):
                        if key == "checklist":
                            print(f"  {key}:")
                            for item in value:
                                mark = "[X]" if item["passed"] else "[ ]"
                                print(f"    {mark} {item['item']}")
                        elif key == "files":
                            print(f"  {key}: ({len(value)} files)")
                            for f in value:
                                print(f"    {f['filename']} "
                                      f"({f['size_bytes']} bytes)")
                        elif key == "acronyms":
                            print(f"  {key}: ({len(value)} entries)")
                        else:
                            print(f"  {key}: "
                                  f"{json.dumps(value, default=str)}")
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
