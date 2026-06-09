"""
Streamlit Dashboard — Icesi IA Commercial System
Métricas MVP + Consola de Chats integrada.
"""
import os
import sys
from datetime import datetime, timedelta

import httpx
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
import streamlit.components.v1 as components
from sqlalchemy import create_engine, text

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ── Page config ────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Icesi IA — Dashboard Comercial",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Custom CSS ─────────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');

:root {
    --navy: #003087;
    --navy-2: #0a4bb5;
    --red: #e63946;
    --bg: #f0f4fa;
    --card: #ffffff;
    --muted: #6b7280;
    --border: #e8eef8;
    --ok: #2a9d8f;
    --text: #1f2937;
    --text-light: #9ca3af;
}

html, body, [class*="css"] { font-family: 'Inter', sans-serif !important; }

/* Ocultar el Streamlit header/footer para look más limpio */
#MainMenu, footer, header { visibility: hidden; }
.block-container { padding-top: 1.5rem !important; }

/* ── Sidebar ─── */
section[data-testid="stSidebar"] {
    background: linear-gradient(180deg, #001f5c 0%, #003087 100%) !important;
    border-right: none;
}
section[data-testid="stSidebar"] * { color: #e8f0ff !important; }
section[data-testid="stSidebar"] .stSlider > div > div > div > div {
    background: #e63946 !important;
}
section[data-testid="stSidebar"] .stSelectbox > div > div {
    background: rgba(255,255,255,0.1) !important;
    border: 1px solid rgba(255,255,255,0.2) !important;
    color: white !important;
}
section[data-testid="stSidebar"] label { color: rgba(255,255,255,0.75) !important; }

/* ── Header ─── */
.dashboard-header {
    background: linear-gradient(135deg, #003087 0%, #0a4bb5 100%);
    border-radius: 16px;
    padding: 22px 28px;
    margin-bottom: 20px;
    display: flex;
    align-items: center;
    gap: 16px;
    box-shadow: 0 8px 32px rgba(0,48,135,0.2);
}
.header-icon {
    width: 48px; height: 48px;
    border-radius: 12px;
    background: rgba(255,255,255,0.15);
    display: flex; align-items: center; justify-content: center;
    flex-shrink: 0;
}
.dashboard-title {
    font-size: 22px;
    font-weight: 800;
    color: white;
    letter-spacing: -0.5px;
    margin: 0;
}
.dashboard-subtitle {
    font-size: 12px;
    color: rgba(255,255,255,0.65);
    margin: 3px 0 0 0;
}
.header-pill {
    background: rgba(255,255,255,0.18);
    color: white;
    border-radius: 99px;
    padding: 4px 14px;
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 0.05em;
    text-transform: uppercase;
    margin-left: auto;
    border: 1px solid rgba(255,255,255,0.2);
}

/* ── KPI cards ─── */
[data-testid="metric-container"] {
    background: white;
    border: 1px solid #e8eef8;
    border-radius: 14px;
    padding: 18px 20px !important;
    box-shadow: 0 2px 12px rgba(0,48,135,0.06);
    transition: transform 0.2s, box-shadow 0.2s;
}
[data-testid="metric-container"]:hover {
    transform: translateY(-2px);
    box-shadow: 0 8px 24px rgba(0,48,135,0.12);
}
[data-testid="metric-container"] [data-testid="stMetricLabel"] {
    font-size: 11px !important;
    font-weight: 700 !important;
    text-transform: uppercase !important;
    letter-spacing: 0.06em !important;
    color: #6b7280 !important;
}
[data-testid="metric-container"] [data-testid="stMetricValue"] {
    font-size: 30px !important;
    font-weight: 800 !important;
    color: #003087 !important;
}
[data-testid="metric-container"] [data-testid="stMetricDelta"] {
    font-size: 12px !important;
    color: #2a9d8f !important;
}

/* ── Section cards ─── */
.section-card {
    background: white;
    border: 1px solid #e8eef8;
    border-radius: 16px;
    padding: 24px;
    box-shadow: 0 2px 12px rgba(0,48,135,0.05);
    margin-bottom: 16px;
}
.section-title {
    font-size: 11px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: #6b7280;
    margin-bottom: 16px;
    display: flex;
    align-items: center;
    gap: 8px;
}
.section-title svg {
    width: 14px;
    height: 14px;
    flex-shrink: 0;
    color: #003087;
}

/* ── Iframe container ─── */
.console-wrap {
    border-radius: 14px;
    overflow: hidden;
    border: 1px solid #e8eef8;
    box-shadow: 0 4px 20px rgba(0,48,135,0.08);
}

/* ── Ticket cards ─── */
.ticket-card {
    border: 1px solid #e8eef8;
    border-radius: 12px;
    padding: 16px 20px;
    margin-bottom: 10px;
    background: white;
    transition: box-shadow 0.15s;
}
.ticket-card:hover { box-shadow: 0 4px 16px rgba(0,48,135,0.09); }
.ticket-header { font-weight: 700; font-size: 14px; color: #1f2937; }
.ticket-meta { font-size: 12px; color: #6b7280; margin-top: 3px; }
.ticket-footer { display: flex; gap: 8px; align-items: center; margin-top: 10px; flex-wrap: wrap; }

/* ── Priority & status badges ─── */
.badge-prio-alta  { background:#fee2e2; color:#991b1b; border-radius:6px; padding:3px 10px; font-size:11px; font-weight:700; }
.badge-prio-media { background:#fef3c7; color:#92400e; border-radius:6px; padding:3px 10px; font-size:11px; font-weight:700; }
.badge-prio-baja  { background:#d1fae5; color:#065f46; border-radius:6px; padding:3px 10px; font-size:11px; font-weight:700; }
.badge-taken      { background:#d1fae5; color:#065f46; border-radius:6px; padding:3px 10px; font-size:11px; font-weight:700; }
.badge-pending    { background:#fef3c7; color:#92400e; border-radius:6px; padding:3px 10px; font-size:11px; font-weight:700; }

/* ── Tabs ─── */
.stTabs [data-baseweb="tab-list"] {
    background: white;
    border-radius: 12px 12px 0 0;
    border: 1px solid #e8eef8;
    border-bottom: none;
    padding: 6px 6px 0;
    gap: 2px;
}
.stTabs [data-baseweb="tab"] {
    border-radius: 10px 10px 0 0;
    font-weight: 600;
    font-size: 13px;
    color: #6b7280;
    padding: 10px 22px;
}
.stTabs [aria-selected="true"] {
    background: #003087 !important;
    color: white !important;
}
.stTabs [data-baseweb="tab-panel"] {
    background: white;
    border: 1px solid #e8eef8;
    border-radius: 0 12px 12px 12px;
    padding: 24px;
}

/* ── Buttons ─── */
.stButton > button {
    background: #003087 !important;
    color: white !important;
    border: none !important;
    border-radius: 10px !important;
    font-weight: 600 !important;
    font-size: 13px !important;
    padding: 8px 18px !important;
    transition: opacity 0.15s !important;
}
.stButton > button:hover { opacity: 0.87 !important; }

/* ── Misc ─── */
hr { border: none; border-top: 1px solid #e8eef8 !important; margin: 16px 0 !important; }
.stInfo { background: #eff6ff; border-left-color: #003087; border-radius: 10px; }
.stSuccess { border-radius: 10px; }
.stWarning { border-radius: 10px; }
.stDataFrame { border-radius: 12px; overflow: hidden; border: 1px solid #e8eef8; }
</style>
""", unsafe_allow_html=True)

# ── Helpers ────────────────────────────────────────────────────────────────────
ORCHESTRATOR_URL = os.getenv("ORCHESTRATOR_URL", "http://localhost:8000")


def _icon(paths: str, color: str = "#003087", size: int = 14) -> str:
    return (
        f'<svg width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" '
        f'stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
        f'{paths}</svg>'
    )


ICONS = {
    "activity":    "<polyline points='22 12 18 12 15 21 9 3 6 12 2 12'/>",
    "clock":       "<circle cx='12' cy='12' r='10'/><polyline points='12 6 12 12 16 14'/>",
    "alert":       "<circle cx='12' cy='12' r='10'/><line x1='12' y1='8' x2='12' y2='12'/><line x1='12' y1='16' x2='12.01' y2='16'/>",
    "trending":    "<polyline points='23 6 13.5 15.5 8.5 10.5 1 18'/><polyline points='17 6 23 6 23 12'/>",
    "layers":      "<polygon points='12 2 2 7 12 12 22 7 12 2'/><polyline points='2 17 12 22 22 17'/><polyline points='2 12 12 17 22 12'/>",
    "bar_chart":   "<line x1='18' y1='20' x2='18' y2='10'/><line x1='12' y1='20' x2='12' y2='4'/><line x1='6' y1='20' x2='6' y2='14'/><line x1='2' y1='20' x2='22' y2='20'/>",
    "funnel":      "<path d='M4 4h16l-7 8v6l-2 2v-8L4 4z'/>",
    "zap":         "<polygon points='13 2 3 14 12 14 11 22 21 10 12 10 13 2'/>",
    "pie":         "<path d='M21.21 15.89A10 10 0 1 1 8 2.83'/><path d='M22 12A10 10 0 0 0 12 2v10z'/>",
    "table":       "<rect x='3' y='3' width='18' height='18' rx='2'/><path d='M3 9h18M3 15h18M9 3v18'/>",
    "ticket":      "<path d='M2 9a3 3 0 0 1 0 6v2a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-2a3 3 0 0 1 0-6V7a2 2 0 0 0-2-2H4a2 2 0 0 0-2 2v2z'/>",
    "clipboard":   "<path d='M9 5H7a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V7a2 2 0 0 0-2-2h-2'/><rect x='9' y='3' width='6' height='4' rx='1'/><path d='m9 14 2 2 4-4'/>",
    "graduation":  "<path d='M22 10v6M2 10l10-5 10 5-10 5z'/><path d='M6 12v5c3 3 9 3 12 0v-5'/>",
    "message":     "<path d='M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z'/>",
    "check":       "<polyline points='20 6 9 17 4 12'/>",
}


def section_title(label: str, icon_key: str) -> str:
    svg = _icon(ICONS[icon_key])
    return f'<div class="section-title">{svg} {label}</div>'


# ── DB connection ──────────────────────────────────────────────────────────────
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
grad_svg = _icon(ICONS["graduation"], color="white", size=24)
st.sidebar.markdown(f"""
<div style="text-align:center; padding:14px 0 22px;">
    <div style="display:inline-flex;align-items:center;justify-content:center;
                width:48px;height:48px;border-radius:12px;
                background:rgba(255,255,255,0.15);margin-bottom:10px;">
        {grad_svg}
    </div>
    <div style="font-size:15px;font-weight:800;color:white;letter-spacing:-0.3px;">Icesi IA</div>
    <div style="font-size:11px;color:rgba(255,255,255,0.6);margin-top:2px;">Dashboard Comercial</div>
</div>
<hr style="border:none;border-top:1px solid rgba(255,255,255,0.12);margin:0 0 18px 0;"/>
""", unsafe_allow_html=True)

days_back = st.sidebar.slider("Ventana de tiempo (días)", 1, 30, 7)
segmento_filter = st.sidebar.selectbox(
    "Filtrar por segmento",
    ["Todos", "pregrado", "posgrado", "educontinua"],
)
since = datetime.utcnow() - timedelta(days=days_back)

st.sidebar.markdown("<hr style='border:none;border-top:1px solid rgba(255,255,255,0.12);margin:18px 0;'/>",
                    unsafe_allow_html=True)
st.sidebar.markdown(f"""
<div style="font-size:11px;color:rgba(255,255,255,0.45);text-align:center;line-height:1.7;">
    Actualizado: {datetime.now().strftime('%d/%m/%Y %H:%M')}<br/>
    MVP v1.0 &middot; 2026
</div>
""", unsafe_allow_html=True)

# ── Header ─────────────────────────────────────────────────────────────────────
grad_svg_lg = _icon(ICONS["graduation"], color="white", size=26)
st.markdown(f"""
<div class="dashboard-header">
    <div class="header-icon">{grad_svg_lg}</div>
    <div>
        <p class="dashboard-title">Sistema Comercial IA — Universidad Icesi</p>
        <p class="dashboard-subtitle">
            Datos de los últimos {days_back} días &nbsp;&middot;&nbsp;
            Actualizado: {datetime.now().strftime('%d/%m/%Y %H:%M')}
        </p>
    </div>
    <span class="header-pill">En vivo</span>
</div>
""", unsafe_allow_html=True)

# ── Tabs ───────────────────────────────────────────────────────────────────────
tab_metricas, tab_chats, tab_tickets, tab_calidad = st.tabs([
    "Métricas & KPIs",
    "Consola de Chats",
    "Escalamientos",
    "Evaluación de Calidad",
])

# ══════════════════════════════════════════════════════════════════════════════
# TAB 1 — MÉTRICAS & KPIs
# ══════════════════════════════════════════════════════════════════════════════
with tab_metricas:

    # ── KPI cards ─────────────────────────────────────────────────────────────
    col1, col2, col3, col4, col5 = st.columns(5)

    total_sessions = run_query(
        "SELECT COUNT(DISTINCT session_id) as n FROM conversation_logs WHERE timestamp >= :since",
        {"since": since},
    )
    col1.metric(
        "Conversaciones",
        int(total_sessions["n"][0]) if not total_sessions.empty and "n" in total_sessions else "—",
    )

    avg_rt = run_query(
        """SELECT ROUND(AVG(latency_ms)::numeric, 0) as avg_ms
           FROM conversation_logs
           WHERE role = 'assistant' AND timestamp >= :since""",
        {"since": since},
    )
    avg_rt_val = avg_rt["avg_ms"][0] if not avg_rt.empty and "avg_ms" in avg_rt else None
    col2.metric(
        "Tiempo de respuesta",
        f"{int(avg_rt_val)} ms" if avg_rt_val else "—",
        delta="bajo meta 5 s" if avg_rt_val and int(avg_rt_val) < 5000 else None,
    )

    esc_count = run_query(
        "SELECT COUNT(*) as n FROM tickets_escalamiento WHERE created_at >= :since",
        {"since": since},
    )
    col3.metric(
        "Escalamientos",
        int(esc_count["n"][0]) if not esc_count.empty and "n" in esc_count else "—",
    )

    advanced = run_query(
        """SELECT COUNT(DISTINCT session_id) as n
           FROM intenciones_log
           WHERE "avanzó_etapa" = true AND timestamp >= :since""",
        {"since": since},
    )
    col4.metric(
        "Avance CIIPOC",
        int(advanced["n"][0]) if not advanced.empty and "n" in advanced else "—",
    )

    col5.metric("Cobertura activa", "Ver CRM", help="Comparar con total leads del CRM")

    st.markdown("<br/>", unsafe_allow_html=True)

    # ── Gráficas ──────────────────────────────────────────────────────────────
    left, right = st.columns(2)

    with left:
        st.markdown('<div class="section-card">', unsafe_allow_html=True)
        st.markdown(section_title("Conversaciones por día", "activity"), unsafe_allow_html=True)
        daily = run_query(
            """SELECT DATE(timestamp) as dia, COUNT(DISTINCT session_id) as sesiones
               FROM conversation_logs
               WHERE timestamp >= :since
               GROUP BY dia ORDER BY dia""",
            {"since": since},
        )
        if not daily.empty and "dia" in daily.columns:
            # Tratar el día como categoría evita que Plotly haga zoom a microsegundos
            # cuando solo hay uno o pocos puntos.
            daily["dia"] = daily["dia"].astype(str)
            fig = px.bar(daily, x="dia", y="sesiones", color_discrete_sequence=["#003087"])
            fig.update_layout(
                height=270, margin=dict(t=4, b=4, l=0, r=0),
                plot_bgcolor="white", paper_bgcolor="white",
                font_family="Inter",
                xaxis=dict(showgrid=False, title="", type="category"),
                yaxis=dict(showgrid=True, gridcolor="#f0f4fa", title="", dtick=1),
            )
            fig.update_traces(marker_line_width=0, marker_cornerradius=4)
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("Sin datos suficientes aún")
        st.markdown('</div>', unsafe_allow_html=True)

    with right:
        st.markdown('<div class="section-card">', unsafe_allow_html=True)
        st.markdown(section_title("Distribución de etapa CIIPOC", "funnel"), unsafe_allow_html=True)
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
            # Color por etapa (degradado azul→rojo siguiendo el avance del funnel)
            etapa_colores = {
                "contacto":       "#003087",
                "indagacion":     "#0a4bb5",
                "identificacion": "#2a9d8f",
                "propuesta":      "#f4a261",
                "objeciones":     "#e76f51",
                "cierre":         "#e63946",
            }
            fig = px.funnel(
                stages, x="n", y="etapa_ciipoc",
                color="etapa_ciipoc", color_discrete_map=etapa_colores,
            )
            fig.update_layout(
                height=270, margin=dict(t=4, b=4, l=0, r=0),
                plot_bgcolor="white", paper_bgcolor="white",
                font_family="Inter", showlegend=False,
                yaxis=dict(title=""),
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("Sin datos suficientes aún")
        st.markdown('</div>', unsafe_allow_html=True)

    left2, right2 = st.columns(2)

    with left2:
        st.markdown('<div class="section-card">', unsafe_allow_html=True)
        st.markdown(section_title("Distribución de tiempos de respuesta", "zap"), unsafe_allow_html=True)
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
            fig.add_vline(x=5000, line_dash="dash", line_color="#e63946",
                          annotation_text="Meta 5 s", annotation_font_size=11)
            fig.update_layout(
                height=270, margin=dict(t=4, b=4, l=0, r=0),
                plot_bgcolor="white", paper_bgcolor="white",
                font_family="Inter",
                xaxis=dict(showgrid=False, title="Latencia (ms)"),
                yaxis=dict(showgrid=True, gridcolor="#f0f4fa", title="Cantidad"),
            )
            fig.update_traces(marker_line_width=0)
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("Sin datos suficientes aún")
        st.markdown('</div>', unsafe_allow_html=True)

    with right2:
        st.markdown('<div class="section-card">', unsafe_allow_html=True)
        st.markdown(section_title("Escalamientos por motivo", "pie"), unsafe_allow_html=True)
        esc_motivos = run_query(
            """SELECT motivo, COUNT(*) as n
               FROM tickets_escalamiento
               WHERE created_at >= :since
               GROUP BY motivo ORDER BY n DESC""",
            {"since": since},
        )
        if not esc_motivos.empty and "motivo" in esc_motivos.columns:
            fig = px.pie(
                esc_motivos, values="n", names="motivo",
                color_discrete_sequence=["#003087", "#e63946", "#2a9d8f", "#f4a261", "#a8dadc"],
                hole=0.45,
            )
            fig.update_layout(
                height=270, margin=dict(t=4, b=4, l=0, r=0),
                font_family="Inter",
                legend=dict(orientation="h", yanchor="bottom", y=-0.22),
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("Sin escalamientos en el periodo")
        st.markdown('</div>', unsafe_allow_html=True)

    # ── Actividad por segmento ────────────────────────────────────────────────
    st.markdown('<div class="section-card">', unsafe_allow_html=True)
    st.markdown(section_title("Actividad por segmento", "layers"), unsafe_allow_html=True)
    seg_data = run_query(
        """SELECT segmento, COUNT(DISTINCT session_id) as sesiones,
                  ROUND(AVG(latency_ms)::numeric, 0) as latencia_promedio_ms
           FROM conversation_logs
           WHERE timestamp >= :since AND segmento IS NOT NULL
           GROUP BY segmento""",
        {"since": since},
    )
    if not seg_data.empty and "segmento" in seg_data.columns:
        st.dataframe(seg_data, use_container_width=True, hide_index=True)
    else:
        st.info("Sin datos por segmento aún")
    st.markdown('</div>', unsafe_allow_html=True)

    # ── Últimos escalamientos ─────────────────────────────────────────────────
    st.markdown('<div class="section-card">', unsafe_allow_html=True)
    st.markdown(section_title("Últimos escalamientos", "ticket"), unsafe_allow_html=True)
    esc_table = run_query(
        """SELECT created_at, motivo, prioridad, asesor_asignado, asesor_tomo_caso
           FROM tickets_escalamiento
           WHERE created_at >= :since
           ORDER BY created_at DESC LIMIT 20""",
        {"since": since},
    )
    if not esc_table.empty and "motivo" in esc_table.columns:
        st.dataframe(esc_table, use_container_width=True, hide_index=True)
    else:
        st.info("Sin escalamientos recientes")
    st.markdown('</div>', unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
# TAB 2 — CONSOLA DE CHATS (iframe al orquestador FastAPI)
# ══════════════════════════════════════════════════════════════════════════════
with tab_chats:
    sub_historial, sub_live = st.tabs(["Conversaciones del bot", "Consola interactiva"])

    # ── Sub-pestaña: transcripciones reales registradas (Telegram / WhatsApp / web) ──
    with sub_historial:
        st.markdown(
            section_title("Conversaciones registradas — todos los canales", "message"),
            unsafe_allow_html=True,
        )

        col_sel, col_rf = st.columns([4, 1])
        with col_rf:
            st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
            if st.button("Actualizar", key="refresh_chats"):
                st.rerun()

        sesiones = run_query(
            """SELECT session_id,
                      MAX(timestamp)            AS ultima,
                      COUNT(*)                  AS turnos,
                      MAX(segmento)             AS segmento,
                      MAX(etapa_ciipoc)         AS etapa,
                      BOOL_OR(escalado)         AS escalado
               FROM conversation_logs
               WHERE timestamp >= :since
               GROUP BY session_id
               ORDER BY ultima DESC
               LIMIT 50""",
            {"since": since},
        )

        if sesiones.empty or "session_id" not in sesiones.columns:
            st.info("Aún no hay conversaciones registradas en este periodo. "
                    "Chatea con el bot y pulsa «Actualizar».")
        else:
            def _fmt(row) -> str:
                ts = str(row["ultima"])[:16].replace("T", " ")
                seg = row["segmento"] or "sin segmento"
                etapa = row["etapa"] or "—"
                flag = " 🔴 escalado" if row.get("escalado") else ""
                return f"{ts} · {row['turnos']} turnos · {seg} · {etapa}{flag} · {row['session_id'][:8]}"

            opciones = {_fmt(r): r["session_id"] for _, r in sesiones.iterrows()}
            with col_sel:
                etiqueta = st.selectbox("Selecciona una conversación", list(opciones.keys()))
            session_id = opciones[etiqueta]

            mensajes = run_query(
                """SELECT role, text, etapa_ciipoc, segmento, timestamp
                   FROM conversation_logs
                   WHERE session_id = :sid
                   ORDER BY turn_id ASC, timestamp ASC""",
                {"sid": session_id},
            )

            st.markdown("<div style='margin-top:6px'></div>", unsafe_allow_html=True)
            if mensajes.empty or "role" not in mensajes.columns:
                st.info("No se pudo cargar el detalle de esta conversación.")
            else:
                for _, m in mensajes.iterrows():
                    rol = "user" if m["role"] == "user" else "assistant"
                    avatar = "🧑" if rol == "user" else "🎓"
                    with st.chat_message(rol, avatar=avatar):
                        st.markdown(m["text"] or "_(sin texto)_")
                        meta = []
                        if m.get("etapa_ciipoc"):
                            meta.append(f"etapa: {m['etapa_ciipoc']}")
                        hora = str(m["timestamp"])[11:16] if m.get("timestamp") is not None else ""
                        if hora:
                            meta.append(hora)
                        if meta:
                            st.caption(" · ".join(meta))

    # ── Sub-pestaña: consola interactiva en vivo (iframe al orquestador) ──
    with sub_live:
        st.markdown(f"""
        <div style="background:#eff6ff;border:1px solid #bfdbfe;border-radius:10px;
                    padding:10px 16px;font-size:13px;color:#1e40af;margin-bottom:14px;
                    display:flex;align-items:center;gap:8px;">
            {_icon(ICONS['message'], color='#1e40af', size=14)}
            <span>Consola interactiva conectada a <strong>{ORCHESTRATOR_URL}</strong>
            &nbsp;&mdash;&nbsp;requiere que el orquestador esté en ejecución.</span>
        </div>
        """, unsafe_allow_html=True)
        components.iframe(src=f"{ORCHESTRATOR_URL}/", height=680, scrolling=False)


# ══════════════════════════════════════════════════════════════════════════════
# TAB 3 — TICKETS DE ESCALAMIENTO
# ══════════════════════════════════════════════════════════════════════════════
with tab_tickets:

    col_filter, col_refresh = st.columns([4, 1])
    with col_filter:
        ticket_filter = st.radio(
            "Mostrar",
            ["Pendientes", "Tomados", "Todos"],
            horizontal=True,
            key="ticket_filter",
        )
    with col_refresh:
        st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
        refresh_t = st.button("Actualizar", key="refresh_tickets")

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

    PRIO_BADGE = {
        "alta":  "badge-prio-alta",
        "media": "badge-prio-media",
        "baja":  "badge-prio-baja",
    }
    PRIO_LABEL = {"alta": "Alta", "media": "Media", "baja": "Baja"}

    st.markdown("<div style='margin-top:8px'></div>", unsafe_allow_html=True)

    if not tickets_data:
        st.info("Sin tickets en esta categoría.")
    else:
        for t in tickets_data:
            prioridad  = t.get("prioridad", "")
            motivo     = t.get("motivo", "—")
            created_at = str(t.get("created_at", ""))[:16].replace("T", " ")
            tomado     = t.get("asesor_tomo_caso", False)
            asesor     = t.get("asesor_nombre") or t.get("asesor_asignado", "—")

            prio_cls   = PRIO_BADGE.get(prioridad, "badge-prio-media")
            prio_label = PRIO_LABEL.get(prioridad, prioridad.capitalize() if prioridad else "—")
            status_cls = "badge-taken" if tomado else "badge-pending"
            status_lbl = f"Tomado · {asesor}" if tomado else "Pendiente"

            st.markdown(f"""
            <div class="ticket-card">
                <div style="display:flex;align-items:flex-start;justify-content:space-between;gap:12px;flex-wrap:wrap;">
                    <div>
                        <div class="ticket-header">{motivo}</div>
                        <div class="ticket-meta">Asesor asignado: {t.get('asesor_asignado','—')} &nbsp;&middot;&nbsp; {created_at}</div>
                    </div>
                    <div class="ticket-footer" style="margin-top:0;">
                        <span class="{prio_cls}">{prio_label}</span>
                        <span class="{status_cls}">{status_lbl}</span>
                    </div>
                </div>
            </div>
            """, unsafe_allow_html=True)

            if not tomado:
                with st.expander("Tomar caso", expanded=False):
                    st.text(t.get("ticket_text", "—"))
                    col_nombre, col_btn = st.columns([3, 1])
                    nombre_input = col_nombre.text_input(
                        "Nombre del asesor", key=f"nombre_{t['id']}", placeholder="Tu nombre completo"
                    )
                    if col_btn.button("Confirmar", key=f"tomar_{t['id']}"):
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
                                    st.success(f"Caso asignado a {nombre_input}. Recarga para actualizar.")
                                else:
                                    st.error(r.json().get("detail", "Error al tomar el caso."))
                            except Exception as e:
                                st.error(f"No se pudo conectar al orquestador: {e}")
            else:
                st.markdown("<div style='margin-bottom:4px'></div>", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
# TAB 4 — EVALUACIÓN DE CALIDAD
# ══════════════════════════════════════════════════════════════════════════════
with tab_calidad:

    st.markdown('<div class="section-card">', unsafe_allow_html=True)
    st.markdown(section_title("Registro de evaluación semanal", "clipboard"), unsafe_allow_html=True)
    st.markdown("""
    <p style="font-size:13px;color:#6b7280;margin-bottom:16px;">
        El Líder Comercial revisa 30 conversaciones aleatorias por semana y califica cada respuesta
        como <strong>Correcta</strong>, <strong>Imprecisa</strong> o <strong>Alucinación</strong>.
        Registra los resultados para seguimiento.
    </p>
    """, unsafe_allow_html=True)

    with st.form("quality_form"):
        col_a, col_b = st.columns(2)
        with col_a:
            eval_date  = st.date_input("Fecha de evaluación", datetime.now())
            evaluador  = st.text_input("Evaluador")
        with col_b:
            correctas     = st.number_input("Respuestas correctas",  min_value=0, max_value=30, value=28)
            imprecisas    = st.number_input("Imprecisas",            min_value=0, max_value=30, value=2)
            alucinaciones = st.number_input("Alucinaciones",         min_value=0, max_value=30, value=0)
        notas     = st.text_area("Notas / hallazgos", height=100)
        submitted = st.form_submit_button("Registrar evaluación", use_container_width=True)

        if submitted:
            total_eval = correctas + imprecisas + alucinaciones
            pct = round(correctas / total_eval * 100, 1) if total_eval > 0 else 0
            cumple = pct >= 95

            if cumple:
                st.success(f"Evaluación registrada: **{pct}% correctas** — Cumple meta ≥ 95%")
            else:
                st.warning(f"Evaluación registrada: **{pct}% correctas** — Por debajo de la meta")

            fig_eval = go.Figure(go.Bar(
                x=["Correctas", "Imprecisas", "Alucinaciones"],
                y=[correctas, imprecisas, alucinaciones],
                marker_color=["#2a9d8f", "#f4a261", "#e63946"],
            ))
            fig_eval.update_layout(
                height=220, margin=dict(t=8, b=8, l=0, r=0),
                plot_bgcolor="white", paper_bgcolor="white",
                font_family="Inter", showlegend=False,
            )
            fig_eval.update_traces(marker_line_width=0, marker_cornerradius=4)
            st.plotly_chart(fig_eval, use_container_width=True)

    st.markdown('</div>', unsafe_allow_html=True)

# ── Footer ─────────────────────────────────────────────────────────────────────
st.markdown("""
<div style="text-align:center;color:#9ca3af;font-size:11px;padding:24px 0 8px;border-top:1px solid #e8eef8;margin-top:12px;">
    Sistema desarrollado para el equipo comercial de la Universidad Icesi &nbsp;&middot;&nbsp; MVP v1.0 &nbsp;&middot;&nbsp; 2026
</div>
""", unsafe_allow_html=True)
