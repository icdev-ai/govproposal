#!/usr/bin/env python3
# CUI // SP-PROPIN
"""End-to-end RFX pipeline CLI.

Automates the full SAM.gov document → proposal generation workflow:
  1. Upload RFP document to GovProposal
  2. Extract requirements from the document
  3. Create or reuse an opportunity
  4. Create a proposal linked to the opportunity
  5. Generate all requested sections via AI
  6. Print a summary with proposal URL

Usage examples:
  # Zero-argument batch mode — searches SAM.gov, downloads, and processes everything
  python tools/scripts/rfx_pipeline.py

  # Batch mode with custom search window / item limit
  python tools/scripts/rfx_pipeline.py --days 14 --limit 10

  # Single opportunity — downloads and processes one notice from SAM.gov
  python tools/scripts/rfx_pipeline.py --notice-id 75N98026R00006

  # Use a local file — still auto-detects title/agency/naics from SAM.gov + doc text
  python tools/scripts/rfx_pipeline.py --doc data/rfx_uploads/requirements.docx

  # Override specific fields (auto-detected values used for anything not provided)
  python tools/scripts/rfx_pipeline.py \\
    --notice-id 75N98026R00006 \\
    --title "NIH AI Pilot Tool" \\
    --agency "HEALTH AND HUMAN SERVICES, DEPARTMENT OF" \\
    --naics 541519

  # Reuse an existing opportunity
  python tools/scripts/rfx_pipeline.py \\
    --doc data/rfx_uploads/requirements.docx \\
    --opp-id opp-nih-aipt-001

  # Custom sections
  python tools/scripts/rfx_pipeline.py \\
    --notice-id 75N98026R00006 \\
    --sections "Executive Summary" "Technical Approach" "Cost Volume"

  # Dry run (upload + extract only, no AI generation)
  python tools/scripts/rfx_pipeline.py --dry-run
"""

import argparse
import json
import os
import re
import sys
import time
import uuid
import urllib.request
import urllib.error
from pathlib import Path

# Windows cp1252 console can't render Unicode — force UTF-8 output
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

BASE_DIR = Path(__file__).resolve().parent.parent.parent

GREEN  = "\033[32m"
RED    = "\033[31m"
YELLOW = "\033[33m"
CYAN   = "\033[36m"
RESET  = "\033[0m"
BOLD   = "\033[1m"

DEFAULT_SECTIONS = [
    ("Executive Summary",    "technical"),
    ("Technical Approach",   "technical"),
    ("Management Plan",      "management"),
    ("Past Performance",     "past_performance"),
    ("Quality Assurance Plan", "management"),
]

VOLUME_MAP = {
    "executive summary":    "technical",
    "technical approach":   "technical",
    "technical":            "technical",
    "management plan":      "management",
    "management":           "management",
    "quality assurance":    "management",
    "quality assurance plan": "management",
    "past performance":     "past_performance",
    "cost":                 "cost",
    "cost volume":          "cost",
    "price":                "cost",
}


def _ok(msg):   print(f"{GREEN}  ✓{RESET} {msg}")
def _warn(msg): print(f"{YELLOW}  ⚠{RESET} {msg}")
def _err(msg):  print(f"{RED}  ✗{RESET} {msg}")
def _info(msg): print(f"{CYAN}  →{RESET} {msg}")
def _step(n, total, msg): print(f"\n{BOLD}[{n}/{total}] {msg}{RESET}")


# ── HTTP helpers using only stdlib (avoids requests connection reset on Windows) ─

def _post_json(url: str, payload: dict, timeout: int = 30) -> dict:
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def _post_multipart(url: str, file_path: Path,
                    fields: dict, timeout: int = 30) -> dict:
    """Upload a file as multipart/form-data."""
    boundary = uuid.uuid4().hex
    body_parts = []

    for key, value in fields.items():
        body_parts.append(
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="{key}"\r\n\r\n'
            f"{value}\r\n"
        )

    file_content = file_path.read_bytes()
    mime = _guess_mime(file_path.suffix)
    body_parts.append(
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{file_path.name}"\r\n'
        f"Content-Type: {mime}\r\n\r\n"
    )
    body = ("".join(body_parts)).encode() + file_content + f"\r\n--{boundary}--\r\n".encode()

    req = urllib.request.Request(
        url, data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def _guess_mime(suffix: str) -> str:
    return {
        ".pdf":  "application/pdf",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".doc":  "application/msword",
        ".txt":  "text/plain",
        ".md":   "text/markdown",
    }.get(suffix.lower(), "application/octet-stream")


def _check_server(base_url: str) -> bool:
    try:
        with urllib.request.urlopen(f"{base_url}/", timeout=5) as r:
            return r.status < 500
    except urllib.error.HTTPError as e:
        return e.code < 500
    except Exception:
        return False


# ── Metadata Auto-Detection ────────────────────────────────────────────────────

# Solicitation number pattern — matches these common federal formats:
#   75N98026R00006   (NIH: digits-letter-digits-letter-digits, no hyphens)
#   36C10B22R0095    (VA: similar compact format with extra segment)
#   W52P1J-24-R-0012 (Army: hyphenated alpha-numeric segments)
#   FA8730-25-R-0001 (Air Force: hyphenated)
#   FA873025R00001   (compact alpha-start)
_NOTICE_ID_RE = re.compile(
    r'\b('
    # Hyphenated with numeric segments: W52P1J-24-R-0012  FA8730-25-R-0001
    # Requires: alphanum prefix, a purely-numeric segment, a letter segment, a numeric suffix
    r'[A-Z][A-Z0-9]{2,8}-[0-9]{2,4}-[A-Z]{1,3}-[0-9]{3,8}'
    # Alpha-start compact: FA873025R00001  FA873025R0001A
    r'|[A-Z]{1,4}[0-9]{3,10}[A-Z]{1,3}[0-9]{3,10}'
    # Digit-start compact: 75N98026R00006  36C10B22R0095
    r'|[0-9]{2,4}[A-Z]{1,3}[0-9]{2,8}[A-Z]{1,2}[0-9]{2,6}(?:[A-Z]{1,2}[0-9]{2,6})?'
    r')\b',
    re.IGNORECASE,
)

# Doc-text regex patterns (label: regex)
_TEXT_PATTERNS = {
    "notice_id": re.compile(
        r'(?:solicitation\s+(?:number|no\.?)|notice\s+id|rfp\s+(?:number|no\.?))\s*[:\-#]?\s*([A-Z0-9][-A-Z0-9_]{5,20})',
        re.IGNORECASE,
    ),
    "naics": re.compile(
        r'\bnaics\s+(?:code\s*)?[:\-#]?\s*(\d{4,6})', re.IGNORECASE
    ),
    "agency": re.compile(
        r'(?:issuing\s+office|contracting\s+office|department|agency)\s*[:\-]?\s*([A-Z][A-Za-z ,&\(\)]{5,80})',
        re.IGNORECASE,
    ),
    "title": re.compile(
        r'(?:subject|title|solicitation\s+title|project\s+title)\s*[:\-]?\s*([A-Z][A-Za-z0-9 ,\-\(\)]{10,120})',
        re.IGNORECASE,
    ),
}


def _load_env() -> dict:
    """Load key=value pairs from .env, return as dict."""
    env_file = BASE_DIR / ".env"
    if not env_file.exists():
        return {}
    result = {}
    for line in env_file.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            result[k.strip()] = v.strip()
    return result


def _extract_docx_text(path: Path) -> str:
    """Extract plain text from a .docx file using python-docx."""
    try:
        from docx import Document  # type: ignore
        doc = Document(str(path))
        return "\n".join(p.text for p in doc.paragraphs if p.text.strip())
    except ImportError:
        _warn("python-docx not installed — skipping document text extraction")
        return ""
    except Exception as e:
        _warn(f"Could not read docx text: {e}")
        return ""


def _extract_pdf_text(path: Path) -> str:
    """Extract plain text from a PDF using pypdf."""
    try:
        from pypdf import PdfReader  # type: ignore
        reader = PdfReader(str(path))
        parts = []
        for page in reader.pages[:10]:  # first 10 pages is enough for metadata
            parts.append(page.extract_text() or "")
        return "\n".join(parts)
    except ImportError:
        return ""
    except Exception as e:
        _warn(f"Could not read pdf text: {e}")
        return ""


def _sam_lookup(notice_id: str, api_key: str) -> dict:
    """Call SAM.gov Opportunities API and return metadata dict (may be empty)."""
    url = (
        f"https://api.sam.gov/opportunities/v2/search"
        f"?api_key={api_key}&noticeid={notice_id}&limit=1"
    )
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        hits = data.get("opportunitiesData", [])
        if not hits:
            return {}
        opp = hits[0]
        result = {}
        # Title
        title_val = opp.get("title", "").strip()
        if title_val:
            result["title"] = title_val
        # Agency — try several field paths
        agency_val = (
            opp.get("organizationName")
            or opp.get("organizationHierarchy", [{}])[0].get("name", "")
            or opp.get("fullParentPathName", "")
        ).strip()
        if agency_val:
            result["agency"] = agency_val
        # NAICS
        naics_val = str(opp.get("naicsCode", "")).strip()
        if naics_val and naics_val != "None":
            result["naics"] = naics_val
        return result
    except Exception as e:
        _warn(f"SAM.gov API lookup failed: {e}")
        return {}


def _sam_download_doc(notice_id: str, api_key: str, dest_dir: Path) -> Path | None:
    """Download the first attached document for a SAM.gov opportunity.

    Uses the opportunity's resourceLinks from the v2 search API.
    Saves the file to dest_dir using the name reported by SAM.gov.
    Returns Path to saved file, or None if no attachments found/downloadable.
    """
    search_url = (
        f"https://api.sam.gov/opportunities/v2/search"
        f"?api_key={api_key}&noticeid={notice_id}&limit=1"
    )
    try:
        req = urllib.request.Request(search_url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
    except Exception as e:
        _warn(f"SAM.gov search failed: {e}")
        return None

    hits = data.get("opportunitiesData", [])
    if not hits:
        _warn(f"No opportunity found for notice ID '{notice_id}'")
        return None

    resource_links = hits[0].get("resourceLinks", [])
    if not resource_links:
        _warn("This opportunity has no attached documents on SAM.gov")
        return None

    dest_dir.mkdir(parents=True, exist_ok=True)

    for link in resource_links:
        # resourceLinks may be strings or dicts depending on API version
        if isinstance(link, dict):
            file_url  = link.get("url") or link.get("fileDownloadUrl", "")
            file_name = link.get("name") or link.get("fileName", "")
        else:
            file_url  = str(link)
            file_name = ""

        if not file_url:
            continue

        # Append api_key if not already present
        if "api_key" not in file_url:
            sep = "&" if "?" in file_url else "?"
            file_url = f"{file_url}{sep}api_key={api_key}"

        _info(f"Downloading document from SAM.gov...")
        try:
            dl_req = urllib.request.Request(file_url, headers={"Accept": "*/*"})
            with urllib.request.urlopen(dl_req, timeout=60) as resp:
                content = resp.read()
                # Try Content-Disposition for canonical filename
                cd = resp.headers.get("Content-Disposition", "")
                if cd and "filename=" in cd:
                    m = re.search(r'filename[^;=\n]*=(["\']?)([^"\';\n]+)\1', cd)
                    if m:
                        file_name = m.group(2).strip()
            # Fall back to URL basename
            if not file_name:
                file_name = file_url.split("?")[0].split("/")[-1]
            if not file_name:
                file_name = f"{notice_id}_rfp.pdf"
            dest_path = dest_dir / file_name
            dest_path.write_bytes(content)
            _ok(f"Downloaded {file_name} ({len(content):,} bytes)")
            return dest_path
        except Exception as e:
            _warn(f"Could not download attachment: {e}")
            continue

    _warn("All resource links failed to download")
    return None


def _sam_search_opportunities(api_key: str,
                               days: int = 7,
                               limit: int = 5) -> list[dict]:
    """Search SAM.gov for recent active solicitations that have attachments.

    Returns a list of dicts:
        {notice_id, title, agency, naics, resource_links}
    Only entries with at least one resource link are returned.
    """
    from datetime import datetime, timedelta
    today = datetime.utcnow()
    posted_from = (today - timedelta(days=days)).strftime("%m/%d/%Y")
    posted_to   = today.strftime("%m/%d/%Y")

    # ptype=o → solicitation, p → presolicitation
    url = (
        "https://api.sam.gov/opportunities/v2/search"
        f"?api_key={api_key}"
        f"&postedFrom={posted_from}&postedTo={posted_to}"
        "&ptype=o,p"
        "&status=active"
        f"&limit={limit}"
    )
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
    except Exception as e:
        _warn(f"SAM.gov batch search failed: {e}")
        return []

    hits = data.get("opportunitiesData", [])
    results = []
    for opp in hits:
        resource_links = opp.get("resourceLinks") or []
        if not resource_links:
            continue  # skip opps with no downloadable attachments

        notice_id = (opp.get("noticeId") or opp.get("solicitationNumber") or "").strip()
        if not notice_id:
            continue  # can't process without an ID

        title  = opp.get("title", "").strip()
        agency = (
            opp.get("organizationName")
            or (opp.get("organizationHierarchy") or [{}])[0].get("name", "")
            or opp.get("fullParentPathName", "")
        ).strip()
        naics = str(opp.get("naicsCode", "")).strip()
        if naics in ("None", ""):
            naics = ""

        results.append({
            "notice_id":     notice_id,
            "title":         title,
            "agency":        agency,
            "naics":         naics,
            "resource_links": resource_links,
        })

    return results


def detect_rfp_metadata(doc_path: Path, known_notice_id: str = "") -> dict:
    """Auto-detect RFP metadata from filename, SAM.gov API, and document text.

    known_notice_id: if already known (e.g. from CLI --notice-id), skip filename scan
                     and use it directly for the SAM.gov lookup.
    Returns a dict with any subset of: notice_id, title, agency, naics.
    """
    meta: dict = {}

    # ── Step 1: notice ID — use known value or scan filename ──────────────────
    if known_notice_id:
        meta["notice_id"] = known_notice_id.upper()
        _info(f"Notice ID (provided): {meta['notice_id']}")
    else:
        m = _NOTICE_ID_RE.search(doc_path.stem)
        if m:
            meta["notice_id"] = m.group(0).upper()
            _info(f"Notice ID from filename: {meta['notice_id']}")

    # ── Step 2: SAM.gov API lookup (if key + notice_id available) ─────────────
    env = _load_env()
    sam_key = env.get("SAM_GOV_API_KEY", "")
    if sam_key and meta.get("notice_id"):
        _info(f"Looking up {meta['notice_id']} on SAM.gov...")
        sam_data = _sam_lookup(meta["notice_id"], sam_key)
        if sam_data:
            meta.update(sam_data)
            _ok(f"SAM.gov: title='{sam_data.get('title', '')}' "
                f"agency='{sam_data.get('agency', '')}' "
                f"naics='{sam_data.get('naics', '')}'")
        else:
            _warn("SAM.gov returned no results for this notice ID")

    # ── Step 3: Parse document text as fallback ────────────────────────────────
    missing = [k for k in ("notice_id", "title", "agency", "naics") if not meta.get(k)]
    if missing:
        suffix = doc_path.suffix.lower()
        if suffix == ".docx":
            text = _extract_docx_text(doc_path)
        elif suffix == ".pdf":
            text = _extract_pdf_text(doc_path)
        else:
            text = ""

        if text:
            for field, pattern in _TEXT_PATTERNS.items():
                if field in missing:
                    m2 = pattern.search(text)
                    if m2:
                        val = m2.group(1).strip().rstrip(".,;")
                        meta[field] = val
                        _info(f"Detected {field} from document: '{val}'")

    return meta


# ── Pipeline Steps ─────────────────────────────────────────────────────────────

def step_upload(doc_path: Path, base_url: str) -> str:
    """Upload document. Returns document_id.

    Handles 409 (duplicate) gracefully — returns the existing document_id.
    """
    _info(f"Uploading {doc_path.name} ({doc_path.stat().st_size:,} bytes)...")
    try:
        result = _post_multipart(
            f"{base_url}/api/rfx/documents/upload",
            doc_path,
            fields={"doc_type": "rfp", "notes": "Uploaded via rfx_pipeline.py"},
            timeout=60,
        )
    except urllib.error.HTTPError as e:
        if e.code == 409:
            # Duplicate — server returns existing document_id in the body
            body = json.loads(e.read())
            doc_id = body.get("document_id")
            if doc_id:
                _warn(f"Document already uploaded — reusing id: {doc_id}")
                return doc_id
        raise

    if "error" in result:
        raise RuntimeError(f"Upload failed: {result['error']}")
    doc_id = result["document_id"]
    chunks = result.get("chunk_count", "?")
    _ok(f"Document uploaded — id: {doc_id}, chunks: {chunks}")
    return doc_id


def step_create_opportunity(title: str, agency: str, naics: str,
                             notice_id: str, base_url: str) -> str:
    """Insert opportunity. Returns opportunity_id.

    If notice_id already exists in DB, returns the existing opp id (idempotent).
    """
    import sqlite3
    env_file = BASE_DIR / ".env"
    db_path_str = None
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if line.startswith("GOVPROPOSAL_DB_PATH="):
                db_path_str = line.split("=", 1)[1].strip()
    db_path = Path(db_path_str) if db_path_str else BASE_DIR / "data" / "govproposal.db"

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        # Check if notice_id already exists
        if notice_id:
            existing = conn.execute(
                "SELECT id FROM opportunities WHERE sam_notice_id = ?", (notice_id,)
            ).fetchone()
            if existing:
                opp_id = existing["id"]
                _warn(f"Opportunity already exists for notice {notice_id} — reusing id: {opp_id}")
                return opp_id

        opp_id = f"opp-{uuid.uuid4().hex[:8]}"
        conn.execute("""
            INSERT INTO opportunities
                (id, sam_notice_id, title, agency, naics_code, status,
                 discovered_at, updated_at)
            VALUES (?, ?, ?, ?, ?, 'qualifying', datetime('now'), datetime('now'))
        """, (opp_id, notice_id or "", title, agency or "", naics or ""))
        conn.commit()
    finally:
        conn.close()

    _ok(f"Opportunity created — id: {opp_id}")
    return opp_id


def step_create_proposal(opp_id: str, title: str, base_url: str) -> str:
    """Create proposal. Returns proposal_id."""
    result = _post_json(
        f"{base_url}/api/rfx/proposals/create",
        {"opportunity_id": opp_id, "title": title},
    )
    if "error" in result:
        raise RuntimeError(f"Proposal create failed: {result['error']}")
    proposal_id = result["proposal_id"]
    _ok(f"Proposal created — id: {proposal_id}")
    return proposal_id


def step_extract_requirements(doc_id: str, proposal_id: str, base_url: str) -> int:
    """Extract requirements. Returns count extracted."""
    result = _post_json(
        f"{base_url}/api/rfx/requirements/extract",
        {"doc_id": doc_id, "proposal_id": proposal_id},
        timeout=60,
    )
    if "error" in result:
        _warn(f"Requirement extraction warning: {result['error']}")
        return 0
    count = result.get("total", result.get("count", len(result.get("requirements", []))))
    _ok(f"{count} requirements extracted")
    return count


def step_generate_sections(proposal_id: str,
                            sections: list[tuple[str, str]],
                            base_url: str,
                            dry_run: bool = False) -> list[dict]:
    """Generate AI sections. Returns list of results."""
    if dry_run:
        _info("--dry-run: skipping AI section generation")
        return []

    results = []
    for i, (title, volume) in enumerate(sections, 1):
        _info(f"  [{i}/{len(sections)}] Generating '{title}' ({volume})...")
        try:
            result = _post_json(
                f"{base_url}/api/rfx/ai/generate",
                {"proposal_id": proposal_id, "section_title": title, "volume": volume},
                timeout=120,
            )
            if "error" in result:
                _warn(f"  Generation warning for '{title}': {result['error']}")
                results.append({"section_title": title, "status": "error", "error": result["error"]})
            else:
                words = len(result.get("content_draft", "").split())
                _ok(f"  '{title}' — {words} words")
                results.append({"section_title": title, "status": "ok", "words": words})
        except Exception as e:
            _err(f"  Failed to generate '{title}': {e}")
            results.append({"section_title": title, "status": "error", "error": str(e)})

    return results


# ── Section argument parsing ───────────────────────────────────────────────────

def parse_sections(section_args: list[str] | None) -> list[tuple[str, str]]:
    """Convert CLI --sections args to (title, volume) pairs."""
    if not section_args:
        return DEFAULT_SECTIONS
    result = []
    for s in section_args:
        volume = VOLUME_MAP.get(s.lower(), "technical")
        result.append((s, volume))
    return result


# ── Single-document pipeline runner ───────────────────────────────────────────

def _run_pipeline_for_doc(
    doc_path:  Path,
    notice_id: str,
    title:     str,
    agency:    str,
    naics:     str,
    opp_id:    str,          # "" → create new
    sections:  list[tuple[str, str]],
    base_url:  str,
    dry_run:   bool = False,
) -> dict:
    """Run the full upload→opportunity→proposal→extract→generate pipeline for one doc.

    Returns a summary dict.  On partial failure the dict contains an 'error' key
    and processing stops at that step (the caller decides whether to continue).
    """
    total_steps = (4 if opp_id else 5) + (0 if dry_run else 1)
    step        = 1
    summary: dict = {"doc": str(doc_path), "title": title, "notice_id": notice_id}

    # ── Upload ────────────────────────────────────────────────────────────────
    _step(step, total_steps, "Upload document")
    step += 1
    try:
        doc_id = step_upload(doc_path, base_url)
        summary["document_id"] = doc_id
    except Exception as e:
        _err(f"Upload failed: {e}")
        summary["error"] = str(e)
        return summary

    # ── Opportunity ───────────────────────────────────────────────────────────
    if opp_id:
        _info(f"Reusing opportunity: {opp_id}")
        summary["opportunity_id"] = opp_id
    else:
        _step(step, total_steps, "Create opportunity")
        step += 1
        try:
            opp_id = step_create_opportunity(title, agency, naics, notice_id, base_url)
            summary["opportunity_id"] = opp_id
        except Exception as e:
            _err(f"Opportunity creation failed: {e}")
            summary["error"] = str(e)
            return summary

    # ── Proposal ──────────────────────────────────────────────────────────────
    _step(step, total_steps, "Create proposal")
    step += 1
    try:
        proposal_id = step_create_proposal(opp_id, title, base_url)
        summary["proposal_id"] = proposal_id
    except Exception as e:
        _err(f"Proposal creation failed: {e}")
        summary["error"] = str(e)
        return summary

    # ── Requirements ──────────────────────────────────────────────────────────
    _step(step, total_steps, "Extract requirements")
    step += 1
    req_count = step_extract_requirements(doc_id, proposal_id, base_url)
    summary["requirements_extracted"] = req_count

    # ── Generate sections ──────────────────────────────────────────────────────
    if not dry_run:
        _step(step, total_steps, f"Generate {len(sections)} AI sections")
        results = step_generate_sections(proposal_id, sections, base_url)
        summary["sections"] = results
        summary["sections_generated"] = sum(1 for r in results if r.get("status") == "ok")

    summary["proposal_url"] = f"{base_url}/ai-proposals/{proposal_id}"
    return summary


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="End-to-end RFX pipeline: document → proposal sections",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--doc", default=None,
                        help="Path to RFP document (.docx, .pdf, .txt). "
                             "If omitted, the document is downloaded from SAM.gov "
                             "using --notice-id (requires SAM_GOV_API_KEY in .env).")
    parser.add_argument("--opp-id",
                        help="Reuse an existing opportunity ID (skip creation)")
    parser.add_argument("--title",
                        help="Proposal/opportunity title (auto-detected if omitted)")
    parser.add_argument("--agency", default="",
                        help="Agency name (auto-detected if omitted)")
    parser.add_argument("--naics", default="",
                        help="NAICS code (auto-detected if omitted)")
    parser.add_argument("--notice-id", default="",
                        help="SAM.gov notice/solicitation ID (auto-detected if omitted)")
    parser.add_argument("--no-detect", action="store_true",
                        help="Skip auto-detection of metadata (use only provided args)")
    parser.add_argument("--sections", nargs="+", metavar="SECTION",
                        help='Section titles to generate (default: 5 standard sections). '
                             'Example: "Executive Summary" "Technical Approach"')
    parser.add_argument("--base-url", default="http://127.0.0.1:5001",
                        help="GovProposal base URL (default: http://127.0.0.1:5001)")
    parser.add_argument("--days", type=int, default=7,
                        help="Batch mode: search SAM.gov for opps posted in the "
                             "last N days (default: 7)")
    parser.add_argument("--limit", type=int, default=5,
                        help="Batch mode: max number of opportunities to process "
                             "(default: 5)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Upload and extract only — skip AI generation")
    parser.add_argument("--json", action="store_true", dest="json_output",
                        help="Output final summary as JSON")
    args = parser.parse_args()

    env     = _load_env()
    sam_key = env.get("SAM_GOV_API_KEY", "")
    sections = parse_sections(args.sections)
    dest_dir = BASE_DIR / "data" / "rfx_uploads"

    # ══════════════════════════════════════════════════════════════════════════
    # BATCH MODE — no --doc and no --notice-id: search SAM.gov and process all
    # ══════════════════════════════════════════════════════════════════════════
    if not args.doc and not args.notice_id:
        if not sam_key:
            _err("SAM_GOV_API_KEY not found in .env — cannot search SAM.gov")
            _err("Add SAM_GOV_API_KEY=<key> to .env, or provide --doc / --notice-id")
            sys.exit(1)

        print(f"\n{BOLD}GovProposal RFX Pipeline — Batch Mode{RESET}")
        print(f"  Search window : last {args.days} day(s)")
        print(f"  Max items     : {args.limit}")
        print(f"  Server        : {args.base_url}")
        if args.dry_run:
            print(f"  Mode          : {YELLOW}DRY RUN (no AI generation){RESET}")

        if not _check_server(args.base_url):
            _err(f"GovProposal not reachable at {args.base_url}")
            _err("Start the server first: python start.py")
            sys.exit(1)
        _ok(f"Server is up at {args.base_url}")

        print(f"\n{BOLD}Searching SAM.gov for active solicitations...{RESET}")
        opportunities = _sam_search_opportunities(sam_key,
                                                  days=args.days,
                                                  limit=args.limit)
        if not opportunities:
            _warn("No active solicitations with attachments found")
            _warn(f"Try --days {args.days * 2} to widen the search window")
            sys.exit(0)

        _ok(f"Found {len(opportunities)} solicitation(s) with attachments")

        batch_results: list[dict] = []
        for idx, opp in enumerate(opportunities, 1):
            label = (opp["title"] or opp["notice_id"])[:60]
            print(f"\n{BOLD}{'=' * 62}{RESET}")
            print(f"{BOLD}[{idx}/{len(opportunities)}] {label}{RESET}")
            print(f"{BOLD}{'=' * 62}{RESET}")
            print(f"  Notice ID : {opp['notice_id']}")
            if opp["agency"]: print(f"  Agency    : {opp['agency']}")
            if opp["naics"]:  print(f"  NAICS     : {opp['naics']}")

            # Download attachment
            print()
            doc_path = _sam_download_doc(opp["notice_id"], sam_key, dest_dir)
            if doc_path is None:
                _warn(f"Skipping {opp['notice_id']} — document download failed")
                batch_results.append({
                    "notice_id": opp["notice_id"],
                    "title":     opp["title"],
                    "status":    "skipped",
                    "reason":    "download_failed",
                })
                continue

            title = (
                opp["title"]
                or doc_path.stem.replace("-", " ").replace("_", " ").title()
            )
            print()
            result = _run_pipeline_for_doc(
                doc_path  = doc_path,
                notice_id = opp["notice_id"],
                title     = title,
                agency    = opp["agency"],
                naics     = opp["naics"],
                opp_id    = "",
                sections  = sections,
                base_url  = args.base_url,
                dry_run   = args.dry_run,
            )
            result["status"] = "error" if "error" in result else "ok"
            batch_results.append(result)

            if result["status"] == "ok":
                _ok(f"Proposal ready: {result.get('proposal_url', '')}")

        # ── Batch summary ──────────────────────────────────────────────────
        ok_count = sum(1 for r in batch_results if r.get("status") == "ok")
        skip_count = sum(1 for r in batch_results if r.get("status") == "skipped")
        err_count  = len(batch_results) - ok_count - skip_count

        if args.json_output:
            print(json.dumps(batch_results, indent=2))
        else:
            print(f"\n{BOLD}{'─' * 62}{RESET}")
            print(f"{BOLD}Batch complete — {len(batch_results)} processed{RESET}")
            print(f"  {GREEN}✓{RESET} {ok_count} succeeded  "
                  f"{YELLOW}⚠{RESET} {skip_count} skipped  "
                  f"{RED}✗{RESET} {err_count} failed")
            print()
            for r in batch_results:
                if r.get("status") == "ok":
                    icon = f"{GREEN}✓{RESET}"
                elif r.get("status") == "skipped":
                    icon = f"{YELLOW}⚠{RESET}"
                else:
                    icon = f"{RED}✗{RESET}"
                label = (r.get("title") or r.get("notice_id") or "unknown")[:50]
                print(f"  {icon} {label}")
                extra = r.get("proposal_url") or r.get("reason") or r.get("error", "")
                if extra:
                    print(f"      {extra}")
            print(f"{BOLD}{'─' * 62}{RESET}\n")
        return

    # ══════════════════════════════════════════════════════════════════════════
    # SINGLE-DOC MODE — --doc or --notice-id provided
    # ══════════════════════════════════════════════════════════════════════════

    # ── Resolve document path ──────────────────────────────────────────────────
    if args.doc:
        doc_path = Path(args.doc)
        if not doc_path.is_absolute():
            doc_path = BASE_DIR / doc_path
        if not doc_path.exists():
            _err(f"Document not found: {doc_path}")
            sys.exit(1)
    else:
        # --notice-id given but no --doc: download from SAM.gov
        if not sam_key:
            _err("SAM_GOV_API_KEY not found in .env — cannot download document automatically")
            _err("Add SAM_GOV_API_KEY=<key> to .env, or provide --doc manually")
            sys.exit(1)
        print(f"\n{BOLD}Downloading RFP from SAM.gov ({args.notice_id})...{RESET}")
        doc_path = _sam_download_doc(args.notice_id, sam_key, dest_dir)
        if doc_path is None:
            _err("Document download failed — provide --doc manually as a fallback")
            sys.exit(1)

    # ── Auto-detect metadata unless suppressed ─────────────────────────────────
    detected: dict = {}
    if not args.no_detect and not args.opp_id:
        any_missing = not all([args.title, args.agency, args.naics, args.notice_id])
        if any_missing:
            print(f"\n{BOLD}Auto-detecting RFP metadata...{RESET}")
            detected = detect_rfp_metadata(doc_path, known_notice_id=args.notice_id)

    # Merge: explicit CLI args win over auto-detected values
    notice_id = args.notice_id or detected.get("notice_id", "")
    agency    = args.agency    or detected.get("agency", "")
    naics     = args.naics     or detected.get("naics", "")
    title     = (
        args.title
        or detected.get("title")
        or doc_path.stem.replace("-", " ").replace("_", " ").title()
    )

    print(f"\n{BOLD}GovProposal RFX Pipeline{RESET}")
    print(f"  Document : {doc_path.name}")
    print(f"  Title    : {title}")
    if agency:     print(f"  Agency   : {agency}")
    if naics:      print(f"  NAICS    : {naics}")
    if notice_id:  print(f"  Notice ID: {notice_id}")
    print(f"  Sections : {len(sections)}")
    print(f"  Server   : {args.base_url}")
    if args.dry_run: print(f"  Mode     : {YELLOW}DRY RUN (no AI generation){RESET}")

    # ── Server check ──────────────────────────────────────────────────────────
    if not _check_server(args.base_url):
        _err(f"GovProposal not reachable at {args.base_url}")
        _err("Start the server first: python start.py")
        sys.exit(1)
    _ok(f"Server is up at {args.base_url}")

    print()
    summary = _run_pipeline_for_doc(
        doc_path  = doc_path,
        notice_id = notice_id,
        title     = title,
        agency    = agency,
        naics     = naics,
        opp_id    = args.opp_id or "",
        sections  = sections,
        base_url  = args.base_url,
        dry_run   = args.dry_run,
    )

    if "error" in summary:
        sys.exit(1)

    # ── Summary ───────────────────────────────────────────────────────────────
    proposal_url = summary.get("proposal_url", "")
    if args.json_output:
        print(json.dumps(summary, indent=2))
    else:
        print(f"\n{BOLD}{'─' * 55}{RESET}")
        print(f"{BOLD}Pipeline complete{RESET}")
        print(f"  Proposal   : {proposal_url}")
        print(f"  Document   : {summary.get('document_id', '—')}")
        print(f"  Opportunity: {summary.get('opportunity_id', '—')}")
        print(f"  Proposal ID: {summary.get('proposal_id', '—')}")
        print(f"  Reqs found : {summary.get('requirements_extracted', 0)}")
        if not args.dry_run:
            ok  = summary.get("sections_generated", 0)
            tot = len(sections)
            print(f"  Sections   : {ok}/{tot} generated")
        print(f"{BOLD}{'─' * 55}{RESET}\n")


if __name__ == "__main__":
    main()
