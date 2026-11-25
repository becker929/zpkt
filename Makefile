# zpkt: the core (zpkt.live, zpkt.audio) is one uv project at the repo root; contrib and prototypes are their own.
PYTEST   := uv run pytest -q -p no:cacheprovider

.PHONY: setup remote-script format lint types test test-all check

setup: remote-script  ## install the core's environment (every extra) and the Live Remote Script
	uv sync -q --all-extras
	@echo "Now restart Live and pick AbletonLiveMCP as a Control Surface (docs/getting-started.md)."

remote-script:
	src/zpkt/live/remote_scripts/install.sh

RUFF     := uvx ruff@0.14.6

format:  ## apply the one style (ruff.toml) to every maintained Python part
	$(RUFF) check --fix -q .
	$(RUFF) format -q .

lint:  ## check style without changing anything
	$(RUFF) check -q .
	$(RUFF) format --check -q .

types:  ## mypy on the core and the mix desk
	uv run --all-extras mypy
	uv run --all-extras mypy --config-file contrib/mixdesk/mypy.ini

check: lint types test-all  ## everything CI runs, before a commit

test:  ## the supported parts: offline, no Live
	uv run --all-extras pytest -q -p no:cacheprovider

test-all: test  ## contrib and prototypes too
	cd contrib/harness && uv run --extra dev pytest -q -p no:cacheprovider
	uv run --all-extras pytest -q -p no:cacheprovider contrib/arranger/tests
	uv run --all-extras pytest -q -p no:cacheprovider contrib/mixdesk/tests
	cd prototypes/audio-browser && $(PYTEST) --ignore tests/test_segment.py
	cd prototypes/checklist && uv run --extra dev pytest -q -p no:cacheprovider
