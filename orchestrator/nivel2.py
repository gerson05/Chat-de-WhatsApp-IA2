"""
Nivel 2 — Business agent.
Processes the session after each turn and decides:
  - Whether to update CRM lead state
  - Whether to create a follow-up task
  - Whether to trigger a reminder job
  - Whether to notify the internal WhatsApp group (escalation)
"""
import json
import logging
from datetime import datetime, timedelta
from typing import Optional

import httpx

from sqlalchemy.orm import Session

from .config import get_settings
from .crm_adapter import get_crm
from .db import EscalamientoTicket, get_engine
from .models import SessionState, EstadoFunnel, EtapaCIIPOC

settings = get_settings()
log = logging.getLogger(__name__)

# ── WhatsApp notification ──────────────────────────────────────────────────────

_GROUP_MAP = {
    "pregrado": settings.internal_wa_group_pregrado,
    "posgrado": settings.internal_wa_group_posgrado,
    "educontinua": settings.internal_wa_group_educontinua,
    "indefinido": settings.internal_wa_group_jefe,
}


async def _notify_internal_group(segmento: str, ticket_text: str):
    """Send escalation ticket to internal WhatsApp group."""
    group_id = _GROUP_MAP.get(segmento, settings.internal_wa_group_jefe)
    if not group_id or not settings.whatsapp_phone_id or not settings.whatsapp_access_token:
        log.info("[Nivel2] WhatsApp interno no configurado — ticket solo en logs")
        log.info(ticket_text)
        return

    url = (
        f"https://graph.facebook.com/v20.0/{settings.whatsapp_phone_id}/messages"
    )
    payload = {
        "messaging_product": "whatsapp",
        "to": group_id,
        "type": "text",
        "text": {"body": ticket_text[:4096]},
    }
    headers = {"Authorization": f"Bearer {settings.whatsapp_access_token}"}
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(url, json=payload, headers=headers, timeout=10)
            if resp.status_code != 200:
                log.warning(f"[Nivel2] WA notify failed: {resp.text}")
        except Exception as exc:
            log.error(f"[Nivel2] WA notify error: {exc}")


# ── CRM sync ───────────────────────────────────────────────────────────────────

async def _sync_crm(session: SessionState, tool_calls_executed: list[dict]):
    crm = get_crm()
    if not session.id_lead_crm:
        return

    fields = {
        "etapa_ciipoc": session.etapa_ciipoc.value,
        "ultima_interaccion_ia": datetime.utcnow().isoformat() + "Z",
    }
    if session.segmento.value != "indefinido":
        fields["segmento"] = session.segmento.value
    if session.programa_interes:
        fields["programa_interes"] = session.programa_interes
    if session.barrera:
        fields["barrera_principal"] = session.barrera
    if session.necesidad_identificada:
        fields["necesidad_identificada"] = session.necesidad_identificada

    await crm.update_lead(session.id_lead_crm, fields)


# ── Escalation handling ────────────────────────────────────────────────────────

async def _handle_escalation(session: SessionState, escalar_result: dict):
    """Create CRM task, persist ticket to DB, and notify internal group."""
    crm = get_crm()

    task = {
        "tipo": "escalamiento_agente_ia",
        "lead_id": session.id_lead_crm,
        "prioridad": escalar_result.get("prioridad", "media"),
        "asesor_destinatario": escalar_result.get("asesor_asignado", ""),
        "titulo": (
            f"Escalamiento IA — "
            f"{session.nombre or 'Aspirante'} — "
            f"{session.programa_interes or 'Programa TBD'} — "
            f"Etapa {session.etapa_ciipoc.value}"
        ),
        "descripcion": escalar_result.get("ticket", ""),
        "vencimiento": (datetime.utcnow() + timedelta(hours=2)).isoformat() + "Z",
        "metadata": {
            "motivo_escalamiento": "escalamiento_ia",
            "etapa_ciipoc": session.etapa_ciipoc.value,
            "session_id": session.id_usuario,
        },
    }

    task_id = await crm.create_task(task)
    log.info(f"[Nivel2] Tarea CRM creada: {task_id}")

    # Persist ticket to DB
    try:
        with Session(get_engine()) as db:
            ticket_row = EscalamientoTicket(
                session_id=session.id_usuario,
                lead_id=session.id_lead_crm,
                motivo=escalar_result.get("motivo", "escalamiento_ia"),
                prioridad=escalar_result.get("prioridad", "media"),
                asesor_asignado=escalar_result.get("asesor_asignado"),
                ticket_text=escalar_result.get("ticket", ""),
            )
            db.add(ticket_row)
            db.commit()
            log.info(f"[Nivel2] Ticket {ticket_row.id} persistido en DB")
    except Exception as exc:
        log.warning(f"[Nivel2] No se pudo persistir ticket en DB: {exc}")

    ticket_text = escalar_result.get("ticket", "")
    if ticket_text:
        await _notify_internal_group(session.segmento.value, ticket_text)


# ── Follow-up scheduling ───────────────────────────────────────────────────────

async def _schedule_followup(session: SessionState):
    """
    Persist follow-up reminders to Postgres (primary — survives restarts) and
    enqueue in Celery (fast execution, best-effort).
    """
    delay_map = {
        EtapaCIIPOC.indagacion: 72 * 3600,
        EtapaCIIPOC.propuesta: 48 * 3600,
        EtapaCIIPOC.objeciones: 24 * 3600,
        EtapaCIIPOC.cierre: 24 * 3600,
    }
    delay = delay_map.get(session.etapa_ciipoc)
    if not delay:
        return

    fire_at = datetime.utcnow() + timedelta(seconds=delay)

    # 1. Persist to Postgres — survives any service restart
    celery_task_id = None
    try:
        from .celery_worker import send_followup_message
        result = send_followup_message.apply_async(
            kwargs={
                "session_id": session.id_usuario,
                "etapa": session.etapa_ciipoc.value,
                "nombre": session.nombre or "",
                "programa": session.programa_interes or "",
            },
            countdown=delay,
        )
        celery_task_id = result.id
        log.debug(f"[Nivel2] Follow-up enqueued in Celery: task_id={celery_task_id}")
    except Exception as exc:
        log.warning(f"[Nivel2] Celery enqueue failed (non-critical): {exc}")

    try:
        from .db import create_followup_job
        create_followup_job(
            session_id=session.id_usuario,
            etapa=session.etapa_ciipoc.value,
            nombre=session.nombre or "",
            programa=session.programa_interes or "",
            fire_at=fire_at,
            celery_task_id=celery_task_id,
        )
        log.debug(f"[Nivel2] Follow-up persisted to Postgres for {session.id_usuario} at {fire_at}")
    except Exception as exc:
        log.warning(f"[Nivel2] Postgres follow-up persist failed: {exc}")


# ── Funnel state machine ───────────────────────────────────────────────────────

FUNNEL_TRANSITIONS = {
    # (current_state, trigger_keyword) -> new_state
    (EstadoFunnel.lead, "ya me inscribí"): EstadoFunnel.inscrito,
    (EstadoFunnel.lead, "ya inscribí"): EstadoFunnel.inscrito,
}


def _try_funnel_transition(session: SessionState, user_message: str) -> Optional[EstadoFunnel]:
    msg_lower = user_message.lower()
    for (state, keyword), next_state in FUNNEL_TRANSITIONS.items():
        if session.estado_funnel_crm == state and keyword in msg_lower:
            return next_state
    return None


# ── Main entry point ───────────────────────────────────────────────────────────

async def process_after_turn(
    session: SessionState,
    user_message: str,
    tool_calls_executed: list[dict],
):
    """Called by orchestrator after every completed conversation turn."""

    # 1. Detect funnel transitions from user message
    new_funnel_state = _try_funnel_transition(session, user_message)
    if new_funnel_state:
        session.estado_funnel_crm = new_funnel_state
        log.info(f"[Nivel2] Funnel → {new_funnel_state.value} for {session.id_usuario}")

    # 2. Detect inactivity (handled at session load time — here we flag)
    # (Inactivity → inactivo is set by the follow-up worker, not here)

    # 3. Handle escalation if escalar_a_asesor was called
    escalar_results = [
        tc.get("result", {})
        for tc in tool_calls_executed
        if tc.get("name") == "escalar_a_asesor"
    ]
    for result in escalar_results:
        await _handle_escalation(session, result)

    # 4. Sync session data to CRM
    await _sync_crm(session, tool_calls_executed)

    # 5. Schedule follow-ups (only if not yet escalated)
    if not session.escalado:
        await _schedule_followup(session)
