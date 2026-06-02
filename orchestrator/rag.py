"""
Pipeline RAG — versión gratuita y sin servidor.

Reemplaza pgvector + Cohere por:
  - embeddings gratuitos (Gemini free tier o sentence-transformers local) → embeddings.py
  - un índice vectorial local persistido en un único archivo (pickle + numpy)

El índice se construye con `python -m ingest.ingest` y se consulta en runtime
con `query_kb`. No requiere Postgres, Redis ni APIs de pago. Si el índice no
existe o el embedding falla, degrada con un mensaje claro en vez de crashear.
"""
import logging
import os
import pickle
from datetime import datetime
from typing import Optional

import numpy as np

from .config import get_settings
from .embeddings import embed_one, embed_texts  # noqa: F401 (embed_texts lo usa ingest)

settings = get_settings()
log = logging.getLogger(__name__)


# ── Índice local en memoria (cargado perezosamente desde disco) ──────────────────

class _Index:
    def __init__(self, matrix: np.ndarray, meta: list[dict]):
        self.matrix = matrix          # (N, D) float32, filas normalizadas
        self.meta = meta              # lista paralela de dicts por chunk


_index_cache: Optional[_Index] = None
_index_load_attempted = False


def _normalize(mat: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(mat, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return mat / norms


def _load_index() -> Optional[_Index]:
    global _index_cache, _index_load_attempted
    if _index_cache is not None:
        return _index_cache
    if _index_load_attempted:
        return None
    _index_load_attempted = True

    path = settings.vector_index_path
    if not os.path.exists(path):
        log.warning(f"[RAG] Índice no encontrado en {path}. Ejecuta: python -m ingest.ingest")
        return None
    try:
        with open(path, "rb") as f:
            data = pickle.load(f)
        matrix = _normalize(np.asarray(data["embeddings"], dtype=np.float32))
        _index_cache = _Index(matrix=matrix, meta=data["meta"])
        log.info(f"[RAG] Índice cargado: {len(_index_cache.meta)} chunks, dim={matrix.shape[1]}")
        return _index_cache
    except Exception as exc:
        log.error(f"[RAG] No se pudo cargar el índice: {exc}")
        return None


def reset_index_cache():
    """Fuerza recarga del índice (útil tras reindexar)."""
    global _index_cache, _index_load_attempted
    _index_cache = None
    _index_load_attempted = False


# ── Consulta ─────────────────────────────────────────────────────────────────────

def _vigente(meta: dict) -> bool:
    vig = meta.get("vigencia")
    if not vig:
        return True
    try:
        return datetime.strptime(str(vig)[:10], "%Y-%m-%d").date() >= datetime.utcnow().date()
    except ValueError:
        return True


def query_kb(
    query: str,
    segmento_filtro: Optional[str] = None,
    top_k: Optional[int] = None,
) -> list[dict]:
    """Devuelve los chunks más relevantes de la KB. Nunca lanza: degrada con
    un único chunk informativo si no hay índice o el embedding falla."""
    top_k = top_k or settings.rag_top_k
    index = _load_index()
    if index is None:
        return [{
            "contenido": "[KB no indexada — ejecuta `python -m ingest.ingest`]",
            "documento_id": "N/A", "score": 0.0,
        }]

    try:
        q_vec = np.asarray(embed_one(query, input_type="query"), dtype=np.float32)
    except Exception as exc:
        log.error(f"[RAG] Falló el embedding de la consulta: {exc}")
        return [{
            "contenido": "[Búsqueda no disponible temporalmente]",
            "documento_id": "N/A", "score": 0.0,
        }]

    q_norm = q_vec / (np.linalg.norm(q_vec) or 1.0)
    scores = index.matrix @ q_norm  # similitud coseno (filas ya normalizadas)

    # Orden descendente y filtrado por segmento + vigencia.
    order = np.argsort(-scores)
    results: list[dict] = []
    for idx in order:
        meta = index.meta[idx]
        if not _vigente(meta):
            continue
        seg = meta.get("segmento")
        if segmento_filtro and segmento_filtro != "transversal":
            if seg not in (segmento_filtro, "transversal", None):
                continue
        results.append({
            "contenido": meta["contenido"],
            "documento_id": meta.get("documento_id", "?"),
            "segmento": seg,
            "score": float(scores[idx]),
        })
        if len(results) >= top_k:
            break

    if not results:
        return [{
            "contenido": "No se encontró información relevante en la base de conocimiento.",
            "documento_id": "N/A", "score": 0.0,
        }]
    return results


def format_kb_results(chunks: list[dict]) -> str:
    if not chunks:
        return "No se encontró información relevante en la base de conocimiento."
    parts = []
    for i, c in enumerate(chunks, 1):
        parts.append(f"[Fuente {i} — {c.get('documento_id', '?')}]\n{c['contenido']}")
    return "\n\n---\n\n".join(parts)


# ── Construcción del índice (usado por ingest) ───────────────────────────────────

def build_index(chunks: list[dict]) -> int:
    """Embebe los chunks y persiste el índice local. `chunks` = lista de dicts con
    al menos {contenido, documento_id, segmento, vigencia}."""
    if not chunks:
        log.warning("[RAG] No hay chunks para indexar.")
        return 0

    textos = [c["contenido"] for c in chunks]
    vectores = embed_texts(textos, input_type="document")
    matrix = np.asarray(vectores, dtype=np.float32)

    path = settings.vector_index_path
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "wb") as f:
        pickle.dump({"embeddings": matrix, "meta": chunks}, f)

    reset_index_cache()
    log.info(f"[RAG] Índice guardado en {path}: {len(chunks)} chunks, dim={matrix.shape[1]}")
    return len(chunks)
