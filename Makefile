.PHONY: verify verify-fast test test-unit test-adversarial lint check-env up down data-build kb-ingest

PYTHON ?= python

check-env:
	$(PYTHON) scripts/check_env.py

verify-fast:
	$(PYTHON) scripts/verify.py --fast

verify:
	$(PYTHON) scripts/verify.py

test:
	pytest tests/unit tests/adversarial -v

test-unit:
	pytest tests/unit -v

test-adversarial:
	pytest tests/adversarial -v

lint:
	ruff check src tests scripts

data-sample:
	$(PYTHON) -m ontoagent.data.make_sample

data-build:
	$(PYTHON) -m ontoagent.data.load_postgres
	$(PYTHON) -m ontoagent.data.load_neo4j
	$(PYTHON) -m ontoagent.data.ingest_kb

kb-ingest:
	$(PYTHON) -m ontoagent.data.ingest_kb

up:
	docker compose up -d

down:
	docker compose down
