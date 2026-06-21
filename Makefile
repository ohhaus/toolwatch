.PHONY: install infra-up infra-down run migrate test test-unit test-integration
.PHONY: test-domain test-api
.PHONY: lint format typecheck check docker-build docker-up docker-down

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
