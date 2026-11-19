"""Node functions for the RAG specialist subgraph.

Purpose:
    Retrieves policy documentation chunks via pgvector (role ontoagent_kb)
    with explicit JSON cache fallback, scans for prompt injection payloads,
    filters quarantined texts, and wraps chunks in strict <untrusted_data> boundaries.
"""

import json
import logging
from pathlib import Path
import time
from typing import Any, Dict, List, Optional
from ontoagent.config import get_settings
from ontoagent.db.embeddings import embed_text
from ontoagent.graph.models import RagChunk, RagResult
from ontoagent.guards.sanitize import scan_untrusted_text, wrap_untrusted_data

logger = logging.getLogger(__name__)


def get_kb_cache_path() -> Path:
    """Resolve path to data/kb_chunks.json from the package or workspace root."""
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "data" / "kb_chunks.json"
        if candidate.exists():
            return candidate
    return Path("data/kb_chunks.json").resolve()


def cosine_similarity(v1: List[float], v2: List[float]) -> float:
    """Compute cosine similarity between two float vectors."""
    dot = sum(a * b for a, b in zip(v1, v2))
    norm_a = sum(a * a for a, b in zip(v1, v2)) ** 0.5
    norm_b = sum(b * b for a, b in zip(v1, v2)) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


async def run_rag_instruction(instruction: str) -> RagResult:
    """Execute RAG retrieval, scanning, filtering, and packaging for an instruction.

    Attempts pgvector retrieval against kb.policy_chunks first (role ontoagent_kb);
    falls back to offline JSON cache if Postgres is unreachable.
    """
    start_time = time.time()
    settings = get_settings()

    # 1. Embed query
    query_vec = embed_text(instruction)

    # 2. Retrieve chunks: try PostgreSQL pgvector first (Bug B5)
    raw_chunks: List[Dict[str, Any]] = []
    used_db = False

    try:
        import psycopg
        import re
        stop_words = {'when', 'does', 'for', 'and', 'what', 'the', 'order', 'according', 'with', 'must', 'per', 'that', 'are', 'which', 'how', 'any', 'tell', 'show'}
        words = [w for w in re.findall(r'\b[a-zA-Z]{3,}\b', instruction) if w.lower() not in stop_words]
        ts_q = ' | '.join(words) if words else ""

        with psycopg.connect(settings.postgres_kb_url, connect_timeout=2) as conn:
            with conn.cursor() as cur:
                if ts_q:
                    cur.execute(
                        """
                        WITH candidates AS (
                            SELECT chunk_id, doc_id, doc_title, section, content, trust_level, quarantined, scan_score,
                                   ts_rank_cd(tsv, to_tsquery('english', %s)) AS fts_score,
                                   (1 - (embedding <=> %s::vector)) AS vec_score
                            FROM kb.policy_chunks
                        )
                        SELECT chunk_id, doc_id, doc_title, section, content, trust_level, quarantined, scan_score,
                               (fts_score * 3.0 + vec_score) AS score
                        FROM candidates
                        ORDER BY (fts_score * 3.0 + vec_score) DESC
                        LIMIT 5;
                        """,
                        (ts_q, query_vec),
                    )
                else:
                    cur.execute(
                        """
                        SELECT chunk_id, doc_id, doc_title, section, content, trust_level, quarantined, scan_score,
                               1 - (embedding <=> %s::vector) AS score
                        FROM kb.policy_chunks
                        ORDER BY embedding <=> %s::vector
                        LIMIT 5;
                        """,
                        (query_vec,),
                    )
                rows = cur.fetchall()
                if rows:
                    for r in rows:
                        raw_chunks.append({
                            "chunk_id": r[0],
                            "doc_id": r[1],
                            "doc_title": r[2],
                            "section": r[3],
                            "content": r[4],
                            "trust_level": r[5],
                            "quarantined": r[6],
                            "scan_score": r[7],
                            "score": float(r[8]),
                            "citation_anchor": f"[{r[1]}#{r[3]}]"
                        })
                    used_db = True
    except Exception as e:
        logger.info(
            "PostgreSQL pgvector retrieval unavailable (%s); falling back to offline JSON cache at %s",
            str(e),
            get_kb_cache_path(),
        )

    # Fallback to local JSON cache if DB unavailable or empty
    if not used_db:
        cache_path = get_kb_cache_path()
        chunks_cache: List[Dict[str, Any]] = []
        if cache_path.exists():
            try:
                with open(cache_path, "r", encoding="utf-8") as f:
                    chunks_cache = json.load(f)
            except Exception as e:
                logger.warning("Failed to load KB cache (%s)", str(e))

        if not chunks_cache:
            from ontoagent.data.ingest_kb import ingest_knowledge_base
            chunks_cache = ingest_knowledge_base()

        # Score chunks by cosine similarity
        scored_chunks = []
        for c in chunks_cache:
            score = cosine_similarity(query_vec, c.get("embedding", []))
            c_copy = dict(c)
            c_copy["score"] = score
            scored_chunks.append((score, c_copy))

        scored_chunks.sort(key=lambda x: x[0], reverse=True)
        raw_chunks = [item[1] for item in scored_chunks[:5]]

    # 3. Scan and filter (Bug B7: filter quarantined chunks, wrap delimiters)
    final_chunks: List[RagChunk] = []
    citations: List[str] = []
    quarantined_count = 0

    for raw_c in raw_chunks:
        content = raw_c["content"]
        scan_res = scan_untrusted_text(content)
        is_quarantined = raw_c.get("quarantined", False) or scan_res.flagged

        if is_quarantined:
            quarantined_count += 1
            if settings.features.scan_untrusted:
                logger.warning("Quarantined chunk %s filtered due to injection score %s", raw_c.get("doc_id"), scan_res.score)
                continue

        anchor = raw_c.get("citation_anchor", f"[{raw_c.get('doc_id')}#{raw_c.get('section')}]")
        citations.append(anchor)

        # Wrap in untrusted data delimiters
        wrapped = wrap_untrusted_data(content, source="kb", item_id=anchor)

        final_chunks.append(
            RagChunk(
                chunk_id=raw_c.get("chunk_id", 0),
                doc_id=raw_c.get("doc_id", "doc"),
                doc_title=raw_c.get("doc_title", ""),
                section=raw_c.get("section", ""),
                citation_anchor=anchor,
                content=wrapped,
                score=round(raw_c.get("score", 0.0), 4),
                trust_level=raw_c.get("trust_level", "internal"),
                quarantined=is_quarantined,
            )
        )

    return RagResult(
        ok=True,
        instruction=instruction,
        chunks=final_chunks,
        citations=citations,
        quarantined_count=quarantined_count,
        elapsed_ms=int((time.time() - start_time) * 1000),
    )
