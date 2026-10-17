SHELL := /bin/bash
PY := uv run python
.PHONY: snapshot check test

snapshot:            ## fetch and freeze every Yukon benchmark (network)
	$(PY) -m snapshot.fetch --out snapshot/raw

test:
	uv run pytest -q

# Tripwire: fail if zero tests ran or any were skipped (AT9).
check:
	uv run pytest -q -rs | tee .pytest-last.txt; \
	status=$${PIPESTATUS[0]}; \
	if grep -qE "no tests ran|[0-9]+ skipped" .pytest-last.txt; then echo "TRIPWIRE: zero tests or skips"; exit 1; fi; \
	exit $$status
