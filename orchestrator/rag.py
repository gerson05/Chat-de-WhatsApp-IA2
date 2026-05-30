"""RAG pipeline: embed → pgvector query → optional rerank → return top-K chunks."""
import os
from typing import Optional
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from .config import get_settings

settings = get_settings()

# Lazy imports so the app starts even without optional deps
_cohere = None
_openai = None


def _get_cohere():
    global _cohere
    if _cohere is None and settings.cohere_api_key:
        import cohere
        _cohere = cohere.Client(settings.cohere_api_key)
    return _cohere


def embed_text(query: str) -> list[float]:
    co = _get_cohere()
    if co:
        resp = co.embed(
            texts=[query],
            model="embed-multilingual-v3.0",
            input_type="search_query",
        )
        return resp.embeddings[0]
    # Fallback: zero vector (development mode)
    return [0.0] * 1024


def rerank(query: str, candidates: list[dict], top_n: int = 5) -> list[dict]:
    co = _get_cohere()
    if co and len(candidates) > top_n:
        docs = [c["contenido"] for c in candidates]
        result = co.rerank(
            query=query,
            documents=docs,
            model="rerank-multilingual-v3.0",
            top_n=top_n,
        )
        return [candidates[r.index] for r in result.results]
    return candidates[:top_n]


_engine = None


def _get_engine():
    global _engine
    if _engine is None:
        _engine = create_engine(settings.database_url)
    return _engine


def query_kb(
    query: str,
    segmento_filtro: Optional[str] = None,
    top_k: int = 5,
) -> list[dict]:
    """Query pgvector for the most relevant KB chunks."""
    embedding = embed_text(query)
    vec_str = "[" + ",".join(str(v) for v in embedding) + "]"

    base_sql = """
        SELECT id, documento_id, contenido, segmento, tags,
               1 - (embedding <=> :vec::vector) AS score
        FROM kb_chunks
        WHERE vigencia >= CURRENT_DATE
    """
    params: dict = {"vec": vec_str}

    if segmento_filtro and segmento_filtro != "transversal":
        base_sql += " AND (segmento = :seg OR segmento = 'transversal')"
        params["seg"] = segmento_filtro

    base_sql += " ORDER BY embedding <=> :vec::vector LIMIT 20"

    try:
        with Session(_get_engine()) as session:
            rows = session.execute(text(base_sql), params).fetchall()
            candidates = [
                {
                    "id": str(r.id),
                    "documento_id": r.documento_id,
                    "contenido": r.contenido,
                    "segmento": r.segmento,
                    "score": float(r.score),
                }
                for r in rows
            ]
        return rerank(query, candidates, top_n=top_k)
    except Exception as exc:
        # DB not available in dev/test: return empty
        return [{"contenido": f"[KB no disponible: {exc}]", "documento_id": "N/A", "score": 0}]


def format_kb_results(chunks: list[dict]) -> str:
    if not chunks:
        return "No se encontró información relevante en la base de conocimiento."
    parts = []
    for i, c in enumerate(chunks, 1):
        parts.append(f"[Fuente {i} — {c.get('documento_id','?')}]\n{c['contenido']}")
    return "\n\n---\n\n".join(parts)
