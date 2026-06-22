.PHONY: install infra-up infra-down run migrate seed test test-unit test-integration
.PHONY: test-domain test-api test-web
.PHONY: lint format typecheck check docker-build docker-up docker-down
.PHONY: attack-list attack-run attack-run-all demo verify-jaeger agent-demo verify-ollama-agent

install:
	uv sync --frozen

infra-up:
	docker compose --profile observability up -d postgres jaeger

infra-down:
	docker compose --profile observability down

run:
	uv run uvicorn toolwatch.main:app --reload

migrate:
	uv run alembic upgrade head

seed:
	uv run python -m toolwatch.seed

test:
	uv run pytest -m "not local_llm"

test-unit:
	uv run pytest tests/unit -m "not local_llm"

test-integration:
	uv run pytest tests/integration -m "not local_llm"

test-domain:
	uv run pytest tests/unit/domain tests/unit/application -m "not local_llm"

test-api:
	uv run pytest tests/unit/api tests/integration/test_registry_and_sessions_api.py -m "not local_llm"

lint:
	uv run ruff check .
	uv run ruff format --check .

format:
	uv run ruff check --fix .
	uv run ruff format .

typecheck:
	uv run pyright

check: lint typecheck test

docker-build:
	docker compose build api

docker-up:
	docker compose up -d --build

docker-down:
	docker compose --profile observability down

test-web:
	uv run pytest tests/unit/web -m "not local_llm"

attack-list:
	uv run python -m toolwatch.attack_lab list

attack-run:
	uv run python -m toolwatch.attack_lab run $(SCENARIO)

attack-run-all:
	uv run python -m toolwatch.attack_lab run-all

verify-jaeger:
	uv run python scripts/verify_jaeger.py

agent-demo:
	uv run python -m toolwatch.agent run --provider $(or $(PROVIDER),fake) $(or $(PROMPT),"Check open issues in demo/backend")

verify-ollama-agent:
	uv run python scripts/verify_ollama_agent.py

demo:
	docker compose --profile observability up -d postgres jaeger
	uv run alembic upgrade head
	uv run python -m toolwatch.seed
	@echo ""
	@echo "ToolWatch demo URLs:"
	@echo "  Dashboard:  http://localhost:8000/ui"
	@echo "  API docs:   http://localhost:8000/docs"
	@echo "  Metrics:    http://localhost:8000/metrics"
	@echo "  Jaeger UI:  http://localhost:16686"
	@echo ""
	@echo "Start the API in another terminal with:  make run"
	@echo "Run an attack scenario with:             make attack-run SCENARIO=destructive-sql"
