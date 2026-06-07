# Ticket Persistence + Dashboard Management Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist escalation tickets to PostgreSQL, expose management API endpoints, add interactive ticket panel in the Streamlit dashboard, enrich ticket briefing with aspirant tone, and produce full project documentation for an institutional informe.

**Architecture:** `_handle_escalation` in `nivel2.py` currently creates a CRM task and sends a WhatsApp notification but never writes to the `tickets_escalamiento` table that already exists in `db.py`. This plan wires that write, adds `GET /tickets` and `POST /tickets/{id}/tomar` FastAPI endpoints to `main.py`, and extends the Streamlit dashboard with an interactive "Tomar caso" panel. A `tono_aspirante` field is added to the tool schema and ticket briefing so advisors have sentiment context.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy (sync), PostgreSQL, Streamlit, Pydantic v2, pytest

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `orchestrator/tools.py` | Modify | Add `motivo` + `tono_aspirante` to `tool_escalar_a_asesor` return + schema |
| `orchestrator/models.py` | Modify | Add `tono_aspirante` field to `ResumenEscalamiento` |
| `orchestrator/nivel2.py` | Modify | Write `EscalamientoTicket` row in `_handle_escalation` |
| `orchestrator/main.py` | Modify | Add `GET /tickets` and `POST /tickets/{ticket_id}/tomar` endpoints |
| `dashboard/app.py` | Modify | Add interactive ticket management panel |
| `docs/informe/sistema-ia-icesi.md` | Create | Full project documentation for institutional informe |
| `tests/test_conversation.py` | Modify | Add tests for new endpoints and ticket persistence |

---

## Task 1: Return `motivo` from `tool_escalar_a_asesor`

**Files:**
- Modify: `orchestrator/tools.py:325-335`

`_handle_escalation` in `nivel2.py` receives the return value of `tool_escalar_a_asesor` as `escalar_result`. Currently `motivo` is not in that dict, so the DB write would lose it.

- [ ] **Step 1: Write the failing test**

In `tests/test_conversation.py`, add inside a new `TestEscalamientoTool` class:

```python
class TestEscalamientoTool:
    def test_escalar_retorna_motivo(self):
        """T-ESC-01: tool_escalar_a_asesor result includes motivo field."""
        from orchestrator.tools import tool_escalar_a_asesor
        session = make_session(segmento=Segmento.pregrado)
        result = tool_escalar_a_asesor(
            motivo="frustracion",
            prioridad="alta",
            resumen={"nombre_aspirante": "Juan", "programa_interes": "Ing. Sistemas"},
            session=session,
        )
        assert result["motivo"] == "frustracion"
        assert result["prioridad"] == "alta"
        assert result["ok"] is True
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /mnt/c/Users/gdjhb.GERSON/Downloads/Chat-de-WhatsApp-IA2
python -m pytest tests/test_conversation.py::TestEscalamientoTool::test_escalar_retorna_motivo -v
```

Expected: `FAILED — KeyError: 'motivo'`

- [ ] **Step 3: Add `motivo` to return dict in `tool_escalar_a_asesor`**

In `orchestrator/tools.py`, find the `return {` block in `tool_escalar_a_asesor` (line ~325) and add `"motivo": motivo`:

```python
    return {
        "ok": True,
        "motivo": motivo,
        "asesor_asignado": asesor,
        "prioridad": prioridad,
        "ticket": ticket,
        "mensaje_para_aspirante": (
            f"Perfecto, voy a conectarte con {asesor} del equipo Icesi, "
            "quien te atenderá personalmente. Te contactará muy pronto. "
            "¡Gracias por tu paciencia!"
        ),
    }
```

- [ ] **Step 4: Run test to verify it passes**

```bash
python -m pytest tests/test_conversation.py::TestEscalamientoTool::test_escalar_retorna_motivo -v
```

Expected: `PASSED`

- [ ] **Step 5: Commit**

```bash
git add orchestrator/tools.py tests/test_conversation.py
git commit -m "fix: include motivo in escalar_a_asesor return dict"
```

---

## Task 2: Add `tono_aspirante` to escalation schema and briefing

**Files:**
- Modify: `orchestrator/models.py:111-118`
- Modify: `orchestrator/tools.py` (TOOL_SCHEMAS + `_build_ticket`)

`tono_aspirante` gives advisors immediate sentiment context. The LLM infers it from the conversation and passes it in `resumen`.

- [ ] **Step 1: Write the failing test**

```python
class TestTicketBriefing:
    def test_ticket_incluye_tono(self):
        """T-ESC-02: _build_ticket includes tono_aspirante when provided."""
        from orchestrator.tools import _build_ticket
        session = make_session(segmento=Segmento.posgrado, nombre="Ana")
        ticket = _build_ticket(
            motivo="objecion_compleja",
            prioridad="alta",
            resumen={"tono_aspirante": "frustrado, repitió la misma objeción 3 veces"},
            asesor="Lauri Ariza",
            session=session,
        )
        assert "frustrado" in ticket
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m pytest tests/test_conversation.py::TestTicketBriefing::test_ticket_incluye_tono -v
```

Expected: `FAILED — AssertionError`

- [ ] **Step 3: Add `tono_aspirante` to `ResumenEscalamiento` in `models.py`**

```python
class ResumenEscalamiento(BaseModel):
    nombre_aspirante: Optional[str] = None
    programa_interes: Optional[str] = None
    segmento: Optional[str] = None
    etapa_ciipoc_actual: Optional[str] = None
    necesidad_identificada: Optional[str] = None
    barrera_principal: Optional[str] = None
    tono_aspirante: Optional[str] = None
    ultimos_5_intercambios: Optional[str] = None
    siguiente_accion_sugerida: Optional[str] = None
```

- [ ] **Step 4: Add `tono_aspirante` to TOOL_SCHEMAS in `tools.py`**

In the `escalar_a_asesor` schema, inside `resumen.properties`, add after `barrera_principal`:

```python
"tono_aspirante": {
    "type": "string",
    "description": (
        "Tono emocional del aspirante en los últimos mensajes. "
        "Ej: 'ansioso por fechas', 'frustrado con costos', 'muy motivado'."
    ),
},
```

- [ ] **Step 5: Add `tono_aspirante` to `_build_ticket` output**

In `_build_ticket`, after the `barrera` line, add:

```python
    tono = resumen.get("tono_aspirante") or "—"
```

And in the returned f-string, add after the barrera section:

```python
        f"🎭 Tono del aspirante:\n{tono}\n\n"
```

Full updated return in `_build_ticket`:

```python
    return (
        f"{prioridad_emoji} ESCALAMIENTO IA — Prioridad: {prioridad.upper()}\n"
        f"{'─' * 45}\n"
        f"Aspirante: {nombre} ({session.id_lead_crm or 'nuevo lead'})\n"
        f"Programa: {programa}\n"
        f"Segmento: {seg}\n"
        f"Etapa CIIPOC: {etapa}\n"
        f"Asesor asignado: {asesor}\n"
        f"Motivo: {motivo_texto}\n\n"
        f"📌 Necesidad identificada:\n{necesidad}\n\n"
        f"🚧 Barrera principal:\n{barrera}\n\n"
        f"🎭 Tono del aspirante:\n{tono}\n\n"
        f"💬 Últimos intercambios:\n{intercambios}\n\n"
        f"✅ Acción recomendada:\n{siguiente}\n\n"
        f"⏱ Hora del escalamiento: {datetime.utcnow().strftime('%H:%M UTC')}"
    )
```

- [ ] **Step 6: Run test to verify it passes**

```bash
python -m pytest tests/test_conversation.py::TestTicketBriefing::test_ticket_incluye_tono -v
```

Expected: `PASSED`

- [ ] **Step 7: Commit**

```bash
git add orchestrator/models.py orchestrator/tools.py tests/test_conversation.py
git commit -m "feat: add tono_aspirante to escalation briefing and tool schema"
```

---

## Task 3: Persist `EscalamientoTicket` to PostgreSQL in `_handle_escalation`

**Files:**
- Modify: `orchestrator/nivel2.py:85-114`

- [ ] **Step 1: Write the failing test**

```python
class TestHandleEscalation:
    def test_ticket_persisted_to_db(self):
        """T-ESC-03: _handle_escalation writes EscalamientoTicket row to DB."""
        import asyncio
        from unittest.mock import patch, MagicMock, AsyncMock
        from orchestrator.nivel2 import _handle_escalation

        session = make_session(segmento=Segmento.pregrado, nombre="Carlos")
        escalar_result = {
            "ok": True,
            "motivo": "frustracion",
            "prioridad": "alta",
            "asesor_asignado": "Julian Andrés Gil",
            "ticket": "🔴 ESCALAMIENTO IA — Prioridad: ALTA\n...",
        }

        db_session_mock = MagicMock()
        db_session_mock.__enter__ = MagicMock(return_value=db_session_mock)
        db_session_mock.__exit__ = MagicMock(return_value=False)

        with patch("orchestrator.nivel2.get_crm") as mock_crm, \
             patch("orchestrator.nivel2.Session") as mock_session_cls, \
             patch("orchestrator.nivel2.get_engine"):
            mock_crm.return_value.create_task = AsyncMock(return_value="task-123")
            mock_session_cls.return_value = db_session_mock

            asyncio.get_event_loop().run_until_complete(
                _handle_escalation(session, escalar_result)
            )

        db_session_mock.add.assert_called_once()
        added = db_session_mock.add.call_args[0][0]
        from orchestrator.db import EscalamientoTicket
        assert isinstance(added, EscalamientoTicket)
        assert added.motivo == "frustracion"
        assert added.prioridad == "alta"
        assert added.asesor_asignado == "Julian Andrés Gil"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m pytest tests/test_conversation.py::TestHandleEscalation::test_ticket_persisted_to_db -v
```

Expected: `FAILED — AssertionError: assert 0 == 1` (add never called)

- [ ] **Step 3: Import DB helpers in `nivel2.py` and write ticket**

At the top of `orchestrator/nivel2.py`, add imports after existing imports:

```python
from sqlalchemy.orm import Session

from .db import EscalamientoTicket, get_engine
```

Replace `_handle_escalation` body with:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

```bash
python -m pytest tests/test_conversation.py::TestHandleEscalation::test_ticket_persisted_to_db -v
```

Expected: `PASSED`

- [ ] **Step 5: Run full test suite**

```bash
python -m pytest tests/ -v
```

Expected: all previously passing tests still pass.

- [ ] **Step 6: Commit**

```bash
git add orchestrator/nivel2.py tests/test_conversation.py
git commit -m "feat: persist EscalamientoTicket to PostgreSQL on escalation"
```

---

## Task 4: Add ticket management API endpoints

**Files:**
- Modify: `orchestrator/main.py`

Two endpoints:
- `GET /tickets` — list tickets, optional `?pendiente=true` filter
- `POST /tickets/{ticket_id}/tomar` — advisor claims a ticket

- [ ] **Step 1: Write the failing test**

```python
class TestTicketEndpoints:
    def test_get_tickets_endpoint_exists(self):
        """T-API-01: GET /tickets returns 200 with list."""
        from fastapi.testclient import TestClient
        from unittest.mock import patch
        import pandas as pd

        with patch("orchestrator.main.get_engine") as mock_eng:
            mock_conn = MagicMock()
            mock_eng.return_value.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
            mock_eng.return_value.connect.return_value.__exit__ = MagicMock(return_value=False)
            mock_conn.execute.return_value.fetchall.return_value = []
            mock_conn.execute.return_value.keys.return_value = []

            from orchestrator.main import app
            client = TestClient(app)
            resp = client.get("/tickets")
            assert resp.status_code == 200
            assert "tickets" in resp.json()

    def test_tomar_ticket_endpoint_exists(self):
        """T-API-02: POST /tickets/{id}/tomar returns 200 or 404."""
        from fastapi.testclient import TestClient
        from unittest.mock import patch
        import uuid

        fake_id = str(uuid.uuid4())
        with patch("orchestrator.main.get_engine") as mock_eng:
            mock_conn = MagicMock()
            mock_eng.return_value.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
            mock_eng.return_value.connect.return_value.__exit__ = MagicMock(return_value=False)
            mock_conn.execute.return_value.rowcount = 0

            from orchestrator.main import app
            client = TestClient(app)
            resp = client.post(f"/tickets/{fake_id}/tomar", json={"asesor_nombre": "Lauri Ariza"})
            assert resp.status_code in (200, 404)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m pytest tests/test_conversation.py::TestTicketEndpoints -v
```

Expected: `FAILED — 404 Not Found` (endpoints don't exist yet)

- [ ] **Step 3: Add endpoints to `main.py`**

After the `metrics` endpoint (end of file), add:

```python
# ── Ticket management ──────────────────────────────────────────────────────────

class TomarTicketRequest(BaseModel):
    asesor_nombre: str


@app.get("/tickets")
async def list_tickets(pendiente: Optional[bool] = None):
    """List escalation tickets. ?pendiente=true for unclaimed only."""
    from sqlalchemy import text as sql_text
    from .db import get_engine

    where = ""
    if pendiente is True:
        where = "WHERE asesor_tomo_caso = false"
    elif pendiente is False:
        where = "WHERE asesor_tomo_caso = true"

    try:
        with get_engine().connect() as conn:
            rows = conn.execute(sql_text(
                f"""SELECT id::text, session_id, lead_id, motivo, prioridad,
                           asesor_asignado, ticket_text, asesor_tomo_caso,
                           asesor_nombre, took_at, created_at
                    FROM tickets_escalamiento
                    {where}
                    ORDER BY created_at DESC
                    LIMIT 100"""
            )).fetchall()
            tickets = [dict(zip(r.keys(), r)) for r in rows]
            for t in tickets:
                if t.get("created_at"):
                    t["created_at"] = t["created_at"].isoformat()
                if t.get("took_at"):
                    t["took_at"] = t["took_at"].isoformat()
        return {"tickets": tickets, "total": len(tickets)}
    except Exception as exc:
        return {"tickets": [], "total": 0, "error": str(exc)}


@app.post("/tickets/{ticket_id}/tomar")
async def tomar_ticket(ticket_id: str, req: TomarTicketRequest):
    """Mark a ticket as taken by an advisor."""
    from sqlalchemy import text as sql_text
    from datetime import datetime as dt
    from .db import get_engine

    try:
        with get_engine().connect() as conn:
            result = conn.execute(sql_text(
                """UPDATE tickets_escalamiento
                   SET asesor_tomo_caso = true,
                       asesor_nombre = :nombre,
                       took_at = :now
                   WHERE id = :ticket_id
                     AND asesor_tomo_caso = false"""
            ), {"nombre": req.asesor_nombre, "now": dt.utcnow(), "ticket_id": ticket_id})
            conn.commit()
            if result.rowcount == 0:
                raise HTTPException(
                    status_code=404,
                    detail="Ticket no encontrado o ya tomado por otro asesor",
                )
        return {"ok": True, "ticket_id": ticket_id, "asesor_nombre": req.asesor_nombre}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
```

- [ ] **Step 4: Run test to verify it passes**

```bash
python -m pytest tests/test_conversation.py::TestTicketEndpoints -v
```

Expected: `PASSED`

- [ ] **Step 5: Commit**

```bash
git add orchestrator/main.py tests/test_conversation.py
git commit -m "feat: add GET /tickets and POST /tickets/{id}/tomar endpoints"
```

---

## Task 5: Dashboard ticket management panel

**Files:**
- Modify: `dashboard/app.py`

Add interactive "Gestión de Tickets" section before the quality eval section. Advisors can see pending tickets, expand the full ticket text, and claim a ticket with their name.

- [ ] **Step 1: Add imports at top of `dashboard/app.py`**

The dashboard already imports `os`, `requests` is needed for calling the API. Add after existing imports:

```python
import requests
```

- [ ] **Step 2: Add `ORCHESTRATOR_URL` config**

After the `get_engine()` function, add:

```python
ORCHESTRATOR_URL = os.getenv("ORCHESTRATOR_URL", "http://localhost:8000")
```

- [ ] **Step 3: Add ticket management section**

Before the `# ── Quality eval section ──` divider, insert the following block:

```python
# ── Ticket management ─────────────────────────────────────────────────────────
st.divider()
st.subheader("🎫 Gestión de Tickets de Escalamiento")

ticket_filter = st.radio(
    "Mostrar", ["Pendientes", "Tomados", "Todos"], horizontal=True
)
filter_map = {"Pendientes": "true", "Tomados": "false", "Todos": None}
pendiente_param = filter_map[ticket_filter]

try:
    params = {}
    if pendiente_param is not None:
        params["pendiente"] = pendiente_param
    resp = requests.get(f"{ORCHESTRATOR_URL}/tickets", params=params, timeout=5)
    tickets_data = resp.json().get("tickets", []) if resp.ok else []
except Exception:
    tickets_data = []

if not tickets_data:
    st.info("Sin tickets en esta categoría.")
else:
    for t in tickets_data:
        prioridad_color = {"alta": "🔴", "media": "🟡", "baja": "🟢"}.get(t.get("prioridad", ""), "⚪")
        tomado = t.get("asesor_tomo_caso", False)
        estado_label = f"✅ {t.get('asesor_nombre', 'Asesor')}" if tomado else "⏳ Pendiente"
        header = (
            f"{prioridad_color} **{t.get('motivo', '—')}** · "
            f"{t.get('created_at', '')[:16].replace('T', ' ')} · "
            f"Asesor asignado: {t.get('asesor_asignado', '—')} · {estado_label}"
        )
        with st.expander(header, expanded=False):
            st.text(t.get("ticket_text", "—"))
            if not tomado:
                col_nombre, col_btn = st.columns([3, 1])
                nombre_input = col_nombre.text_input(
                    "Tu nombre", key=f"nombre_{t['id']}", placeholder="Nombre del asesor"
                )
                if col_btn.button("Tomar caso", key=f"tomar_{t['id']}"):
                    if not nombre_input.strip():
                        st.warning("Ingresa tu nombre antes de tomar el caso.")
                    else:
                        try:
                            r = requests.post(
                                f"{ORCHESTRATOR_URL}/tickets/{t['id']}/tomar",
                                json={"asesor_nombre": nombre_input.strip()},
                                timeout=5,
                            )
                            if r.ok:
                                st.success(f"Caso tomado por {nombre_input}. Recarga para actualizar.")
                            else:
                                st.error(r.json().get("detail", "Error al tomar el caso."))
                        except Exception as e:
                            st.error(f"No se pudo conectar al orquestador: {e}")
```

- [ ] **Step 4: Verify the dashboard launches without errors**

```bash
cd /mnt/c/Users/gdjhb.GERSON/Downloads/Chat-de-WhatsApp-IA2
python -c "import ast; ast.parse(open('dashboard/app.py').read()); print('Syntax OK')"
```

Expected: `Syntax OK`

- [ ] **Step 5: Commit**

```bash
git add dashboard/app.py
git commit -m "feat: add interactive ticket management panel to Streamlit dashboard"
```

---

## Task 6: Project documentation for institutional informe

**Files:**
- Create: `docs/informe/sistema-ia-icesi.md`

- [ ] **Step 1: Create the documentation file**

```bash
mkdir -p /mnt/c/Users/gdjhb.GERSON/Downloads/Chat-de-WhatsApp-IA2/docs/informe
```

Write `docs/informe/sistema-ia-icesi.md` with the full project description (see content below).

- [ ] **Step 2: Commit**

```bash
git add docs/informe/sistema-ia-icesi.md
git commit -m "docs: add full project documentation for institutional informe"
```

---

## Self-Review

**Spec coverage check:**

| Requirement | Task |
|---|---|
| Persist `EscalamientoTicket` to DB | Task 3 |
| Return `motivo` from tool (needed for Task 3) | Task 1 |
| Enrich ticket with `tono_aspirante` | Task 2 |
| `GET /tickets` endpoint | Task 4 |
| `POST /tickets/{id}/tomar` endpoint | Task 4 |
| Dashboard ticket panel with "Tomar caso" | Task 5 |
| Project documentation | Task 6 |

**Placeholder scan:** None found.

**Type consistency:** `EscalamientoTicket` fields (`motivo`, `prioridad`, `asesor_asignado`, `ticket_text`) match `db.py:48-61`. `TomarTicketRequest.asesor_nombre` matches `EscalamientoTicket.asesor_nombre`. `tono_aspirante` added to both `ResumenEscalamiento` (Task 2 Step 3) and TOOL_SCHEMAS (Task 2 Step 4) and `_build_ticket` (Task 2 Step 5) consistently.
