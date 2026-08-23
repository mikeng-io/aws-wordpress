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
	@printf 'aws cli       : '; aws --version 2>&1 | head -1
	@aws --version 2>&1 | grep -q '^aws-cli/2' \
	  || echo "  WARNING: AWS CLI v2 required for deployment work; v1 detected"
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

.PHONY: results
results: ## List recorded runs
	@find results -mindepth 2 -maxdepth 2 -type d 2>/dev/null | sort || echo "no runs yet"

.PHONY: status
status: ## Show the hypothesis register at a glance
	@sed -n '/^| ID/,/^$$/p' hypotheses/README.md
