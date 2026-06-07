# Icesi IA — Comandos de desarrollo

.PHONY: install dev infra ingest test dashboard lint clean

install:
	uv venv .venv --python 3.12
	uv pip install -r requirements.txt --python .venv/bin/python

# Start local infrastructure (Postgres + Redis)
infra:
	docker compose up postgres redis -d
	@echo "Waiting for DB to be ready..."
	@sleep 5
	python -c "from orchestrator.db import init_db; init_db()" && echo "DB initialized"

# Start the orchestrator in development mode
dev: infra
	cp -n .env.example .env || true
	uvicorn orchestrator.main:app --reload --host 0.0.0.0 --port 8000

# Index knowledge base into pgvector
ingest:
	python -m ingest.ingest --path ./icesi-kb

# Full re-index
ingest-full:
	python -m ingest.ingest --path ./icesi-kb --full

# Run Streamlit dashboard
dashboard:
	streamlit run dashboard/app.py

# Run tests
test:
	.venv/bin/pytest tests/ -v --tb=short

# Run tests with coverage
test-cov:
	.venv/bin/pytest tests/ -v --cov=orchestrator --cov-report=term-missing

# Lint
lint:
	ruff check orchestrator/ ingest/ tests/ || true
	mypy orchestrator/ --ignore-missing-imports || true

# Quick chat test (requires ANTHROPIC_API_KEY and running infra)
chat-test:
	@echo "Testing chat endpoint..."
	curl -s -X POST http://localhost:8000/chat \
	  -H "Content-Type: application/json" \
	  -d '{"phone": "+573001234567", "message": "Hola, me interesa la maestría en mercadeo"}' \
	  | python -m json.tool

# Stop infrastructure
clean:
	docker compose down
