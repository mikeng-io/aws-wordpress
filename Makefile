# Single entrypoint for the study. If a step isn't here, it isn't reproducible.
.DEFAULT_GOAL := help
SHELL := /bin/bash

NODE_VERSION := $(shell cat .nvmrc)

.PHONY: help
help: ## Show available targets
	@grep -hE '^[a-zA-Z0-9_.-]+:.*?## ' $(MAKEFILE_LIST) \
	  | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2}'

# --- environment ------------------------------------------------------------

.PHONY: doctor
doctor: ## Check the toolchain is usable before anything else
	@echo "node required : $(NODE_VERSION)"
	@echo "node active   : $$(node -v 2>/dev/null || echo MISSING)"
	@node -e 'const w="v$(NODE_VERSION)",g=process.version; if(g!==w){console.error("\n  WRONG NODE. run: nvm use\n");process.exit(1)}' \
	  && echo "  node OK"
	@# collect.sh uses the first WORKING v2 on PATH, not the first aws; check the same.
	@v2=""; for c in $$(type -ap aws); do "$$c" --version 2>&1 | grep -q '^aws-cli/2' && { v2=$$c; break; }; done; \
	  if [ -n "$$v2" ]; then echo "aws cli       : $$("$$v2" --version 2>&1 | head -1) ($$v2)"; \
	  else echo "aws cli       : MISSING - no working AWS CLI v2 on PATH"; exit 1; fi
	@printf 'docker        : '; docker --version 2>&1 | head -1
	@printf 'cdk           : '; (cd infra && npx cdk --version 2>/dev/null || echo "not installed - run make bootstrap")

.PHONY: bootstrap
bootstrap: ## Install dependencies
	cd infra && npm install

# --- apparatus --------------------------------------------------------------

.PHONY: synth
synth: ## Synthesize all experiment stacks (no AWS calls, no cost)
	@cd infra && if [ -z "$$(npx cdk list 2>/dev/null)" ]; then \
	   echo "No stacks registered yet - expected during bootstrap."; \
	   echo "Experiment stacks are added to infra/bin/apparatus.ts as they are specced."; \
	 else npx cdk synth; fi

.PHONY: build
build: ## Typecheck the CDK apparatus
	cd infra && npx tsc --noEmit

# --- experiments ------------------------------------------------------------

.PHONY: e0
e0: ## E0 syscall census - local Docker, no AWS, no cost
	./experiments/E0-syscall-census/run.sh

# --- results ----------------------------------------------------------------

.PHONY: e2
e2: ## E2 storage matrix - deploys, runs both arms, collects, DESTROYS. ~$0.96/hr while up
	@set -a; . ./.env; set +a; ./experiments/E2-storage-matrix/scripts/collect.sh $(REPS)

# The same collection, from the pinned runner image rather than the workstation's
# toolchain. infra/node_modules is shadowed by a named volume so the container's
# Linux dependencies never overwrite the host's macOS ones. Runs detached, so it
# survives the terminal closing; follow it with `docker logs -f e2-run`.
# Pause/resume pass straight through: STOP_AFTER_REP=1, RESUME_RUN_ID=<run-id>.
.PHONY: runner
runner: ## Build the pinned deploy/collect runner image (Node 22.17, AWS CLI v2, Docker CLI)
	docker build -t aws-wordpress-runner infra/runner

.PHONY: e2-container
e2-container: runner ## E2 from the runner container, detached. Same cost and teardown as `make e2`
	docker run -d --name e2-run \
	  -v /var/run/docker.sock:/var/run/docker.sock \
	  -v "$$PWD":/repo -v aws-wordpress-node-modules:/repo/infra/node_modules \
	  -e STOP_AFTER_REP="$(STOP_AFTER_REP)" -e RESUME_RUN_ID="$(RESUME_RUN_ID)" \
	  aws-wordpress-runner \
	  bash -c 'cd infra && npm ci --no-audit --no-fund --loglevel=error && cd .. && make doctor && make e2 REPS=$(or $(REPS),3)'

.PHONY: e5
e5: ## Internal guarded-runner entrypoint; use e5-container from the host
	@set -a; . ./.env; set +a; ./experiments/E5-attribute-cache/scripts/collect.sh $(REPS)

.PHONY: e5-container
e5-container: runner ## Launch E5 with a detached HOST watchdog; status: make e5-watchdog-status
	@set -a; . ./.env; set +a; STOP_AFTER_REP="$(STOP_AFTER_REP)" RESUME_RUN_ID="$(RESUME_RUN_ID)" RESUME_ALLOW_CHANGED="$(RESUME_ALLOW_CHANGED)" python3 experiments/E5-attribute-cache/scripts/watchdog.py launch --reps $(or $(REPS),3)

.PHONY: e5-diagnostic
e5-diagnostic: runner ## One authorised AWS diagnostic; detached host watchdog, 75m run ceiling
	@set -a; . ./.env; set +a; E5_RUN_KIND=diagnostic STOP_AFTER_REP=1 python3 experiments/E5-attribute-cache/scripts/watchdog.py launch --reps 1

.PHONY: e5-watchdog-status e5-watchdog-recover e5-watchdog-selftest
e5-watchdog-status: ## Read the latest local watchdog state (no AWS calls)
	@python3 experiments/E5-attribute-cache/scripts/watchdog.py status

e5-watchdog-recover: ## Retry the latest run's scoped cleanup using host AWS CLI; does not deploy
	@set -a; . ./.env; set +a; python3 experiments/E5-attribute-cache/scripts/watchdog.py recover

e5-watchdog-selftest: ## Fault-injection tests with fake AWS/Docker; no live calls
	@PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s analysis -p test_e5_watchdog.py -v

.PHONY: e5-watchdog-synth-check
e5-watchdog-synth-check: runner ## Offline CDK ownership-tag checks with dummy account/AZ context
	./experiments/E5-attribute-cache/scripts/watchdog-synth-check.sh

.PHONY: e5-preflight
e5-preflight: pricing ## Read-only live baseline, IAM simulation and budget evidence; never deploys
	@set -a; . ./.env; set +a; PYTHONDONTWRITEBYTECODE=1 python3 experiments/E5-attribute-cache/scripts/preflight.py

.PHONY: e5-preflight-selftest
e5-preflight-selftest: ## Verify readiness and read-only guards without AWS calls
	@PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s analysis -p test_e5_preflight.py -v

.PHONY: e5-local
e5-local: ## E5 apparatus check against a local kernel NFS server - no AWS, no cost. MODE="fast", "fast-probe" and/or "leases-off"
	./experiments/E5-attribute-cache/scripts/local-nfs-check.sh $(or $(OUT),/tmp/e5-local) $(MODE)

.PHONY: e5-stats
e5-stats: ## Grade E5 from the latest committed run (or RUN=results/E5/<run-id>)
	@python3 analysis/e5_stats.py $(or $(RUN),$$(ls -d results/E5/*/ | tail -1))

.PHONY: e5-selftest
e5-selftest: ## Run E5's grader against synthetic runs that must reach every grade
	@PYTHONDONTWRITEBYTECODE=1 python3 analysis/e5_selftest.py
	@PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s analysis -p test_e5_attribution.py
	@PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s analysis -p test_e5_pilot_diagnose.py

.PHONY: e5-p7-review
e5-p7-review: ## Recompute the P7 control review from committed raw data; no AWS
	@PYTHONDONTWRITEBYTECODE=1 python3 analysis/e5_p7_control_review.py

.PHONY: e5-instrument-selftest
e5-instrument-selftest: ## Linux integration checks for opt-in telemetry; no privileges/NFS/AWS
	docker build -q -t e5-bench-local infra/lib/stacks/bench
	docker run --rm --entrypoint python3 -v "$$PWD:/repo:ro" e5-bench-local /repo/analysis/test_e5_instrument.py -v

.PHONY: e5-diagnostic-selftest
e5-diagnostic-selftest: ## Diagnostic controls, analysis and watchdog checks; no AWS calls
	@PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s analysis -p test_e5_watchdog.py
	@PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s analysis -p test_e5_diagnostic_control.py
	@PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s analysis -p test_e5_diagnostic_stats.py
	@PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s analysis -p test_e5_isolation_acceptance.py

.PHONY: e5-formal-selftest
e5-formal-selftest: ## Full-window formal fixtures, matched P7 controls and guard gates; no AWS calls
	@PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s analysis -p test_e5_formal.py -v
	@PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s analysis -p test_e5_watchdog.py

.PHONY: charts
charts: ## Regenerate E2's figures from the committed raw results
	@python3 analysis/e2_chart.py $$(ls -d results/E2/*/ | tail -1)

.PHONY: pricing
pricing: ## Refresh the AWS pricing snapshot used by every cost table
	@set -a; . ./.env; set +a; python3 analysis/aws_pricing.py

.PHONY: results
results: ## List recorded runs
	@find results -mindepth 2 -maxdepth 2 -type d 2>/dev/null | sort || echo "no runs yet"

.PHONY: status
status: ## Show the hypothesis register at a glance
	@sed -n '/^| ID/,/^$$/p' hypotheses/README.md
