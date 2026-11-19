"""Knowledge base ingestion and indexing pipeline.

Purpose:
    Parses policy documents and adversarial test bulletins into heading-based chunks.
    Computes dense embeddings, runs the injection scanner, and persists chunks
    both to PostgreSQL (kb.policy_chunks) and a local offline JSON cache.
"""

import json
from pathlib import Path
import re
from typing import Any, Dict, List
from ontoagent.config import get_settings
from ontoagent.db.embeddings import embed_text
from ontoagent.guards.sanitize import scan_untrusted_text

DOCS_DIR = Path("policies/docs")
OFFLINE_CACHE_PATH = Path("data/kb_chunks.json")


def parse_markdown_doc(doc_path: Path) -> List[Dict[str, Any]]:
    """Split markdown document by ## and ### headings into citation-anchored chunks."""
    doc_id = doc_path.stem
    text = doc_path.read_text(encoding="utf-8")

    # Extract title from # Heading
    title_match = re.search(r"^#\s+(.+)$", text, re.MULTILINE)
    doc_title = title_match.group(1).strip() if title_match else doc_id

    # Split by headings (## or ###)
    sections = re.split(r"(^#{2,3}\s+.+$)", text, flags=re.MULTILINE)
    chunks: List[Dict[str, Any]] = []

    current_section = "Overview"
    current_content: List[str] = []

    for part in sections:
        part = part.strip()
        if not part:
            continue
        if part.startswith("## ") or part.startswith("### "):
            if current_content:
                body = "\n".join(current_content).strip()
                if body:
                    chunks.append({
                        "doc_id": doc_id,
                        "doc_title": doc_title,
                        "section": current_section,
                        "content": body,
                    })
                current_content = []
            current_section = re.sub(r"^#{2,3}\s+", "", part).strip()
        else:
            current_content.append(part)

    if current_content:
        body = "\n".join(current_content).strip()
        if body:
            chunks.append({
                "doc_id": doc_id,
                "doc_title": doc_title,
                "section": current_section,
                "content": body,
            })

    return chunks


def ingest_knowledge_base() -> List[Dict[str, Any]]:
    """Ingest, embed, and index all markdown policy and adversarial documents."""
    settings = get_settings()
    all_docs = list(DOCS_DIR.glob("**/*.md"))

    all_chunks: List[Dict[str, Any]] = []
    chunk_counter = 1

    for doc_file in all_docs:
        # Check if under adversarial
        is_adversarial = "adversarial" in str(doc_file).lower()
        if is_adversarial and not settings.red_team_mode:
            continue

        raw_chunks = parse_markdown_doc(doc_file)
        for rc in raw_chunks:
            content = rc["content"]
            scan_res = scan_untrusted_text(content)
            emb = embed_text(content)

            chunk_obj = {
                "chunk_id": chunk_counter,
                "doc_id": rc["doc_id"],
                "doc_title": rc["doc_title"],
                "section": rc["section"],
                "citation_anchor": f"[{rc['doc_id']}#{rc['section']}]",
                "content": content,
                "embedding": emb,
                "trust_level": "untrusted" if is_adversarial else "internal",
                "quarantined": scan_res.flagged,
                "scan_score": scan_res.score,
                "matches": scan_res.matches,
            }
            all_chunks.append(chunk_obj)
            chunk_counter += 1

    # Save to offline JSON cache
    OFFLINE_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OFFLINE_CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(all_chunks, f, indent=2)

    print(f"Successfully processed {len(all_chunks)} policy chunks from {len(all_docs)} documents.")

    # Try inserting into PostgreSQL if connection is reachable
    try:
        import psycopg
        with psycopg.connect(settings.postgres_admin_url, autocommit=True, connect_timeout=2) as conn:
            with conn.cursor() as cur:
                cur.execute("TRUNCATE TABLE kb.policy_chunks;")
                for c in all_chunks:
                    cur.execute(
                        """
                        INSERT INTO kb.policy_chunks 
                        (doc_id, doc_title, section, content, embedding, trust_level, quarantined, scan_score)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s);
                        """,
                        (
                            c["doc_id"], c["doc_title"], c["section"], c["content"],
                            c["embedding"], c["trust_level"], c["quarantined"], c["scan_score"]
                        )
                    )
        print("Inserted policy chunks into live PostgreSQL kb.policy_chunks.")
    except Exception as e:
        print(f"Note: PostgreSQL unavailable for live KB insert ({str(e)}). Offline cache populated.")

    return all_chunks


if __name__ == "__main__":
    ingest_knowledge_base()
