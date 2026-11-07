SHELL := /bin/bash

.PHONY: help check-adrs check-runbooks check-saved-searches check-jaeger-links validate-compose verify-registry-obs notebooks all ci-local clean

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

validate-compose:
	@bash scripts/validate-compose.sh

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

# Regenerate analytics/*.ipynb from the jupytext .py sources under
# notebooks/analytics/. Requires `jupytext` on PATH (`pip install
# jupytext`). Re-run after editing any .py source so the checked-in
# .ipynb stays in sync — the pair keeps clean diffs on review + a
# Colab-native deliverable side-by-side. See ADR-0021.
notebooks:
	@command -v jupytext >/dev/null 2>&1 || { echo "install jupytext: pip install jupytext"; exit 1; }
	@for f in notebooks/analytics/*.py; do \
	  jupytext --to notebook "$$f"; \
	done

clean:
	@echo "nothing to clean"
