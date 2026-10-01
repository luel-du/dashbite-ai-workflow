# DashBite pipeline — common teaching commands
# Usage: make help

PYTHON      ?= python3
VENV        ?= .venv
BIN         := $(VENV)/bin
PY          := $(BIN)/python
PIP         := $(BIN)/pip
PYTEST      := $(BIN)/pytest
STREAMLIT   := $(BIN)/streamlit

# Demo-friendly defaults (override on the command line)
export TRAIN_EVERY_N_EVENTS    ?= 50
export BATCH_SIZE              ?= 20
export POLL_INTERVAL_SECONDS   ?= 2.0
export CORRUPT_BATCH_RATE      ?= 0.25
export PYTHONPATH              := $(CURDIR)

LOG_DIR := .logs
PIDS    := $(LOG_DIR)/pids

.PHONY: help install test test-unit test-regression test-integration \
	simulator preprocess train infer dashboard \
	run stop clean clean-data

help:
	@echo "DashBite Make targets"
	@echo ""
	@echo "  make install              Create .venv and install pinned requirements (+ pytest)"
	@echo "  make test                 Run full pytest suite (unit+regression+integration)"
	@echo "  make test-unit            Run unit tests only"
	@echo "  make test-regression      Run regression tests only"
	@echo "  make test-integration     Run integration tests only"
	@echo "  make simulator            Run order feed (foreground)"
	@echo "  make preprocess           Run preprocess loop (foreground)"
	@echo "  make train                Run training loop (foreground)"
	@echo "  make infer                Run inference loop (foreground)"
	@echo "  make dashboard            Run Streamlit on :8501 (foreground)"
	@echo "  make run                  Start all stages in background + dashboard"
	@echo "  make stop                 Stop background pipeline processes"
	@echo "  make clean-data           Remove runtime files under DATA_ROOT, default data/ (keep .gitkeep)"
	@echo "  make clean                clean-data + logs + pytest cache"
	@echo ""
	@echo "Env defaults: TRAIN_EVERY_N_EVENTS=$(TRAIN_EVERY_N_EVENTS) BATCH_SIZE=$(BATCH_SIZE)"

install: $(VENV)/.installed

# constraints.txt pins every package to the versions the Docker image uses.
$(VENV)/.installed: requirements.txt requirements-dev.txt constraints.txt
	$(PYTHON) -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements-dev.txt -c constraints.txt
	@touch $@

test: install
	$(PYTEST)

test-unit: install
	$(PYTEST) -m unit

test-regression: install
	$(PYTEST) -m regression

test-integration: install
	$(PYTEST) -m integration

simulator: install
	$(PY) -m pipeline.simulator

preprocess: install
	$(PY) -m pipeline.preprocess

train: install
	$(PY) -m pipeline.train

infer: install
	$(PY) -m pipeline.infer

dashboard: install
	PYTHONPATH=$(CURDIR) $(STREAMLIT) run pipeline/dashboard/app.py \
		--server.headless true --server.port 8501

run: install stop
	@mkdir -p $(LOG_DIR) $(PIDS)
	@echo "Starting pipeline (logs in $(LOG_DIR)/)..."
	@nohup $(PY) -m pipeline.simulator >$(LOG_DIR)/simulator.log 2>&1 & echo $$! > $(PIDS)/simulator.pid
	@nohup $(PY) -m pipeline.preprocess >$(LOG_DIR)/preprocess.log 2>&1 & echo $$! > $(PIDS)/preprocess.pid
	@nohup $(PY) -m pipeline.train >$(LOG_DIR)/train.log 2>&1 & echo $$! > $(PIDS)/train.pid
	@nohup $(PY) -m pipeline.infer >$(LOG_DIR)/infer.log 2>&1 & echo $$! > $(PIDS)/infer.pid
	@nohup env PYTHONPATH=$(CURDIR) $(STREAMLIT) run pipeline/dashboard/app.py \
		--server.headless true --server.port 8501 >$(LOG_DIR)/dashboard.log 2>&1 & echo $$! > $(PIDS)/dashboard.pid
	@echo "Dashboard: http://localhost:8501"
	@echo "Stop with: make stop"

stop:
	@if [ -d "$(PIDS)" ]; then \
		for f in $(PIDS)/*.pid; do \
			[ -f "$$f" ] || continue; \
			pid=$$(cat "$$f"); \
			kill $$pid 2>/dev/null || true; \
			rm -f "$$f"; \
		done; \
	fi
	@pkill -f "python -m pipeline.simulator" 2>/dev/null || true
	@pkill -f "python -m pipeline.preprocess" 2>/dev/null || true
	@pkill -f "python -m pipeline.train" 2>/dev/null || true
	@pkill -f "python -m pipeline.infer" 2>/dev/null || true
	@pkill -f "streamlit run pipeline/dashboard/app.py" 2>/dev/null || true
	@echo "Pipeline stopped."

# Cleans the directory the stages write to: DATA_ROOT if set, else data/.
# pipeline.paths resolves it, so the rules (and errors) match the pipeline's.
clean-data:
	@dir="$$($(PYTHON) -c 'from pipeline.paths import data_root; print(data_root())')" || exit 1; \
	rm -f "$$dir"/raw/orders_*.csv \
		"$$dir"/features/features_*.csv "$$dir"/features/.done_* \
		"$$dir"/models/checkpoint_*.joblib "$$dir"/models/metrics_*.json "$$dir"/models/train_state.json \
		"$$dir"/predictions/predictions_*.csv \
		"$$dir"/quality/batch_quality.csv; \
	echo "Runtime data cleared in $$dir"

clean: clean-data
	@rm -rf $(LOG_DIR) .pytest_cache
	@find . -type d -name __pycache__ -not -path './.venv/*' -exec rm -rf {} + 2>/dev/null || true
	@echo "Clean complete."
