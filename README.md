# DashBite — Simple Stage-by-Stage ML Pipeline

> Based on the [DashBite teaching demo](https://github.com/ammylin/TestingAndContainerizationDemo)
> by Kedar and Ammy Lin, introduced in class.

Teaching demo of a modular data + ML application. **DashBite** predicts whether a food-delivery order will be **late**.

No containers. Stages are separate Python modules that share folders under `data/`. Training and inference are **independent processes** coupled only by timestamped checkpoints in `data/models/`. Inference always uses the **newest** checkpoint.

## Stages

| Stage | Module | What it does |
|-------|--------|----------------|
| 0 | `pipeline.config`, `pipeline.paths` | Shared config + data folders |
| 1 | `pipeline.simulator` | Writes timed CSV batches to `data/raw/` (“new orders arrived”) |
| 2 | `pipeline.preprocess` | Drops bad rows, adds `hour` / `is_peak` → `data/features/` |
| 3 | `pipeline.train` | Retrains when ≥ `TRAIN_EVERY_N_EVENTS` new labeled rows; writes checkpoints |
| 4 | `pipeline.infer` | Scores unscored rows with newest checkpoint → `data/predictions/` |
| 5–6 | `pipeline.dashboard` | Streamlit: **Model Pulse** + **Ops Control** |

## Setup

```bash
make install
```

Or manually:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt -c constraints.txt
export PYTHONPATH=.
```

`requirements.txt` lists the runtime dependencies, `requirements-dev.txt` adds pytest, and `constraints.txt` pins every package to the versions the Docker image uses. `PYTHONPATH=.` makes the `pipeline` package importable; the `make` targets set it for you, and the manual `pytest` and `streamlit` commands below need it.

## Makefile shortcuts

```bash
make help          # list targets
make test          # full pytest gate
make run           # start all stages in background + dashboard
make stop          # stop background pipeline
make clean-data    # wipe runtime CSVs/checkpoints under data/ (or DATA_ROOT if set)
```

Foreground single stages: `make simulator`, `make preprocess`, `make train`, `make infer`, `make dashboard`.

## Testing gate (required after every stage)

After each stage you implement or change, run the **full** suite:

```bash
make test
```

That runs **unit**, **regression**, and **integration** tests together so new work cannot break older stages. `make test` is the gate: it uses the pinned `.venv` and sets `PYTHONPATH`. A bare `pytest` without `PYTHONPATH` fails the dashboard launch test, which checks that `pipeline` is importable the way `streamlit run` needs it.

```bash
make test-unit
make test-regression
make test-integration
```

Layout:

```
tests/
  unit/
  regression/
  integration/
  fixtures/
```

## Run the pipeline (separate terminals)

Use a small retrain threshold for demos:

```bash
export TRAIN_EVERY_N_EVENTS=50
export BATCH_SIZE=20
```

Terminal 1 — intake:

```bash
python -m pipeline.simulator
```

Terminal 2 — preprocess:

```bash
python -m pipeline.preprocess
```

Terminal 3 — train (write path only):

```bash
python -m pipeline.train
```

Terminal 4 — infer (read path only; picks newest checkpoint):

```bash
python -m pipeline.infer
```

Terminal 5 — dashboards:

```bash
make dashboard
# or: PYTHONPATH=. streamlit run pipeline/dashboard/app.py
```

`streamlit run` does not put the working directory on the import path, so without `PYTHONPATH` the page fails with `ModuleNotFoundError: No module named 'pipeline'`.

## Config (environment)

| Variable | Default | Meaning |
|----------|---------|---------|
| `TRAIN_EVERY_N_EVENTS` | `2000` | Retrain after this many **new** labeled rows |
| `BATCH_SIZE` | `50` | Orders per simulator tick |
| `POLL_INTERVAL_SECONDS` | `2.0` | Sleep between polls/ticks |
| `RANDOM_SEED` | `42` | Training seed |
| `CORRUPT_BATCH_RATE` | `0.25` | Fraction of batches that include NaNs / bad types |

Preprocess logs per-batch **throughput** and **field-level failures** to `data/quality/batch_quality.csv`. Model Pulse shows these live.

## Design notes for class

- Intake uses **batch CSV files** under the hood; logs say “new orders arrived”.
- Train **only writes** `data/models/checkpoint_*.joblib`.
- Infer **only reads** that folder and never imports train.
- Dashboards read `data/features/` and `data/predictions/` — test the metric helpers with `pytest`, not the browser UI.
