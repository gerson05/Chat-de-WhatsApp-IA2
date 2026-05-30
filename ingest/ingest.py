"""
Knowledge Base ingestion pipeline.
Reads Markdown files from icesi-kb/, chunks them, embeds with Cohere,
and upserts into PostgreSQL pgvector.

Usage:
    python -m ingest.ingest [--full] [--path ./icesi-kb]
"""
import argparse
import os
import sys
import uuid
import yaml
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from orchestrator.config import get_settings
from orchestrator.rag import embed_text

settings = get_settings()

CHUNK_SIZE = 500
CHUNK_OVERLAP = 50


def load_manifest(kb_path: str) -> list[dict]:
    manifest_path = os.path.join(kb_path, "manifest.yaml")
    if not os.path.exists(manifest_path):
        print(f"[Ingest] manifest.yaml not found at {manifest_path}")
        return []
    with open(manifest_path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data.get("documentos", [])


def read_markdown(path: str) -> tuple[str, dict]:
    """Returns (body_text, frontmatter_dict)."""
    with open(path, encoding="utf-8") as f:
        content = f.read()

    frontmatter = {}
    body = content

    if content.startswith("---"):
        end = content.find("---", 3)
        if end != -1:
            try:
                frontmatter = yaml.safe_load(content[3:end]) or {}
            except yaml.YAMLError:
                pass
            body = content[end + 3:].strip()

    return body, frontmatter


def chunk_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunk = text[start:end]
        chunks.append(chunk.strip())
        start += chunk_size - overlap
    return [c for c in chunks if len(c) > 30]


def ingest_document(doc: dict, kb_path: str, engine) -> int:
    from sqlalchemy import text
    from sqlalchemy.orm import Session

    ruta = os.path.join(kb_path, doc["ruta"])
    if not os.path.exists(ruta):
        print(f"[Ingest] SKIP (not found): {ruta}")
        return 0

    body, frontmatter = read_markdown(ruta)
    chunks = chunk_text(body)

    # Parse vigencia
    vigencia_raw = doc.get("vigencia") or frontmatter.get("vigencia")
    vigencia = None
    if vigencia_raw:
        try:
            vigencia = datetime.strptime(str(vigencia_raw), "%Y-%m-%d")
        except ValueError:
            pass

    segmento = doc.get("segmento", ["transversal"])
    if isinstance(segmento, list):
        segmento = segmento[0] if segmento else "transversal"

    count = 0
    with Session(engine) as session:
        # Delete old chunks for this document
        session.execute(
            text("DELETE FROM kb_chunks WHERE documento_id = :doc_id"),
            {"doc_id": doc["id"]},
        )

        for i, chunk in enumerate(chunks):
            embedding = embed_text(chunk)
            vec_str = "[" + ",".join(str(v) for v in embedding) + "]"

            session.execute(
                text("""
                    INSERT INTO kb_chunks
                    (id, documento_id, contenido, segmento, tags, vigencia, embedding, created_at)
                    VALUES
                    (:id, :doc_id, :contenido, :segmento, :tags::jsonb,
                     :vigencia, :embedding::vector, NOW())
                """),
                {
                    "id": str(uuid.uuid4()),
                    "doc_id": doc["id"],
                    "contenido": chunk,
                    "segmento": segmento,
                    "tags": str(doc.get("tags", [])),
                    "vigencia": vigencia,
                    "embedding": vec_str,
                },
            )
            count += 1

        session.commit()

    print(f"[Ingest] {doc['id']}: {count} chunks indexed")
    return count


def main():
    parser = argparse.ArgumentParser(description="Icesi KB ingestion")
    parser.add_argument("--full", action="store_true", help="Full re-index")
    parser.add_argument("--path", default=settings.kb_path, help="KB path")
    parser.add_argument("--doc", default=None, help="Ingest single document ID")
    args = parser.parse_args()

    from sqlalchemy import create_engine
    engine = create_engine(settings.database_url)

    docs = load_manifest(args.path)
    if not docs:
        print("[Ingest] No documents found in manifest.yaml")
        return

    if args.doc:
        docs = [d for d in docs if d["id"] == args.doc]
        if not docs:
            print(f"[Ingest] Document {args.doc} not found in manifest")
            return

    total = 0
    for doc in docs:
        total += ingest_document(doc, args.path, engine)

    print(f"[Ingest] Done. Total chunks indexed: {total}")


if __name__ == "__main__":
    main()
