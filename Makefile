# JobPilot — repository targets.
#
# `make check` is the gate CLAUDE.md's per-requirement loop runs: lint, types,
# the spec gates, and the tests. It grows as the phases land; today it covers
# the spec tooling built in step 1.

SHELL := /bin/bash
PY := py -m uv run --project apps/api
SPECGATE := PYTHONPATH=infra/scripts py -m specgate

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

.PHONY: generate
generate: build-order status spec-trace spec-metadata  ## Regenerate every committed artifact

# --- the gate ---------------------------------------------------------------

.PHONY: lint
lint:  ## ruff
	$(PY) ruff check apps/api/tests infra/scripts

.PHONY: format
format:  ## ruff format
	$(PY) ruff format apps/api/tests infra/scripts

.PHONY: types
types:  ## mypy
	cd apps/api && py -m uv run mypy

.PHONY: test
test:  ## pytest
	cd apps/api && py -m uv run pytest

.PHONY: check
check: lint types test  ## Everything that must be green before a commit
	@echo "make check: green"
