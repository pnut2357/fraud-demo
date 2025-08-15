# .PHONY: venv install train eval publish
# venv:
# 	python3 -m venv .venv
# 	. .venv/bin/activate; python -m pip install --upgrade pip wheel
# install:
# 	. .venv/bin/activate; pip install -r requirements-dev.txt
# train:
# 	. .venv/bin/activate; python scripts/train_artifacts.py
# eval:
# 	. .venv/bin/activate; python scripts/evaluate_artifacts.py --threshold 0.75
# publish:
# 	. .venv/bin/activate; python scripts/publish_sample.py --file data/transactions_sample.jsonl
# Use bash with strict flags so failures are obvious
SHELL := bash
.ONESHELL:
.SHELLFLAGS := -eu -o pipefail -c

# Paths & vars
VENV := .venv
PY   := $(VENV)/bin/python
UV   := $(shell command -v uv 2>/dev/null || true)
COMPOSE := docker compose -f infra/docker-compose.yml

CSV := data/raw/PaySim.csv
JSONL := data/transactions_sample.jsonl
THRESH ?= 0.75        # default eval threshold
ALERT_RATE ?=         # e.g. 0.03 to evaluate at 3% alert rate

# Queues we use in RabbitMQ
QUEUES := transactions.raw fraud.scores alerts.high_risk analyst.recommendations

.PHONY: help
help:
	@echo "Targets:"
	@echo "  uv-check          - verify 'uv' is installed"
	@echo "  venv              - create .venv with uv"
	@echo "  install           - install dev deps into .venv using uv pip"
	@echo "  prepare-data      - build $(JSONL) from $(CSV)"
	@echo "  train             - train artifacts/model.pkl & model_config.json"
	@echo "  eval              - evaluate artifacts (THRESH=$(THRESH), ALERT_RATE=$(ALERT_RATE))"
	@echo "  compose-up        - docker compose up -d --build"
	@echo "  compose-down      - docker compose down"
	@echo "  logs              - tail worker/agent logs"
	@echo "  publish           - publish $(JSONL) into RabbitMQ"
	@echo "  purge-queues      - purge RabbitMQ queues ($(QUEUES))"
	@echo "  soft-reset        - purge queues + remove data/fraud.db, then restart worker/agent/ui"
	@echo "  nuke              - full reset: compose down, delete db, compose up -d --build"

.PHONY: uv-check
uv-check:
	@if [[ -z "$(UV)" ]]; then \
	  echo "ERROR: 'uv' not found. Install via:" ; \
	  echo "  curl -LsSf https://astral.sh/uv/install.sh | sh" ; \
	  exit 1 ; \
	fi
	@$(UV) --version

# Create a virtualenv using uv (no activation needed)
.PHONY: venv
venv: uv-check
	$(UV) venv $(VENV)
	$(PY) -V

# Install pinned deps into that venv using uv pip
.PHONY: install
install: venv
	# ensure you have requirements-dev.txt at repo root
	$(UV) pip install -r requirements-dev.txt -p $(PY)
	$(PY) -c "import numpy, pandas, sklearn, joblib; print('OK:', numpy.__version__, pandas.__version__, sklearn.__version__)"

# Convert PaySim -> JSONL
.PHONY: prepare-data
prepare-data: #install
	@test -f "$(CSV)" || { echo "Missing $(CSV)"; exit 1; }
	$(PY) scripts/prepare_paysim.py --csv $(CSV) --out $(JSONL) --max-rows 20000
	@echo "Wrote $(JSONL)"

# Train model artifacts
.PHONY: train
train: #install
	$(PY) scripts/train_artifacts.py
	@echo "Artifacts ready in ./artifacts. Restart model_api if running:"
	@echo "$(COMPOSE) restart model_api"

# Evaluate artifacts with metrics
.PHONY: eval
eval: #install
	ARGS=()
	if [[ -n "$(ALERT_RATE)" ]]; then ARGS+=(--alert-rate $(ALERT_RATE)); fi
	$(PY) scripts/evaluate_artifacts.py --threshold $(THRESH) "$${ARGS[@]}"

# Docker compose helpers
.PHONY: compose-up compose-down logs
compose-up:
	$(COMPOSE) up -d --build

compose-down:
	$(COMPOSE) down

logs:
	$(COMPOSE) logs -f stream_worker agent

# Publish events from JSONL into RabbitMQ
.PHONY: publish
publish: #install
	@test -f "$(JSONL)" || { echo "Missing $(JSONL). Run 'make prepare-data' first."; exit 1; }
	$(PY) scripts/publish_sample.py --file $(JSONL)

# Purge queues in RabbitMQ
.PHONY: purge-queues
purge-queues:
	for q in $(QUEUES); do \
	  $(COMPOSE) exec -T rabbitmq rabbitmqctl purge_queue $$q || true ; \
	done
	$(COMPOSE) exec -T rabbitmq rabbitmqctl list_queues name messages

# Soft reset: clear queues + DB, then restart consumers
.PHONY: soft-reset
soft-reset:
	$(COMPOSE) stop stream_worker agent ui || true
	$(MAKE) purge-queues
	rm -f data/fraud.db
	$(COMPOSE) start stream_worker agent ui

# Full reset: recreate broker + services
.PHONY: nuke
nuke:
	$(COMPOSE) down
	rm -f data/fraud.db
	$(COMPOSE) up -d --build