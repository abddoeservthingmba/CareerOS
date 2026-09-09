# syntax=docker/dockerfile:1.7

# `15-infra-and-ops.md` §1 (`OPS-01`), ADR-002 — one artifact that runs the API
# or the worker, identical in every environment.
#
# THE BUILD CONTEXT IS THE REPOSITORY ROOT, not `apps/api`:
#
#     docker build -f apps/api/Dockerfile -t jobpilot:$(git rev-parse HEAD) .
#
# `AC-FOUND-01.2` says `docker build apps/api`, and that cannot work as the
# code stands. `app/ai/budget.py` line 59 resolves its degradation matrix as
# `Path(__file__).resolve().parents[4] / "docs" / "spec" / "ai-budget.yaml"`
# and loads it at *module scope* (line 588, `MATRIX = load_matrix()`), so the
# file must sit inside the image four directories above the package — which a
# context rooted at `apps/api` cannot reach.
#
# Nothing imports `app.ai.budget` yet, so today this is latent rather than
# broken. It becomes an import-time crash the moment a module wires the budget
# in. Two ways to settle it, and this is a spec decision, not mine to take:
# either `AC-FOUND-01.2` is amended to name the root context, or
# `ai-budget.yaml` moves to package data under `app/ai/` beside
# `model-pricing.yaml`, which already resolves with `Path(__file__).with_name`.
# Until then the layout below preserves the repository's directory depth so
# `parents[4]` lands on `/srv`, and the file is copied in.

# --- build stage ------------------------------------------------------------
#
# `uv` installs into a virtual environment here and never reaches the runtime
# image ("No compiler, no `uv`, no git in the runtime image").

FROM python:3.12-slim AS build

# Pinned. An unpinned tool version makes the image non-reproducible, which is
# the thing tagging by git SHA exists to guarantee.
COPY --from=ghcr.io/astral-sh/uv:0.12.10 /uv /usr/local/bin/uv

ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /srv/apps/api

# Dependencies before the application, so an application-only change does not
# reinstall them (`AC-OPS-01.5`). Only the two files that describe the
# dependency set are copied in this layer — touching `app/` must not bust it.
COPY apps/api/pyproject.toml apps/api/uv.lock ./

# `--frozen` installs the lockfile and resolves nothing, so the image contains
# exactly what CI resolved. `--no-dev` drops the dev group: pytest, mypy, ruff
# and import-linter are not runtime dependencies.
#
# `--no-install-project` is not passed: `pyproject.toml` declares no
# `[build-system]`, so the project is virtual and `uv sync` installs only its
# dependencies. The application is imported from the source tree via WORKDIR,
# which is what `infra/scripts/run_api.py` does locally.
RUN uv sync --frozen --no-dev

# --- runtime stage ----------------------------------------------------------

FROM python:3.12-slim AS runtime

# `AC-OPS-01.1` — a non-root user. The read-only root filesystem is a *runtime*
# property and cannot be set from here; the deployment must pass
# `--read-only --tmpfs /tmp` (compose: `read_only: true`), which is asserted
# against the running container, not the image.
RUN groupadd --system --gid 10001 jobpilot \
 && useradd --system --uid 10001 --gid jobpilot --no-create-home jobpilot

ENV PATH=/opt/venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    # `app` is importable because WORKDIR is the package's parent, matching the
    # repository layout that `app/ai/budget.py` walks upward through.
    PYTHONPATH=/srv/apps/api

COPY --from=build /opt/venv /opt/venv

WORKDIR /srv/apps/api

# The application last, for the layer-cache order above.
COPY apps/api/app ./app

# Read at runtime by `app/ai/budget.py`, from four directories up. See the
# header: this is why the build context is the repository root. Nothing else
# from `docs/` enters the image.
COPY docs/spec/ai-budget.yaml /srv/docs/spec/ai-budget.yaml

# `--chmod` rather than the file's own mode bit: this repository is developed on
# Windows, where the executable bit is not a thing the filesystem records, so a
# checkout there would produce a non-executable entrypoint and an image that
# cannot start. Setting it here makes the mode a property of the build.
COPY --chmod=0755 apps/api/docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh

USER jobpilot

EXPOSE 8000

# `HEALTHCHECK` hits `/healthz` — liveness only. `/readyz` is what a load
# balancer polls, because it additionally reaches Mongo and Redis and verifies
# the declared indexes; a container that is up but missing an index is not
# ready, and that is a scheduling decision rather than a restart decision.
#
# `urllib` from the interpreter that is already present, rather than `curl`:
# `python:3.12-slim` ships no curl, and installing one would add a package
# manager footprint to a runtime image that `AC-OPS-01.4` wants clean.
HEALTHCHECK --interval=30s --timeout=3s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import os,urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:%s/healthz' % os.environ.get('PORT','8000'), timeout=2).status == 200 else 1)"]

# Two entrypoints, selected by the command and never by an environment
# variable (ADR-002): a misconfigured variable cannot start the wrong process.
ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["api"]
