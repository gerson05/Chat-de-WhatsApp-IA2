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
    # HMAC with secret_key as salt — prevents rainbow table attacks on low-entropy phone numbers
    return hmac.new(
        settings.secret_key.encode(),
        phone.encode(),
        hashlib.sha256,
    ).hexdigest()


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


async def create_session(phone: str, crm_data: Optional[dict] = None) -> SessionState:
    id_usuario = hash_phone(phone)
    session = SessionState(id_usuario=id_usuario)

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
