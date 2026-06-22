.PHONY: install infra-up infra-down run migrate seed test test-unit test-integration
.PHONY: test-domain test-api test-web
.PHONY: lint format typecheck check docker-build docker-up docker-down recover
.PHONY: build package-check image image-smoke sbom security-scan load-seed load-test query-plans
.PHONY: workflow-check
.PHONY: attack-list attack-run attack-run-all demo verify-jaeger agent-demo verify-ollama-agent
.PHONY: test-local-llm-repeat

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

recover:
	uv run python -m toolwatch.recovery run

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

build:
	rm -rf dist
	uv build

package-check:
	UV_CACHE_DIR=$(or $(UV_CACHE_DIR),/tmp/toolwatch-uv-cache) uv run python scripts/package_check.py

image:
	docker build \
		--build-arg VERSION=0.1.0 \
		--build-arg REVISION=$(or $(REVISION),local) \
		--build-arg SOURCE_URL=$(or $(SOURCE_URL),https://example.invalid/toolwatch) \
		-t toolwatch:0.1.0 .

image-smoke:
	uv run python scripts/image_smoke.py

sbom:
	uv run python scripts/generate_sbom.py --output dist/toolwatch-python.spdx.json
	uv run python scripts/generate_sbom.py --image toolwatch:0.1.0 --output dist/toolwatch-image.spdx.json

security-scan:
	uvx --from pip-audit==2.9.0 pip-audit
	uvx --from bandit==1.8.6 bandit -q -r src

load-test:
	uv run python scripts/load_test.py $(LOAD_ARGS)

load-seed:
	uv run python scripts/seed_load.py

query-plans:
	uv run python scripts/query_plans.py

workflow-check:
	uv run python scripts/validate_workflows.py

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

test-local-llm-repeat:
	uv run python scripts/repeat_local_llm.py --count $(or $(COUNT),5)

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
