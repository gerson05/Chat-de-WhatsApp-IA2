"""
Indexador de la base de conocimiento (versión gratuita, sin servidor).

Lee los Markdown de icesi-kb/ según manifest.yaml, los parte en chunks,
genera embeddings (Gemini free o sentence-transformers local) y guarda un
índice vectorial local en un único archivo. No usa Postgres/pgvector ni Cohere.

Uso:
    python -m ingest.ingest [--path ./icesi-kb] [--doc DOC_ID]
"""
import argparse
import os
import sys
import logging
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))

from orchestrator.config import get_settings
from orchestrator.rag import build_index

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("ingest")

settings = get_settings()

CHUNK_SIZE = 500
CHUNK_OVERLAP = 50


def load_manifest(kb_path: str) -> list[dict]:
    manifest_path = os.path.join(kb_path, "manifest.yaml")
    if not os.path.exists(manifest_path):
        log.warning(f"[Ingest] manifest.yaml no encontrado en {manifest_path}")
        return []
    with open(manifest_path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data.get("documentos", [])


def read_markdown(path: str) -> tuple[str, dict]:
    """Devuelve (cuerpo, frontmatter)."""
    with open(path, encoding="utf-8") as f:
        content = f.read()
    frontmatter, body = {}, content
    if content.startswith("---"):
        end = content.find("---", 3)
        if end != -1:
            try:
                frontmatter = yaml.safe_load(content[3:end]) or {}
            except yaml.YAMLError:
                pass
            body = content[end + 3:].strip()
    return body, frontmatter


def chunk_text(text: str, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    chunks, start = [], 0
    while start < len(text):
        chunks.append(text[start:start + size].strip())
        start += size - overlap
    return [c for c in chunks if len(c) > 30]


def _segmento(doc: dict) -> str:
    seg = doc.get("segmento", ["transversal"])
    if isinstance(seg, list):
        return seg[0] if seg else "transversal"
    return seg


def collect_chunks(docs: list[dict], kb_path: str) -> list[dict]:
    all_chunks: list[dict] = []
    for doc in docs:
        ruta = os.path.join(kb_path, doc["ruta"])
        if not os.path.exists(ruta):
            log.warning(f"[Ingest] SKIP (no existe): {ruta}")
            continue
        body, frontmatter = read_markdown(ruta)
        vigencia = doc.get("vigencia") or frontmatter.get("vigencia")
        segmento = _segmento(doc)
        pieces = chunk_text(body)
        for piece in pieces:
            all_chunks.append({
                "documento_id": doc["id"],
                "contenido": piece,
                "segmento": segmento,
                "vigencia": str(vigencia) if vigencia else None,
                "tags": doc.get("tags", []),
            })
        log.info(f"[Ingest] {doc['id']}: {len(pieces)} chunks")
    return all_chunks


def main():
    parser = argparse.ArgumentParser(description="Indexador KB Icesi (local, gratis)")
    parser.add_argument("--path", default=settings.kb_path, help="Ruta de la KB")
    parser.add_argument("--doc", default=None, help="Indexar solo un documento por ID")
    args = parser.parse_args()

    docs = load_manifest(args.path)
    if not docs:
        log.warning("[Ingest] No hay documentos en manifest.yaml")
        return
    if args.doc:
        docs = [d for d in docs if d["id"] == args.doc]
        if not docs:
            log.warning(f"[Ingest] Documento {args.doc} no está en el manifest")
            return

    log.info(f"[Ingest] Proveedor de embeddings: {settings.embedding_provider}")
    chunks = collect_chunks(docs, args.path)
    if not chunks:
        log.warning("[Ingest] No se generaron chunks.")
        return

    total = build_index(chunks)
    log.info(f"[Ingest] Listo. {total} chunks indexados → {settings.vector_index_path}")


if __name__ == "__main__":
    main()
