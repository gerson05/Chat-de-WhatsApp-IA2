"""Database setup: SQLAlchemy + pgvector tables."""
from datetime import datetime
from sqlalchemy import (
    Column, String, Integer, Boolean, DateTime, Text, Float, JSON,
    create_engine, Index,
)
from sqlalchemy.orm import declarative_base, Session
from sqlalchemy.dialects.postgresql import UUID
import uuid

from .config import get_settings

settings = get_settings()
Base = declarative_base()


class KBChunk(Base):
    __tablename__ = "kb_chunks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    documento_id = Column(String(50), nullable=False, index=True)
    contenido = Column(Text, nullable=False)
    segmento = Column(String(20), default="transversal")
    tags = Column(JSON, default=list)
    vigencia = Column(DateTime, nullable=True)
    # embedding column added via raw SQL after table creation (pgvector)
    created_at = Column(DateTime, default=datetime.utcnow)


class ConversationLog(Base):
    __tablename__ = "conversation_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id = Column(String(64), nullable=False, index=True)
    tel_hash = Column(String(64), nullable=False)
    turn_id = Column(Integer, nullable=False)
    role = Column(String(10), nullable=False)
    text = Column(Text, nullable=False)
    tool_calls = Column(JSON, default=list)
    etapa_ciipoc = Column(String(20), nullable=True)
    segmento = Column(String(20), nullable=True)
    escalado = Column(Boolean, default=False)
    tokens_used = Column(Integer, default=0)
    latency_ms = Column(Integer, default=0)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)


class EscalamientoTicket(Base):
    __tablename__ = "tickets_escalamiento"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id = Column(String(64), nullable=False, index=True)
    lead_id = Column(String(100), nullable=True)
    motivo = Column(String(50), nullable=False)
    prioridad = Column(String(10), nullable=False)
    asesor_asignado = Column(String(100), nullable=True)
    ticket_text = Column(Text, nullable=False)
    asesor_tomo_caso = Column(Boolean, default=False)
    asesor_nombre = Column(String(100), nullable=True)
    took_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


class IntentionLog(Base):
    __tablename__ = "intenciones_log"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id = Column(String(64), nullable=False, index=True)
    etapa = Column(String(20), nullable=False)
    programa = Column(String(200), nullable=True)
    siguiente_accion = Column(String(200), nullable=True)
    barrera = Column(Text, nullable=True)
    necesidad = Column(Text, nullable=True)
    avanzó_etapa = Column(Boolean, default=False)
    timestamp = Column(DateTime, default=datetime.utcnow)


class ArchivedSession(Base):
    """Full session JSON archived from Redis before TTL expiry. Audit trail / Ley 1581."""
    __tablename__ = "archived_sessions"

    session_id = Column(String(64), primary_key=True)
    session_json = Column(Text, nullable=False)
    etapa_ciipoc = Column(String(20), nullable=True)
    segmento = Column(String(20), nullable=True)
    escalado = Column(Boolean, default=False)
    created_at = Column(DateTime, nullable=True, index=True)
    last_updated = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    purge_after = Column(DateTime, nullable=True, index=True)


class FollowupJob(Base):
    """Persistent follow-up queue backed by Postgres. Survives Redis/service restarts."""
    __tablename__ = "followup_jobs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id = Column(String(64), nullable=False, index=True)
    etapa = Column(String(20), nullable=False)
    nombre = Column(String(200), nullable=True)
    programa = Column(String(200), nullable=True)
    fire_at = Column(DateTime, nullable=False, index=True)
    executed = Column(Boolean, default=False, index=True)
    celery_task_id = Column(String(100), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    executed_at = Column(DateTime, nullable=True)


_engine = None


def get_engine():
    global _engine
    if _engine is None:
        _engine = create_engine(settings.database_url)
    return _engine


def init_db():
    """Create all tables (conversation_logs, tickets, archived_sessions, followup_jobs, …)."""
    engine = get_engine()
    with engine.connect() as conn:
        conn.execute(
            __import__("sqlalchemy").text("CREATE EXTENSION IF NOT EXISTS vector")
        )
        conn.commit()
    Base.metadata.create_all(engine)
    # Add embedding column if not exists
    with engine.connect() as conn:
        conn.execute(__import__("sqlalchemy").text(
            "ALTER TABLE kb_chunks ADD COLUMN IF NOT EXISTS embedding vector(1024)"
        ))
        conn.execute(__import__("sqlalchemy").text(
            "CREATE INDEX IF NOT EXISTS kb_chunks_embedding_idx "
            "ON kb_chunks USING ivfflat (embedding vector_cosine_ops)"
        ))
        conn.commit()


def archive_session(session_json: str, session_id: str, etapa: str, segmento: str,
                    escalado: bool, created_at, retention_days: int = 90):
    """Upsert full session JSON to Postgres. Called on every save — last write wins."""
    from datetime import timedelta
    try:
        with Session(get_engine()) as db:
            existing = db.get(ArchivedSession, session_id)
            purge_after = datetime.utcnow() + timedelta(days=retention_days)
            if existing:
                existing.session_json = session_json
                existing.etapa_ciipoc = etapa
                existing.segmento = segmento
                existing.escalado = escalado
                existing.last_updated = datetime.utcnow()
                existing.purge_after = purge_after
            else:
                db.add(ArchivedSession(
                    session_id=session_id,
                    session_json=session_json,
                    etapa_ciipoc=etapa,
                    segmento=segmento,
                    escalado=escalado,
                    created_at=created_at,
                    purge_after=purge_after,
                ))
            db.commit()
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning(f"[DB] archive_session failed: {exc}")


def create_followup_job(session_id: str, etapa: str, nombre: str, programa: str,
                        fire_at, celery_task_id: str = None):
    """Persist a follow-up job to Postgres so it survives service restarts."""
    try:
        with Session(get_engine()) as db:
            job = FollowupJob(
                session_id=session_id,
                etapa=etapa,
                nombre=nombre,
                programa=programa,
                fire_at=fire_at,
                celery_task_id=celery_task_id,
            )
            db.add(job)
            db.commit()
            return str(job.id)
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning(f"[DB] create_followup_job failed: {exc}")
        return None


def purge_expired_sessions(retention_days: int = None):
    """Delete archived sessions past their purge_after date. Call periodically."""
    from datetime import timedelta
    try:
        with Session(get_engine()) as db:
            cutoff = datetime.utcnow()
            result = db.execute(
                __import__("sqlalchemy").text(
                    "DELETE FROM archived_sessions WHERE purge_after < :cutoff"
                ),
                {"cutoff": cutoff},
            )
            db.commit()
            import logging
            logging.getLogger(__name__).info(
                f"[DB] Purged {result.rowcount} expired archived sessions."
            )
            return result.rowcount
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning(f"[DB] purge_expired_sessions failed: {exc}")
        return 0


def log_turn(
    session_id: str,
    tel_hash: str,
    turn_id: int,
    role: str,
    text: str,
    tool_calls: list,
    etapa: str,
    segmento: str,
    escalado: bool,
    tokens: int = 0,
    latency_ms: int = 0,
):
    try:
        with Session(get_engine()) as db:
            row = ConversationLog(
                session_id=session_id,
                tel_hash=tel_hash,
                turn_id=turn_id,
                role=role,
                text=text,
                tool_calls=tool_calls,
                etapa_ciipoc=etapa,
                segmento=segmento,
                escalado=escalado,
                tokens_used=tokens,
                latency_ms=latency_ms,
            )
            db.add(row)
            db.commit()
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning(f"[DB] log_turn failed: {exc}")
