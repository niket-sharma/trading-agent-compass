.PHONY: install dev test lint fmt typecheck refresh-data clean

install:
	pip install -e .[dev]

dev:
	streamlit run streamlit_app.py

test:
	pytest

lint:
	ruff check tradeagent tests scripts

fmt:
	ruff format tradeagent tests scripts
	black tradeagent tests scripts

typecheck:
	mypy tradeagent

refresh-data:
	python scripts/refresh_static_data.py

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	rm -rf .pytest_cache .mypy_cache .ruff_cache dist build *.egg-info
