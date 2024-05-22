SHELL := /bin/bash

.PHONY: help check-adrs check-runbooks validate-compose all ci-local clean

help:
	@echo "Targets:"
	@echo "  check-adrs       - verify the ADR README index matches the folder"
	@echo "  check-runbooks   - verify every alert has a runbook_url + 5-section runbook"
	@echo "  validate-compose - lint every docker-compose.*.yaml file via 'docker compose config'"
	@echo "  ci-local         - the same checks CI runs, in the same order"
	@echo "  clean            - remove generated artifacts"

check-adrs:
	@bash scripts/check-adrs.sh

check-runbooks:
	@bash scripts/check-runbooks.sh

# Walk each docker-compose.*.yaml file in the repo root and let
# docker compose resolve the merged config. A YAML / schema /
# unknown-key error from compose fails the step. Skipped (with a
# notice) when docker is not on PATH so the gate stays usable on
# minimal CI runners; the GitHub Actions image has docker
# preinstalled so production CI still validates.
validate-compose:
	@for f in docker-compose*.yaml; do \
	  [ -e "$$f" ] || continue; \
	  if command -v docker >/dev/null 2>&1; then \
	    echo "validate-compose: $$f"; \
	    docker compose -f "$$f" config -q || exit 1; \
	  else \
	    echo "validate-compose: docker not on PATH -- skipping $$f"; \
	  fi; \
	done

all: check-adrs check-runbooks validate-compose

ci-local: all

clean:
	@echo "nothing to clean"
