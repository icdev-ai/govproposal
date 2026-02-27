#!/usr/bin/env python3
# CUI // SP-PROPIN
# Controlled by: GovProposal Portal
# CUI Category: PROPIN
# Distribution: D
# POC: GovProposal System Administrator
"""Hybrid search (BM25 keyword + semantic vector) over the GovProposal
knowledge base.

Combines BM25 keyword matching (weight 0.7) with vector cosine similarity
(weight 0.3) for optimal retrieval. Falls back gracefully when rank_bm25
or numpy are not installed.

Usage:
    python tools/knowledge/kb_search.py --search --query "cloud migration" --json
    python tools/knowledge/kb_search.py --keyword --query "FedRAMP ATO" --json
    python tools/knowledge/kb_search.py --semantic --query "zero trust architecture" --json
    python tools/knowledge/kb_search.py --embed --id KB-abc123def456
    python tools/knowledge/kb_search.py --embed-all --json
"""

import json
import math
import os
import re
import sqlite3
import struct
import sys
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent
DB_PATH = Path(os.environ.get(
    "GOVPROPOSAL_DB_PATH", str(BASE_DIR / "data" / "govproposal.db")
))

# Graceful imports for optional dependencies
try:
    from rank_bm25 import BM25Okapi
    HAS_BM25 = True
except ImportError:
    HAS_BM25 = False

try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False

try:
    import openai
    HAS_OPENAI = True
except ImportError:
    HAS_OPENAI = False

# Search weights
BM25_WEIGHT = 0.7
SEMANTIC_WEIGHT = 0.3

# Embedding model configuration
EMBEDDING_MODEL = os.environ.get("GOVPROPOSAL_EMBEDDING_MODEL", "text-embedding-3-small")
EMBEDDING_DIMS = int(os.environ.get("GOVPROPOSAL_EMBEDDING_DIMS", "1536"))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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
            "kb_search",
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


def _tokenize(text):
    """Simple whitespace + punctuation tokenizer for BM25.

    Lowercases, strips punctuation, and splits on whitespace.

    Args:
        text: Input string.

    Returns:
        list of lowercase token strings.
    """
    if not text:
        return []
    text = text.lower()
    text = re.sub(r"[^\w\s]", " ", text)
    return [t for t in text.split() if len(t) > 1]


def _embedding_to_blob(embedding):
    """Pack a list of floats into a binary BLOB for SQLite storage.

    Args:
        embedding: list of float values.

    Returns:
        bytes object containing packed floats.
    """
    return struct.pack(f"{len(embedding)}f", *embedding)


def _blob_to_embedding(blob):
    """Unpack a binary BLOB into a list of floats.

    Args:
        blob: bytes object containing packed floats.

    Returns:
        list of float values.
    """
    if blob is None:
        return None
    count = len(blob) // 4  # 4 bytes per float
    return list(struct.unpack(f"{count}f", blob))


def _cosine_similarity(vec_a, vec_b):
    """Compute cosine similarity between two vectors.

    Uses numpy if available, falls back to pure Python.

    Args:
        vec_a: First vector (list of floats).
        vec_b: Second vector (list of floats).

    Returns:
        float between -1.0 and 1.0.
    """
    if HAS_NUMPY:
        a = np.array(vec_a, dtype=np.float32)
        b = np.array(vec_b, dtype=np.float32)
        dot = np.dot(a, b)
        norm = np.linalg.norm(a) * np.linalg.norm(b)
        if norm == 0:
            return 0.0
        return float(dot / norm)
    else:
        dot = sum(a * b for a, b in zip(vec_a, vec_b))
        norm_a = math.sqrt(sum(a * a for a in vec_a))
        norm_b = math.sqrt(sum(b * b for b in vec_b))
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)


def _get_embedding(text):
    """Generate an embedding vector for the given text using an
    OpenAI-compatible API.

    Requires the openai package. Respects OPENAI_API_KEY and
    OPENAI_BASE_URL / OLLAMA_BASE_URL environment variables.

    Args:
        text: Input text to embed.

    Returns:
        list of floats (embedding vector), or None if unavailable.
    """
    if not HAS_OPENAI:
        return None

    api_key = os.environ.get("OPENAI_API_KEY")
    base_url = os.environ.get(
        "OPENAI_BASE_URL",
        os.environ.get("OLLAMA_BASE_URL"),
    )

    if not api_key and not base_url:
        return None

    try:
        kwargs = {}
        if base_url:
            kwargs["base_url"] = base_url
        if api_key:
            kwargs["api_key"] = api_key
        else:
            kwargs["api_key"] = "not-needed"

        client = openai.OpenAI(**kwargs)
        response = client.embeddings.create(
            model=EMBEDDING_MODEL,
            input=text,
        )
        return response.data[0].embedding
    except Exception:
        return None


def _fetch_active_entries(conn, entry_type=None):
    """Fetch all active KB entries, optionally filtered by type.

    Args:
        conn: Database connection.
        entry_type: Optional filter.

    Returns:
        list of sqlite3.Row objects.
    """
    if entry_type:
        return conn.execute(
            "SELECT * FROM kb_entries WHERE is_active = 1 AND entry_type = ? "
            "ORDER BY updated_at DESC",
            (entry_type,),
        ).fetchall()
    else:
        return conn.execute(
            "SELECT * FROM kb_entries WHERE is_active = 1 "
            "ORDER BY updated_at DESC",
        ).fetchall()


# ---------------------------------------------------------------------------
# Search Functions
# ---------------------------------------------------------------------------

def keyword_search(query, entry_type=None, limit=10, db_path=None):
    """BM25 keyword search over the knowledge base.

    Uses rank_bm25 if installed; falls back to simple term-frequency
    matching otherwise.

    Args:
        query: Search query string.
        entry_type: Optional filter by entry type.
        limit: Maximum results to return (default 10).
        db_path: Optional database path override.

    Returns:
        list of dicts, each with entry fields plus a 'score' key.
    """
    conn = _get_db(db_path)
    try:
        entries = _fetch_active_entries(conn, entry_type)
        if not entries:
            return []

        query_tokens = _tokenize(query)
        if not query_tokens:
            return []

        # Build corpus: combine title + content + tags for each entry
        corpus = []
        for entry in entries:
            text = f"{entry['title']} {entry['content'] or ''} {entry['tags'] or ''}"
            corpus.append(_tokenize(text))

        if HAS_BM25:
            bm25 = BM25Okapi(corpus)
            scores = bm25.get_scores(query_tokens)
        else:
            # Fallback: simple term frequency matching
            scores = []
            query_set = set(query_tokens)
            for doc_tokens in corpus:
                if not doc_tokens:
                    scores.append(0.0)
                    continue
                doc_set = set(doc_tokens)
                overlap = len(query_set & doc_set)
                tf = sum(1 for t in doc_tokens if t in query_set)
                score = (overlap / max(len(query_set), 1)) * 0.5 + \
                        (tf / max(len(doc_tokens), 1)) * 0.5
                scores.append(score)

        # Pair scores with entries and sort
        scored = []
        for i, entry in enumerate(entries):
            s = float(scores[i]) if i < len(scores) else 0.0
            if s > 0:
                result = _row_to_dict(entry)
                result["score"] = round(s, 6)
                scored.append(result)

        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored[:limit]
    finally:
        conn.close()


def semantic_search(query, entry_type=None, limit=10, db_path=None):
    """Vector cosine similarity search over KB entry embeddings.

    Requires embeddings to be pre-generated via embed_entry or embed_all.

    Args:
        query: Search query string.
        entry_type: Optional filter by entry type.
        limit: Maximum results to return (default 10).
        db_path: Optional database path override.

    Returns:
        list of dicts, each with entry fields plus a 'score' key.
    """
    query_embedding = _get_embedding(query)
    if query_embedding is None:
        return []

    conn = _get_db(db_path)
    try:
        # Fetch entries with their embeddings
        if entry_type:
            rows = conn.execute(
                "SELECT e.*, emb.embedding FROM kb_entries e "
                "JOIN kb_embeddings emb ON e.id = emb.kb_entry_id "
                "WHERE e.is_active = 1 AND e.entry_type = ?",
                (entry_type,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT e.*, emb.embedding FROM kb_entries e "
                "JOIN kb_embeddings emb ON e.id = emb.kb_entry_id "
                "WHERE e.is_active = 1",
            ).fetchall()

        if not rows:
            return []

        scored = []
        for row in rows:
            stored_emb = _blob_to_embedding(row["embedding"])
            if stored_emb is None:
                continue
            sim = _cosine_similarity(query_embedding, stored_emb)
            if sim > 0:
                result = _row_to_dict(row)
                # Remove raw embedding blob from output
                result.pop("embedding", None)
                result["score"] = round(sim, 6)
                scored.append(result)

        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored[:limit]
    finally:
        conn.close()


def search(query, entry_type=None, limit=10, db_path=None):
    """Hybrid search combining BM25 keyword matching and vector similarity.

    BM25 weight: 0.7, semantic weight: 0.3. Falls back to keyword-only
    search if semantic search returns no results (e.g., missing embeddings
    or API keys).

    Args:
        query: Search query string.
        entry_type: Optional filter by entry type.
        limit: Maximum results to return (default 10).
        db_path: Optional database path override.

    Returns:
        list of dicts, each with entry fields plus a 'score' key,
        sorted by combined score descending.
    """
    kw_results = keyword_search(query, entry_type=entry_type,
                                limit=limit * 2, db_path=db_path)
    sem_results = semantic_search(query, entry_type=entry_type,
                                  limit=limit * 2, db_path=db_path)

    # If no semantic results, return keyword results alone
    if not sem_results:
        return kw_results[:limit]

    # Normalize scores to [0, 1] range within each result set
    def _normalize(results):
        if not results:
            return {}
        max_score = max(r["score"] for r in results) or 1.0
        return {r["id"]: r["score"] / max_score for r in results}

    kw_scores = _normalize(kw_results)
    sem_scores = _normalize(sem_results)

    # Merge all unique entry IDs
    all_ids = set(kw_scores.keys()) | set(sem_scores.keys())

    # Build combined entry lookup
    entry_lookup = {}
    for r in kw_results:
        entry_lookup[r["id"]] = r
    for r in sem_results:
        if r["id"] not in entry_lookup:
            entry_lookup[r["id"]] = r

    # Compute weighted combined scores
    combined = []
    for entry_id in all_ids:
        kw_s = kw_scores.get(entry_id, 0.0)
        sem_s = sem_scores.get(entry_id, 0.0)
        final_score = (BM25_WEIGHT * kw_s) + (SEMANTIC_WEIGHT * sem_s)

        result = dict(entry_lookup[entry_id])
        result["score"] = round(final_score, 6)
        result["score_breakdown"] = {
            "keyword": round(kw_s, 6),
            "semantic": round(sem_s, 6),
        }
        combined.append(result)

    combined.sort(key=lambda x: x["score"], reverse=True)
    return combined[:limit]


# ---------------------------------------------------------------------------
# Embedding Functions
# ---------------------------------------------------------------------------

def embed_entry(entry_id, db_path=None):
    """Generate and store an embedding for a single KB entry.

    Combines title + content for embedding input.

    Args:
        entry_id: The KB entry ID.
        db_path: Optional database path override.

    Returns:
        dict with status, entry_id, model, and dimensions.

    Raises:
        ValueError: If entry not found or embedding generation fails.
    """
    conn = _get_db(db_path)
    try:
        row = conn.execute(
            "SELECT id, title, content FROM kb_entries WHERE id = ? AND is_active = 1",
            (entry_id,),
        ).fetchone()
        if row is None:
            raise ValueError(f"KB entry not found or inactive: {entry_id}")

        text = f"{row['title']}\n\n{row['content'] or ''}"
        embedding = _get_embedding(text)
        if embedding is None:
            raise ValueError(
                "Embedding generation failed. Ensure OPENAI_API_KEY is set "
                "or OLLAMA_BASE_URL is configured."
            )

        blob = _embedding_to_blob(embedding)
        now = _now()

        # Upsert: delete existing embedding for this entry, then insert
        conn.execute(
            "DELETE FROM kb_embeddings WHERE kb_entry_id = ?", (entry_id,)
        )

        import secrets as _secrets
        emb_id = "KBEMB-" + _secrets.token_hex(6)
        conn.execute(
            "INSERT INTO kb_embeddings (id, kb_entry_id, embedding, model, "
            "dimensions, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (emb_id, entry_id, blob, EMBEDDING_MODEL, len(embedding), now),
        )

        _audit(conn, "kb.embed", f"Generated embedding for KB entry: {entry_id}",
               "kb_entry", entry_id,
               {"model": EMBEDDING_MODEL, "dimensions": len(embedding)})
        conn.commit()

        return {
            "status": "embedded",
            "entry_id": entry_id,
            "embedding_id": emb_id,
            "model": EMBEDDING_MODEL,
            "dimensions": len(embedding),
            "created_at": now,
        }
    finally:
        conn.close()


def embed_all(db_path=None):
    """Batch-embed all active KB entries that are missing embeddings.

    Args:
        db_path: Optional database path override.

    Returns:
        dict with counts of embedded, skipped, and failed entries.
    """
    conn = _get_db(db_path)
    try:
        # Find entries without embeddings
        rows = conn.execute(
            "SELECT e.id, e.title FROM kb_entries e "
            "LEFT JOIN kb_embeddings emb ON e.id = emb.kb_entry_id "
            "WHERE e.is_active = 1 AND emb.id IS NULL",
        ).fetchall()
    finally:
        conn.close()

    embedded = 0
    failed = 0
    errors = []

    for row in rows:
        try:
            embed_entry(row["id"], db_path=db_path)
            embedded += 1
        except ValueError as exc:
            failed += 1
            errors.append({"id": row["id"], "error": str(exc)})

    return {
        "status": "completed",
        "total_missing": len(rows),
        "embedded": embedded,
        "failed": failed,
        "errors": errors if errors else None,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_parser():
    """Build the argument parser for the CLI."""
    parser = argparse.ArgumentParser(
        description="GovProposal Knowledge Base Search",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  %(prog)s --search --query 'cloud migration FedRAMP' --json\n"
            "  %(prog)s --keyword --query 'past performance DoD' --type case_study --json\n"
            "  %(prog)s --semantic --query 'zero trust architecture' --json\n"
            "  %(prog)s --embed --id KB-abc123def456\n"
            "  %(prog)s --embed-all --json\n"
        ),
    )

    # Action group
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--search", action="store_true",
                        help="Hybrid search (BM25 + semantic)")
    action.add_argument("--keyword", action="store_true",
                        help="BM25 keyword search only")
    action.add_argument("--semantic", action="store_true",
                        help="Semantic vector search only")
    action.add_argument("--embed", action="store_true",
                        help="Generate embedding for a single entry")
    action.add_argument("--embed-all", action="store_true",
                        help="Batch embed all entries missing embeddings")

    parser.add_argument("--query", help="Search query string")
    parser.add_argument("--id", help="KB entry ID (for --embed)")
    parser.add_argument("--type", dest="entry_type",
                        help="Filter by entry type")
    parser.add_argument("--limit", type=int, default=10,
                        help="Max results (default: 10)")
    parser.add_argument("--json", action="store_true", help="JSON output")
    parser.add_argument("--db-path", help="Override database path")

    return parser


def main():
    """CLI entry point."""
    parser = _build_parser()
    args = parser.parse_args()
    db = args.db_path

    try:
        if args.search:
            if not args.query:
                parser.error("--search requires --query")
            result = search(args.query, entry_type=args.entry_type,
                            limit=args.limit, db_path=db)

        elif args.keyword:
            if not args.query:
                parser.error("--keyword requires --query")
            result = keyword_search(args.query, entry_type=args.entry_type,
                                    limit=args.limit, db_path=db)

        elif args.semantic:
            if not args.query:
                parser.error("--semantic requires --query")
            result = semantic_search(args.query, entry_type=args.entry_type,
                                     limit=args.limit, db_path=db)

        elif args.embed:
            if not args.id:
                parser.error("--embed requires --id")
            result = embed_entry(args.id, db_path=db)

        elif args.embed_all:
            result = embed_all(db_path=db)

        # Output
        if args.json:
            print(json.dumps(result, indent=2, default=str))
        else:
            if isinstance(result, list):
                print(f"Found {len(result)} results:")
                for i, entry in enumerate(result, 1):
                    score = entry.get("score", 0)
                    print(f"  {i}. [{entry.get('id')}] {entry.get('title')} "
                          f"(score: {score:.4f})")
                    breakdown = entry.get("score_breakdown")
                    if breakdown:
                        print(f"     keyword={breakdown['keyword']:.4f} "
                              f"semantic={breakdown['semantic']:.4f}")
            elif isinstance(result, dict):
                for key, value in result.items():
                    if key == "errors" and value:
                        print(f"  {key}:")
                        for err in value:
                            print(f"    - {err}")
                    else:
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
