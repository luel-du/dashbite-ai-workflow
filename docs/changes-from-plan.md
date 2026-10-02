# Changes from the plan

`docs/plan.md` is the Architect's approved plan and is left as written. This
file lists every place where the implementation differs from it, and why.

The "Approval" column says how each difference was accepted:

- **Decided**: the repository owner chose it explicitly.
- **Reviewed**: a small Builder decision, reported at the milestone and accepted
  with it.
- **M5**: made in the last milestone and reported in the hand-off.

## Behaviour and design

| # | Milestone | Plan | Implementation | Why | Approval |
|---|---|---|---|---|---|
| 1 | M1 | `DATA_ROOT` unset keeps the default. | An empty `DATA_ROOT` also counts as unset. | An empty value would otherwise resolve to the current working directory. | Decided |
| 2 | M1 | `DATA_ROOT` is used as given. | A leading `~` is expanded; a value that is still relative raises `ValueError`. | `DATA_ROOT=~/dash` created a folder literally named `~`, and a relative value resolved against each stage's working directory, so stages could silently stop sharing data. | Decided |
| 3 | M1 | `make clean-data` is not mentioned; it cleaned the fixed `data/` path. | It cleans the directory `pipeline.paths.data_root()` returns, and only files the pipeline writes (`raw/orders_*.csv`, `quality/batch_quality.csv` instead of `raw/*.csv`, `quality/*.csv`). | It must clean where the stages write. The target can now be any directory, so the patterns were narrowed. | Decided |
| 4 | M2 | Containerized tests: `docker compose build`, then `docker compose --profile test run --rm tests`. | Documented as `docker compose --profile test run --rm --build tests`. | Plain `build` skips the profile-gated `tests` service and `run` only builds a missing image, so the plan's form can test a stale image. | Decided |
| 5 | M3 | `init: true` is listed as the rejected alternative to in-process signal handling. | Both are used: the stages handle SIGTERM themselves, and `init: true` is set on the five services. | For about the first second (Python imports) a stage has no handler. As PID 1 it ignored SIGTERM, kept running and was killed after 15 s with exit 137. With an init process an early stop ends it at once with 143, while nothing is being written. After startup the stage still exits 0. | Decided |
| 6 | M3 | Shutdown check: `docker compose up -d`, then `docker compose stop`, expect exit 0 everywhere. | The check waits for startup first: `docker compose up -d --wait --wait-timeout 120`, then `stop`. An immediate stop is expected to give 143, never 137. | The back-to-back form stops inside the startup window of item 5. | Decided |
| 7 | M3 | Not in the plan's known limitations. | The startup window is a documented known limitation (README, comment in `compose.yaml`). | It cannot be closed for the dashboard, whose window is inside Streamlit's own startup. | Decided |
| 8 | M4 | `HEALTH_DIR` is used as given. | Same rule as `DATA_ROOT`: `~` expanded, relative values rejected. The probe reports the error and exits 1. | The stage and the probe would each resolve a relative value against their own working directory. | Decided |
| 9 | M4 | The heartbeat threshold is configurable (risk 3). | No design change. The README states that `HEALTH_MAX_AGE_SECONDS` must exceed `POLL_INTERVAL_SECONDS` plus one iteration. | A poll interval at or above the threshold makes healthy workers flap to unhealthy, because the heartbeat is written between waits. | Decided |
| 10 | M4 | Not in the plan's known limitations. | A stale heartbeat after a restart of the same container is a documented known limitation. | The file survives the restart, so a worker can look healthy for up to the threshold before it has finished starting. | Decided |
| 11 | M5 | Nice-to-have items N1, N2 and N3 may follow M5 on request. | None of them was built. | The owner chose to skip them. | Decided |

## Smaller implementation differences

| # | Milestone | Plan | Implementation | Why | Approval |
|---|---|---|---|---|---|
| 12 | M1 | One line changes in `pipeline/dashboard/app.py`. | Two lines: `base = None`, and `PROJECT_ROOT` removed from the import. | The change left the import unused. | Reviewed |
| 13 | M1 | — | `pipeline/paths.py` exports a constant `DATA_ROOT_ENV`. | One place for the variable name. | Reviewed |
| 14 | M2 | User: uid 10001, owning `/data`. | A real user `dashbite` (uid and gid 10001) with a home directory. | Streamlit writes to `~/.streamlit`. | Reviewed |
| 15 | M2 | The `test` stage adds only dev dependencies and the tests. | It also creates `/app/.pytest_cache`, owned by uid 10001. | pytest can write its cache while the code stays root-owned. | Reviewed |
| 16 | M2 | `${VAR:-default}` for the tunables. | `RANDOM_SEED` is included alongside the four the old Compose file had. | `Config.from_env` reads it. | Reviewed |
| 17 | M2 | `.dockerignore`: stop excluding `tests`; exclude `.env`, `hello-docker`, `docs`, `data`. | Also excludes `.gitignore` and uses `**/__pycache__` and `**/*.pyc`. | The old patterns only matched at the top level, so nested bytecode would have been sent to the build. | Reviewed |
| 18 | M2 | README: fix the dashboard command and make `make test` the gate. | The manual setup block also changed: it installs `requirements-dev.txt` with `constraints.txt` and exports `PYTHONPATH=.`. | The old block installed unpinned versions and left `pipeline` unimportable for the manual commands. | Reviewed |
| 19 | M3 | `run_polling_loop(step, interval, stage)`. | `run_polling_loop(step, interval, stage, *, banner=None, stop=None)`. | The helper prints the banner so the handlers are installed first; `stop` lets unit tests drive the loop without signals. | Reviewed |
| 20 | M3 | — | The loop restores the previous signal handlers when it returns and prints `<stage> stopped cleanly (<signal>)`. | Keeps the in-process signal tests from leaking into pytest, and makes a graceful stop visible in the logs. | Reviewed |
| 21 | M3 | Only `run_loop` changes in the four stage modules. | The unused `import time` was removed from `simulator.py`, `preprocess.py` and `train.py`. | The change left it unused. | Reviewed |
| 22 | M4 | No timing given for the health checks. | Interval 10 s, timeout 5 s, 3 retries, start period 30 s with a 2 s start interval. | Values were needed; the short start interval lets `up --wait` return in a few seconds. | Reviewed |
| 23 | M4 | "CLI exit codes" are not specified. | The probe exits 0 when healthy and 1 for everything else, including bad usage. | Docker reserves exit code 2 for health checks. | Reviewed |
| 24 | M5 | `scripts/smoke.sh` fails fast if port 8501 is busy. | It honours `DASHBOARD_PORT` (default 8501), fixes the pipeline tunables itself, and accepts `SMOKE_START_TIMEOUT` and `SMOKE_OUTPUT_TIMEOUT`. It also checks persistence across `down`/`up` and exit code 0 after a stop. | The run should not depend on the caller's shell or need port 8501, and the plan calls the script the only check against the real runtime containers. | M5 |
| 25 | M5 | README env table in the "Run with Docker" section. | Two tables: host defaults under "Config (environment)", Compose defaults under "Run with Docker". | The defaults differ (for example `TRAIN_EVERY_N_EVENTS` is 2000 on the host and 50 in Compose). | M5 |
| 26 | M5 | — | The README also documents how to re-pin `constraints.txt` and the smoke script. | The pinning file needs an empty-file bootstrap that is not obvious. | M5 |

## Tests beyond the plan's lists

The plan names the cases each new test file must cover. All of them are
covered, the 33 original tests are unchanged, and no planned test was dropped.
These cases were added:

| File | Added cases | Approval |
|---|---|---|
| `tests/unit/test_data_root.py` | Variable re-read on each call; empty value; `ensure_data_dirs()` under the env root; `~` expansion; relative values rejected and nothing created; explicit `base` ignores an invalid value. | Reviewed (the `~` and relative cases were requested) |
| `tests/unit/test_runtime.py` | Stop already set; banner and stop message order; a real SIGTERM and SIGINT finish the iteration and restore the handlers; heartbeat written at start and after each iteration. | Reviewed |
| `tests/integration/test_graceful_shutdown.py` | A 30 s poll interval, so only an interrupted wait can pass; the stop message; the heartbeat file appears in the test's own `HEALTH_DIR`. | Reviewed |
| `tests/unit/test_health.py` | Per-stage files; threshold from the environment; default directory; the real `python -m pipeline.health` command; the module imports no heavy packages; `~` expansion and relative values rejected. | Reviewed (the `HEALTH_DIR` rule cases were requested) |
