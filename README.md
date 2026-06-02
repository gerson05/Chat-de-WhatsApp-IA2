# Sistema Comercial IA — Universidad Icesi

MVP del agente comercial IA para el Canal Personas (Pregrado, Posgrado, Educación Continua).

## Arquitectura

```
WhatsApp Cloud API
       │
       ▼
Orquestador (FastAPI)
  ├── Nivel 1: Claude Sonnet 4 + 5 tools + RAG (pgvector)
  └── Nivel 2: Motor de reglas (funnel, escalamiento, seguimientos)
       │
       ├── Redis (sesiones)
       ├── PostgreSQL + pgvector (logs, KB, métricas)
       └── CRM Adapter (HubSpot / mock)
```

## Inicio rápido

### 1. Requisitos
- Python 3.11+
- Docker y Docker Compose
- API key de Google Gemini (AI Studio — capa gratuita): https://aistudio.google.com/apikey

### 2. Configuración
```bash
cp .env.example .env
# Edita .env con tu GEMINI_API_KEY
```

### 3. Levantar infraestructura e iniciar
```bash
# Opción A — con Make
make infra      # Levanta Postgres + Redis con Docker
make ingest     # Indexa la base de conocimiento
make dev        # Inicia el orquestador en modo desarrollo

# Opción B — con Docker Compose completo
docker compose up --build
```

### 4. Dashboard
```bash
make dashboard
# Accede en http://localhost:8501
```

### 5. Tests
```bash
make test
```

### 6. Consola web interactiva (recomendado)
Con el orquestador corriendo, abre en el navegador:
```
http://localhost:8000/
```
Es una consola de chat que arma las peticiones a `/chat` por ti (no necesitas `curl`):
muestra la respuesta del bot, la etapa CIIPOC, el segmento, si se escaló y las tools
llamadas en cada turno. Permite cambiar el teléfono (simular distintos aspirantes) y
reiniciar la sesión. Funciona aunque Redis no esté levantado (usa sesión en memoria).

### 7. Probar el chat por terminal
```bash
make chat-test
# o directamente:
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"phone": "+573001234567", "message": "Hola, me interesa la maestría en mercadeo"}'
```

## Estructura del proyecto

```
icesi-ia/
├── orchestrator/           # Núcleo del sistema
│   ├── main.py             # FastAPI: webhook + /chat endpoint
│   ├── conversation.py     # Loop tool-use con Claude
│   ├── tools.py            # 5 herramientas del agente
│   ├── nivel2.py           # Motor de negocio (funnel, CRM, seguimientos)
│   ├── session_store.py    # Redis session management
│   ├── rag.py              # Pipeline RAG (embed + pgvector + rerank)
│   ├── crm_adapter.py      # Adaptador anti-corrupción CRM
│   ├── whatsapp.py         # WhatsApp Cloud API
│   ├── db.py               # SQLAlchemy models + logging
│   ├── system_prompt.py    # System prompt CIIPOC completo
│   ├── models.py           # Pydantic models (SessionState, etc.)
│   └── config.py           # Settings (pydantic-settings)
├── ingest/
│   └── ingest.py           # Indexador KB → pgvector
├── dashboard/
│   └── app.py              # Streamlit dashboard de métricas
├── icesi-kb/               # Base de conocimiento (Markdown + YAML)
│   ├── manifest.yaml       # Tabla maestra de documentos
│   ├── 00_diferenciales_icesi/
│   ├── 01_metodologia_ciipoc/
│   ├── 02_portafolio/      # 9 fichas de programa piloto
│   ├── 03_faqs/
│   └── 04_reglas_escalamiento/
├── tests/
│   └── test_conversation.py  # 21 casos de prueba
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
└── Makefile
```

## Configuración de variables de entorno

| Variable | Descripción | Requerida |
|----------|-------------|-----------|
| `GEMINI_API_KEY` | API key de Google Gemini (AI Studio) | ✅ |
| `DATABASE_URL` | PostgreSQL con pgvector | ✅ |
| `REDIS_URL` | Redis para sesiones | ✅ |
| `WHATSAPP_PHONE_ID` | ID del número de WA Business | Para producción |
| `WHATSAPP_ACCESS_TOKEN` | Token de WA Cloud API | Para producción |
| `COHERE_API_KEY` | Para embeddings y rerank de calidad | Recomendado |
| `CRM_BACKEND` | `mock` (dev) o `hubspot` | Opcional |

## Endpoints principales

| Método | Ruta | Descripción |
|--------|------|-------------|
| `GET` | `/health` | Health check |
| `GET` | `/webhook/whatsapp` | Verificación webhook Meta |
| `POST` | `/webhook/whatsapp` | Mensajes entrantes de WhatsApp |
| `POST` | `/chat` | Chat directo para testing |
| `GET` | `/metrics` | Snapshot de métricas |

## Base de conocimiento

Los documentos en `icesi-kb/` siguen el esquema del `manifest.yaml`.
Para agregar o actualizar un documento:
1. Crea o edita el `.md` en la carpeta correspondiente.
2. Agrega/actualiza la entrada en `manifest.yaml`.
3. Ejecuta `make ingest` para re-indexar.

## Semana de despliegue (guía)

1. **Semana 1**: Completar y validar las fichas de programa con los gestores. Firmar aprobaciones en cada `.md`.
2. **Semana 2**: `make dev` + 20 pruebas simuladas vía `/chat`.
3. **Semana 3**: Conectar WhatsApp sandbox + pruebas de campo con el equipo comercial.
4. **Semana 4**: CRM real, dashboard en producción, demo ejecutiva.

---
*Sistema desarrollado para el equipo comercial de la Universidad Icesi · MVP v1.0 · 2026*
