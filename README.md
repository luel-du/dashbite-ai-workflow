# DashBite — Simple Stage-by-Stage ML Pipeline

> Based on the [DashBite teaching demo](https://github.com/ammylin/TestingAndContainerizationDemo)
> by Kedar and Ammy Lin, introduced in class.

**Repository B, Option 1: extend and containerize DashBite.** This repository takes the class
demo and makes it ready to run in containers, built through an Architect, Builder, Tester
workflow with an AI assistant. Added on top of the demo: a multi-stage non-root image, a Compose
stack with health checks and graceful shutdown, a configurable data folder, pinned dependencies,
and a test suite that runs on the host and in a container. To run it, see
[Run with Docker](#run-with-docker). For how it was built, see
[AI workflow reflection](#ai-workflow-reflection).

Teaching demo of a modular data + ML application. **DashBite** predicts whether a food-delivery order will be **late**.

Stages are separate Python modules that share folders under `data/` (or `DATA_ROOT`). Training and inference are **independent processes** coupled only by timestamped checkpoints in `data/models/`. Inference always uses the **newest** checkpoint. The stages run directly on the host or as containers built from one image; see [Run with Docker](#run-with-docker).

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

In each terminal, activate the virtual environment first (`source .venv/bin/activate`), or use the matching `make` target (`make simulator`, `make preprocess`, `make train`, `make infer`), which uses `.venv` for you. Without it, `python` is either missing or lacks the dependencies.

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
| `POLL_INTERVAL_SECONDS` | `2.0` | Sleep between polls/ticks; must be greater than 0 |
| `RANDOM_SEED` | `42` | Training seed |
| `CORRUPT_BATCH_RATE` | `0.25` | Fraction of batches that include NaNs / bad types |
| `DATA_ROOT` | `<project>/data` | The data directory itself (holds `raw/`, `features/`, ...) |
| `HEALTH_DIR` | `<system temp dir>/dashbite-health` | Where each stage touches its heartbeat file |
| `HEALTH_MAX_AGE_SECONDS` | `30` | A heartbeat older than this is unhealthy; must be greater than 0 |

`DATA_ROOT` and `HEALTH_DIR` must be absolute paths. A leading `~` is expanded; a relative value stops the stage with an error, because each process would resolve it against its own working directory. An empty value counts as unset.

`POLL_INTERVAL_SECONDS` and `HEALTH_MAX_AGE_SECONDS` must be positive, finite numbers. A poll interval of `0` or less (or `nan`, `inf`) stops the stage with an error, because it would poll without a pause. With an invalid threshold the health probe reports unhealthy and exits 1.

Preprocess logs per-batch **throughput** and **field-level failures** to `data/quality/batch_quality.csv`. Model Pulse shows these live.

## Run with Docker

One image, `dashbite:local`, runs all five services; Compose gives each service its own command. Tested with Docker Engine 29.7 and Compose 5.4.

```bash
docker compose up -d --build --wait   # build, start, wait until all five are healthy
docker compose ps                     # state and health per service
docker compose logs -f preprocess     # follow one stage
docker compose stop                   # graceful stop; containers and data kept
docker compose down                   # remove containers; data kept
docker compose down -v                # also delete the data volume (full reset)
bash scripts/smoke.sh                 # end-to-end check in a throwaway project
```

The dashboard is at http://127.0.0.1:8501.

### What the image contains

- Built in stages: `base` (environment, runtime dependencies, `pipeline/`), `test` (adds pytest and `tests/`) and `runtime` (the default target, identical to `base`). The runtime image has no tests and no pytest.
- Runs as a non-root user, uid 10001.
- Sets `PYTHONPATH=/app`, so `pipeline` is importable from any working directory, and `DATA_ROOT=/data`.
- Installs the exact versions listed in `constraints.txt`.
- Pipeline data lives in the named volume `dashbite_dashbite-data`, mounted at `/data` in every service.

### Configuration

Compose reads these from your shell and falls back to the defaults below, for example `TRAIN_EVERY_N_EVENTS=100 DASHBOARD_PORT=8600 docker compose up -d --wait`.

| Variable | Compose default | Meaning |
|----------|-----------------|---------|
| `TRAIN_EVERY_N_EVENTS` | `50` | Retrain after this many **new** labeled rows |
| `BATCH_SIZE` | `20` | Orders per simulator tick |
| `POLL_INTERVAL_SECONDS` | `2` | Wait between polls/ticks; must be greater than 0, or the workers stop with an error |
| `CORRUPT_BATCH_RATE` | `0.25` | Fraction of batches that include NaNs / bad types |
| `RANDOM_SEED` | `42` | Training seed |
| `HEALTH_MAX_AGE_SECONDS` | `30` | A worker whose heartbeat is older than this is unhealthy. Must be larger than `POLL_INTERVAL_SECONDS` plus the time one iteration takes, or healthy workers are reported unhealthy between iterations |
| `DASHBOARD_PORT` | `8501` | Host port for the dashboard, bound to `127.0.0.1` |
| `DATA_ROOT` | `/data` | Set in the image to match the volume mount; not read from your shell |
| `HEALTH_DIR` | unset | Heartbeats go to `/tmp/dashbite-health` inside each container, not on the shared volume |

### Health checks

| Service | Probe | Proves | Does not prove |
|---------|-------|--------|----------------|
| simulator, preprocess, train, infer | `python -m pipeline.health <stage>`: the heartbeat file in `HEALTH_DIR` is newer than `HEALTH_MAX_AGE_SECONDS` | The loop started or finished an iteration recently, so the process is alive and not hung | That the stage produced output, or correct output. Infer is healthy while it waits for a checkpoint |
| dashboard | Python `urllib` request to `http://127.0.0.1:8501/_stcore/health` | The Streamlit server is up and answering HTTP on 8501 | That the app imports or renders. The launch test and the smoke script's import check cover that gap |

Each probe runs every 10 seconds (every 2 seconds during the first 30), and three failures in a row mark the service unhealthy.

Docker does not restart unhealthy containers. Health status feeds `docker compose ps` and `docker compose up --wait`; `restart: unless-stopped` restarts a stage that crashes.

### Shutdown

`docker compose stop` sends SIGTERM. Each worker finishes its current iteration, prints `<stage> stopped cleanly (SIGTERM)` and exits with code 0, usually within a second. Streamlit handles SIGTERM itself. A service that has not stopped after 15 seconds (`stop_grace_period`) is killed.

The stages behave the same on the host: SIGTERM or Ctrl-C ends the loop after the current iteration.

To check it, wait for startup first:

```bash
docker compose up -d --wait --wait-timeout 120
docker compose stop
docker compose ps -a --format 'table {{.Service}}\t{{.State}}\t{{.ExitCode}}'   # every service 0
```

### Tests in a container

```bash
docker compose --profile test run --rm --build tests
```

This runs the same suite as `make test` in the `dashbite:test` image. Keep `--build`: a plain `docker compose build` skips the `tests` service because of its profile, and `run` alone only builds when the image is missing, so without it you can test a stale image.

To see the launch test catch a missing `PYTHONPATH`, this must fail:

```bash
docker compose --profile test run --rm -e PYTHONPATH= tests \
  pytest tests/integration/test_dashboard_launch.py
```

### Smoke script

`bash scripts/smoke.sh` builds the image and starts all five services under a separate Compose project, `dashbite-smoke`, so it never touches the normal containers or data volume. It removes its own containers, network and volume on exit, and exits non-zero if any check fails.

It checks that every service is healthy, that containers run as uid 10001 without pytest, that the dashboard answers and its app imports, that every stage produced output, that data survives `down`/`up`, and that a stop gives exit code 0 everywhere.

It refuses to start if the dashboard port is busy; run `docker compose down` first or set `DASHBOARD_PORT`.

### Re-pinning dependencies

`constraints.txt` is the output of `pip freeze` in the `dashbite:test` image; `make install` and the Dockerfile both install against it. To move to newer versions:

```bash
: > constraints.txt                                  # build once without pins
docker compose --profile test build tests
docker run --rm dashbite:test pip freeze > constraints.txt
docker compose --profile test build                  # rebuild with the new pins
make test
```

### Volume from the earlier setup

The earlier Compose file had no project name, so its volume is `testingandcontainerizationdemo_dashbite-data`. It is owned by root and was mounted at `/app/data`. The current setup uses the new volume `dashbite_dashbite-data`; it does not read, migrate or delete the old one. Remove the old volume yourself when you no longer need it: `docker volume rm testingandcontainerizationdemo_dashbite-data`.

### Known limitations

- **Startup window.** For about the first second, while Python imports its libraries, a stage has no SIGTERM handler yet. A stop in that window ends the service at once with exit code 143 instead of 0. Nothing is being written at that point. Wait for healthy (`up --wait`) before stopping if the exit code matters.
- **Stale heartbeat after a restart.** Heartbeat files survive a restart of the same container. For up to `HEALTH_MAX_AGE_SECONDS` after `stop` then `up`, or after a crash restart, a worker can be reported healthy before it has finished starting. Fresh containers after `down` are not affected.
- **Health is liveness, not correctness.** See the "Does not prove" column above.
- **No atomic writes.** A reader could in principle see a half-written file on the shared volume.
- **Unbounded data growth.** There is no retention; `docker compose down -v` resets.
- **Single replica per stage.** The `.done_` markers and the "already scored" filter are not safe with several replicas.
- **Bind mounts.** Mounting a host directory instead of the named volume hits uid mismatches on Linux.
- **Test image is not the runtime image.** They share the `base` stage, but only the smoke script checks the real runtime containers.
- **Pins come from a Linux image.** `constraints.txt` may not install on macOS or Windows hosts.
- **No automated check that the dashboard shows the data.** The tests and the smoke script check that the dashboard app imports and that the server answers, not that the pages show the pipeline's data. If the dashboard stopped honouring `DATA_ROOT`, it would show empty pages in the container while every check stayed green. The render test that would catch this was cut for time. The dashboard was checked by hand instead: both pages were opened in a browser against the running containers and showed live data.
- **No test that the stop handlers are installed before the start banner.** The shutdown test sends SIGTERM as soon as a stage prints its banner and relies on that order, but nothing asserts the order directly. A regression would show up as an occasional failure of that test rather than a clear one.

### This README and the Docker guide

Where this README and `docs/docker-k8s-guide.md` disagree, this README is authoritative. The guide is an earlier design note; for example it uses the tag `dashbite:latest`, the data path `/app/data` and a dashboard port published on all interfaces.

## Design notes for class

- Intake uses **batch CSV files** under the hood; logs say “new orders arrived”.
- Train **only writes** `data/models/checkpoint_*.joblib`.
- Infer **only reads** that folder and never imports train.
- Dashboards read `data/features/` and `data/predictions/` — test the metric helpers with `pytest`, not the browser UI.

## Manual smoke test

I ran this myself on 2026-10-01 (Linux, Docker Desktop), after the Builder finished and before
the Tester stage.

| Step | Result |
|---|---|
| `bash scripts/smoke.sh` | All 14 checks passed: `SMOKE PASSED` |
| Services | All five reported healthy and ran as uid 10001 |
| Pipeline output | Raw files, features, quality log, a checkpoint and predictions appeared within 90 s |
| Persistence | Raw files survived `down` then `up` (4 before, 5 after) |
| Shutdown | All five services exited with code 0 on stop |
| Dashboard in a browser | Opened `http://127.0.0.1:8501`: the page loaded and worked, with no import error |

<details>
<summary>Output of <code>bash scripts/smoke.sh</code> from that run</summary>

```text
== build and start (project dashbite-smoke, port 8501)
== checks
PASS  simulator is healthy
PASS  preprocess is healthy
PASS  train is healthy
PASS  infer is healthy
PASS  dashboard is healthy
PASS  containers run as uid 10001
PASS  pytest is not in the runtime image
PASS  dashboard answers on http://127.0.0.1:8501/_stcore/health
PASS  dashboard app imports without the working directory on sys.path
PASS  raw, features, quality log, checkpoint and predictions exist within 90s
PASS  data is owned by uid 10001
PASS  heartbeat files are not on the data volume
== persistence: down (volume kept), then up
PASS  raw files survive down/up (4 before, 5 after)
== graceful shutdown: stop after startup
dashboard: exited, exit code 0
infer: exited, exit code 0
preprocess: exited, exit code 0
simulator: exited, exit code 0
train: exited, exit code 0
PASS  all five services exited with code 0
SMOKE PASSED
```

</details>

The browser check matters because nothing automated covers it: the health endpoint reports
`ok` even when the app fails to import, which is how the original image was broken.

## AI workflow reflection

**Option and purpose.** Option 1: extend and containerize DashBite, the late-delivery prediction
pipeline from class. The goal was a stack that builds, starts, reports its health, stops cleanly
and keeps its data, with tests proving each of those.

**Install, run, test.**

```bash
make install && make test                              # host: 93 tests
docker compose up -d --build --wait                    # five services, all healthy
docker compose --profile test run --rm --build tests   # the same suite in a container
bash scripts/smoke.sh                                  # end-to-end check, cleans up after itself
```

**How each role contributed.** Each role was a fresh conversation in Claude Code. The
transcripts are in [`docs/transcripts/`](docs/transcripts/).

| Role | Contribution |
|---|---|
| Architect | Read the code and wrote [`docs/plan.md`](docs/plan.md): findings, options with trade-offs, five milestones and exact verification commands. It found that the dashboard in the class image could not import its own package. |
| Builder | Implemented the plan one milestone at a time, stopping for review after each. Tests grew from 33 to 78. It found that the plan's own shutdown check failed and stopped to ask. Approved differences are in [`docs/changes-from-plan.md`](docs/changes-from-plan.md). |
| Tester | Worked only from the plan, the changes file and the code. It confirmed every requirement, then found six problems by trying to break things, including a `make stop` bug that predates this work. |

**Recommendations I accepted.**

- The Builder noticed that the documented test command could silently run a stale image, and
  proposed `--build`. That is now the documented command.
- When a stop sent in the first second killed every service with exit code 137, the Builder
  proposed adding an init process next to the signal handlers. I accepted it on the condition
  that it tested the combination first.
- The Architect advised against startup ordering between services, because each stage already
  tolerates missing input.

**Recommendations I changed or rejected.**

- I did not accept the first draft plan as written. Its main finding said the dashboard
  "probably" crashed, and Docker had not been run. I had the Architect reproduce it first. The
  crash was real, but its shutdown timing was wrong (3 s, not 10 s), and the run showed that the
  health endpoint answers `ok` while the app is broken. The plan changed because of that.
- Rejected: read-only root filesystem hardening. It depended on Streamlit behaviour nobody had
  tested and added little here.
- Rejected: rewriting the class Docker guide. It is left untouched and the README is the
  reference.
- Declined two Tester findings. The host dashboard failure comes from a monitoring agent on my
  laptop, not from the repository. The missing render test was cut for time, so it is listed
  under known limitations and covered by a manual browser check.
- The Builder once implemented an answer before I had decided. I told it to answer first and
  wait, and it did from then on.

**How I verified the result independently.** I ran the smoke script and opened the dashboard in a
browser myself (see [Manual smoke test](#manual-smoke-test)). After each milestone the host
tests, the containerized tests, the negative control and the container checks were rerun outside
the Builder's conversation before I committed. The Tester's fixes were rerun the same way: 93
tests pass and `make stop` exits 0.

**What I learned.**

- **Refine the question instead of accepting the first answer.** The most useful moments came
  from follow-up questions: asking for a reproduction, asking what happens with `~` or a
  relative path in `DATA_ROOT`, asking which test would have caught the dashboard bug. Each one
  changed the outcome.
- **Write the plan down and keep it.** Because the plan and the list of approved changes are
  files in the repository, three separate conversations could work from the same reference, the
  Tester could judge the work without seeing the Builder's explanations, and I can check later
  why a decision was made.

**Disclosure.** Besides the three role conversations, I used a separate AI chat as a second
reviewer. It reran checks, pointed out edge cases, and helped me draft follow-up questions and
this README text. I chose what to send and what to accept.
