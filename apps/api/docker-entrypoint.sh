#!/bin/sh
# `OPS-01`, ADR-002 — one image, two entrypoints, chosen by the command.
#
#     docker run <img> api        # uvicorn, 2 workers
#     docker run <img> worker     # arq app.worker.WorkerSettings
#
# The dispatch is on "$1" rather than on an environment variable, so a
# misconfigured variable cannot start the wrong process. An unrecognised
# argument is executed verbatim, which keeps `docker run <img> python -c ...`
# and `sh` available for a shell in a container without a second image.

set -eu

case "${1:-}" in
  api)
    shift
    # `15-infra-and-ops.md` §1: "api (uvicorn, 2 workers)".
    #
    # PORT is honoured because managed container hosts assign the port and
    # inject it; it defaults to 8000, which is what the Compose stack and the
    # HEALTHCHECK use. The process count is not taken from the environment —
    # two is what the spec says and what the memory budget assumes.
    exec uvicorn app.main:create_app \
      --factory \
      --host 0.0.0.0 \
      --port "${PORT:-8000}" \
      --workers 2 \
      "$@"
    ;;
  worker)
    shift
    exec arq app.worker.WorkerSettings "$@"
    ;;
  "")
    echo "docker-entrypoint.sh: expected 'api' or 'worker'" >&2
    exit 2
    ;;
  *)
    exec "$@"
    ;;
esac
