#!/usr/bin/env python3
# CUI // SP-PROPIN
# Controlled by: GovProposal Portal
# CUI Category: PROPIN (Proprietary Business Information)
# Distribution: D
"""Add RFX AI Proposal Engine tables to GovProposal's SQLite database.

Tables added:
  rfx_documents         — uploaded RFI/RFP + corpus docs for RAG
  rfx_document_chunks   — text chunks with vector BLOBs (numpy float32)
  rfx_requirements      — requirements extracted from RFI/RFP documents
  rfx_requirement_status — per-requirement address status per proposal
  rfx_ai_sections       — AI-generated proposal sections (HITL workflow)
  rfx_hitl_reviews      — append-only HITL review decisions
  rfx_exclusion_list    — sensitive term masking (term -> placeholder)
  rfx_research_cache    — web/gov research results with TTL
  rfx_model_config      — fine-tuned model registry (Ollama + Bedrock)
  rfx_finetune_jobs     — Unsloth/LoRA training job queue

Usage:
    python tools/db/migrate_rfx.py [--json]
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


def run(db_path=None):
    path = str(db_path or DB_PATH)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    cur = conn.cursor()
    created = []

    # ── rfx_documents ─────────────────────────────────────────────────────────
    # Uploaded documents: RFI/RFP solicitations + past proposal corpus for RAG.
    # file_path points to data/rfx_uploads/ on local filesystem (no MinIO).
    cur.execute("""
        CREATE TABLE IF NOT EXISTS rfx_documents (
            id                  TEXT PRIMARY KEY,
            proposal_id         TEXT REFERENCES proposals(id),
            opportunity_id      TEXT REFERENCES opportunities(id),
            filename            TEXT NOT NULL,
            doc_type            TEXT NOT NULL DEFAULT 'other'
                CHECK(doc_type IN ('rfi', 'rfp', 'sow', 'cdrl', 'conops',
                                   'past_proposal', 'capability_doc', 'other')),
            file_path           TEXT NOT NULL,
            file_hash           TEXT NOT NULL,
            mime_type           TEXT,
            file_size_bytes     INTEGER,
            content             TEXT,
            page_count          INTEGER,
            chunk_count         INTEGER NOT NULL DEFAULT 0,
            embedding_model     TEXT NOT NULL DEFAULT 'all-MiniLM-L6-v2',
            embedding_dims      INTEGER NOT NULL DEFAULT 384,
            vectorized          INTEGER NOT NULL DEFAULT 0,
            vectorized_at       TEXT,
            exclude_from_training INTEGER NOT NULL DEFAULT 0,
            classification      TEXT NOT NULL DEFAULT 'CUI // SP-PROPIN',
            uploaded_by         TEXT,
            notes               TEXT,
            created_at          TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at          TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    created.append("rfx_documents")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_rfxdoc_proposal  ON rfx_documents(proposal_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_rfxdoc_opp       ON rfx_documents(opportunity_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_rfxdoc_type      ON rfx_documents(doc_type)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_rfxdoc_hash      ON rfx_documents(file_hash)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_rfxdoc_vector    ON rfx_documents(vectorized)")

    # ── rfx_document_chunks ───────────────────────────────────────────────────
    # Text chunks from rfx_documents with float32 embedding BLOBs for RAG.
    # embedding column stores raw bytes from numpy.ndarray.tobytes().
    cur.execute("""
        CREATE TABLE IF NOT EXISTS rfx_document_chunks (
            id              TEXT PRIMARY KEY,
            document_id     TEXT NOT NULL REFERENCES rfx_documents(id) ON DELETE CASCADE,
            chunk_index     INTEGER NOT NULL,
            content         TEXT NOT NULL,
            word_count      INTEGER NOT NULL DEFAULT 0,
            embedding       BLOB,
            embedding_model TEXT NOT NULL DEFAULT 'all-MiniLM-L6-v2',
            metadata        TEXT,
            created_at      TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    created.append("rfx_document_chunks")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_rfxchunk_doc    ON rfx_document_chunks(document_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_rfxchunk_idx    ON rfx_document_chunks(document_id, chunk_index)")

    # ── rfx_requirements ──────────────────────────────────────────────────────
    # Requirements extracted from RFI/RFP documents (shall/should/must statements).
    cur.execute("""
        CREATE TABLE IF NOT EXISTS rfx_requirements (
            id              TEXT PRIMARY KEY,
            document_id     TEXT NOT NULL REFERENCES rfx_documents(id),
            proposal_id     TEXT REFERENCES proposals(id),
            req_number      TEXT,
            section         TEXT NOT NULL DEFAULT 'other'
                CHECK(section IN ('section_l', 'section_m', 'sow', 'cdrl',
                                  'evaluation_criteria', 'contract_terms', 'other')),
            req_text        TEXT NOT NULL,
            req_type        TEXT NOT NULL DEFAULT 'shall'
                CHECK(req_type IN ('shall', 'should', 'will', 'must', 'may', 'other')),
            volume          TEXT
                CHECK(volume IN ('technical', 'management', 'past_performance',
                                 'cost', 'executive_summary', 'attachments', NULL)),
            page_number     INTEGER,
            priority        TEXT NOT NULL DEFAULT 'medium'
                CHECK(priority IN ('critical', 'high', 'medium', 'low')),
            notes           TEXT,
            extracted_by    TEXT NOT NULL DEFAULT 'ai'
                CHECK(extracted_by IN ('ai', 'manual')),
            created_at      TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    created.append("rfx_requirements")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_rfxreq_doc      ON rfx_requirements(document_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_rfxreq_proposal ON rfx_requirements(proposal_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_rfxreq_section  ON rfx_requirements(section)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_rfxreq_priority ON rfx_requirements(priority)")

    # ── rfx_requirement_status ────────────────────────────────────────────────
    # Tracks how each requirement is addressed in a specific proposal.
    cur.execute("""
        CREATE TABLE IF NOT EXISTS rfx_requirement_status (
            id              TEXT PRIMARY KEY,
            requirement_id  TEXT NOT NULL REFERENCES rfx_requirements(id),
            proposal_id     TEXT NOT NULL REFERENCES proposals(id),
            section_id      TEXT REFERENCES proposal_sections(id),
            ai_section_id   TEXT REFERENCES rfx_ai_sections(id),
            status          TEXT NOT NULL DEFAULT 'not_addressed'
                CHECK(status IN ('not_addressed', 'partial', 'addressed', 'not_applicable')),
            compliance_notes TEXT,
            updated_by      TEXT,
            updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    created.append("rfx_requirement_status")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_rfxreqst_req     ON rfx_requirement_status(requirement_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_rfxreqst_prop    ON rfx_requirement_status(proposal_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_rfxreqst_status  ON rfx_requirement_status(status)")

    # ── rfx_ai_sections ───────────────────────────────────────────────────────
    # AI-generated proposal sections. One row per generation attempt.
    # HITL workflow: pending -> accepted / revised / rejected.
    # When accepted, content_accepted is copied to proposal_sections.content.
    cur.execute("""
        CREATE TABLE IF NOT EXISTS rfx_ai_sections (
            id                  TEXT PRIMARY KEY,
            proposal_id         TEXT NOT NULL REFERENCES proposals(id),
            proposal_section_id TEXT REFERENCES proposal_sections(id),
            volume              TEXT NOT NULL
                CHECK(volume IN ('technical', 'management', 'past_performance',
                                 'cost', 'executive_summary', 'attachments')),
            section_number      TEXT,
            section_title       TEXT NOT NULL,
            content_draft       TEXT,
            content_accepted    TEXT,
            source_type         TEXT NOT NULL DEFAULT 'hybrid'
                CHECK(source_type IN ('ai', 'rag', 'web', 'hybrid', 'manual')),
            rag_sources         TEXT,
            web_sources         TEXT,
            pricing_scenario_id TEXT REFERENCES pricing_scenarios(id),
            model_used          TEXT,
            prompt_hash         TEXT,
            generation_tokens   INTEGER NOT NULL DEFAULT 0,
            hitl_status         TEXT NOT NULL DEFAULT 'pending'
                CHECK(hitl_status IN ('pending', 'accepted', 'revised', 'rejected')),
            hitl_feedback       TEXT,
            hitl_reviewed_by    TEXT,
            hitl_reviewed_at    TEXT,
            revision_count      INTEGER NOT NULL DEFAULT 0,
            cag_cleared         INTEGER NOT NULL DEFAULT 0,
            classification      TEXT NOT NULL DEFAULT 'CUI // SP-PROPIN',
            created_at          TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at          TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    created.append("rfx_ai_sections")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_rfxaisec_prop    ON rfx_ai_sections(proposal_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_rfxaisec_hitl    ON rfx_ai_sections(hitl_status)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_rfxaisec_volume  ON rfx_ai_sections(volume)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_rfxaisec_pricing ON rfx_ai_sections(pricing_scenario_id)")

    # ── rfx_hitl_reviews ──────────────────────────────────────────────────────
    # Append-only log of every HITL review action (accept / revise / reject).
    # Satisfies NIST AU-2 (event logging), AU-3 (content), AU-9 (protection).
    cur.execute("""
        CREATE TABLE IF NOT EXISTS rfx_hitl_reviews (
            id              TEXT PRIMARY KEY,
            ai_section_id   TEXT NOT NULL REFERENCES rfx_ai_sections(id),
            proposal_id     TEXT NOT NULL REFERENCES proposals(id),
            reviewer        TEXT,
            action          TEXT NOT NULL
                CHECK(action IN ('accept', 'revise', 'reject', 'flag')),
            feedback        TEXT,
            revised_content TEXT,
            classification  TEXT NOT NULL DEFAULT 'CUI // SP-PROPIN',
            reviewed_at     TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    created.append("rfx_hitl_reviews")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_rfxhitl_section  ON rfx_hitl_reviews(ai_section_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_rfxhitl_proposal ON rfx_hitl_reviews(proposal_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_rfxhitl_action   ON rfx_hitl_reviews(action)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_rfxhitl_time     ON rfx_hitl_reviews(reviewed_at)")

    # ── rfx_exclusion_list ────────────────────────────────────────────────────
    # Sensitive term masking: maps real terms to safe placeholders.
    # Applied during AI generation; merge-back restores originals at export.
    cur.execute("""
        CREATE TABLE IF NOT EXISTS rfx_exclusion_list (
            id              TEXT PRIMARY KEY,
            sensitive_term  TEXT NOT NULL,
            placeholder     TEXT NOT NULL,
            term_type       TEXT NOT NULL DEFAULT 'custom'
                CHECK(term_type IN ('person', 'program', 'location',
                                    'capability', 'organization', 'custom')),
            case_sensitive  INTEGER NOT NULL DEFAULT 0,
            whole_word      INTEGER NOT NULL DEFAULT 1,
            is_active       INTEGER NOT NULL DEFAULT 1,
            context_notes   TEXT,
            created_by      TEXT,
            created_at      TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    created.append("rfx_exclusion_list")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_rfxexcl_type     ON rfx_exclusion_list(term_type)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_rfxexcl_active   ON rfx_exclusion_list(is_active)")

    # ── rfx_research_cache ────────────────────────────────────────────────────
    # Cached web/gov search results. Keyed by SHA-256(query).
    # expires_at enables TTL-based invalidation (default 24h).
    cur.execute("""
        CREATE TABLE IF NOT EXISTS rfx_research_cache (
            id              TEXT PRIMARY KEY,
            proposal_id     TEXT REFERENCES proposals(id),
            query           TEXT NOT NULL,
            query_hash      TEXT NOT NULL,
            cache_type      TEXT NOT NULL DEFAULT 'web_search'
                CHECK(cache_type IN ('web_search', 'deep_research',
                                     'gov_sources', 'academic')),
            results         TEXT NOT NULL,
            source_count    INTEGER NOT NULL DEFAULT 0,
            expires_at      TEXT NOT NULL,
            created_at      TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    created.append("rfx_research_cache")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_rfxcache_hash    ON rfx_research_cache(query_hash)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_rfxcache_prop    ON rfx_research_cache(proposal_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_rfxcache_expire  ON rfx_research_cache(expires_at)")

    # ── rfx_model_config ──────────────────────────────────────────────────────
    # Registry of available fine-tuned and base models (Ollama + Bedrock).
    # is_default=1 is the model used when no explicit model is requested.
    cur.execute("""
        CREATE TABLE IF NOT EXISTS rfx_model_config (
            id              TEXT PRIMARY KEY,
            model_name      TEXT NOT NULL UNIQUE,
            base_model      TEXT NOT NULL,
            model_path      TEXT,
            ollama_model_tag TEXT,
            provider        TEXT NOT NULL DEFAULT 'ollama'
                CHECK(provider IN ('ollama', 'bedrock', 'icdev_router')),
            enabled         INTEGER NOT NULL DEFAULT 1,
            is_default      INTEGER NOT NULL DEFAULT 0,
            priority        INTEGER NOT NULL DEFAULT 100,
            lora_rank       INTEGER DEFAULT 16,
            quantization    TEXT DEFAULT 'q4_k_m',
            context_window  INTEGER DEFAULT 4096,
            notes           TEXT,
            created_at      TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    created.append("rfx_model_config")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_rfxmodel_enabled ON rfx_model_config(enabled)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_rfxmodel_default ON rfx_model_config(is_default)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_rfxmodel_prio    ON rfx_model_config(priority)")

    # ── rfx_finetune_jobs ─────────────────────────────────────────────────────
    # Unsloth/LoRA training jobs. Each job trains one model on a set of docs.
    # Runs as a Python subprocess; progress_pct updated by the job runner.
    cur.execute("""
        CREATE TABLE IF NOT EXISTS rfx_finetune_jobs (
            id                  TEXT PRIMARY KEY,
            job_name            TEXT,
            model_config_id     TEXT REFERENCES rfx_model_config(id),
            model_name          TEXT NOT NULL,
            base_model          TEXT NOT NULL,
            backend             TEXT NOT NULL DEFAULT 'unsloth'
                CHECK(backend IN ('unsloth', 'transformers', 'axolotl')),
            status              TEXT NOT NULL DEFAULT 'pending'
                CHECK(status IN ('pending', 'queued', 'running', 'completed', 'failed', 'cancelled')),
            training_doc_ids    TEXT,
            training_doc_count  INTEGER NOT NULL DEFAULT 0,
            training_samples    INTEGER NOT NULL DEFAULT 0,
            lora_rank           INTEGER NOT NULL DEFAULT 16,
            lora_alpha          INTEGER NOT NULL DEFAULT 32,
            epochs              INTEGER NOT NULL DEFAULT 3,
            batch_size          INTEGER NOT NULL DEFAULT 2,
            learning_rate       TEXT NOT NULL DEFAULT '2e-4',
            export_gguf         INTEGER NOT NULL DEFAULT 1,
            progress_pct        REAL NOT NULL DEFAULT 0.0,
            current_epoch       INTEGER,
            total_epochs        INTEGER,
            train_loss          REAL,
            error_message       TEXT,
            output_model_path   TEXT,
            pid                 INTEGER,
            started_at          TEXT,
            completed_at        TEXT,
            created_at          TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    created.append("rfx_finetune_jobs")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_rfxft_status     ON rfx_finetune_jobs(status)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_rfxft_model      ON rfx_finetune_jobs(model_name)")

    conn.commit()
    conn.close()
    return created


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Migrate GovProposal DB: add RFX tables")
    parser.add_argument("--json", action="store_true", help="JSON output")
    parser.add_argument("--db-path", help="Override database path")
    args = parser.parse_args()

    tables = run(db_path=args.db_path)

    result = {
        "status": "ok",
        "tables_created": tables,
        "count": len(tables),
        "db_path": str(args.db_path or DB_PATH),
        "migrated_at": datetime.now(timezone.utc).isoformat(),
    }

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"RFX migration complete: {result['db_path']}")
        for t in tables:
            print(f"  + {t}")
        print(f"  {len(tables)} tables ready")
