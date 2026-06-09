# Documentación de Chat-de-WhatsApp-IA2

Este proyecto es un **Agente Comercial de IA** (MVP) para la Universidad Icesi, diseñado para interactuar con aspirantes a través de WhatsApp y Telegram. Su propósito es resolver dudas y acompañar el proceso de inscripción para los programas de pregrado, posgrado y educación continua.

# Video Demostrativo del chatbot 

https://youtu.be/0vCiAvxr5IQ


## Arquitectura General

El sistema está construido con una arquitectura de dos niveles:
- **Nivel 1 (LLM y RAG):** Impulsado por un LLM (Claude/Gemini) con capacidad de uso de herramientas (tool-use) y un sistema de Generación Aumentada por Recuperación (RAG) utilizando `pgvector` para consultar documentos de la base de conocimiento.
- **Nivel 2 (Motor de Negocio):** Un motor de reglas que gestiona el embudo de ventas, el escalamiento a asesores humanos y los seguimientos.

### Componentes Principales
- **Orquestador (`orchestrator/`):** El backend en FastAPI que sirve como webhook para WhatsApp y Telegram, gestiona el ciclo de la conversación, la ejecución de herramientas, el estado de las sesiones (a través de Redis) y se conecta al CRM.
- **Base de Conocimiento (`icesi-kb/`):** Contiene la documentación (archivos Markdown + un manifiesto YAML) sobre la universidad, metodologías, programas y preguntas frecuentes.
- **Canal de Ingesta (`ingest/`):** Script encargado de vectorizar e indexar la base de conocimiento en la base de datos `pgvector`.
- **Dashboard (`dashboard/`):** Aplicación web basada en Streamlit para visualizar métricas e interacciones.
- **Base de Datos:** PostgreSQL con `pgvector` para almacenar la base de conocimiento, registros (logs) y métricas. Redis se utiliza para una gestión rápida y eficiente de las sesiones.

## Estructura del Proyecto

- `orchestrator/` - Aplicación principal (FastAPI, ciclo conversacional del LLM, RAG, adaptador de CRM y las integraciones de WhatsApp/Telegram).
- `ingest/` - Contiene el script (`ingest.py`) para vectorizar los documentos.
- `dashboard/` - Contiene la aplicación de Streamlit (`app.py`) para el panel de métricas.
- `icesi-kb/` - Archivos fuente de la base de conocimiento en Markdown y YAML.
- `tests/` - Casos de prueba para validar el comportamiento del agente.
- `docker-compose.yml` y `Dockerfile` - Configuración de infraestructura y contenedores.
- `Makefile` - Comandos útiles para levantar la infraestructura, procesar datos e iniciar la aplicación.

## Guía de Inicio

1. **Configuración:** Copia el archivo `.env.example` a `.env` y agrega tus claves de API (ej. `GEMINI_API_KEY`, tokens de WhatsApp y Telegram).
2. **Infraestructura:** Ejecuta `make infra` para iniciar PostgreSQL y Redis usando Docker.
3. **Ingesta de Datos:** Ejecuta `make ingest` para procesar y cargar la base de conocimiento.
4. **Ejecutar la Aplicación:** Ejecuta `make dev` para iniciar el orquestador FastAPI en modo desarrollo.
5. **Dashboard:** Ejecuta `make dashboard` para acceder a la interfaz de métricas en el puerto 8501.
6. **Pruebas:** Ejecuta `make test` o `make chat-test` para probar el agente por terminal o usando la consola web en `http://localhost:8000/`.

## Integración con Telegram

Además de WhatsApp, el sistema permite la interacción con los usuarios mediante un bot de Telegram. Esta integración sigue la misma estructura de webhook que WhatsApp.

- El **Adaptador de Telegram** (`orchestrator/telegram.py` - *componente planificado o en curso*) maneja la comunicación con la API de Telegram, convirtiendo los mensajes entrantes al formato estándar del sistema y enviando las respuestas generadas por el agente de vuelta a Telegram.
- **Configuración requerida:** Necesitas registrar un bot con BotFather en Telegram y agregar el token correspondiente en tu archivo `.env` (ej. `TELEGRAM_BOT_TOKEN`).

## Endpoints Principales

- `POST /webhook/whatsapp` - Recibe mensajes entrantes desde Meta (WhatsApp Cloud API).
- `POST /webhook/telegram` - Recibe actualizaciones (mensajes) entrantes desde la API de Telegram.
- `POST /chat` - Endpoint directo para probar el chat sin depender de clientes externos.
- `GET /metrics` - Obtiene una instantánea de las métricas del sistema para el dashboard.
