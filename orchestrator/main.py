"""
FastAPI orchestrator — main entry point.
Handles:
  - GET  /webhook/whatsapp  → Meta verification challenge
  - POST /webhook/whatsapp  → Incoming messages
  - POST /chat              → Direct API (testing / dashboard)
  - GET  /health            → Health check
  - GET  /metrics           → Basic metrics snapshot
"""
import hmac
import logging
import time
import uuid
from contextlib import asynccontextmanager
from typing import Optional

import anthropic
import sentry_sdk
from fastapi import FastAPI, HTTPException, Request, Response, Security
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from .config import get_settings
from .conversation import run_conversation_turn
from .crm_adapter import get_crm
from .db import init_db, log_turn
from .nivel2 import process_after_turn
from .session_store import (
    check_rate_limit, create_session, hash_phone,
    load_session, save_session, compress_history,
)
from .whatsapp import parse_incoming_message, send_text_message, verify_signature

settings = get_settings()
log = logging.getLogger(__name__)

# Deduplication: circular buffer via dict preserves insertion order (Python 3.7+)
# Evicts oldest entries instead of clearing the whole set on overflow.
_seen_message_ids: dict[str, bool] = {}
_DEDUP_MAX = 10_000

_bearer = HTTPBearer(auto_error=False)

# Shared Anthropic client
_anthropic_client: Optional[anthropic.AsyncAnthropic] = None


def get_client() -> anthropic.AsyncAnthropic:
    global _anthropic_client
    if _anthropic_client is None:
        _anthropic_client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    return _anthropic_client


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    if settings.sentry_dsn:
        sentry_sdk.init(dsn=settings.sentry_dsn, traces_sample_rate=0.1)

    if settings.app_env != "development":
        try:
            init_db()
            log.info("[Startup] Database initialized")
        except Exception as exc:
            log.warning(f"[Startup] DB init skipped: {exc}")

    log.info(f"[Startup] Icesi IA Orchestrator — env={settings.app_env}")
    yield
    # Shutdown
    log.info("[Shutdown] Closing connections")


app = FastAPI(
    title="Icesi IA — Orquestador Comercial",
    version="1.0.0",
    lifespan=lifespan,
)

_CORS_ORIGINS = (
    ["*"] if settings.app_env == "development"
    else ["https://icesi.edu.co", "https://*.icesi.edu.co"]
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_CORS_ORIGINS,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)


# ── Health ─────────────────────────────────────────────────────────────────────

def _require_chat_key(credentials: HTTPAuthorizationCredentials = Security(_bearer)):
    """Validates Bearer token on /chat. Bypassed when CHAT_API_KEY is not set (dev mode)."""
    if not settings.chat_api_key:
        return  # dev mode
    if not credentials or not hmac.compare_digest(
        credentials.credentials, settings.chat_api_key
    ):
        raise HTTPException(status_code=401, detail="Unauthorized")


@app.get("/health")
async def health():
    return {"status": "ok"}


# ── WhatsApp webhook verification ─────────────────────────────────────────────

@app.get("/webhook/whatsapp")
async def wa_verify(
    hub_mode: Optional[str] = None,
    hub_verify_token: Optional[str] = None,
    hub_challenge: Optional[str] = None,
):
    if hub_mode == "subscribe" and hub_verify_token == settings.whatsapp_verify_token:
        return Response(content=hub_challenge, media_type="text/plain")
    raise HTTPException(status_code=403, detail="Verification failed")


# ── WhatsApp webhook — incoming messages ───────────────────────────────────────

@app.post("/webhook/whatsapp")
async def wa_incoming(request: Request):
    body_bytes = await request.body()
    sig = request.headers.get("X-Hub-Signature-256", "")

    if not verify_signature(body_bytes, sig):
        raise HTTPException(status_code=401, detail="Invalid signature")

    body = await request.json()
    msg = parse_incoming_message(body)
    if not msg:
        return {"ok": True}  # Not a text message — acknowledge silently

    # Idempotency — evict oldest entry when buffer full
    if msg["message_id"] in _seen_message_ids:
        return {"ok": True}
    if len(_seen_message_ids) >= _DEDUP_MAX:
        _seen_message_ids.pop(next(iter(_seen_message_ids)))
    _seen_message_ids[msg["message_id"]] = True

    phone = msg["from"]
    text = msg["text"]

    await _process_message(phone, text)
    return {"ok": True}


# ── Direct chat endpoint (testing) ────────────────────────────────────────────

class ChatRequest(BaseModel):
    phone: str
    message: str
    reset_session: bool = False


class ChatResponse(BaseModel):
    reply: str
    session_id: str
    etapa_ciipoc: str
    segmento: str
    escalado: bool
    tool_calls: list


@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest, _: None = Security(_require_chat_key)):
    if req.reset_session:
        from .session_store import get_redis
        r = await get_redis()
        await r.delete(f"session:{hash_phone(req.phone)}")

    reply, session, tool_calls = await _process_message(req.phone, req.message)
    return ChatResponse(
        reply=reply,
        session_id=session.id_usuario,
        etapa_ciipoc=session.etapa_ciipoc.value,
        segmento=session.segmento.value,
        escalado=session.escalado,
        tool_calls=tool_calls,
    )


# ── Core processing pipeline ───────────────────────────────────────────────────

async def _process_message(phone: str, user_text: str):
    id_usuario = hash_phone(phone)
    client = get_client()

    # Rate limit
    within_limit = await check_rate_limit(id_usuario)
    if not within_limit:
        await send_text_message(phone, (
            "Has enviado muchos mensajes hoy. "
            "Por favor intenta nuevamente mañana o llámanos directamente."
        ))
        return "rate_limited", None, []

    # Load or create session
    session = await load_session(id_usuario)
    if session is None:
        crm = get_crm()
        crm_data = await crm.get_lead(id_usuario)
        session = await create_session(phone, crm_data)

    # Compress history if needed
    if len(session.historial) > settings.history_window:
        session = await compress_history(session, client)

    # Max bot messages guard
    if session.total_bot_messages >= settings.max_messages_per_session and not session.escalado:
        from .tools import dispatch_tool
        result = dispatch_tool(
            "escalar_a_asesor",
            {
                "motivo": "sin_avance",
                "prioridad": "media",
                "resumen": {
                    "nombre_aspirante": session.nombre,
                    "programa_interes": session.programa_interes,
                    "segmento": session.segmento.value,
                    "etapa_ciipoc_actual": session.etapa_ciipoc.value,
                    "siguiente_accion_sugerida": "Continuar con asesor humano",
                },
            },
            session,
        )
        await send_text_message(phone, result.get("mensaje_para_aspirante", ""))
        await save_session(session)
        return result.get("mensaje_para_aspirante", ""), session, []

    # Record user turn
    session.add_turn("user", user_text)
    turn_id = len(session.historial)
    t0 = time.monotonic()

    # Run conversation
    reply, tool_calls = await run_conversation_turn(user_text, session, client)
    latency_ms = int((time.monotonic() - t0) * 1000)

    # Record assistant turn
    session.add_turn("assistant", reply)
    session.total_bot_messages += 1

    # Nivel 2 processing
    await process_after_turn(session, user_text, tool_calls)

    # Persist session
    await save_session(session)

    # Log to DB
    log_turn(
        session_id=session.id_usuario,
        tel_hash=id_usuario,
        turn_id=turn_id,
        role="assistant",
        text=reply,
        tool_calls=tool_calls,
        etapa=session.etapa_ciipoc.value,
        segmento=session.segmento.value,
        escalado=session.escalado,
        latency_ms=latency_ms,
    )

    # Send WhatsApp reply
    await send_text_message(phone, reply)

    return reply, session, tool_calls


# ── Metrics snapshot ───────────────────────────────────────────────────────────

@app.get("/metrics")
async def metrics():
    """Returns a quick snapshot. Real metrics come from the Streamlit dashboard."""
    from sqlalchemy import text as sql_text
    from .db import get_engine

    try:
        with get_engine().connect() as conn:
            total = conn.execute(
                sql_text("SELECT COUNT(DISTINCT session_id) FROM conversation_logs")
            ).scalar()
            escalated = conn.execute(
                sql_text("SELECT COUNT(*) FROM tickets_escalamiento")
            ).scalar()
            avg_latency = conn.execute(
                sql_text("SELECT AVG(latency_ms) FROM conversation_logs WHERE role='assistant'")
            ).scalar()
        return {
            "total_sessions": total,
            "total_escalations": escalated,
            "avg_latency_ms": round(avg_latency or 0, 1),
        }
    except Exception as exc:
        return {"error": str(exc)}
