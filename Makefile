# AirWatch — top-level Makefile.
#
# The cleanroom-pretag target runs the full migration test (~5 min). Run it
# before tagging a release. See cleanroom/README.md.

SHELL := /bin/bash
PYTHON ?= python3
BASELINE ?=

.PHONY: cleanroom-pretag cleanroom-bootstrap cleanroom-verify-latest cleanroom-cleanup-all cleanroom-lint help

help:
	@echo "Targets:"
	@echo "  cleanroom-pretag        Full migration test: bootstrap → upgrade → verify."
	@echo "                          Override baseline with: make cleanroom-pretag BASELINE=v1.4.0"
	@echo "  cleanroom-lint          Run the cleanroom config lint (HACS pin + allowlist sanity)."
	@echo "  cleanroom-cleanup-all   docker rm every aw-cleanroom-<ts> container (preserves snapshots)."

cleanroom-lint:
	$(PYTHON) cleanroom/lint.py

cleanroom-pretag:
	@set -e -o pipefail; \
	cd $(CURDIR); \
	bootstrap_log=$$(mktemp /tmp/cleanroom-bootstrap.XXXXXX.log); \
	echo "=== bootstrap (streaming + tee'd to $$bootstrap_log) ==="; \
	if [ -n "$(BASELINE)" ]; then \
	    $(PYTHON) cleanroom/bootstrap.py --baseline $(BASELINE) 2>&1 | tee "$$bootstrap_log"; \
	else \
	    $(PYTHON) cleanroom/bootstrap.py 2>&1 | tee "$$bootstrap_log"; \
	fi; \
	run_dir=$$(awk '/^RUN_DIR:/ {print $$2}' "$$bootstrap_log"); \
	rm -f "$$bootstrap_log"; \
	if [ -z "$$run_dir" ]; then echo "bootstrap did not print RUN_DIR" >&2; exit 1; fi; \
	echo; \
	echo "=== upgrade ==="; \
	$(PYTHON) cleanroom/upgrade.py "$$run_dir"; \
	echo; \
	echo "=== verify ==="; \
	$(PYTHON) cleanroom/verify.py "$$run_dir"

cleanroom-cleanup-all:
	@docker ps -a --filter "name=aw-cleanroom-" --format '{{.Names}}' \
	    | grep -v '^aw-cleanroom$$' \
	    | xargs -r docker rm -f
	@echo "cleaned up cleanroom-runs containers (preserved snapshots/runs/)"
