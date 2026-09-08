# JobPilot — repository targets.
#
# `make check` is the gate CLAUDE.md's per-requirement loop runs: lint, types,
# the spec gates, and the tests. It grows as the phases land; today it covers
# the spec tooling built in step 1.

SHELL := /bin/bash
PY := py -m uv run --project apps/api
SPECGATE := PYTHONPATH=infra/scripts py -m specgate
TASKS := py infra/scripts/tasks.py

# The machine's certificate chain is intercepted, so uv needs the system trust
# store to reach its download hosts.
export UV_SYSTEM_CERTS := 1

.DEFAULT_GOAL := help

.PHONY: help
help:  ## List the targets
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

.PHONY: install
install:  ## Create the API virtualenv from apps/api/pyproject.toml
	py -m uv sync --project apps/api

# --- the spec gates ---------------------------------------------------------

.PHONY: bundle
bundle:  ## Files an agent needs for one requirement: make bundle REQ=MATCH-05
	@$(SPECGATE) bundle $(REQ)

.PHONY: build-order
build-order:  ## Regenerate docs/spec/BUILD-ORDER.md from the manifest
	@$(SPECGATE) build-order --write

.PHONY: spec-trace
spec-trace:  ## Regenerate docs/spec/TRACEABILITY.md and run the gate
	@$(SPECGATE) trace --write

.PHONY: spec-trace-strict
spec-trace-strict:  ## The R1-gate form: every named test file must exist
	@$(SPECGATE) trace --strict

.PHONY: status
status:  ## Regenerate docs/spec/status.yaml
	@$(SPECGATE) status --write

.PHONY: spec-metadata
spec-metadata:  ## Regenerate docs/spec/SPEC-METADATA.json
	@$(SPECGATE) spec-metadata --write

.PHONY: check-spec
check-spec:  ## Run every spec gate and print a per-check report
	@$(SPECGATE) check

.PHONY: error-codes
error-codes:  ## Regenerate docs/error-codes.md from the ErrorCode enum
	@cd apps/api && py -m uv run python -c "from app.core.errors import render_error_codes; open('../../docs/error-codes.md','w',encoding='utf-8',newline='').write(render_error_codes())"
	@echo "wrote docs/error-codes.md"

.PHONY: api
api:  ## Run the API locally without Docker (http://localhost:8000)
	@py infra/scripts/run_api.py

.PHONY: web
web:  ## Run the web client locally (http://localhost:5173)
	cd apps/web && npm run dev

.PHONY: events-doc
events-doc:  ## Regenerate docs/events.md from the event registry
	@cd apps/api && py -m uv run python -c "from app.core.events import render_events_doc; open('../../docs/events.md','w',encoding='utf-8',newline='').write(render_events_doc())"
	@echo "wrote docs/events.md"

.PHONY: import-contracts
import-contracts:  ## Regenerate apps/api/.importlinter from the module tree
	@py infra/scripts/gen_importlinter.py --write

.PHONY: lint-imports
lint-imports:  ## import-linter (FOUND-04, HR-12)
	cd apps/api && py -m uv run lint-imports --config .importlinter

.PHONY: new-module
new-module:  ## Scaffold a module: make new-module NAME=demo
	@py infra/scripts/new_module.py $(NAME)
	@py infra/scripts/gen_importlinter.py --write

.PHONY: openapi
openapi:  ## Regenerate packages/contracts/openapi.json (FOUND-13)
	@py infra/scripts/export_openapi.py --write

.PHONY: api-diff
api-diff:  ## Classify an API change: make api-diff ARGS="before.json after.json"
	@py infra/scripts/diff_openapi.py $(ARGS)

.PHONY: generate
generate: build-order status spec-trace spec-metadata error-codes events-doc import-contracts openapi  ## Regenerate every committed artifact

# --- the gate ---------------------------------------------------------------
#
# Every target below delegates to `infra/scripts/tasks.py`, and that is the
# point rather than laziness.
#
# There used to be three definitions of "lint": this file ran
# `ruff check apps/api/tests infra/scripts` from the repository root - which
# covered the tests and **not `apps/api/app`** - `tasks.py` ran it over
# `apps/api infra/scripts`, also from the root, and `api-ci.yml` ran it from
# `apps/api` over `../../apps/api ../../infra/scripts`.
#
# The three disagreed in a way nobody could see. Ruff's configuration
# discovery depends on the working directory and the only config in this
# repository is `apps/api/pyproject.toml`, so the CI invocation applied
# line-length 100 and `E,F,I,UP,B,SIM` to `infra/scripts` while both local ones
# applied ruff's weaker built-in defaults. Six commits reported green locally
# and failed CI on the first step.
#
# One definition, in `tasks.py`, called by both this file and the workflow. A
# gate that is not the same command everywhere is not a gate.

.PHONY: lint
lint:  ## ruff check — the same invocation api-ci.yml runs
	@$(TASKS) lint

.PHONY: format
format:  ## ruff format — rewrites files
	@$(TASKS) format

.PHONY: format-check
format-check:  ## ruff format --check — what api-ci.yml runs
	@$(TASKS) format-check

.PHONY: types
types:  ## mypy
	@$(TASKS) types

.PHONY: test
test:  ## pytest
	@$(TASKS) test

.PHONY: check
check: lint lint-imports types test  ## Everything that must be green before a commit
	@echo "make check: green"
