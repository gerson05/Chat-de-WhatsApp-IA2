from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # ── LLM: Google Gemini (AI Studio) ──────────────────────────────────────────
    # Migrado de Anthropic/Claude a Gemini para operar en la capa gratuita.
    gemini_api_key: str = ""
    llm_model: str = "gemini-2.5-flash"
    llm_model_cheap: str = "gemini-2.5-flash-lite"

    # ── RAG / Embeddings (gratis, sin servidor) ─────────────────────────────────
    # provider: "gemini" (free tier, sin descarga) | "local" (sentence-transformers, offline)
    embedding_provider: str = "gemini"
    embedding_model_gemini: str = "models/gemini-embedding-001"
    embedding_model_local: str = "intfloat/multilingual-e5-small"
    # Índice vectorial local en archivo (no requiere Postgres/pgvector).
    vector_index_path: str = "./icesi-kb/.index/kb_index.pkl"
    rag_top_k: int = 5

    cohere_api_key: str = ""  # legado — ya no se usa (se reemplazó por embeddings gratis)

    database_url: str = "postgresql://icesi:icesi_pass@localhost:5432/icesi_ia"
    redis_url: str = "redis://localhost:6379/0"

    # ── Telegram (canal recomendado para la demo — gratis) ──────────────────────
    telegram_bot_token: str = ""

    whatsapp_phone_id: str = ""
    whatsapp_access_token: str = ""
    whatsapp_app_secret: str = ""       # Meta App Secret — used for webhook HMAC verification
    whatsapp_verify_token: str = "icesi_verify_2026"

    chat_api_key: str = ""              # Bearer token required on /chat endpoint (set in production)

    crm_backend: str = "mock"
    hubspot_api_key: str = ""
    salesforce_instance_url: str = ""
    salesforce_access_token: str = ""

    secret_key: str = "cambia_esto_en_produccion_32chars_min"
    encryption_key: str = "cambia_esto_en_produccion_32chars_min"
    phone_hash_secret: str = ""  # dedicated secret for phone hashing — falls back to secret_key

    # Compliance / retention
    data_retention_days: int = 90  # Ley 1581: default 90-day session retention

    # A/B prompt testing
    prompt_variant_default: str = "v1"

    internal_wa_group_pregrado: str = ""
    internal_wa_group_posgrado: str = ""
    internal_wa_group_educontinua: str = ""
    internal_wa_group_jefe: str = ""

    sentry_dsn: str = ""

    app_env: str = "development"
    app_port: int = 8000
    log_level: str = "INFO"
    kb_path: str = "./icesi-kb"

    # Límites operacionales
    session_ttl_days: int = 7
    max_messages_per_day: int = 60
    max_bot_messages_per_session: int = 20
    max_turns_without_advance: int = 10
    model_timeout_seconds: int = 15
    history_window: int = 8

    class Config:
        env_file = ".env"
        extra = "ignore"


@lru_cache
def get_settings() -> Settings:
    return Settings()
