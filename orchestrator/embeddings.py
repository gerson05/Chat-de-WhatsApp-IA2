"""
Embeddings pluggables y gratuitos para el RAG.

Dos proveedores, seleccionables por `EMBEDDING_PROVIDER`:
  - "gemini": usa la API de embeddings de Google AI Studio (capa gratuita,
    sin descarga de modelos). Modelo por defecto: text-embedding-004.
  - "local": usa sentence-transformers en local (100% offline, sin cuota).
    Requiere `pip install sentence-transformers` (descarga ~120 MB la 1ª vez).

Ambos exponen la misma función `embed_texts(textos, input_type)` donde
`input_type` es "document" (para indexar chunks) o "query" (para buscar).
"""
import logging
from typing import Literal

from .config import get_settings

settings = get_settings()
log = logging.getLogger(__name__)

InputType = Literal["document", "query"]


# ── Proveedor: Gemini (AI Studio, free tier) ─────────────────────────────────────

_gemini_ready = False


def _ensure_gemini():
    global _gemini_ready
    if not _gemini_ready:
        import google.generativeai as genai
        genai.configure(api_key=settings.gemini_api_key)
        _gemini_ready = True


def _embed_gemini(texts: list[str], input_type: InputType) -> list[list[float]]:
    import google.generativeai as genai
    _ensure_gemini()
    task = "retrieval_query" if input_type == "query" else "retrieval_document"
    vectors: list[list[float]] = []
    # El SDK admite lista en `content`, pero embebemos uno a uno para tolerar
    # fallos puntuales y mantener el orden de forma simple.
    for text in texts:
        resp = genai.embed_content(
            model=settings.embedding_model_gemini,
            content=text,
            task_type=task,
        )
        vectors.append(resp["embedding"])
    return vectors


# ── Proveedor: local (sentence-transformers) ─────────────────────────────────────

_local_model = None


def _get_local_model():
    global _local_model
    if _local_model is None:
        from sentence_transformers import SentenceTransformer
        log.info(f"[Embeddings] Cargando modelo local {settings.embedding_model_local}…")
        _local_model = SentenceTransformer(settings.embedding_model_local)
    return _local_model


def _embed_local(texts: list[str], input_type: InputType) -> list[list[float]]:
    model = _get_local_model()
    # Los modelos e5 esperan prefijos "query:" / "passage:".
    prefix = "query: " if input_type == "query" else "passage: "
    prefixed = [prefix + t for t in texts]
    embs = model.encode(prefixed, normalize_embeddings=True, convert_to_numpy=True)
    return [e.tolist() for e in embs]


# ── API pública ──────────────────────────────────────────────────────────────────

def embed_texts(texts: list[str], input_type: InputType = "document") -> list[list[float]]:
    """Devuelve un vector por cada texto. Lanza excepción si el proveedor falla;
    los llamadores (rag.query_kb / ingest) deben capturarla y degradar."""
    if not texts:
        return []
    if settings.embedding_provider == "local":
        return _embed_local(texts, input_type)
    return _embed_gemini(texts, input_type)


def embed_one(text: str, input_type: InputType = "query") -> list[float]:
    return embed_texts([text], input_type)[0]
