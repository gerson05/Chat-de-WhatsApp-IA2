"""
Celery worker for Icesi IA.
Uses Redis as broker (same Redis instance as session store).

Start worker:
    celery -A orchestrator.celery_worker worker --loglevel=info

Inspect queued tasks:
    celery -A orchestrator.celery_worker inspect scheduled
"""
import logging

from celery import Celery

from .config import get_settings

settings = get_settings()
log = logging.getLogger(__name__)

celery_app = Celery(
    "icesi_ia",
    broker=settings.redis_url,
    backend=settings.redis_url,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="America/Bogota",
    enable_utc=True,
    task_acks_late=True,          # ACK after execution — no message loss on worker crash
    worker_prefetch_multiplier=1,
    task_track_started=True,
)

_FOLLOWUP_TEMPLATES = {
    "indagacion": (
        "Hola {nombre}, veo que estuviste explorando opciones en Icesi. "
        "¿Tienes alguna pregunta pendiente? Estoy aquí para ayudarte."
    ),
    "propuesta": (
        "Hola {nombre}, ¿pudiste revisar la información sobre {programa}? "
        "Con gusto resolvemos cualquier duda que tengas."
    ),
    "objeciones": (
        "Hola {nombre}, ¿lograste resolver las inquietudes sobre {programa}? "
        "Un asesor puede ayudarte a dar el siguiente paso."
    ),
    "cierre": (
        "Hola {nombre}, ¿cómo va tu proceso de inscripción en Icesi? "
        "Aún estamos disponibles para acompañarte."
    ),
}


@celery_app.task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    max_retries=3,
    name="icesi.send_followup",
)
def send_followup_message(
    self,
    session_id: str,
    etapa: str,
    nombre: str = "",
    programa: str = "",
):
    """
    Send a follow-up WhatsApp message to a user based on their CIIPOC stage.
    Automatically retries up to 3 times with exponential backoff on failure.
    """
    template = _FOLLOWUP_TEMPLATES.get(etapa)
    if not template:
        log.warning(f"[Celery] No follow-up template for etapa '{etapa}'. Skipping.")
        return {"ok": False, "reason": f"no template for etapa: {etapa}"}

    nombre_display = nombre or "aspirante"
    programa_display = programa or "los programas Icesi"
    message = template.format(nombre=nombre_display, programa=programa_display)

    # Mark job as executed in Postgres
    try:
        from .db import get_engine
        from sqlalchemy import text as sql_text
        from sqlalchemy.orm import Session as DBSession
        from datetime import datetime as dt
        with DBSession(get_engine()) as db:
            db.execute(
                sql_text(
                    "UPDATE followup_jobs SET executed = true, executed_at = :now "
                    "WHERE id = ("
                    "  SELECT id FROM followup_jobs "
                    "  WHERE session_id = :sid AND etapa = :etapa AND executed = false "
                    "  ORDER BY created_at DESC LIMIT 1"
                    ")"
                ),
                {"now": dt.utcnow(), "sid": session_id, "etapa": etapa},
            )
            db.commit()
    except Exception as exc:
        log.warning(f"[Celery] Could not mark job as executed: {exc}")

    log.info(
        f"[Celery] Follow-up ready for session={session_id} etapa={etapa}. "
        f"Message: {message[:80]}… "
        "(WhatsApp send requires phone number — wire up tel_encrypted in session to enable)"
    )

    return {
        "ok": True,
        "session_id": session_id,
        "etapa": etapa,
        "message_preview": message[:100],
    }
