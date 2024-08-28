SHELL := /bin/bash

.PHONY: help check-adrs check-runbooks check-saved-searches check-jaeger-links validate-compose verify-registry-obs all ci-local clean

help:
	@echo "Targets:"
	@echo "  check-adrs       - verify the ADR README index matches the folder"
	@echo "  check-runbooks   - verify every alert has a runbook_url + 5-section runbook"
	@echo "  check-saved-searches - verify runbook discover links resolve to NDJSON entries"
	@echo "  check-jaeger-links   - verify runbook Jaeger deep-links are service-scoped"
	@echo "  validate-compose - lint every docker-compose.*.yaml file via 'docker compose config'"
	@echo "  verify-registry-obs - LIVE-STACK: boot a registry, drive a round-trip,"
	@echo "                        poll Jaeger + Prom + ES to prove obs data flows"
	@echo "                        (requires the stack up + REGISTRY_BIN set; see scripts/)"
	@echo "  ci-local         - the same checks CI runs, in the same order"
	@echo "  clean            - remove generated artifacts"

check-adrs:
	@bash scripts/check-adrs.sh

check-runbooks:
	@bash scripts/check-runbooks.sh

check-saved-searches:
	@bash scripts/check-saved-searches.sh

check-jaeger-links:
	@bash scripts/check-jaeger-links.sh

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

all: check-adrs check-runbooks check-saved-searches check-jaeger-links validate-compose

ci-local: all

# Live-stack verification target. NOT part of ci-local because it
# requires the full observability stack + a markup-svc + a built
# model-registry binary. Operator-run; see ADR-0019 + the script
# header for prerequisites. Pass the registry binary path as
# REGISTRY_BIN or as $$ARGS:
#   make verify-registry-obs REGISTRY_BIN=/abs/path/to/model-registry
#   make verify-registry-obs ARGS=/abs/path/to/model-registry
verify-registry-obs:
	@bash scripts/verify-registry-observability.sh $(ARGS)

clean:
	@echo "nothing to clean"
