# One image for all five services. Stages:
#   base     shared environment, runtime dependencies and the pipeline code
#   test     base + dev dependencies + tests (docker compose --profile test)
#   runtime  base, unchanged; last, so it is the default build target

FROM python:3.12-slim AS base

# PYTHONPATH makes `pipeline` importable from any working directory, which
# `streamlit run` needs: it only adds the script's own folder to sys.path.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    DATA_ROOT=/data

WORKDIR /app

# Non-root user with a home directory (Streamlit writes to ~/.streamlit).
# /data is owned by that user so a fresh named volume inherits the ownership.
RUN groupadd --gid 10001 dashbite \
    && useradd --uid 10001 --gid 10001 --create-home dashbite \
    && mkdir /data \
    && chown 10001:10001 /data

COPY requirements.txt constraints.txt ./
RUN pip install --no-cache-dir -r requirements.txt -c constraints.txt

COPY pipeline ./pipeline

USER 10001

EXPOSE 8501

CMD ["python", "-m", "pipeline.simulator"]


FROM base AS test

USER root
COPY requirements-dev.txt ./
RUN pip install --no-cache-dir -r requirements-dev.txt -c constraints.txt \
    && install -d -o 10001 -g 10001 /app/.pytest_cache
COPY pytest.ini ./
COPY tests ./tests
USER 10001

CMD ["pytest"]


FROM base AS runtime
