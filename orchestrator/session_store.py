import fnmatch
import hashlib
import hmac
import json
import logging
import redis.asyncio as aioredis
from datetime import datetime, timedelta
from typing import Optional

from .config import get_settings
from .models import SessionState, TurnMessage

settings = get_settings()
log = logging.getLogger(__name__)


class _InMemoryRedis:
    """Fallback en memoria con el subconjunto de la API de Redis que usa el
    session store. Solo para desarrollo/pruebas sin Redis: NO persiste entre
    reinicios ni sirve para múltiples procesos."""

    def __init__(self):
        self._store: dict = {}

    async def ping(self):
        return True

    async def get(self, key):
        return self._store.get(key)

    async def setex(self, key, ttl, value):
        self._store[key] = value
        return True

    async def set(self, key, value):
        self._store[key] = value
        return True

    async def delete(self, *keys):
        for k in keys:
            self._store.pop(k, None)
        return True

    async def incr(self, key):
        value = int(self._store.get(key, 0)) + 1
        self._store[key] = str(value)
        return value

    async def expire(self, key, ttl):
        return True

    async def mget(self, *keys):
        return [self._store.get(k) for k in keys]

    async def scan_iter(self, match="*", count=None):
        for key in list(self._store.keys()):
            if fnmatch.fnmatch(key, match):
                yield key


_redis = None


async def get_redis():
    global _redis
    if _redis is None:
        try:
            client = await aioredis.from_url(settings.redis_url, decode_responses=True)
            await client.ping()
            _redis = client
        except Exception as exc:
            log.warning(
                f"[SessionStore] Redis no disponible ({exc}). "
                "Usando almacenamiento EN MEMORIA (solo desarrollo, no persiste)."
            )
            _redis = _InMemoryRedis()
    return _redis


def hash_phone(phone: str) -> str:
    # Uses phone_hash_secret when available (dedicated secret, Ley 1581 best practice).
    # Falls back to secret_key for backward compatibility.
    salt = (settings.phone_hash_secret or settings.secret_key).encode()
    return hmac.new(salt, phone.encode(), hashlib.sha256).hexdigest()


def _session_key(id_usuario: str) -> str:
    return f"session:{id_usuario}"


def _rate_key(id_usuario: str) -> str:
    return f"rate:{id_usuario}:{datetime.utcnow().strftime('%Y%m%d')}"


async def check_rate_limit(id_usuario: str) -> bool:
    """Returns True if the user is within the daily rate limit."""
    r = await get_redis()
    key = _rate_key(id_usuario)
    count = await r.incr(key)
    if count == 1:
        await r.expire(key, 86400)
    return count <= settings.max_messages_per_day


async def load_session(id_usuario: str) -> Optional[SessionState]:
    r = await get_redis()
    raw = await r.get(_session_key(id_usuario))
    if not raw:
        return None
    data = json.loads(raw)
    # Deserialize historial
    data["historial"] = [TurnMessage(**t) for t in data.get("historial", [])]
    return SessionState(**data)


async def save_session(session: SessionState):
    r = await get_redis()
    ttl = settings.session_ttl_days * 86400
    session.updated_at = datetime.utcnow()
    raw = session.model_dump_json()
    await r.setex(_session_key(session.id_usuario), ttl, raw)

    # Archive to Postgres for audit trail / Ley 1581 compliance (non-blocking).
    try:
        from .db import archive_session
        archive_session(
            session_json=raw,
            session_id=session.id_usuario,
            etapa=session.etapa_ciipoc.value,
            segmento=session.segmento.value,
            escalado=session.escalado,
            created_at=session.created_at,
            retention_days=settings.data_retention_days,
        )
    except Exception as exc:
        log.warning(f"[SessionStore] archive_session failed (non-critical): {exc}")


async def create_session(phone: str, crm_data: Optional[dict] = None) -> SessionState:
    id_usuario = hash_phone(phone)
    session = SessionState(id_usuario=id_usuario, prompt_variant=settings.prompt_variant_default)

    if crm_data:
        session.id_lead_crm = crm_data.get("lead_id")
        session.nombre = crm_data.get("nombre")
        seg = crm_data.get("segmento", "indefinido")
        session.segmento = seg
        session.programa_interes = crm_data.get("programa_interes")
        estado = crm_data.get("estado_funnel", "lead")
        session.estado_funnel_crm = estado

    await save_session(session)
    return session


async def register_phone_display(id_usuario: str, phone: str) -> None:
    """Stores the plain phone number for display in the testing console.
    Only called from the /chat endpoint (never from WhatsApp/Telegram)."""
    r = await get_redis()
    ttl = settings.session_ttl_days * 86400
    await r.setex(f"display:{id_usuario}", ttl, phone)


async def list_sessions(limit: int = 50) -> list[dict]:
    """Returns up to `limit` active sessions, sorted by last update descending."""
    r = await get_redis()
    keys = [k async for k in r.scan_iter("session:*", count=200)]
    if not keys:
        return []

    raws = await r.mget(*keys)
    parsed = []
    for raw in raws:
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except Exception:
            continue
        parsed.append(data)

    if not parsed:
        return []

    display_keys = [f"display:{d.get('id_usuario', '')}" for d in parsed]
    display_values = await r.mget(*display_keys)
    display_map = {
        d.get("id_usuario", ""): (v or d.get("id_usuario", "")[:8] + "…")
        for d, v in zip(parsed, display_values)
    }

    sessions = []
    for data in parsed:
        id_usuario = data.get("id_usuario", "")
        sessions.append({
            "phone": display_map.get(id_usuario, id_usuario[:8] + "…"),
            "session_id": id_usuario,
            "etapa_ciipoc": data.get("etapa_ciipoc", "contacto"),
            "segmento": data.get("segmento", "indefinido"),
            "escalado": data.get("escalado", False),
            "turn_count": len(data.get("historial", [])),
            "last_active_ts": data.get("updated_at") or data.get("created_at"),
        })

    sessions.sort(key=lambda s: s["last_active_ts"] or "", reverse=True)
    return sessions[:limit]


async def compress_history(session: SessionState, llm_client) -> SessionState:
    """Compress old turns into resumen_temprano using the cheap LLM model."""
    if len(session.historial) <= settings.history_window:
        return session

    old_turns = session.historial[: -settings.history_window]
    recent = session.historial[-settings.history_window :]

    turns_text = "\n".join(
        f"[{t.role}] {t.text}" for t in old_turns
    )
    msg = await llm_client.messages.create(
        model=settings.llm_model_cheap,
        max_tokens=300,
        messages=[
            {
                "role": "user",
                "content": (
                    "Resume en máximo 200 palabras los puntos clave de esta "
                    "conversación entre un aspirante y el asistente de Icesi. "
                    "Incluye: programa de interés, necesidad, barrera y etapa "
                    "CIIPOC alcanzada.\n\n" + turns_text
                ),
            }
        ],
    )
    session.resumen_temprano = msg.content[0].text if msg.content else ""
    session.historial = recent
    return session
