# Dashboard Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rediseñar `console.html` en tres archivos separados (HTML + CSS + JS) con panel de sesiones activas, Lucide Icons, y un nuevo endpoint `GET /sessions` que lee de Redis.

**Architecture:** FastAPI sirve la shell HTML via `FileResponse`; CSS y JS se sirven via `StaticFiles` montado en `/static`. El endpoint `GET /sessions` escanea Redis con `SCAN session:*` y devuelve metadatos. El número de teléfono se almacena en una key aparte `display:{id_usuario}` escrita por `/chat` para que el panel lo muestre.

**Tech Stack:** FastAPI · redis.asyncio · Vanilla JS ES2020 · Lucide Icons CDN · CSS custom properties

---

## File Map

| Acción | Archivo |
|---|---|
| Modificar | `orchestrator/main.py` |
| Modificar | `orchestrator/session_store.py` |
| Crear | `orchestrator/static/css/console.css` |
| Crear | `orchestrator/static/js/console.js` |
| Reescribir | `orchestrator/static/console.html` |
| Crear | `tests/test_sessions_endpoint.py` |

---

## Task 1: StaticFiles mount en main.py

**Files:**
- Modify: `orchestrator/main.py` (líneas ~130-138)

- [ ] **Agregar import StaticFiles**

En el bloque de imports de `main.py`, añadir:
```python
from fastapi.staticfiles import StaticFiles
```

- [ ] **Montar /static después de crear `app`**

Después de `app.add_middleware(...)` (~línea 109), añadir:
```python
_STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")
```

- [ ] **Crear directorios CSS y JS**

```bash
mkdir -p orchestrator/static/css orchestrator/static/js
```

- [ ] **Verificar que FastAPI arranca sin error**

```bash
uvicorn orchestrator.main:app --reload --port 8000
```

Esperado: `Application startup complete.` sin excepción.

- [ ] **Commit**

```bash
git add orchestrator/main.py
git commit -m "feat: mount StaticFiles at /static"
```

---

## Task 2: session_store.py — soporte para listar sesiones

**Files:**
- Modify: `orchestrator/session_store.py`
- Test: `tests/test_sessions_endpoint.py`

- [ ] **Agregar `scan_iter` y `mget` a `_InMemoryRedis`**

En la clase `_InMemoryRedis` (después del método `expire`):
```python
async def mget(self, *keys):
    return [self._store.get(k) for k in keys]

async def scan_iter(self, match="*", count=None):
    import fnmatch
    for key in list(self._store.keys()):
        if fnmatch.fnmatch(key, match):
            yield key
```

- [ ] **Agregar `register_phone_display` al final del archivo**

```python
async def register_phone_display(id_usuario: str, phone: str) -> None:
    """Stores the plain phone number for display in the testing console.
    Only called from the /chat endpoint (never from WhatsApp/Telegram)."""
    r = await get_redis()
    ttl = settings.session_ttl_days * 86400
    await r.setex(f"display:{id_usuario}", ttl, phone)
```

- [ ] **Agregar `list_sessions` al final del archivo**

```python
async def list_sessions(limit: int = 50) -> list[dict]:
    """Returns up to `limit` active sessions, sorted by last update descending."""
    r = await get_redis()
    keys = [k async for k in r.scan_iter("session:*", count=200)]
    if not keys:
        return []

    raws = await r.mget(*keys)
    sessions = []
    for raw in raws:
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except Exception:
            continue
        id_usuario = data.get("id_usuario", "")
        display_phone = await r.get(f"display:{id_usuario}") or id_usuario[:8] + "…"
        updated_at = data.get("updated_at") or data.get("created_at")
        sessions.append({
            "phone": display_phone,
            "session_id": id_usuario,
            "etapa_ciipoc": data.get("etapa_ciipoc", "contacto"),
            "segmento": data.get("segmento", "indefinido"),
            "escalado": data.get("escalado", False),
            "turn_count": len(data.get("historial", [])),
            "last_active_ts": updated_at,
        })

    sessions.sort(key=lambda s: s["last_active_ts"] or "", reverse=True)
    return sessions[:limit]
```

- [ ] **Escribir test para `list_sessions`**

Crear `tests/test_sessions_endpoint.py`:
```python
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
```

- [ ] **Correr tests (deben fallar si aún no están implementadas)**

```bash
pytest tests/test_sessions_endpoint.py -v
```

Esperado si `list_sessions` ya existe: PASS. Si no: ImportError.

- [ ] **Commit**

```bash
git add orchestrator/session_store.py tests/test_sessions_endpoint.py
git commit -m "feat: add list_sessions and register_phone_display to session_store"
```

---

## Task 3: GET /sessions endpoint en main.py

**Files:**
- Modify: `orchestrator/main.py`

- [ ] **Agregar import de las nuevas funciones**

En el bloque de imports de session_store (línea ~42):
```python
from .session_store import (
    check_rate_limit, create_session, hash_phone,
    list_sessions, load_session, register_phone_display,
    save_session, compress_history,
)
```

- [ ] **Agregar endpoint GET /sessions**

Después del endpoint `GET /` (~línea 138), añadir:
```python
@app.get("/sessions")
async def sessions_list(_: None = Security(_require_chat_key)):
    """Lists active sessions for the testing console panel."""
    return await list_sessions()
```

- [ ] **Llamar `register_phone_display` en el endpoint `/chat`**

En el endpoint `POST /chat` (línea ~200), después de `if req.reset_session:` block y antes de `reply, session, tool_calls = await _process_message(...)`:
```python
    await register_phone_display(hash_phone(req.phone), req.phone)
```

El bloque completo queda:
```python
@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest, _: None = Security(_require_chat_key)):
    if req.reset_session:
        from .session_store import get_redis
        r = await get_redis()
        await r.delete(f"session:{hash_phone(req.phone)}")

    await register_phone_display(hash_phone(req.phone), req.phone)
    reply, session, tool_calls = await _process_message(req.phone, req.message, NOOP)
    ...
```

- [ ] **Verificar endpoint**

```bash
uvicorn orchestrator.main:app --reload --port 8000
curl http://localhost:8000/sessions
```

Esperado: `[]` (si no hay sesiones en Redis) o lista de sesiones.

- [ ] **Correr tests**

```bash
pytest tests/test_sessions_endpoint.py -v
```

Esperado: 4 tests PASS.

- [ ] **Commit**

```bash
git add orchestrator/main.py
git commit -m "feat: add GET /sessions endpoint and register phone display on /chat"
```

---

## Task 4: console.css

**Files:**
- Create: `orchestrator/static/css/console.css`

- [ ] **Crear el archivo CSS completo**

```css
/* ── Variables ─────────────────────────────────────────────────── */
:root {
  --navy: #003087;
  --navy-2: #0a4bb5;
  --red: #e63946;
  --bg: #f0f4fa;
  --card: #ffffff;
  --muted: #6b7280;
  --border: #e8eef8;
  --border-light: #f0f4fa;
  --ok: #2a9d8f;
  --text: #1f2937;
  --text-light: #9ca3af;
}

/* ── Reset ─────────────────────────────────────────────────────── */
*, *::before, *::after { box-sizing: border-box; }
html, body { height: 100%; margin: 0; }
body {
  font-family: -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  background: var(--bg);
  color: var(--text);
  display: flex;
  flex-direction: column;
  height: 100vh;
  overflow: hidden;
}

/* ── Header ────────────────────────────────────────────────────── */
.c-header {
  background: linear-gradient(135deg, var(--navy) 0%, var(--navy-2) 100%);
  padding: 0 20px;
  height: 52px;
  display: flex;
  align-items: center;
  gap: 12px;
  flex-shrink: 0;
  box-shadow: 0 2px 8px rgba(0, 48, 135, 0.3);
  z-index: 10;
}
.c-logo {
  font-size: 15px;
  font-weight: 800;
  color: #fff;
  letter-spacing: -0.4px;
}
.c-pill {
  background: rgba(255, 255, 255, 0.18);
  color: rgba(255, 255, 255, 0.9);
  border-radius: 99px;
  padding: 3px 10px;
  font-size: 11px;
  font-weight: 500;
}
.c-spacer { flex: 1; }
.c-icon-btn {
  width: 32px;
  height: 32px;
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.12);
  border: none;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  transition: background 0.15s;
}
.c-icon-btn:hover { background: rgba(255, 255, 255, 0.22); }
.c-icon-btn svg { width: 16px; height: 16px; }
.c-btn {
  background: var(--red);
  color: #fff;
  border: none;
  border-radius: 8px;
  padding: 0 14px;
  height: 32px;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 6px;
  box-shadow: 0 2px 6px rgba(230, 57, 70, 0.4);
  transition: opacity 0.15s;
}
.c-btn:hover { opacity: 0.9; }
.c-btn svg { width: 14px; height: 14px; }

/* ── Settings bar ──────────────────────────────────────────────── */
#settings-bar {
  display: none;
  background: rgba(0, 0, 0, 0.05);
  padding: 8px 20px;
  gap: 14px;
  align-items: center;
  flex-wrap: wrap;
  border-bottom: 1px solid var(--border);
  flex-shrink: 0;
}
#settings-bar.show { display: flex; }
#settings-bar label { font-size: 12px; color: var(--text); }
#settings-bar input {
  border: 1.5px solid var(--border);
  border-radius: 7px;
  padding: 5px 9px;
  font-size: 12px;
  width: 220px;
  outline: none;
}
#settings-bar input:focus { border-color: var(--navy); }
#settings-bar .hint { font-size: 11px; color: var(--muted); }

/* ── Main layout ───────────────────────────────────────────────── */
.c-body {
  display: flex;
  flex: 1;
  min-height: 0;
}

/* ── Sessions Panel (left) ─────────────────────────────────────── */
.sessions-panel {
  width: 220px;
  flex-shrink: 0;
  background: var(--card);
  border-right: 1px solid var(--border);
  display: flex;
  flex-direction: column;
}
.sessions-header {
  padding: 14px 14px 10px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  border-bottom: 1px solid var(--border-light);
}
.sessions-title {
  font-size: 10px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: var(--text-light);
}
.sessions-actions { display: flex; gap: 4px; }
.sp-icon-btn {
  width: 26px;
  height: 26px;
  border-radius: 6px;
  border: none;
  background: transparent;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--text-light);
  transition: all 0.15s;
}
.sp-icon-btn:hover { background: var(--border-light); color: var(--navy); }
.sp-icon-btn svg { width: 14px; height: 14px; }
.sp-icon-btn.spinning svg { animation: spin 0.8s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }

.sessions-new-phone {
  padding: 10px 12px;
  border-bottom: 1px solid var(--border-light);
  display: flex;
  gap: 6px;
}
.sessions-new-phone input {
  flex: 1;
  border: 1.5px solid var(--border);
  border-radius: 7px;
  padding: 6px 9px;
  font-size: 12px;
  color: var(--text);
  background: var(--bg);
  outline: none;
  transition: border-color 0.15s;
}
.sessions-new-phone input:focus { border-color: var(--navy); background: #fff; }
.sessions-new-phone button {
  width: 30px;
  height: 30px;
  border-radius: 7px;
  border: none;
  background: var(--navy);
  color: #fff;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  transition: opacity 0.15s;
}
.sessions-new-phone button:hover { opacity: 0.85; }
.sessions-new-phone button svg { width: 14px; height: 14px; }

.sessions-list { flex: 1; overflow-y: auto; }
.sessions-empty {
  padding: 20px 14px;
  font-size: 12px;
  color: var(--muted);
  font-style: italic;
  text-align: center;
}

.session-item {
  padding: 10px 14px;
  border-bottom: 1px solid var(--border-light);
  cursor: pointer;
  transition: background 0.12s;
  position: relative;
  border-left: 3px solid transparent;
}
.session-item:hover { background: var(--bg); }
.session-item.active {
  background: #eff6ff;
  border-left-color: var(--navy);
  padding-left: 11px;
}
.si-phone { font-size: 12.5px; font-weight: 600; color: var(--text); }
.si-meta { font-size: 11px; color: var(--text-light); margin-top: 2px; }
.si-badges { display: flex; gap: 4px; margin-top: 5px; flex-wrap: wrap; }
.si-badge {
  font-size: 10px;
  font-weight: 600;
  border-radius: 99px;
  padding: 1px 7px;
}
.si-badge.etapa { background: #eff6ff; color: var(--navy); }
.si-badge.escalado { background: #fee2e2; color: var(--red); }
.si-badge.segmento { background: #f0fdf4; color: #166534; }

/* ── Chat Panel (center) ───────────────────────────────────────── */
.chat-panel {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
  background: var(--bg);
}
.chat-log {
  flex: 1;
  overflow-y: auto;
  padding: 20px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.bubble {
  max-width: 72%;
  padding: 10px 14px;
  border-radius: 14px;
  line-height: 1.5;
  font-size: 13.5px;
  word-wrap: break-word;
  white-space: pre-wrap;
}
.bubble.user {
  align-self: flex-end;
  background: var(--navy);
  color: #fff;
  border-bottom-right-radius: 4px;
  box-shadow: 0 2px 8px rgba(0, 48, 135, 0.25);
}
.bubble.bot {
  align-self: flex-start;
  background: var(--card);
  color: var(--text);
  border: 1px solid var(--border);
  border-bottom-left-radius: 4px;
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.06);
}
.bubble.sys {
  align-self: center;
  background: #fff9ec;
  color: #92400e;
  border: 1px solid #fde68a;
  font-size: 12px;
  border-radius: 8px;
  max-width: 88%;
}
.bubble.err {
  align-self: center;
  background: #fef2f2;
  color: #991b1b;
  border: 1px solid #fecaca;
  font-size: 12px;
  border-radius: 8px;
  max-width: 88%;
}
.bubble-meta {
  font-size: 10px;
  color: var(--text-light);
  margin-top: 4px;
}

.typing-indicator {
  align-self: flex-start;
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 10px 14px;
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 14px;
  border-bottom-left-radius: 4px;
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.06);
}
.typing-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--text-light);
  animation: blink 1.2s infinite;
}
.typing-dot:nth-child(2) { animation-delay: 0.2s; }
.typing-dot:nth-child(3) { animation-delay: 0.4s; }
@keyframes blink {
  0%, 80%, 100% { opacity: 0.3; }
  40% { opacity: 1; }
}

.chips-row {
  padding: 8px 16px;
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  background: var(--card);
  border-top: 1px solid var(--border);
  flex-shrink: 0;
}
.chip {
  background: #eff6ff;
  color: var(--navy);
  border: 1px solid #bfdbfe;
  border-radius: 99px;
  padding: 5px 12px;
  font-size: 12px;
  cursor: pointer;
  transition: all 0.15s;
  white-space: nowrap;
}
.chip:hover { background: #dbeafe; border-color: #93c5fd; }

.composer {
  border-top: 1px solid var(--border);
  background: var(--card);
  padding: 12px 16px;
  display: flex;
  gap: 10px;
  align-items: flex-end;
  flex-shrink: 0;
}
.composer textarea {
  flex: 1;
  resize: none;
  border: 1.5px solid var(--border);
  border-radius: 10px;
  padding: 10px 13px;
  font: inherit;
  font-size: 13.5px;
  min-height: 42px;
  max-height: 120px;
  background: var(--bg);
  color: var(--text);
  outline: none;
  transition: border-color 0.15s, background 0.15s;
  line-height: 1.5;
}
.composer textarea:focus { border-color: var(--navy); background: #fff; }
.composer-send {
  background: var(--navy);
  color: #fff;
  border: none;
  border-radius: 10px;
  width: 42px;
  height: 42px;
  cursor: pointer;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: 0 2px 8px rgba(0, 48, 135, 0.3);
  transition: opacity 0.15s;
}
.composer-send:hover { opacity: 0.9; }
.composer-send:disabled { opacity: 0.45; cursor: not-allowed; }
.composer-send svg { width: 18px; height: 18px; }

/* ── Sidebar Panel (right) ─────────────────────────────────────── */
.sidebar-panel {
  width: 260px;
  flex-shrink: 0;
  background: var(--card);
  border-left: 1px solid var(--border);
  overflow-y: auto;
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.sb-section {
  display: flex;
  flex-direction: column;
  gap: 0;
}
.sb-section-title {
  font-size: 10px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: var(--text-light);
  margin-bottom: 10px;
  display: flex;
  align-items: center;
  gap: 6px;
}
.sb-section-title svg { width: 13px; height: 13px; }

.sb-field {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 13px;
  padding: 7px 0;
  border-bottom: 1px solid var(--border-light);
}
.sb-field:last-child { border-bottom: none; }
.sb-field-label { color: var(--muted); }
.sb-field-value { color: var(--text); font-weight: 600; }

.badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 3px 9px;
  border-radius: 99px;
  font-size: 11px;
  font-weight: 600;
}
.badge.si { background: #fee2e2; color: var(--red); }
.badge.no { background: #f3f4f6; color: var(--muted); }
.badge svg { width: 10px; height: 10px; }

.sid-text {
  font-size: 10.5px;
  color: var(--muted);
  font-family: "SF Mono", "Fira Code", ui-monospace, monospace;
  word-break: break-all;
  margin-top: 4px;
}

/* Latency */
.latency-val {
  font-size: 24px;
  font-weight: 800;
  color: var(--navy);
  line-height: 1;
}
.latency-unit { font-size: 11px; color: var(--text-light); margin-top: 3px; }

/* CIIPOC Stepper */
.stepper {
  display: flex;
  flex-direction: column;
  position: relative;
}
.stepper::before {
  content: '';
  position: absolute;
  left: 9px;
  top: 10px;
  bottom: 10px;
  width: 2px;
  background: var(--border);
  z-index: 0;
}
.step {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 5px 0;
  position: relative;
  z-index: 1;
}
.step-dot {
  width: 20px;
  height: 20px;
  border-radius: 50%;
  flex-shrink: 0;
  border: 2px solid var(--border);
  background: var(--card);
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.2s;
}
.step-dot svg { width: 11px; height: 11px; }
.step.done .step-dot { background: var(--ok); border-color: var(--ok); }
.step.current .step-dot {
  background: var(--navy);
  border-color: var(--navy);
  box-shadow: 0 0 0 3px rgba(0, 48, 135, 0.15);
}
.step-label { font-size: 12.5px; color: var(--text-light); }
.step.done .step-label { color: #4b5563; }
.step.current .step-label { color: var(--navy); font-weight: 700; }

/* Tools */
.tool-item {
  border: 1px solid var(--border);
  border-radius: 8px;
  overflow: hidden;
  margin-bottom: 6px;
}
.tool-item:last-child { margin-bottom: 0; }
.tool-header {
  padding: 8px 11px;
  background: var(--bg);
  display: flex;
  align-items: center;
  gap: 7px;
  cursor: pointer;
  font-size: 12px;
  font-weight: 600;
  color: var(--navy);
  user-select: none;
  list-style: none;
}
.tool-header svg { width: 13px; height: 13px; color: var(--navy); }
.tool-ms {
  margin-left: auto;
  font-size: 10px;
  font-weight: 400;
  color: var(--text-light);
}
.tool-body {
  font-size: 10.5px;
  background: #0f172a;
  color: #93c5fd;
  padding: 8px 10px;
  overflow-x: auto;
  font-family: "SF Mono", "Fira Code", ui-monospace, monospace;
  line-height: 1.5;
  max-height: 200px;
}
.tools-empty {
  font-size: 12px;
  color: var(--muted);
  font-style: italic;
}
```

- [ ] **Verificar que el archivo existe**

```bash
ls orchestrator/static/css/console.css
```

- [ ] **Commit**

```bash
git add orchestrator/static/css/console.css
git commit -m "feat: add console.css with Clean Light design"
```

---

## Task 5: console.js

**Files:**
- Create: `orchestrator/static/js/console.js`

- [ ] **Crear el archivo JS completo**

```javascript
"use strict";

const CIIPOC = ["contacto", "indagacion", "identificacion", "propuesta", "objeciones", "cierre"];
const CIIPOC_LABELS = { contacto: "Contacto", indagacion: "Indagación", identificacion: "Identificación", propuesta: "Propuesta", objeciones: "Objeciones", cierre: "Cierre" };

const $ = id => document.getElementById(id);

// ── Settings (localStorage) ──────────────────────────────────────

function loadSettings() {
  $("phone").value = localStorage.getItem("icesi_phone") || "+573001234567";
  $("base-url").value = localStorage.getItem("icesi_base") || window.location.origin;
  $("api-key").value = localStorage.getItem("icesi_apikey") || "";
}

function saveSettings() {
  localStorage.setItem("icesi_phone", $("phone").value);
  localStorage.setItem("icesi_base", $("base-url").value);
  localStorage.setItem("icesi_apikey", $("api-key").value);
}

// ── Sessions panel ───────────────────────────────────────────────

let _refreshTimer = null;

async function fetchSessions() {
  const btn = $("refresh-btn");
  if (btn) btn.classList.add("spinning");
  try {
    const base = ($("base-url").value || window.location.origin).replace(/\/$/, "");
    const headers = {};
    if ($("api-key").value) headers["Authorization"] = "Bearer " + $("api-key").value;
    const resp = await fetch(base + "/sessions", { headers });
    if (!resp.ok) return;
    const sessions = await resp.json();
    renderSessions(sessions);
  } catch (_) {
    // silently ignore — sessions panel is non-critical
  } finally {
    if (btn) btn.classList.remove("spinning");
  }
}

function renderSessions(sessions) {
  const list = $("sessions-list");
  const activePhone = $("phone").value;

  if (!sessions || sessions.length === 0) {
    list.innerHTML = '<div class="sessions-empty">Sin sesiones activas.</div>';
    return;
  }

  list.innerHTML = sessions.map(s => {
    const isActive = s.phone === activePhone;
    const timeAgo = _timeAgo(s.last_active_ts);
    const turns = s.turn_count > 0 ? `· ${s.turn_count} turnos` : "";
    const badges = [
      `<span class="si-badge etapa">${CIIPOC_LABELS[s.etapa_ciipoc] || s.etapa_ciipoc}</span>`,
      s.escalado ? `<span class="si-badge escalado">Escalado</span>` : "",
      s.segmento && s.segmento !== "indefinido" ? `<span class="si-badge segmento">${s.segmento}</span>` : "",
    ].filter(Boolean).join("");

    return `<div class="session-item${isActive ? " active" : ""}" data-phone="${_esc(s.phone)}" onclick="loadSessionPhone('${_esc(s.phone)}')">
      <div class="si-phone">${_esc(s.phone)}</div>
      <div class="si-meta">${timeAgo} ${turns}</div>
      <div class="si-badges">${badges}</div>
    </div>`;
  }).join("");
}

function loadSessionPhone(phone) {
  $("phone").value = phone;
  saveSettings();
  // Highlight active session
  document.querySelectorAll(".session-item").forEach(el => {
    el.classList.toggle("active", el.dataset.phone === phone);
  });
}

function _timeAgo(ts) {
  if (!ts) return "—";
  const date = new Date(ts);
  const diff = Math.floor((Date.now() - date.getTime()) / 1000);
  if (diff < 60) return "Hace un momento";
  if (diff < 3600) return `Hace ${Math.floor(diff / 60)} min`;
  if (diff < 86400) return `Hace ${Math.floor(diff / 3600)}h`;
  return `Hace ${Math.floor(diff / 86400)} días`;
}

function _esc(str) {
  return String(str).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

// ── Chat ─────────────────────────────────────────────────────────

const log = $("chat-log");

function addBubble(text, cls, meta) {
  const div = document.createElement("div");
  div.className = "bubble " + cls;
  div.textContent = text;
  if (meta) {
    const m = document.createElement("div");
    m.className = "bubble-meta";
    m.textContent = meta;
    div.appendChild(m);
  }
  log.appendChild(div);
  log.scrollTop = log.scrollHeight;
  return div;
}

function renderStepper(stage) {
  const stepper = $("stepper");
  const idx = CIIPOC.indexOf(stage);
  stepper.innerHTML = CIIPOC.map((s, i) => {
    const cls = idx === -1 ? "" : (i < idx ? "done" : i === idx ? "current" : "");
    const dotContent = cls === "done"
      ? `<svg data-lucide="check" stroke="white" fill="none" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"></svg>`
      : cls === "current"
      ? `<svg data-lucide="circle" stroke="white" fill="white"></svg>`
      : "";
    return `<div class="step ${cls}">
      <div class="step-dot">${dotContent}</div>
      <span class="step-label">${CIIPOC_LABELS[s]}</span>
    </div>`;
  }).join("");
  lucide.createIcons();
}

function renderTools(toolCalls) {
  const box = $("tools-panel");
  if (!toolCalls || toolCalls.length === 0) {
    box.innerHTML = '<div class="tools-empty">Sin tools en este turno.</div>';
    return;
  }
  box.innerHTML = toolCalls.map(tc => `
    <details class="tool-item">
      <summary class="tool-header">
        <svg data-lucide="wrench" stroke="currentColor" fill="none" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"></svg>
        ${_esc(tc.name)}
        <span class="tool-ms">${tc.latency_ms != null ? tc.latency_ms + " ms" : ""}</span>
      </summary>
      <div class="tool-body">input: ${JSON.stringify(tc.input, null, 2)}\n\nresult: ${JSON.stringify(tc.result, null, 2)}</div>
    </details>`).join("");
  lucide.createIcons();
}

function setState(data) {
  $("segmento").textContent = data.segmento || "—";
  $("session-id").textContent = (data.session_id || "—").slice(0, 16) + "…";

  const escaladoBadge = $("escalado");
  escaladoBadge.className = "badge " + (data.escalado ? "si" : "no");
  escaladoBadge.innerHTML = data.escalado
    ? `<svg data-lucide="alert-circle" stroke="currentColor" fill="none" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"></svg> Sí`
    : `No`;

  $("latency-val").textContent = data._latency_ms != null ? data._latency_ms.toLocaleString() : "—";
  $("latency-unit").textContent = data._latency_ms != null
    ? `ms · último turno${data.tool_calls?.length ? " · " + data.tool_calls.length + " tool(s)" : ""}`
    : "";

  renderStepper(data.etapa_ciipoc);
  renderTools(data.tool_calls);
  lucide.createIcons();
}

// ── Send ─────────────────────────────────────────────────────────

let busy = false;

async function send(text, reset = false) {
  if (busy) return;
  const message = text ?? $("chat-input").value.trim();
  if (!message && !reset) return;
  busy = true;
  $("send-btn").disabled = true;

  if (message) addBubble(message, "user");
  $("chat-input").value = "";
  autoResize($("chat-input"));

  const typing = document.createElement("div");
  typing.className = "typing-indicator";
  typing.innerHTML = '<div class="typing-dot"></div><div class="typing-dot"></div><div class="typing-dot"></div>';
  log.appendChild(typing);
  log.scrollTop = log.scrollHeight;

  const base = ($("base-url").value || window.location.origin).replace(/\/$/, "");
  const headers = { "Content-Type": "application/json" };
  if ($("api-key").value) headers["Authorization"] = "Bearer " + $("api-key").value;

  try {
    const t0 = performance.now();
    const resp = await fetch(base + "/chat", {
      method: "POST",
      headers,
      body: JSON.stringify({ phone: $("phone").value, message: message || "Hola", reset_session: reset }),
    });
    const ms = Math.round(performance.now() - t0);
    typing.remove();

    if (!resp.ok) {
      const detail = await resp.text();
      addBubble(`Error ${resp.status}: ${detail}`, "err");
      return;
    }

    const data = await resp.json();
    data._latency_ms = ms;
    addBubble(data.reply, "bot", `${CIIPOC_LABELS[data.etapa_ciipoc] || data.etapa_ciipoc} · ${data.segmento} · ${ms} ms${data.tool_calls?.length ? " · " + data.tool_calls.length + " tool(s)" : ""}`);
    setState(data);
    // Refresh sessions to reflect updated state
    fetchSessions();
  } catch (e) {
    typing.remove();
    addBubble("No se pudo contactar el servidor: " + e.message, "err");
  } finally {
    busy = false;
    $("send-btn").disabled = false;
    $("chat-input").focus();
  }
}

// ── Auto-resize textarea ─────────────────────────────────────────

function autoResize(el) {
  el.style.height = "auto";
  el.style.height = Math.min(el.scrollHeight, 120) + "px";
}

// ── Reset session ─────────────────────────────────────────────────

async function resetSession() {
  log.innerHTML = "";
  addBubble("Sesión reiniciada para " + $("phone").value, "sys");
  renderStepper("contacto");
  renderTools([]);
  $("segmento").textContent = "—";
  $("latency-val").textContent = "—";
  $("latency-unit").textContent = "";
  const escaladoBadge = $("escalado");
  escaladoBadge.className = "badge no";
  escaladoBadge.innerHTML = "No";
  lucide.createIcons();
  await send("Hola", true);
}

// ── Init ──────────────────────────────────────────────────────────

function init() {
  loadSettings();
  renderStepper("contacto");
  renderTools([]);
  addBubble("Bienvenido a la consola de pruebas del agente comercial Icesi. Escribe un mensaje o usa una sugerencia para iniciar la conversación.", "sys");
  lucide.createIcons();

  // Sessions
  fetchSessions();
  _refreshTimer = setInterval(fetchSessions, 30000);

  // Event listeners
  $("phone").addEventListener("change", saveSettings);
  $("base-url").addEventListener("change", saveSettings);
  $("api-key").addEventListener("change", saveSettings);

  $("settings-btn").addEventListener("click", () => $("settings-bar").classList.toggle("show"));

  $("reset-btn").addEventListener("click", resetSession);

  $("refresh-btn").addEventListener("click", fetchSessions);

  $("load-phone-btn").addEventListener("click", () => {
    loadSessionPhone($("phone").value);
  });

  $("send-btn").addEventListener("click", () => send());

  $("chat-input").addEventListener("keydown", e => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); }
  });
  $("chat-input").addEventListener("input", () => autoResize($("chat-input")));

  $("chips-row").addEventListener("click", e => {
    if (e.target.classList.contains("chip")) {
      $("chat-input").value = e.target.textContent;
      $("chat-input").focus();
      autoResize($("chat-input"));
    }
  });

  $("chat-input").focus();
}

init();
```

- [ ] **Commit**

```bash
git add orchestrator/static/js/console.js
git commit -m "feat: add console.js with sessions panel and improved chat logic"
```

---

## Task 6: Reescribir console.html como shell

**Files:**
- Rewrite: `orchestrator/static/console.html`

- [ ] **Reemplazar console.html completo**

```html
<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>Icesi IA — Consola</title>
  <link rel="stylesheet" href="/static/css/console.css"/>
  <script src="https://unpkg.com/lucide@latest/dist/umd/lucide.min.js"></script>
</head>
<body>

  <!-- Header -->
  <header class="c-header">
    <span class="c-logo">Icesi IA</span>
    <span class="c-pill">Consola</span>
    <div class="c-spacer"></div>
    <button class="c-icon-btn" id="settings-btn" title="Ajustes">
      <svg data-lucide="settings" stroke="currentColor" fill="none" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"></svg>
    </button>
    <button class="c-btn" id="reset-btn">
      <svg data-lucide="rotate-ccw" stroke="currentColor" fill="none" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"></svg>
      Reiniciar sesión
    </button>
  </header>

  <!-- Settings bar (hidden by default) -->
  <div id="settings-bar">
    <label for="base-url">URL del servidor</label>
    <input id="base-url" placeholder="http://localhost:8000"/>
    <label for="api-key">API key</label>
    <input id="api-key" type="password" placeholder="CHAT_API_KEY (opcional)"/>
    <span class="hint">Guardados en localStorage.</span>
  </div>

  <!-- Body -->
  <div class="c-body">

    <!-- Left: Sessions panel -->
    <aside class="sessions-panel">
      <div class="sessions-header">
        <span class="sessions-title">Sesiones</span>
        <div class="sessions-actions">
          <button class="sp-icon-btn" id="refresh-btn" title="Actualizar sesiones">
            <svg data-lucide="refresh-cw" stroke="currentColor" fill="none" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"></svg>
          </button>
        </div>
      </div>
      <div class="sessions-new-phone">
        <input id="phone" placeholder="+573001234567" title="Identificador del aspirante"/>
        <button id="load-phone-btn" title="Cargar sesión">
          <svg data-lucide="arrow-right" stroke="currentColor" fill="none" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"></svg>
        </button>
      </div>
      <div class="sessions-list" id="sessions-list">
        <div class="sessions-empty">Cargando sesiones…</div>
      </div>
    </aside>

    <!-- Center: Chat -->
    <section class="chat-panel">
      <div class="chat-log" id="chat-log"></div>
      <div class="chips-row" id="chips-row">
        <span class="chip">Hola, me interesa la Maestría en Mercadeo</span>
        <span class="chip">¿Cuánto cuesta el MBA?</span>
        <span class="chip">Quiero hablar con un asesor</span>
        <span class="chip">Estoy explorando pregrado en Sistemas</span>
      </div>
      <div class="composer">
        <textarea id="chat-input" rows="1" placeholder="Escribe un mensaje como si fueras el aspirante… (Enter envía, Shift+Enter nueva línea)"></textarea>
        <button class="composer-send" id="send-btn">
          <svg data-lucide="send" stroke="currentColor" fill="none" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"></svg>
        </button>
      </div>
    </section>

    <!-- Right: Sidebar -->
    <aside class="sidebar-panel">

      <div class="sb-section">
        <div class="sb-section-title">
          <svg data-lucide="user" stroke="currentColor" fill="none" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"></svg>
          Estado de sesión
        </div>
        <div class="sb-field">
          <span class="sb-field-label">Segmento</span>
          <span class="sb-field-value" id="segmento">—</span>
        </div>
        <div class="sb-field">
          <span class="sb-field-label">Escalado</span>
          <span class="badge no" id="escalado">No</span>
        </div>
        <div class="sb-field" style="border:none; padding-bottom:0">
          <span class="sb-field-label">Session ID</span>
        </div>
        <div class="sid-text" id="session-id">—</div>
      </div>

      <div class="sb-section">
        <div class="sb-section-title">
          <svg data-lucide="zap" stroke="currentColor" fill="none" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"></svg>
          Latencia
        </div>
        <div class="latency-val" id="latency-val">—</div>
        <div class="latency-unit" id="latency-unit"></div>
      </div>

      <div class="sb-section">
        <div class="sb-section-title">
          <svg data-lucide="git-commit" stroke="currentColor" fill="none" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"></svg>
          Etapa CIIPOC
        </div>
        <div class="stepper" id="stepper"></div>
      </div>

      <div class="sb-section">
        <div class="sb-section-title">
          <svg data-lucide="wrench" stroke="currentColor" fill="none" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"></svg>
          Tools del último turno
        </div>
        <div id="tools-panel"></div>
      </div>

    </aside>
  </div>

  <script src="/static/js/console.js"></script>
</body>
</html>
```

- [ ] **Abrir http://localhost:8000/ en el navegador**

Verificar:
- Panel izquierdo muestra "Cargando sesiones…" luego lista o "Sin sesiones activas."
- Stepper CIIPOC visible en sidebar derecha
- Iconos Lucide renderizan (no cuadrados vacíos)
- Enviar un mensaje → burbuja aparece, respuesta llega, latencia se muestra
- Botón Reiniciar sesión funciona
- Chips llenan el textarea al hacer clic

- [ ] **Commit**

```bash
git add orchestrator/static/console.html
git commit -m "feat: rewrite console.html as clean shell with CSS/JS separation"
```

---

## Task 7: Verificación final

- [ ] **Correr todos los tests**

```bash
pytest tests/ -v
```

Esperado: todos PASS (incluyendo los 4 de `test_sessions_endpoint.py`).

- [ ] **Smoke test manual completo**

1. Abrir `http://localhost:8000/`
2. Enviar "Hola, me interesa la Maestría en Mercadeo"
3. Verificar que la sesión aparece en el panel izquierdo al refrescar
4. Click en "Actualizar" (icono refresh) → sesión aparece
5. Reiniciar sesión → log se limpia, agente responde "Hola"
6. Abrir Ajustes → panel de settings aparece
7. Verificar que no hay emojis en ningún componente
8. Verificar iconos Lucide en: header, sidebar titles, stepper, send button

- [ ] **Commit final de limpieza si necesario**

```bash
git add -p
git commit -m "fix: post-review cleanups"
```
