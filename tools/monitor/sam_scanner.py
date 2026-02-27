#!/usr/bin/env python3
# CUI // SP-PROPIN
# Controlled by: GovProposal Portal
# CUI Category: PROPIN
# Distribution: D
# POC: GovProposal System Administrator
"""SAM.gov opportunity monitor — polls the SAM.gov Opportunities API v2.

Discovers new government contract opportunities, stores them in the
opportunities table with deduplication by sam_notice_id, and tracks
modifications to already-tracked opportunities.

Supports filtering by NAICS code, agency, opportunity type, and
set-aside type. Gracefully degrades when the SAM.gov API is
unavailable (missing API key or network error).

Usage:
    # Scan for new opportunities (last 7 days)
    python tools/monitor/sam_scanner.py --scan --json

    # Scan specific NAICS and agency
    python tools/monitor/sam_scanner.py --scan --naics 541512 --agency "Department of Defense"

    # Scan for modifications to tracked opportunities
    python tools/monitor/sam_scanner.py --scan-mods --json

    # List tracked opportunities
    python tools/monitor/sam_scanner.py --list --json
    python tools/monitor/sam_scanner.py --list --status qualifying

    # Get opportunity details
    python tools/monitor/sam_scanner.py --detail --opp-id OPP-abc123def456

    # View scan history
    python tools/monitor/sam_scanner.py --history --json

API Reference:
    SAM.gov Opportunities API v2
    https://api.sam.gov/opportunities/v2/search
    API key required via SAM_GOV_API_KEY environment variable.
"""

import argparse
import hashlib
import json
import os
import sqlite3
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Graceful optional imports
# ---------------------------------------------------------------------------
try:
    import yaml
except ImportError:
    yaml = None

try:
    import requests
except ImportError:
    requests = None

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent.parent
DB_PATH = Path(os.environ.get(
    "GOVPROPOSAL_DB_PATH", str(BASE_DIR / "data" / "govproposal.db")
))

# Load .env if present (development convenience; production uses real env vars)
try:
    from dotenv import load_dotenv
    _env_path = BASE_DIR / ".env"
    if _env_path.exists():
        load_dotenv(_env_path, override=False)
except ImportError:
    pass
CONFIG_PATH = BASE_DIR / "args" / "proposal_config.yaml"

# ---------------------------------------------------------------------------
# SAM.gov API type code -> opportunity_type mapping
# ---------------------------------------------------------------------------
SAM_TYPE_MAP = {
    "o": "solicitation",
    "p": "presolicitation",
    "k": "combined_synopsis",
    "r": "sources_sought",
    "i": "special_notice",
    "g": "award_notice",
    "s": "special_notice",
    "a": "award_notice",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_db(db_path=None):
    """Return a sqlite3 connection with WAL mode and foreign keys enabled."""
    path = str(db_path or DB_PATH)
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    return conn


def _now():
    """Return current UTC timestamp as ISO-8601 string."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _opp_id():
    """Generate a unique opportunity ID: OPP- + 12 hex chars."""
    raw = hashlib.sha256(os.urandom(32)).hexdigest()[:12]
    return f"OPP-{raw}"


def _score_id():
    """Generate a unique score ID: SCR- + 12 hex chars."""
    raw = hashlib.sha256(os.urandom(32)).hexdigest()[:12]
    return f"SCR-{raw}"


def _audit(conn, event_type, action, entity_type=None, entity_id=None,
           details=None, actor="sam_scanner"):
    """Write an append-only audit trail entry."""
    conn.execute(
        "INSERT INTO audit_trail (event_type, actor, action, entity_type, "
        "entity_id, details, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (event_type, actor, action, entity_type, entity_id,
         json.dumps(details) if isinstance(details, dict) else details,
         _now()),
    )


def _load_config():
    """Load proposal_config.yaml; returns dict or empty dict on failure."""
    if yaml is None:
        return {}
    if not CONFIG_PATH.exists():
        return {}
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
            return yaml.safe_load(fh) or {}
    except Exception:
        return {}


def _parse_sam_response(data):
    """Parse a SAM.gov API v2 JSON response into a list of opportunity dicts.

    SAM.gov returns opportunities under the ``opportunitiesData`` key. Each
    item has fields such as noticeId, title, solicitationNumber, department,
    subtier, office, postedDate, responseDeadLine, naicsCode,
    classificationCode, typeOfSetAside, type, description, etc.

    Returns a list of dicts ready for insertion into the opportunities table.
    """
    results = []
    opps = data.get("opportunitiesData", [])
    if not opps:
        # Fallback: check alternate key
        opps = data.get("opportunities", data.get("data", []))

    for item in opps:
        opp_type_code = (item.get("type") or "").lower()
        opp_type = SAM_TYPE_MAP.get(opp_type_code, "solicitation")

        # Build description from available text fields
        desc_parts = []
        for key in ("description", "additionalInfoLink", "organizationType"):
            val = item.get(key)
            if val:
                desc_parts.append(str(val))
        description = "\n".join(desc_parts) if desc_parts else None

        # Parse point of contact
        pocs = item.get("pointOfContact", [])
        contact_name = None
        contact_email = None
        contact_phone = None
        if pocs and isinstance(pocs, list):
            primary = pocs[0] if pocs else {}
            contact_name = primary.get("fullName") or primary.get("name")
            contact_email = primary.get("email")
            contact_phone = primary.get("phone")

        # Parse place of performance
        pop = item.get("placeOfPerformance", {})
        pop_str = None
        if pop:
            pop_parts = []
            if pop.get("city", {}).get("name"):
                pop_parts.append(pop["city"]["name"])
            if pop.get("state", {}).get("name"):
                pop_parts.append(pop["state"]["name"])
            if pop.get("country", {}).get("name"):
                pop_parts.append(pop["country"]["name"])
            if pop_parts:
                pop_str = ", ".join(pop_parts)

        # Build the URL to the opportunity on SAM.gov
        notice_id = item.get("noticeId", "")
        source_url = (
            f"https://sam.gov/opp/{notice_id}/view"
            if notice_id else None
        )

        # Attachments: store resource links if present
        attachments = None
        resource_links = item.get("resourceLinks", [])
        if resource_links:
            attachments = json.dumps(resource_links)

        # Archive info
        archive_info = item.get("archive", {})
        archive_date = archive_info.get("date") if archive_info else None

        # Award info (for award notices / modifications)
        award = item.get("award", {})

        row = {
            "sam_notice_id": notice_id,
            "title": item.get("title", "Untitled"),
            "solicitation_number": item.get("solicitationNumber"),
            "agency": item.get("fullParentPathName")
                      or item.get("department", {}).get("name")
                      or item.get("department", "Unknown"),
            "sub_agency": (item.get("subtierAgency", {}).get("name")
                           if isinstance(item.get("subtierAgency"), dict)
                           else item.get("subtierAgency")),
            "office": (item.get("office", {}).get("name")
                       if isinstance(item.get("office"), dict)
                       else item.get("office")),
            "naics_code": item.get("naicsCode"),
            "set_aside_type": item.get("typeOfSetAside")
                              or item.get("typeOfSetAsideDescription"),
            "contract_type": item.get("archiveType"),
            "classification_code": item.get("classificationCode"),
            "description": description,
            "response_deadline": item.get("responseDeadLine"),
            "posted_date": item.get("postedDate"),
            "archive_date": archive_date,
            "place_of_performance": pop_str,
            "contact_name": contact_name,
            "contact_email": contact_email,
            "contact_phone": contact_phone,
            "opportunity_type": opp_type,
            "source_url": source_url,
            "full_text": json.dumps(item),
            "attachments": attachments,
            "estimated_value_low": (award.get("amount")
                                    if award else None),
        }
        results.append(row)

    return results


# ---------------------------------------------------------------------------
# Core functions
# ---------------------------------------------------------------------------

def scan_opportunities(naics=None, agency=None, days_back=7, db_path=None):
    """Query SAM.gov Opportunities API v2 for new opportunities.

    Args:
        naics: Comma-separated NAICS codes or list. If None, uses config
               defaults.
        agency: Agency name filter. If None, uses config defaults.
        days_back: Number of days to look back for posted opportunities.
        db_path: Override database path.

    Returns:
        dict with keys: status, new_count, duplicate_count, total_scanned,
        errors, scan_time.
    """
    config = _load_config()
    sam_cfg = config.get("sam_gov", {})
    api_base = sam_cfg.get("api_base", "https://api.sam.gov/opportunities/v2")
    api_key = os.environ.get("SAM_GOV_API_KEY", "")
    max_per_page = sam_cfg.get("max_results_per_page", 100)

    # ---- Validate prerequisites ----
    if requests is None:
        return {
            "status": "error",
            "error": "requests library not installed. "
                     "Install with: pip install requests",
            "new_count": 0,
            "duplicate_count": 0,
            "total_scanned": 0,
        }

    if not api_key:
        return {
            "status": "error",
            "error": "SAM_GOV_API_KEY environment variable not set. "
                     "Register at https://sam.gov/content/entity-registration "
                     "to obtain an API key.",
            "new_count": 0,
            "duplicate_count": 0,
            "total_scanned": 0,
        }

    # ---- Build query parameters ----
    posted_from = (
        datetime.now(timezone.utc) - timedelta(days=days_back)
    ).strftime("%m/%d/%Y")
    posted_to = datetime.now(timezone.utc).strftime("%m/%d/%Y")

    params = {
        "api_key": api_key,
        "postedFrom": posted_from,
        "postedTo": posted_to,
        "limit": max_per_page,
        "offset": 0,
    }

    # NAICS filter — SAM.gov ncode param only accepts one code at a time.
    # Build a list of codes; we'll iterate over them making one call each.
    naics_list = None
    if naics:
        naics_list = (naics if isinstance(naics, list)
                      else [n.strip() for n in naics.split(",")])
    elif sam_cfg.get("default_naics"):
        naics_list = sam_cfg["default_naics"]

    # Opportunity type filter
    opp_types = sam_cfg.get("opportunity_types", ["o", "p", "k", "r", "i"])
    if opp_types:
        params["ptype"] = ",".join(opp_types)

    # Agency filter (description-based for API v2)
    target_agency = agency  # may be None

    # ---- Build list of (naics_code_or_None) slices to query ----
    # If no NAICS specified run one unfiltered call; otherwise one call per code.
    naics_slices = naics_list if naics_list else [None]

    # ---- Execute API calls (one per NAICS code) with pagination ----
    all_raw = []
    seen_notice_ids = set()   # dedup across NAICS slices
    total_available = None
    errors = []
    max_pages = 10  # Safety limit per NAICS slice

    for ncode in naics_slices:
        slice_params = dict(params)
        if ncode is not None:
            slice_params["ncode"] = str(ncode)
        else:
            slice_params.pop("ncode", None)

        # Small pause between NAICS slice calls to respect rate limits
        if ncode != naics_slices[0]:
            time.sleep(0.5)

        page = 0
        slice_hit_limit = False
        while page < max_pages:
            slice_params["offset"] = page * max_per_page
            try:
                resp = requests.get(
                    f"{api_base}/search",
                    params=slice_params,
                    timeout=30,
                    headers={"Accept": "application/json"},
                )
                if resp.status_code == 429:
                    errors.append(
                        "SAM.gov rate limit reached (HTTP 429). "
                        "Individual (non-federal) accounts are limited to "
                        "10 requests/day. Request a System Account at "
                        "https://sam.gov for 1,000+/day. "
                        "Try again tomorrow or reduce the number of NAICS codes."
                    )
                    slice_hit_limit = True
                    break
                resp.raise_for_status()
                data = resp.json()
            except requests.exceptions.ConnectionError as exc:
                errors.append(f"Connection error: {exc}")
                break
            except requests.exceptions.Timeout:
                errors.append("API request timed out after 30s")
                break
            except requests.exceptions.HTTPError as exc:
                errors.append(f"HTTP error {resp.status_code}: {exc}")
                break
            except (ValueError, json.JSONDecodeError) as exc:
                errors.append(f"Invalid JSON response: {exc}")
                break
        if slice_hit_limit:
            break

            parsed = _parse_sam_response(data)

            # Cross-slice deduplication by notice ID
            for item in parsed:
                nid = item.get("sam_notice_id")
                if nid and nid not in seen_notice_ids:
                    seen_notice_ids.add(nid)
                    all_raw.append(item)
                elif not nid:
                    all_raw.append(item)

            # Accumulate total from first page of first slice
            if total_available is None:
                total_available = data.get("totalRecords", len(parsed))

            if len(parsed) < max_per_page:
                break
            page += 1

    # ---- Apply agency filter client-side (API v2 doesn't have exact match)
    if target_agency:
        agency_lower = target_agency.lower()
        all_raw = [
            r for r in all_raw
            if agency_lower in (r.get("agency") or "").lower()
        ]

    # ---- Deduplicate and insert into DB ----
    conn = _get_db(db_path)
    new_count = 0
    dup_count = 0

    try:
        for opp in all_raw:
            notice_id = opp.get("sam_notice_id")
            if not notice_id:
                continue

            # Check for existing entry
            existing = conn.execute(
                "SELECT id FROM opportunities WHERE sam_notice_id = ?",
                (notice_id,),
            ).fetchone()

            if existing:
                dup_count += 1
                continue

            opp_id = _opp_id()
            now = _now()
            conn.execute(
                """INSERT INTO opportunities (
                    id, sam_notice_id, title, solicitation_number, agency,
                    sub_agency, office, naics_code, set_aside_type,
                    contract_type, classification_code, description,
                    response_deadline, posted_date, archive_date,
                    place_of_performance, contact_name, contact_email,
                    contact_phone, opportunity_type, source_url, full_text,
                    attachments, estimated_value_low, status,
                    discovered_at, updated_at
                ) VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, 'discovered', ?, ?
                )""",
                (
                    opp_id, notice_id, opp["title"],
                    opp["solicitation_number"], opp["agency"],
                    opp["sub_agency"], opp["office"], opp["naics_code"],
                    opp["set_aside_type"], opp["contract_type"],
                    opp["classification_code"], opp["description"],
                    opp["response_deadline"], opp["posted_date"],
                    opp["archive_date"], opp["place_of_performance"],
                    opp["contact_name"], opp["contact_email"],
                    opp["contact_phone"], opp["opportunity_type"],
                    opp["source_url"], opp["full_text"],
                    opp["attachments"], opp["estimated_value_low"],
                    now, now,
                ),
            )
            new_count += 1

            _audit(
                conn, "opportunity.discovered", f"Discovered: {opp['title']}",
                "opportunity", opp_id,
                {"sam_notice_id": notice_id, "agency": opp["agency"],
                 "naics": opp["naics_code"]},
            )

        conn.commit()

        # Record scan in audit trail
        _audit(
            conn, "scan.completed", "SAM.gov scan completed",
            details={
                "days_back": days_back,
                "naics_filter": naics,
                "agency_filter": agency,
                "new": new_count,
                "duplicates": dup_count,
                "total": len(all_raw),
                "errors": errors,
            },
        )
        conn.commit()

    finally:
        conn.close()

    return {
        "status": "success" if not errors else "partial",
        "new_count": new_count,
        "duplicate_count": dup_count,
        "total_scanned": len(all_raw),
        "total_available": total_available,
        "errors": errors if errors else None,
        "scan_time": _now(),
        "filters": {
            "naics": naics,
            "agency": agency,
            "days_back": days_back,
        },
    }


def scan_modifications(days_back=3, db_path=None):
    """Check SAM.gov for modifications to already-tracked opportunities.

    Queries the SAM.gov API for modification notices and matches them
    against existing tracked opportunities by solicitation number.

    Args:
        days_back: Number of days to look back for modifications.
        db_path: Override database path.

    Returns:
        dict with keys: status, modifications_found, updated_count, errors.
    """
    config = _load_config()
    sam_cfg = config.get("sam_gov", {})
    api_base = sam_cfg.get("api_base", "https://api.sam.gov/opportunities/v2")
    api_key = os.environ.get("SAM_GOV_API_KEY", "")

    if requests is None:
        return {
            "status": "error",
            "error": "requests library not installed",
            "modifications_found": 0,
            "updated_count": 0,
        }

    if not api_key:
        return {
            "status": "error",
            "error": "SAM_GOV_API_KEY environment variable not set",
            "modifications_found": 0,
            "updated_count": 0,
        }

    posted_from = (
        datetime.now(timezone.utc) - timedelta(days=days_back)
    ).strftime("%m/%d/%Y")
    posted_to = datetime.now(timezone.utc).strftime("%m/%d/%Y")

    params = {
        "api_key": api_key,
        "postedFrom": posted_from,
        "postedTo": posted_to,
        "ptype": "a",  # Award/modification type
        "limit": 100,
        "offset": 0,
    }

    errors = []
    modifications = []
    try:
        resp = requests.get(
            f"{api_base}/search",
            params=params,
            timeout=30,
            headers={"Accept": "application/json"},
        )
        resp.raise_for_status()
        data = resp.json()
        modifications = _parse_sam_response(data)
    except Exception as exc:
        errors.append(f"API error: {exc}")

    # Match modifications against tracked opportunities
    conn = _get_db(db_path)
    updated_count = 0

    try:
        for mod in modifications:
            sol_num = mod.get("solicitation_number")
            notice_id = mod.get("sam_notice_id")
            if not sol_num and not notice_id:
                continue

            # Find matching tracked opportunity
            row = None
            if sol_num:
                row = conn.execute(
                    "SELECT id, title FROM opportunities "
                    "WHERE solicitation_number = ? "
                    "AND status NOT IN ('no_bid', 'archived')",
                    (sol_num,),
                ).fetchone()

            if not row and notice_id:
                row = conn.execute(
                    "SELECT id, title FROM opportunities "
                    "WHERE sam_notice_id = ? "
                    "AND status NOT IN ('no_bid', 'archived')",
                    (notice_id,),
                ).fetchone()

            if not row:
                continue

            opp_id = row["id"]
            now = _now()

            # Update key fields that may have changed
            updates = {}
            if mod.get("response_deadline"):
                updates["response_deadline"] = mod["response_deadline"]
            if mod.get("description"):
                updates["description"] = mod["description"]

            if updates:
                set_clause = ", ".join(f"{k} = ?" for k in updates)
                vals = list(updates.values()) + [now, opp_id]
                conn.execute(
                    f"UPDATE opportunities SET {set_clause}, updated_at = ? "
                    f"WHERE id = ?",
                    vals,
                )

            _audit(
                conn, "opportunity.modified",
                f"Modification detected: {row['title']}",
                "opportunity", opp_id,
                {"solicitation_number": sol_num,
                 "updated_fields": list(updates.keys())},
            )
            updated_count += 1

        conn.commit()
    finally:
        conn.close()

    return {
        "status": "success" if not errors else "partial",
        "modifications_found": len(modifications),
        "updated_count": updated_count,
        "errors": errors if errors else None,
        "scan_time": _now(),
    }


def get_scan_history(days=30, db_path=None):
    """Return scan history from the audit trail.

    Args:
        days: Number of days of history to retrieve.
        db_path: Override database path.

    Returns:
        list of dicts with scan event details.
    """
    conn = _get_db(db_path)
    try:
        cutoff = (
            datetime.now(timezone.utc) - timedelta(days=days)
        ).strftime("%Y-%m-%dT%H:%M:%SZ")

        rows = conn.execute(
            "SELECT id, event_type, actor, action, details, created_at "
            "FROM audit_trail "
            "WHERE event_type LIKE 'scan.%' AND created_at >= ? "
            "ORDER BY created_at DESC",
            (cutoff,),
        ).fetchall()

        history = []
        for r in rows:
            entry = {
                "id": r["id"],
                "event_type": r["event_type"],
                "actor": r["actor"],
                "action": r["action"],
                "created_at": r["created_at"],
            }
            if r["details"]:
                try:
                    entry["details"] = json.loads(r["details"])
                except (json.JSONDecodeError, TypeError):
                    entry["details"] = r["details"]
            history.append(entry)

        return history
    finally:
        conn.close()


def list_opportunities(status=None, limit=50, db_path=None):
    """List tracked opportunities with optional status filter.

    Args:
        status: Filter by pipeline status (e.g. 'discovered', 'qualifying').
        limit: Maximum number of results.
        db_path: Override database path.

    Returns:
        list of opportunity dicts.
    """
    conn = _get_db(db_path)
    try:
        if status:
            rows = conn.execute(
                "SELECT id, sam_notice_id, title, solicitation_number, "
                "agency, naics_code, set_aside_type, response_deadline, "
                "posted_date, opportunity_type, status, fit_score, "
                "qualification_score, go_decision, discovered_at "
                "FROM opportunities WHERE status = ? "
                "ORDER BY response_deadline ASC LIMIT ?",
                (status, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, sam_notice_id, title, solicitation_number, "
                "agency, naics_code, set_aside_type, response_deadline, "
                "posted_date, opportunity_type, status, fit_score, "
                "qualification_score, go_decision, discovered_at "
                "FROM opportunities "
                "ORDER BY response_deadline ASC LIMIT ?",
                (limit,),
            ).fetchall()

        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_opportunity_detail(opp_id, db_path=None):
    """Get full details for a single opportunity.

    Args:
        opp_id: The opportunity ID (OPP-xxxx format).
        db_path: Override database path.

    Returns:
        dict with all opportunity fields, scores, and pipeline history,
        or None if not found.
    """
    conn = _get_db(db_path)
    try:
        row = conn.execute(
            "SELECT * FROM opportunities WHERE id = ?", (opp_id,)
        ).fetchone()

        if not row:
            return None

        result = dict(row)

        # Parse full_text JSON if present
        if result.get("full_text"):
            try:
                result["full_text_parsed"] = json.loads(result["full_text"])
            except (json.JSONDecodeError, TypeError):
                result["full_text_parsed"] = None

        # Parse attachments JSON if present
        if result.get("attachments"):
            try:
                result["attachments_parsed"] = json.loads(
                    result["attachments"])
            except (json.JSONDecodeError, TypeError):
                result["attachments_parsed"] = None

        # Fetch dimension scores
        scores = conn.execute(
            "SELECT dimension, score, rationale, evidence, scored_by, "
            "scored_at FROM opportunity_scores "
            "WHERE opportunity_id = ? ORDER BY scored_at DESC",
            (opp_id,),
        ).fetchall()
        result["scores"] = [dict(s) for s in scores]

        # Fetch pipeline history
        stages = conn.execute(
            "SELECT stage, entered_at, exited_at, duration_hours, notes, "
            "advanced_by FROM pipeline_stages "
            "WHERE opportunity_id = ? ORDER BY entered_at ASC",
            (opp_id,),
        ).fetchall()
        result["pipeline_history"] = [dict(s) for s in stages]

        return result
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _format_opp_table(opps):
    """Format opportunity list as human-readable table."""
    if not opps:
        return "  No opportunities found."

    lines = []
    header = (f"  {'ID':<18} {'Status':<13} {'Score':>5}  "
              f"{'Deadline':<12} {'Agency':<30} {'Title'}")
    lines.append(header)
    lines.append("  " + "-" * 110)

    for o in opps:
        score_str = (f"{o['fit_score']:.0f}"
                     if o.get("fit_score") is not None else "--")
        deadline = (o.get("response_deadline") or "N/A")[:10]
        agency = (o.get("agency") or "Unknown")[:29]
        title = (o.get("title") or "Untitled")[:50]
        lines.append(
            f"  {o['id']:<18} {o.get('status', '?'):<13} {score_str:>5}  "
            f"{deadline:<12} {agency:<30} {title}"
        )
    return "\n".join(lines)


def main():
    """CLI entry point for the SAM.gov opportunity scanner."""
    parser = argparse.ArgumentParser(
        description="SAM.gov Opportunity Scanner — discover and track "
                    "government contract opportunities",
    )

    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--scan", action="store_true",
        help="Scan SAM.gov for new opportunities",
    )
    group.add_argument(
        "--scan-mods", action="store_true",
        help="Scan for modifications to tracked opportunities",
    )
    group.add_argument(
        "--history", action="store_true",
        help="View scan history from audit trail",
    )
    group.add_argument(
        "--list", action="store_true",
        help="List tracked opportunities",
    )
    group.add_argument(
        "--detail", action="store_true",
        help="Get full details for an opportunity (requires --opp-id)",
    )

    parser.add_argument("--naics", help="NAICS code(s), comma-separated")
    parser.add_argument("--agency", help="Agency name filter")
    parser.add_argument(
        "--days-back", type=int, default=7,
        help="Days to look back (default: 7)",
    )
    parser.add_argument("--status", help="Filter by status")
    parser.add_argument(
        "--limit", type=int, default=50,
        help="Max results for --list (default: 50)",
    )
    parser.add_argument("--opp-id", help="Opportunity ID for --detail")
    parser.add_argument(
        "--json", action="store_true", help="JSON output",
    )
    parser.add_argument("--db-path", help="Override database path")

    args = parser.parse_args()

    # -------------------------------------------------------------------
    if args.scan:
        result = scan_opportunities(
            naics=args.naics,
            agency=args.agency,
            days_back=args.days_back,
            db_path=args.db_path,
        )
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print("SAM.gov Opportunity Scan")
            print("=" * 40)
            print(f"  Status:      {result['status']}")
            print(f"  New:         {result['new_count']}")
            print(f"  Duplicates:  {result['duplicate_count']}")
            print(f"  Scanned:     {result['total_scanned']}")
            if result.get("total_available"):
                print(f"  Available:   {result['total_available']}")
            if result.get("scan_time"):
                print(f"  Scan time:   {result['scan_time']}")
            if result.get("errors"):
                print(f"  Errors:")
                for e in result["errors"]:
                    print(f"    - {e}")

    # -------------------------------------------------------------------
    elif args.scan_mods:
        result = scan_modifications(
            days_back=args.days_back, db_path=args.db_path,
        )
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print("SAM.gov Modification Scan")
            print("=" * 40)
            print(f"  Status:       {result['status']}")
            print(f"  Found:        {result['modifications_found']}")
            print(f"  Updated:      {result['updated_count']}")
            print(f"  Scan time:    {result['scan_time']}")
            if result.get("errors"):
                print(f"  Errors:")
                for e in result["errors"]:
                    print(f"    - {e}")

    # -------------------------------------------------------------------
    elif args.history:
        history = get_scan_history(
            days=args.days_back, db_path=args.db_path,
        )
        if args.json:
            print(json.dumps(history, indent=2))
        else:
            print(f"Scan History (last {args.days_back} days)")
            print("=" * 40)
            if not history:
                print("  No scan history found.")
            for entry in history:
                print(f"  [{entry['created_at']}] "
                      f"{entry['event_type']}: {entry['action']}")
                if entry.get("details") and isinstance(entry["details"], dict):
                    d = entry["details"]
                    if "new" in d:
                        print(f"    New: {d['new']}, "
                              f"Dups: {d.get('duplicates', 0)}, "
                              f"Total: {d.get('total', 0)}")

    # -------------------------------------------------------------------
    elif args.list:
        opps = list_opportunities(
            status=args.status, limit=args.limit, db_path=args.db_path,
        )
        if args.json:
            print(json.dumps(opps, indent=2))
        else:
            status_label = f" (status={args.status})" if args.status else ""
            print(f"Tracked Opportunities{status_label}")
            print("=" * 40)
            print(_format_opp_table(opps))
            print(f"\n  Total: {len(opps)}")

    # -------------------------------------------------------------------
    elif args.detail:
        if not args.opp_id:
            print("Error: --detail requires --opp-id", file=sys.stderr)
            sys.exit(1)
        detail = get_opportunity_detail(args.opp_id, db_path=args.db_path)
        if args.json:
            print(json.dumps(detail, indent=2, default=str))
        else:
            if detail is None:
                print(f"Opportunity {args.opp_id} not found.")
                sys.exit(1)
            print(f"Opportunity: {detail['title']}")
            print("=" * 60)
            print(f"  ID:              {detail['id']}")
            print(f"  SAM Notice ID:   {detail.get('sam_notice_id', 'N/A')}")
            print(f"  Solicitation:    "
                  f"{detail.get('solicitation_number', 'N/A')}")
            print(f"  Agency:          {detail.get('agency', 'N/A')}")
            print(f"  Sub-Agency:      {detail.get('sub_agency', 'N/A')}")
            print(f"  Office:          {detail.get('office', 'N/A')}")
            print(f"  NAICS:           {detail.get('naics_code', 'N/A')}")
            print(f"  Set-Aside:       {detail.get('set_aside_type', 'N/A')}")
            print(f"  Type:            "
                  f"{detail.get('opportunity_type', 'N/A')}")
            print(f"  Status:          {detail.get('status', 'N/A')}")
            print(f"  Deadline:        "
                  f"{detail.get('response_deadline', 'N/A')}")
            print(f"  Posted:          {detail.get('posted_date', 'N/A')}")
            print(f"  Fit Score:       {detail.get('fit_score', '--')}")
            print(f"  Qual Score:      "
                  f"{detail.get('qualification_score', '--')}")
            print(f"  Go Decision:     {detail.get('go_decision', '--')}")
            print(f"  Contact:         {detail.get('contact_name', 'N/A')} "
                  f"({detail.get('contact_email', 'N/A')})")
            if detail.get("description"):
                desc = detail["description"][:300]
                print(f"\n  Description:\n    {desc}")
            if detail.get("scores"):
                print(f"\n  Scores:")
                for s in detail["scores"]:
                    print(f"    {s['dimension']}: {s['score']:.2f}"
                          f"  ({s.get('rationale', '')})")
            if detail.get("pipeline_history"):
                print(f"\n  Pipeline History:")
                for p in detail["pipeline_history"]:
                    print(f"    {p['stage']}: {p['entered_at']}")


if __name__ == "__main__":
    main()
