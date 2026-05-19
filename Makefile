.PHONY: dev test lint typecheck format install

install:
	pip install -r requirements-dev.txt

dev:
	functions-framework --target=main --source=src --port=8080

test:
	pytest

lint:
	ruff check src tests
	black --check src tests

typecheck:
	mypy --strict src

format:
	black src tests
	isort src tests
