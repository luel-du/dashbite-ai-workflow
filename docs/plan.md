# Plan: container-ready DashBite

Status: approved on 2026-10-01. Written by the Architect; implemented by the Builder.

Goal: make the DashBite pipeline ready to run in containers, with a suitable
Dockerfile, a Compose configuration, tests, documentation, and four further
container-readiness improvements (configurable data root, graceful shutdown,
health checks, containerized tests).

## 1. Verified findings in the current files

These were reproduced against the unchanged repository (commit `e022720`),
image `dashbite:demo`, Docker Desktop server 29.7.2, Compose 5.4.0.

| # | Finding | Evidence |
|---|---|---|
| 1 | The dashboard fails on every page load with `ModuleNotFoundError: No module named 'pipeline'`. The image sets no `PYTHONPATH`, and `streamlit run` adds only the script's own folder to `sys.path`, never the working directory. | Reproduced in headless Chrome and in the server log. The same image with `-e PYTHONPATH=/app` renders the Model Pulse page. |
| 2 | Workers ignore SIGTERM. They are killed after the grace period (3 s on this engine) and exit with code 137. | Docker events: SIGTERM at +0.0 s, SIGKILL at +3.0 s, four workers exit 137, dashboard exits 0. `docker stop -t 10` takes 10.25 s and also ends in 137. With `--init` the stop takes 0.2 s but exits 143. |
| 3 | Streamlit's `/_stcore/health` returned `ok` the whole time finding 1 was happening. | Observed during the reproduction. |
| 4 | The data path is hard-wired to `<code dir>/data`. | `pipeline/paths.py:27`, `pipeline/dashboard/app.py:46` |
| 5 | Containers run as root and write root-owned data. There are no health checks and no restart policy. | `stat` in the volume showed owner `0:0`. |
| 6 | Tests cannot run in a container, and the 33 host tests passed while finding 1 existed. | `.dockerignore` excludes `tests`; `pytest.ini` sets `pythonpath = .`, which hides the missing `PYTHONPATH` from every in-process test. |
| 7 | Dependencies are unpinned. The image resolved Streamlit 1.64.0 while the host had 1.48.0. | `pip list` in the image. |
| 8 | The README's `streamlit run pipeline/dashboard/app.py` very likely fails on the host the same way. | `python3 -P -c "import pipeline.dashboard.app"` fails on the host with no `PYTHONPATH`. `make dashboard` works because the Makefile exports it. |

## 2. Requirements

- **R1 Dockerfile:** one image for all five services; non-root; `pipeline`
  importable from the environment; runtime image has no tests or pytest; pinned
  dependencies.
- **R2 Compose:** five services plus an opt-in `tests` service; shared
  persistent volume; env-driven config.
- **R3 Tests:** the 33 existing tests stay unchanged and green; new behaviour is
  covered; the same suite runs on the host and in a container.
- **R4 Docs:** everything is documented in `README.md`.
  `docs/docker-k8s-guide.md` is not touched.
- **R5 Improvements:** configurable data root, graceful shutdown, health checks,
  containerized tests.
- **R6 Gate:** `make test` is the documented host gate.

## 3. Rules for the Builder

1. **New tests never write into the repo's `data/` folder.** In-process tests
   pass `tmp_path` as `base` or set `DATA_ROOT` with `monkeypatch`, as the
   existing tests do with `tmp_path`. Subprocess tests pass the inherited
   environment plus `DATA_ROOT` and `HEALTH_DIR` pointing into `tmp_path`.
2. **The README sections "Manual smoke test" and "AI workflow reflection"
   belong to the repository owner.** The Builder adds both as empty headings and
   writes no content or results under them.
3. **Nothing is dropped silently.** If a test or a nice-to-have item is dropped
   or changed, the Builder says so in the hand-off, with the reason.
4. **Leave existing Docker state alone.** Do not delete the volume
   `testingandcontainerizationdemo_dashbite-data` or the image `dashbite:demo`
   (it is the "before" for the size comparison).
5. **Do not edit** `docs/docker-k8s-guide.md`,
   `docs/lld-dashbite-ml-pipeline.md`, `hello-docker/`, the fixtures, the 33
   existing tests, or any pure stage function.

## 4. Design decisions

| Area | Decision | Rejected alternative and why |
|---|---|---|
| Data root | `paths.data_root()` reads `DATA_ROOT` at call time. An explicit `base` still wins; unset keeps today's default. The container uses `/data`. Note that `base` means "project root" (data lives in `base/data`), while `DATA_ROOT` is the data directory itself. | A `Config` field breaks the frozen-defaults regression test, and the path helpers do not take a config. Keeping `/app/data` leaves the path unconfigurable. |
| Image layout | Multi-stage: `base`, then `test`, then `runtime` (last, so it is the default target). All `ENV`, `WORKDIR` and code layout live in `base`; `test` adds only dev dependencies and the tests. | A single image ships pytest and tests in the runtime image. Bind-mounting tests is not self-contained. |
| Import fix | `ENV PYTHONPATH=/app` in `base`. | A `pyproject.toml` with an editable install fixes the host too but is more than this assignment needs. |
| Base image | `python:3.12-slim`, matching the host's Python 3.12. | Alpine means musl wheel trouble for numpy and scikit-learn. |
| User | uid 10001, owning `/data`. | Root, as today. |
| Pinning | `constraints.txt` produced by `pip freeze` in the `test` stage, used by the Dockerfile and by `make install`, so host and image install the same versions. | Exact pins in `requirements.txt` hide which packages are direct dependencies. |
| Requirements | `requirements.txt` holds runtime dependencies; `requirements-dev.txt` includes it and adds pytest. | One file puts pytest in the runtime image. |
| Shutdown | `pipeline/runtime.py` with `run_polling_loop(step, interval, stage)`. SIGTERM and SIGINT set an event, the current iteration finishes, `Event.wait()` replaces `time.sleep()`, and the process exits 0. Handlers are installed before the start banner prints. Streamlit already handles SIGTERM. | `init: true` stops in 0.2 s but with exit 143, mid-iteration. Turning SIGTERM into `KeyboardInterrupt` also interrupts mid-write. |
| Grace period | `stop_grace_period: 15s`, because the engine default here is 3 s. | Relying on the default. |
| Heartbeat location | Directory from the `HEALTH_DIR` environment variable, read at call time; default `<system temp dir>/dashbite-health`; one file per stage. Container-local in Compose (not on the shared volume). Tests set it to `tmp_path` so host runs never share a file. | A fixed path makes parallel host tests and local runs collide. The shared volume would mix liveness with pipeline data. |
| Health checks | Defined per service in `compose.yaml`, since one image needs two different probes. `pipeline/health.py` imports only the standard library so the probe is cheap. | A Dockerfile `HEALTHCHECK` can hold only one probe. Installing curl adds an apt layer for no gain. |
| Start order | No `depends_on`; the stages already tolerate missing inputs. | A `service_healthy` chain couples stages that were designed to be independent. |
| Project name | `name: dashbite`, image tags `dashbite:local` (runtime) and `dashbite:test`. | Reusing the old root-owned volume fails under uid 10001. |

### Health checks: what each one proves

| Service | Probe | Proves | Does not prove |
|---|---|---|---|
| simulator, preprocess, train, infer | `python -m pipeline.health <stage>`: the heartbeat file in `HEALTH_DIR` is newer than `HEALTH_MAX_AGE_SECONDS` (default 30). | The loop started or finished an iteration recently, so the process is alive and not hung. | That the stage produced output, or correct output. Infer is healthy while it waits for a checkpoint. |
| dashboard | Python `urllib` request to `http://127.0.0.1:8501/_stcore/health`. | The Streamlit server is up and answering HTTP on 8501. | That the app imports or renders (finding 3). That gap is covered by the import test, the smoke import check and the optional render test. |

Docker does not restart unhealthy containers. Health status feeds
`docker compose ps` and `docker compose up --wait`; `restart: unless-stopped`
covers crashes.

## 5. Must-have milestones

Every milestone ends with `make test` green. From M2 onward,
`docker compose --profile test run --rm tests` must be green too.

### M1. Configurable data root (host only)

- Edit `pipeline/paths.py` and one line in `pipeline/dashboard/app.py`
  (pass `None` instead of `PROJECT_ROOT`).
- New `tests/unit/test_data_root.py`: env honoured when `base` is `None`;
  explicit `base` wins; unset gives the old default.
- New `tests/integration/test_data_root_pipeline.py`: one pass of simulator,
  preprocess, train and infer using only the env var lands all output under it.

### M2. Image, Compose and containerized tests

- Rewrite `Dockerfile` (stages, non-root, `PYTHONPATH`, `DATA_ROOT=/data`) and
  `.dockerignore` (stop excluding `tests`; exclude `.env`, `hello-docker`,
  `docs`, `data`).
- Split `requirements.txt` and add `requirements-dev.txt`; add
  `constraints.txt`; `make install` uses both.
- Rewrite `compose.yaml`: project name, volume at `/data`, `${VAR:-default}` for
  the tunables and `DASHBOARD_PORT`, `tests` service under `profiles: [test]`
  with `build.target: test`.
- New `tests/integration/test_dashboard_launch.py`, the subprocess import test:

  ```python
  @pytest.mark.integration
  def test_dashboard_imports_without_cwd_on_sys_path(tmp_path):
      result = subprocess.run(
          [sys.executable, "-P", "-c", "import pipeline.dashboard.app"],
          cwd=PROJECT_ROOT,
          env={**os.environ, "DATA_ROOT": str(tmp_path)},
          capture_output=True, text=True, timeout=60,
      )
      assert result.returncode == 0, result.stderr
  ```

  It must stay a subprocess: a child inherits environment variables but not
  pytest's `sys.path`, and `-P` keeps the working directory off the path. Run
  against the unchanged image it gave `1 failed, 33 passed`; with
  `PYTHONPATH=/app` it gave `34 passed`.
- The Builder must show this test failing in the container with `PYTHONPATH`
  emptied, then passing normally (commands in section 11).
- README: fix the host dashboard command (`make dashboard`, or
  `PYTHONPATH=. streamlit run pipeline/dashboard/app.py`) and make `make test`
  the documented gate. These go in now so the docs are never wrong between
  milestones.

### M3. Graceful shutdown

- New `pipeline/runtime.py`; the four `run_loop` functions become thin wrappers.
- Add `stop_grace_period: 15s` to the services.
- New `tests/unit/test_runtime.py`: the loop runs its step and returns promptly
  once stop is set, even with a long interval.
- New `tests/integration/test_graceful_shutdown.py`: start each stage as a
  subprocess with `DATA_ROOT` and `HEALTH_DIR` in `tmp_path`, wait for its start
  banner, send SIGTERM, expect exit 0 within 5 s.

### M4. Health checks

- New `pipeline/health.py`; the loop helper writes the heartbeat once at start
  and after each iteration.
- Add per-service `healthcheck` and `restart: unless-stopped`.
- New `tests/unit/test_health.py`, with `HEALTH_DIR` in `tmp_path`: fresh is
  healthy; aged with `os.utime` is unhealthy; missing is unhealthy; CLI exit
  codes.

### M5. Smoke script and README

- New `scripts/smoke.sh`, running under its own project name `dashbite-smoke`
  and removing its own containers and volume on exit. It fails fast if port 8501
  is busy and exits non-zero on any failed check.
- README "Run with Docker" section:
  - commands and the env table (including `DATA_ROOT`, `HEALTH_DIR`,
    `HEALTH_MAX_AGE_SECONDS`, `DASHBOARD_PORT`);
  - the health table above and the shutdown behaviour;
  - containerized tests and the old-volume note;
  - known limitations;
  - a statement that the README is authoritative where it disagrees with
    `docs/docker-k8s-guide.md`.
- README: add "Manual smoke test" and "AI workflow reflection" as empty
  headings (rule 2).
- Report the image sizes in the hand-off (section 11).

## 6. Nice-to-have

| # | Item | Note |
|---|---|---|
| N1 | Render-level test: Streamlit `AppTest` in a clean child interpreter (`-P`) against fixture data seeded into a temporary `DATA_ROOT`. Needs one app change: a `key` on the auto-refresh checkbox so the test can switch it off; without it `AppTest` times out on the endless `st.rerun()`. | If it is flaky, the Builder may drop it and must say so. |
| N2 | Makefile wrappers: `docker-build`, `docker-test`, `docker-up`, `docker-down`, `docker-smoke`. | Convenience only. |
| N3 | Mount the data volume read-only for the dashboard. | The dashboard only reads data, so this is not the rejected read-only root filesystem. The Builder must confirm the page still renders with it. |

## 7. Important files

| Action | Files |
|---|---|
| Rewrite | `Dockerfile`, `compose.yaml`, `.dockerignore` |
| Edit | `pipeline/paths.py`, `pipeline/dashboard/app.py`, `run_loop` in `pipeline/simulator.py`, `pipeline/preprocess.py`, `pipeline/train.py`, `pipeline/infer.py`, `requirements.txt`, `Makefile`, `README.md` |
| New | `pipeline/runtime.py`, `pipeline/health.py`, `requirements-dev.txt`, `constraints.txt`, `scripts/smoke.sh`, `tests/unit/test_data_root.py`, `tests/unit/test_runtime.py`, `tests/unit/test_health.py`, `tests/integration/test_data_root_pipeline.py`, `tests/integration/test_dashboard_launch.py`, `tests/integration/test_graceful_shutdown.py` |
| Untouched | See rule 5 |

## 8. Risks and design concerns

1. **Signal test flakiness.** Mitigated by waiting for the banner and a generous
   timeout. If one stage stays flaky, the Builder reports it.
2. **Constraints across platforms.** `pip freeze` from a Linux image may not
   install on macOS or Windows hosts. Acceptable here: host and image are both
   Linux with Python 3.12.
3. **Heartbeat threshold on a large volume.** Train and infer re-read every
   feature file each poll, so iterations slow as data grows. The threshold is
   configurable.
4. **Test image is not the runtime image.** They share `base`, but the smoke
   script is the only check against the real runtime container.
5. **Stale guide.** `docs/docker-k8s-guide.md` will disagree with the
   implementation in places (for example the `DATA_ROOT` default).
6. **Bare `pytest` on the host.** The import test fails without `PYTHONPATH`,
   which is why `make test` is the gate.

## 9. Known limitations (accepted)

- **No atomic writes.** A reader could in principle see a half-written file on
  the shared volume. It was not observed: after a SIGKILL of all workers the
  volume was consistent (13 raw files, 13 feature files, 13 markers, 13 quality
  rows). The files are small, and graceful shutdown removes the mid-write kill.
- **Unbounded data growth.** There is no retention; `docker compose down -v`
  resets.
- **Single replica per stage.** The `.done_` markers and the "already scored"
  filter are not safe with several replicas.
- **Bind mounts.** A host directory instead of the named volume hits uid
  mismatches on Linux.

## 10. Out of scope

- Kubernetes, CI and registry push.
- Read-only root filesystem, `cap_drop` and other hardening.
- Retention and multi-replica logic.
- Model, feature or dashboard UI changes beyond the N1 checkbox key.
- Image digest pinning and vulnerability scanning.
- Deleting the old volume or the `dashbite:demo` image.

## 11. Verification

Start Docker Desktop first.

```bash
# After every milestone
make test
find data -type f ! -name .gitkeep                                # prints nothing (rule 1)

# M2: image and containerized tests
docker compose config --quiet
docker compose build
docker compose --profile test run --rm tests                      # all pass
docker compose --profile test run --rm -e PYTHONPATH= tests \
  pytest tests/integration/test_dashboard_launch.py               # must FAIL (negative control)
docker run --rm dashbite:local python -c "import pytest"          # must FAIL (not in runtime image)
docker run --rm dashbite:local id -u                              # 10001

# M2: pinning (run once, commit the file, then rebuild)
docker run --rm dashbite:test pip freeze > constraints.txt

# M3: graceful shutdown (judge by exit code, not time)
docker compose up -d
docker compose stop
docker compose ps -a --format 'table {{.Service}}\t{{.State}}\t{{.ExitCode}}'   # every service 0, none 137

# M4: health
docker compose up -d --wait --wait-timeout 120                    # fails unless all five are healthy
docker compose ps
curl -fsS http://127.0.0.1:8501/_stcore/health                    # ok
docker compose exec dashboard sh -c 'cd / && python -c "import pipeline.dashboard"'   # exit 0

# M5: pipeline output, persistence, size
docker compose exec infer sh -c 'ls /data/models/checkpoint_*.joblib /data/predictions/predictions_*.csv'
docker compose down && docker compose up -d --wait
docker compose exec preprocess sh -c 'ls /data/raw | wc -l'       # not reset to zero
docker compose down
docker images --format '{{.Repository}}:{{.Tag}}  {{.Size}}' | grep dashbite
bash scripts/smoke.sh                                             # exit 0

# N3 only: open http://127.0.0.1:8501 and confirm both pages render
```

### Image size

Report the `docker images` SIZE column for `dashbite:demo` (before, 1.04 GB),
`dashbite:local` and `dashbite:test` in the hand-off. Use the same column for
all three: `docker image inspect` reports a different, compressed figure
(239 MB for the current image).

Expect almost no reduction. The 1.04 GB is 623 MB of Python dependencies
(pyarrow, scipy, pandas, scikit-learn) on a 179 MB base, and pytest accounts for
about 4 MB. Pass means the runtime image is within about 2% of the old size and
the test image is only slightly larger. The gain from the multi-stage build is
that tests and pytest are not shipped, not a smaller image.
