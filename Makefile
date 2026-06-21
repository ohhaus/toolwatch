install:
	uv sync

infra-up:
	docker compose up -d postgres jaeger mock-tools

infra-down:
	docker compose down

run:
	uv run uvicorn toolwatch.main:app --reload

test:
	uv run pytest

test-unit:
	uv run pytest tests/unit

test-integration:
	uv run pytest tests/integration

lint:
	uv run ruff check .
	uv run ruff format --check .

format:
	uv run ruff check --fix .
	uv run ruff format .

typecheck:
	uv run pyright

check: lint typecheck test
