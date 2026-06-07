import pytest
from orchestrator.session_store import (
    _InMemoryRedis, register_phone_display, list_sessions, get_redis, save_session
)
from orchestrator.models import SessionState
import orchestrator.session_store as ss


@pytest.fixture(autouse=True)
def reset_redis(monkeypatch):
    """Reset the global Redis client to a fresh in-memory instance per test."""
    mem = _InMemoryRedis()
    monkeypatch.setattr(ss, "_redis", mem)
    return mem


@pytest.mark.asyncio
async def test_list_sessions_empty():
    result = await list_sessions()
    assert result == []


@pytest.mark.asyncio
async def test_list_sessions_returns_session():
    session = SessionState(id_usuario="abc123")
    await save_session(session)
    await register_phone_display("abc123", "+573001234567")

    result = await list_sessions()
    assert len(result) == 1
    assert result[0]["phone"] == "+573001234567"
    assert result[0]["session_id"] == "abc123"
    assert result[0]["etapa_ciipoc"] == "contacto"
    assert result[0]["escalado"] is False


@pytest.mark.asyncio
async def test_list_sessions_no_display_phone_falls_back():
    session = SessionState(id_usuario="xyz999")
    await save_session(session)

    result = await list_sessions()
    assert len(result) == 1
    assert result[0]["phone"].startswith("xyz999"[:8])


@pytest.mark.asyncio
async def test_register_phone_display_stores_value():
    await register_phone_display("hash01", "+573009876543")
    r = await get_redis()
    stored = await r.get("display:hash01")
    assert stored == "+573009876543"


@pytest.mark.asyncio
async def test_list_sessions_sorted_by_last_active():
    from datetime import datetime, timedelta
    now = datetime.utcnow()

    session_old = SessionState(id_usuario="old_session")
    session_old.updated_at = now - timedelta(hours=2)
    await save_session(session_old)

    session_new = SessionState(id_usuario="new_session")
    session_new.updated_at = now
    await save_session(session_new)

    result = await list_sessions()
    assert len(result) == 2
    assert result[0]["session_id"] == "new_session"
    assert result[1]["session_id"] == "old_session"
