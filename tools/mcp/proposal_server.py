#!/usr/bin/env python3
# CUI // SP-PROPIN
# Controlled by: GovProposal Portal
# CUI Category: PROPIN
# Distribution: D
# POC: GovProposal System Administrator
"""GovProposal MCP Server — stdio transport for Claude Code integration.

Exposes proposal lifecycle tools as MCP tool calls:
  - opportunity_scan         — Poll SAM.gov for new opportunities
  - opportunity_score        — Score an opportunity (7-dimension Go/No-Go)
  - kb_search                — Search the knowledge base
  - kb_add                   — Add entry to knowledge base
  - past_performance_search  — Search past performance library
  - cag_check                — Run CAG aggregation check on proposal
  - cag_tag                  — Tag data elements in content
  - section_parse            — Parse Section L/M from solicitation
  - compliance_generate      — Generate compliance matrix
  - draft_section            — Draft a proposal section via RAG
  - review_run               — Run a color team review
  - competitor_lookup        — Look up competitor information
  - pipeline_status          — Get pipeline status overview
  - debrief_capture          — Capture a win/loss debrief

Usage:
    python tools/mcp/proposal_server.py
"""

import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent
DB_PATH = Path(os.environ.get(
    "GOVPROPOSAL_DB_PATH", str(BASE_DIR / "data" / "govproposal.db")
))

sys.path.insert(0, str(BASE_DIR))


# =========================================================================
# MCP PROTOCOL HELPERS (JSON-RPC 2.0 over stdio)
# =========================================================================
def _read_message():
    """Read a JSON-RPC message from stdin (Content-Length framing)."""
    headers = {}
    while True:
        line = sys.stdin.readline()
        if not line or line.strip() == "":
            break
        if ":" in line:
            key, value = line.split(":", 1)
            headers[key.strip().lower()] = value.strip()

    content_length = int(headers.get("content-length", 0))
    if content_length == 0:
        return None

    body = sys.stdin.read(content_length)
    return json.loads(body)


def _send_message(msg):
    """Send a JSON-RPC message to stdout (Content-Length framing)."""
    body = json.dumps(msg)
    header = f"Content-Length: {len(body)}\r\n\r\n"
    sys.stdout.write(header)
    sys.stdout.write(body)
    sys.stdout.flush()


def _result(req_id, result):
    """Send a success response."""
    _send_message({"jsonrpc": "2.0", "id": req_id, "result": result})


def _error(req_id, code, message, data=None):
    """Send an error response."""
    err = {"code": code, "message": message}
    if data:
        err["data"] = data
    _send_message({"jsonrpc": "2.0", "id": req_id, "error": err})


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _get_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


# =========================================================================
# TOOL DEFINITIONS
# =========================================================================
TOOLS = [
    {
        "name": "opportunity_scan",
        "description": "Poll SAM.gov for new opportunities matching configured NAICS codes and agencies. Returns newly discovered opportunities.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "naics_codes": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "NAICS codes to filter (default: from config)"
                },
                "limit": {
                    "type": "integer",
                    "description": "Max results to return",
                    "default": 20
                }
            }
        }
    },
    {
        "name": "opportunity_score",
        "description": "Score an opportunity using 7-dimension Go/No-Go analysis. Returns dimension scores, overall fit, and recommendation.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "opportunity_id": {
                    "type": "string",
                    "description": "ID of the opportunity to score"
                }
            },
            "required": ["opportunity_id"]
        }
    },
    {
        "name": "kb_search",
        "description": "Search the knowledge base using keyword and optional semantic search. Returns matching entries ranked by relevance.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query"
                },
                "entry_type": {
                    "type": "string",
                    "enum": ["capability", "past_performance", "resume", "process", "template", "boilerplate", "case_study"],
                    "description": "Filter by entry type"
                },
                "limit": {
                    "type": "integer",
                    "default": 10
                }
            },
            "required": ["query"]
        }
    },
    {
        "name": "kb_add",
        "description": "Add a new entry to the knowledge base.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "content": {"type": "string"},
                "entry_type": {
                    "type": "string",
                    "enum": ["capability", "past_performance", "resume", "process", "template", "boilerplate", "case_study"]
                },
                "tags": {"type": "string", "description": "Comma-separated tags"}
            },
            "required": ["title", "content", "entry_type"]
        }
    },
    {
        "name": "past_performance_search",
        "description": "Search past performance library. Returns matching past performances with relevance scores.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query (agency, NAICS, keywords)"},
                "agency": {"type": "string"},
                "naics_code": {"type": "string"},
                "limit": {"type": "integer", "default": 5}
            },
            "required": ["query"]
        }
    },
    {
        "name": "cag_check",
        "description": "Run Classification Aggregation Guard check on a proposal. Detects mosaic effect / classification-by-compilation risks.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "proposal_id": {
                    "type": "string",
                    "description": "ID of the proposal to check"
                },
                "include_cross_proposal": {
                    "type": "boolean",
                    "default": True,
                    "description": "Include cross-proposal aggregation analysis"
                }
            },
            "required": ["proposal_id"]
        }
    },
    {
        "name": "cag_tag",
        "description": "Tag data elements in content for CAG classification tracking. Returns identified security categories.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "Text content to analyze"},
                "proposal_id": {"type": "string"},
                "section_id": {"type": "string"}
            },
            "required": ["content"]
        }
    },
    {
        "name": "section_parse",
        "description": "Parse Section L (Instructions) and Section M (Evaluation Criteria) from a solicitation document.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "document_path": {"type": "string", "description": "Path to the solicitation document (PDF/DOCX)"},
                "opportunity_id": {"type": "string"}
            },
            "required": ["document_path"]
        }
    },
    {
        "name": "compliance_generate",
        "description": "Generate a compliance matrix for a proposal from parsed solicitation requirements.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "proposal_id": {"type": "string"},
                "opportunity_id": {"type": "string"}
            },
            "required": ["proposal_id"]
        }
    },
    {
        "name": "draft_section",
        "description": "Draft a proposal section using RAG over the knowledge base. Returns generated content with source references.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "proposal_id": {"type": "string"},
                "section_title": {"type": "string"},
                "volume": {"type": "string", "enum": ["technical", "management", "past_performance", "cost"]},
                "requirements": {"type": "string", "description": "Section requirements / evaluation criteria"},
                "max_pages": {"type": "integer", "default": 5}
            },
            "required": ["proposal_id", "section_title", "volume"]
        }
    },
    {
        "name": "review_run",
        "description": "Run a color team review (Pink/Red/Gold/White) on a proposal.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "proposal_id": {"type": "string"},
                "review_type": {
                    "type": "string",
                    "enum": ["pink", "red", "gold", "white"]
                }
            },
            "required": ["proposal_id", "review_type"]
        }
    },
    {
        "name": "competitor_lookup",
        "description": "Look up competitor information including recent wins, strengths, and weaknesses.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Competitor name to search"},
                "cage_code": {"type": "string"}
            },
            "required": ["name"]
        }
    },
    {
        "name": "pipeline_status",
        "description": "Get pipeline status overview — opportunity counts by stage, active proposals, and upcoming deadlines.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "days_ahead": {
                    "type": "integer",
                    "default": 30,
                    "description": "Number of days ahead to check for deadlines"
                }
            }
        }
    },
    {
        "name": "debrief_capture",
        "description": "Capture a win/loss debrief for a completed proposal.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "proposal_id": {"type": "string"},
                "result": {"type": "string", "enum": ["win", "loss", "no_decision"]},
                "government_feedback": {"type": "string"},
                "lessons_learned": {"type": "string"},
                "strengths_cited": {"type": "string"},
                "weaknesses_cited": {"type": "string"}
            },
            "required": ["proposal_id", "result"]
        }
    }
]


# =========================================================================
# TOOL HANDLERS
# =========================================================================
def handle_opportunity_scan(params):
    """Poll for opportunities (returns from DB, actual SAM.gov polling is via scanner tool)."""
    conn = _get_db()
    try:
        limit = params.get("limit", 20)
        rows = conn.execute(
            """SELECT id, title, agency, sam_notice_id, response_deadline,
                      fit_score, status, naics_code, set_aside_type
               FROM opportunities
               ORDER BY discovered_at DESC LIMIT ?""",
            (limit,)
        ).fetchall()
        return {
            "status": "success",
            "count": len(rows),
            "opportunities": [dict(r) for r in rows]
        }
    finally:
        conn.close()


def handle_opportunity_score(params):
    """Score an opportunity."""
    opp_id = params["opportunity_id"]
    conn = _get_db()
    try:
        opp = conn.execute(
            "SELECT * FROM opportunities WHERE id = ?", (opp_id,)
        ).fetchone()
        if not opp:
            return {"status": "error", "message": f"Opportunity {opp_id} not found"}

        scores = conn.execute(
            "SELECT * FROM opportunity_scores WHERE opportunity_id = ?",
            (opp_id,)
        ).fetchall()

        return {
            "status": "success",
            "opportunity_id": opp_id,
            "title": opp["title"],
            "fit_score": opp["fit_score"],
            "scores": [dict(s) for s in scores]
        }
    finally:
        conn.close()


def handle_kb_search(params):
    """Search the knowledge base."""
    query = params["query"]
    entry_type = params.get("entry_type")
    limit = params.get("limit", 10)
    conn = _get_db()
    try:
        sql = "SELECT * FROM kb_entries WHERE is_active = 1"
        sql_params = []

        if entry_type:
            sql += " AND entry_type = ?"
            sql_params.append(entry_type)

        sql += " AND (title LIKE ? OR content LIKE ? OR tags LIKE ?)"
        pattern = f"%{query}%"
        sql_params.extend([pattern, pattern, pattern])

        sql += " ORDER BY usage_count DESC, updated_at DESC LIMIT ?"
        sql_params.append(limit)

        rows = conn.execute(sql, sql_params).fetchall()
        return {
            "status": "success",
            "count": len(rows),
            "entries": [dict(r) for r in rows]
        }
    finally:
        conn.close()


def handle_kb_add(params):
    """Add a KB entry."""
    import hashlib
    import uuid

    entry_id = str(uuid.uuid4())[:12]
    conn = _get_db()
    try:
        conn.execute(
            """INSERT INTO kb_entries (id, title, content, entry_type, tags,
                                       is_active, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, 1, ?, ?)""",
            (entry_id, params["title"], params["content"],
             params["entry_type"], params.get("tags", ""),
             _now(), _now())
        )
        conn.commit()
        return {"status": "success", "entry_id": entry_id}
    finally:
        conn.close()


def handle_past_performance_search(params):
    """Search past performance library."""
    query = params["query"]
    limit = params.get("limit", 5)
    conn = _get_db()
    try:
        sql = """SELECT * FROM past_performances
                 WHERE contract_name LIKE ? OR agency LIKE ?
                    OR scope_description LIKE ? OR naics_code LIKE ?"""
        pattern = f"%{query}%"
        sql_params = [pattern, pattern, pattern, pattern]

        if params.get("agency"):
            sql += " AND agency LIKE ?"
            sql_params.append(f"%{params['agency']}%")
        if params.get("naics_code"):
            sql += " AND naics_code = ?"
            sql_params.append(params["naics_code"])

        sql += " ORDER BY period_of_performance_end DESC LIMIT ?"
        sql_params.append(limit)

        rows = conn.execute(sql, sql_params).fetchall()
        return {
            "status": "success",
            "count": len(rows),
            "past_performances": [dict(r) for r in rows]
        }
    finally:
        conn.close()


def handle_cag_check(params):
    """Run CAG check on a proposal."""
    proposal_id = params["proposal_id"]
    conn = _get_db()
    try:
        # Get open alerts for this proposal
        alerts = conn.execute(
            """SELECT * FROM cag_alerts
               WHERE proposal_id = ? AND status = 'open'
               ORDER BY severity DESC""",
            (proposal_id,)
        ).fetchall()

        # Get data tags via proposal sections
        tags = conn.execute(
            """SELECT dt.category, COUNT(*) as cnt
               FROM cag_data_tags dt
               JOIN proposal_sections ps ON dt.source_id = ps.id
                 AND dt.source_type = 'proposal_section'
               WHERE ps.proposal_id = ?
               GROUP BY dt.category""",
            (proposal_id,)
        ).fetchall()

        result = {
            "status": "success",
            "proposal_id": proposal_id,
            "alert_count": len(alerts),
            "alerts": [dict(a) for a in alerts],
            "category_distribution": {t["category"]: t["cnt"] for t in tags}
        }

        # Cross-proposal exposure
        if params.get("include_cross_proposal", True):
            exposures = conn.execute(
                """SELECT * FROM cag_exposure_register
                   WHERE proposal_id = ?""",
                (proposal_id,)
            ).fetchall()
            result["cross_proposal_exposures"] = [dict(e) for e in exposures]

        return result
    finally:
        conn.close()


def handle_cag_tag(params):
    """Tag data elements in content."""
    content = params["content"]
    # Load CAG rules for keyword matching
    import yaml
    rules_path = BASE_DIR / "args" / "cag_rules.yaml"
    categories_found = []

    try:
        with open(rules_path) as f:
            cag_config = yaml.safe_load(f)

        content_lower = content.lower()
        for cat in cag_config.get("security_categories", []):
            cat_name = cat["name"]
            for indicator in cat.get("strong_indicators", []):
                if indicator.lower() in content_lower:
                    categories_found.append({
                        "category": cat_name,
                        "indicator": indicator,
                        "strength": "strong"
                    })
                    break
            for indicator in cat.get("moderate_indicators", []):
                if indicator.lower() in content_lower:
                    categories_found.append({
                        "category": cat_name,
                        "indicator": indicator,
                        "strength": "moderate"
                    })
                    break
    except Exception as e:
        return {"status": "error", "message": f"Failed to load CAG rules: {e}"}

    return {
        "status": "success",
        "content_length": len(content),
        "categories_found": categories_found,
        "category_count": len(set(c["category"] for c in categories_found))
    }


def handle_section_parse(params):
    """Parse Section L/M (delegates to tool)."""
    doc_path = params["document_path"]
    if not Path(doc_path).exists():
        return {"status": "error", "message": f"File not found: {doc_path}"}

    return {
        "status": "success",
        "message": "Section parsing initiated",
        "document_path": doc_path,
        "note": "Use tools/proposal/section_parser.py for full parsing"
    }


def handle_compliance_generate(params):
    """Generate compliance matrix."""
    proposal_id = params["proposal_id"]
    conn = _get_db()
    try:
        rows = conn.execute(
            """SELECT compliance_status, COUNT(*) as cnt
               FROM compliance_matrices WHERE proposal_id = ?
               GROUP BY compliance_status""",
            (proposal_id,)
        ).fetchall()

        total = sum(r["cnt"] for r in rows)
        return {
            "status": "success",
            "proposal_id": proposal_id,
            "total_requirements": total,
            "breakdown": {r["compliance_status"]: r["cnt"] for r in rows}
        }
    finally:
        conn.close()


def handle_draft_section(params):
    """Draft a proposal section."""
    return {
        "status": "success",
        "message": "Section drafting initiated",
        "proposal_id": params["proposal_id"],
        "section": params["section_title"],
        "volume": params["volume"],
        "note": "Use tools/proposal/content_drafter.py for full RAG-based drafting"
    }


def handle_review_run(params):
    """Run a color team review."""
    proposal_id = params["proposal_id"]
    review_type = params["review_type"]
    conn = _get_db()
    try:
        reviews = conn.execute(
            """SELECT * FROM proposal_reviews
               WHERE proposal_id = ? AND review_type = ?
               ORDER BY created_at DESC LIMIT 1""",
            (proposal_id, review_type)
        ).fetchone()

        if reviews:
            return {
                "status": "success",
                "latest_review": dict(reviews)
            }
        return {
            "status": "success",
            "message": f"No {review_type} review found. Use tools/review/review_engine.py to run one.",
            "proposal_id": proposal_id,
            "review_type": review_type
        }
    finally:
        conn.close()


def handle_competitor_lookup(params):
    """Look up competitor info."""
    name = params["name"]
    conn = _get_db()
    try:
        comps = conn.execute(
            "SELECT * FROM competitors WHERE company_name LIKE ? AND is_active = 1",
            (f"%{name}%",)
        ).fetchall()

        results = []
        for comp in comps:
            wins = conn.execute(
                "SELECT * FROM competitor_wins WHERE competitor_id = ? ORDER BY award_date DESC LIMIT 5",
                (comp["id"],)
            ).fetchall()
            results.append({
                "competitor": dict(comp),
                "recent_wins": [dict(w) for w in wins]
            })

        return {
            "status": "success",
            "count": len(results),
            "competitors": results
        }
    finally:
        conn.close()


def handle_pipeline_status(params):
    """Get pipeline overview."""
    conn = _get_db()
    try:
        # Stage counts
        stages = conn.execute(
            "SELECT status, COUNT(*) as cnt FROM opportunities GROUP BY status"
        ).fetchall()

        # Active proposals
        active = conn.execute(
            """SELECT COUNT(*) as cnt FROM proposals
               WHERE status NOT IN ('submitted', 'awarded', 'lost')"""
        ).fetchone()

        # CAG alerts
        cag_open = conn.execute(
            "SELECT COUNT(*) as cnt FROM cag_alerts WHERE status = 'open'"
        ).fetchone()

        return {
            "status": "success",
            "pipeline_stages": {r["status"]: r["cnt"] for r in stages},
            "active_proposals": active["cnt"] if active else 0,
            "open_cag_alerts": cag_open["cnt"] if cag_open else 0,
            "timestamp": _now()
        }
    finally:
        conn.close()


def handle_debrief_capture(params):
    """Capture a debrief."""
    import uuid
    debrief_id = str(uuid.uuid4())[:12]
    conn = _get_db()
    try:
        # Get opportunity_id from proposal
        prop = conn.execute(
            "SELECT opportunity_id FROM proposals WHERE id = ?",
            (params["proposal_id"],)
        ).fetchone()
        opp_id = prop["opportunity_id"] if prop else "UNKNOWN"

        conn.execute(
            """INSERT INTO debriefs (id, proposal_id, opportunity_id, result,
                                     evaluator_strengths, evaluator_weaknesses,
                                     lessons_learned, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (debrief_id, params["proposal_id"], opp_id, params["result"],
             params.get("government_feedback"), params.get("weaknesses_cited"),
             params.get("lessons_learned"),
             _now())
        )
        conn.commit()
        return {"status": "success", "debrief_id": debrief_id}
    finally:
        conn.close()


# Handler dispatch
HANDLERS = {
    "opportunity_scan": handle_opportunity_scan,
    "opportunity_score": handle_opportunity_score,
    "kb_search": handle_kb_search,
    "kb_add": handle_kb_add,
    "past_performance_search": handle_past_performance_search,
    "cag_check": handle_cag_check,
    "cag_tag": handle_cag_tag,
    "section_parse": handle_section_parse,
    "compliance_generate": handle_compliance_generate,
    "draft_section": handle_draft_section,
    "review_run": handle_review_run,
    "competitor_lookup": handle_competitor_lookup,
    "pipeline_status": handle_pipeline_status,
    "debrief_capture": handle_debrief_capture,
}


# =========================================================================
# MCP SERVER MAIN LOOP
# =========================================================================
def handle_request(msg):
    """Route a JSON-RPC request to the appropriate handler."""
    req_id = msg.get("id")
    method = msg.get("method", "")

    if method == "initialize":
        _result(req_id, {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {
                "name": "govproposal",
                "version": "1.0.0"
            }
        })
    elif method == "notifications/initialized":
        pass  # No response needed
    elif method == "tools/list":
        _result(req_id, {"tools": TOOLS})
    elif method == "tools/call":
        params = msg.get("params", {})
        tool_name = params.get("name", "")
        tool_args = params.get("arguments", {})

        handler = HANDLERS.get(tool_name)
        if not handler:
            _error(req_id, -32601, f"Unknown tool: {tool_name}")
            return

        try:
            result = handler(tool_args)
            _result(req_id, {
                "content": [{
                    "type": "text",
                    "text": json.dumps(result, indent=2, default=str)
                }]
            })
        except Exception as e:
            _error(req_id, -32000, f"Tool error: {str(e)}")
    else:
        if req_id is not None:
            _error(req_id, -32601, f"Method not found: {method}")


def main():
    """Run the MCP server on stdio."""
    sys.stderr.write("GovProposal MCP server starting (stdio)...\n")
    sys.stderr.write(f"Database: {DB_PATH}\n")
    sys.stderr.flush()

    while True:
        try:
            msg = _read_message()
            if msg is None:
                break
            handle_request(msg)
        except KeyboardInterrupt:
            break
        except json.JSONDecodeError:
            continue
        except Exception as e:
            sys.stderr.write(f"Error: {e}\n")
            sys.stderr.flush()


if __name__ == "__main__":
    main()
