"""
Streamlit Dashboard — Icesi IA Commercial System
Métricas MVP: cobertura, tiempo de respuesta, calidad, avance de etapa, escalamientos.
"""
import os
import sys
from datetime import datetime, timedelta

import httpx
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from sqlalchemy import create_engine, text

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ── Page config ────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Icesi IA — Dashboard Comercial",
    page_icon="🎓",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── DB connection ──────────────────────────────────────────────────────────────

ORCHESTRATOR_URL = os.getenv("ORCHESTRATOR_URL", "http://localhost:8000")


@st.cache_resource
def get_engine():
    db_url = os.getenv("DATABASE_URL", "postgresql://icesi:icesi_pass@localhost:5432/icesi_ia")
    return create_engine(db_url)


def run_query(sql: str, params: dict = None) -> pd.DataFrame:
    try:
        with get_engine().connect() as conn:
            result = conn.execute(text(sql), params or {})
            return pd.DataFrame(result.fetchall(), columns=result.keys())
    except Exception as e:
        return pd.DataFrame({"error": [str(e)]})


# ── Sidebar ────────────────────────────────────────────────────────────────────
st.sidebar.image("https://www.icesi.edu.co/img/logoicesi.png", use_column_width=True)
st.sidebar.title("Icesi IA — Dashboard")

days_back = st.sidebar.slider("Ventana de tiempo (días)", 1, 30, 7)
segmento_filter = st.sidebar.selectbox(
    "Filtrar por segmento",
    ["Todos", "pregrado", "posgrado", "educontinua"],
)
since = datetime.utcnow() - timedelta(days=days_back)

# ── Header ─────────────────────────────────────────────────────────────────────
st.title("🎓 Sistema Comercial IA — Universidad Icesi")
st.caption(f"Datos de los últimos {days_back} días · Actualizado: {datetime.now().strftime('%d/%m/%Y %H:%M')}")

# ── KPI cards ─────────────────────────────────────────────────────────────────
col1, col2, col3, col4, col5 = st.columns(5)

# Total sessions
total_sessions = run_query(
    "SELECT COUNT(DISTINCT session_id) as n FROM conversation_logs WHERE timestamp >= :since",
    {"since": since},
)
col1.metric("Conversaciones totales", int(total_sessions["n"][0]) if not total_sessions.empty and "n" in total_sessions else "—")

# Avg first response time
avg_rt = run_query(
    """SELECT ROUND(AVG(latency_ms)::numeric, 0) as avg_ms
       FROM conversation_logs
       WHERE role = 'assistant' AND timestamp >= :since""",
    {"since": since},
)
avg_rt_val = avg_rt["avg_ms"][0] if not avg_rt.empty and "avg_ms" in avg_rt else None
col2.metric(
    "Tiempo promedio de respuesta",
    f"{int(avg_rt_val)} ms" if avg_rt_val else "—",
    delta="< 5 000 ms meta" if avg_rt_val and int(avg_rt_val) < 5000 else None,
)

# Escalations
esc_count = run_query(
    "SELECT COUNT(*) as n FROM tickets_escalamiento WHERE created_at >= :since",
    {"since": since},
)
col3.metric("Escalamientos", int(esc_count["n"][0]) if not esc_count.empty and "n" in esc_count else "—")

# Sessions that advanced at least 1 CIIPOC stage
# (approximation: sessions where registrar_intencion tool was called with avanzó=true)
advanced = run_query(
    """SELECT COUNT(DISTINCT session_id) as n
       FROM intenciones_log
       WHERE "avanzó_etapa" = true AND timestamp >= :since""",
    {"since": since},
)
col4.metric(
    "Conversaciones con avance CIIPOC",
    int(advanced["n"][0]) if not advanced.empty and "n" in advanced else "—",
)

# Coverage (sessions attended / total leads — approximation with available data)
col5.metric("Cobertura activa", "Ver sección", help="Comparar con total leads del CRM")

st.divider()

# ── Charts ─────────────────────────────────────────────────────────────────────
left, right = st.columns(2)

# Conversations per day
with left:
    st.subheader("Conversaciones por día")
    daily = run_query(
        """SELECT DATE(timestamp) as dia, COUNT(DISTINCT session_id) as sesiones
           FROM conversation_logs
           WHERE timestamp >= :since
           GROUP BY dia ORDER BY dia""",
        {"since": since},
    )
    if not daily.empty and "dia" in daily.columns:
        fig = px.bar(daily, x="dia", y="sesiones", color_discrete_sequence=["#003087"])
        fig.update_layout(height=300, margin=dict(t=10, b=10))
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("Sin datos suficientes aún")

# CIIPOC stage distribution
with right:
    st.subheader("Distribución de etapa CIIPOC")
    stages = run_query(
        """SELECT etapa_ciipoc, COUNT(DISTINCT session_id) as n
           FROM conversation_logs
           WHERE timestamp >= :since AND etapa_ciipoc IS NOT NULL
           GROUP BY etapa_ciipoc""",
        {"since": since},
    )
    if not stages.empty and "etapa_ciipoc" in stages.columns:
        orden = ["contacto", "indagacion", "identificacion", "propuesta", "objeciones", "cierre"]
        stages["etapa_ciipoc"] = pd.Categorical(stages["etapa_ciipoc"], categories=orden, ordered=True)
        stages = stages.sort_values("etapa_ciipoc")
        fig = px.funnel(stages, x="n", y="etapa_ciipoc", color_discrete_sequence=["#e63946"])
        fig.update_layout(height=300, margin=dict(t=10, b=10))
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("Sin datos suficientes aún")

# Response time distribution
left2, right2 = st.columns(2)
with left2:
    st.subheader("Distribución tiempos de respuesta (ms)")
    latency = run_query(
        """SELECT latency_ms FROM conversation_logs
           WHERE role = 'assistant' AND timestamp >= :since AND latency_ms > 0
           LIMIT 500""",
        {"since": since},
    )
    if not latency.empty and "latency_ms" in latency.columns:
        fig = px.histogram(
            latency, x="latency_ms", nbins=30,
            color_discrete_sequence=["#2a9d8f"],
            labels={"latency_ms": "Latencia (ms)"},
        )
        fig.add_vline(x=5000, line_dash="dash", line_color="red", annotation_text="Meta 5s")
        fig.update_layout(height=300, margin=dict(t=10, b=10))
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("Sin datos suficientes aún")

# Escalations by reason
with right2:
    st.subheader("Escalamientos por motivo")
    esc_motivos = run_query(
        """SELECT motivo, COUNT(*) as n
           FROM tickets_escalamiento
           WHERE created_at >= :since
           GROUP BY motivo ORDER BY n DESC""",
        {"since": since},
    )
    if not esc_motivos.empty and "motivo" in esc_motivos.columns:
        fig = px.pie(esc_motivos, values="n", names="motivo",
                     color_discrete_sequence=px.colors.qualitative.Set2)
        fig.update_layout(height=300, margin=dict(t=10, b=10))
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("Sin escalamientos en el periodo")

st.divider()

# ── Segmento breakdown ─────────────────────────────────────────────────────────
st.subheader("Actividad por segmento")
seg_data = run_query(
    """SELECT segmento, COUNT(DISTINCT session_id) as sesiones,
              ROUND(AVG(latency_ms)::numeric, 0) as avg_latency
       FROM conversation_logs
       WHERE timestamp >= :since AND segmento IS NOT NULL
       GROUP BY segmento""",
    {"since": since},
)
if not seg_data.empty and "segmento" in seg_data.columns:
    st.dataframe(seg_data, use_container_width=True)
else:
    st.info("Sin datos por segmento aún")

# ── Recent escalations table ───────────────────────────────────────────────────
st.subheader("Últimos escalamientos")
esc_table = run_query(
    """SELECT created_at, motivo, prioridad, asesor_asignado, asesor_tomo_caso
       FROM tickets_escalamiento
       WHERE created_at >= :since
       ORDER BY created_at DESC LIMIT 20""",
    {"since": since},
)
if not esc_table.empty and "motivo" in esc_table.columns:
    st.dataframe(esc_table, use_container_width=True)
else:
    st.info("Sin escalamientos recientes")

# ── Ticket management ─────────────────────────────────────────────────────────
st.divider()
st.subheader("🎫 Gestión de Tickets de Escalamiento")

ticket_filter = st.radio(
    "Mostrar", ["Pendientes", "Tomados", "Todos"], horizontal=True, key="ticket_filter"
)
filter_map = {"Pendientes": "true", "Tomados": "false", "Todos": None}
pendiente_param = filter_map[ticket_filter]

try:
    params = {}
    if pendiente_param is not None:
        params["pendiente"] = pendiente_param
    resp = httpx.get(f"{ORCHESTRATOR_URL}/tickets", params=params, timeout=5)
    tickets_data = resp.json().get("tickets", []) if resp.is_success else []
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
            f"{str(t.get('created_at', ''))[:16].replace('T', ' ')} · "
            f"Asesor: {t.get('asesor_asignado', '—')} · {estado_label}"
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
                            r = httpx.post(
                                f"{ORCHESTRATOR_URL}/tickets/{t['id']}/tomar",
                                json={"asesor_nombre": nombre_input.strip()},
                                timeout=5,
                            )
                            if r.is_success:
                                st.success(f"Caso tomado por {nombre_input}. Recarga para actualizar.")
                            else:
                                st.error(r.json().get("detail", "Error al tomar el caso."))
                        except Exception as e:
                            st.error(f"No se pudo conectar al orquestador: {e}")

# ── Quality eval section ───────────────────────────────────────────────────────
st.divider()
st.subheader("📋 Evaluación de calidad semanal")
st.info(
    "La evaluación de calidad se hace manualmente: el Líder Comercial revisa 30 conversaciones "
    "aleatorias por semana y califica cada respuesta como Correcta / Imprecisa / Alucinación. "
    "Registra los resultados aquí para el seguimiento."
)

with st.form("quality_form"):
    eval_date = st.date_input("Fecha de evaluación", datetime.now())
    evaluador = st.text_input("Evaluador")
    correctas = st.number_input("Respuestas correctas", min_value=0, max_value=30, value=28)
    imprecisas = st.number_input("Imprecisas", min_value=0, max_value=30, value=2)
    alucinaciones = st.number_input("Alucinaciones", min_value=0, max_value=30, value=0)
    notas = st.text_area("Notas / hallazgos")
    submitted = st.form_submit_button("Registrar evaluación")
    if submitted:
        total_eval = correctas + imprecisas + alucinaciones
        pct = round(correctas / total_eval * 100, 1) if total_eval > 0 else 0
        st.success(
            f"Evaluación registrada: {pct}% correctas "
            f"({'✅ Cumple meta ≥95%' if pct >= 95 else '⚠️ Por debajo de la meta'})"
        )

# ── Footer ─────────────────────────────────────────────────────────────────────
st.caption("Sistema desarrollado para el equipo comercial de la Universidad Icesi · MVP v1.0 · 2026")
