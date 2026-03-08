## =============================================================================
## voice-to-vault — Makefile
## =============================================================================
## Common targets for local development and production operations.
##
## Usage:
##   make setup      — copy .env template and check prerequisites
##   make deploy     — pull images and start all services
##   make logs       — tail OpenClaw container logs
##   make test       — run end-to-end smoke test
##   make stop       — stop all services
##   make clean      — remove containers and local volumes
## =============================================================================

.DEFAULT_GOAL := help
.PHONY: help setup deploy start stop restart logs status test smoke-test \
        validate-env pull update-skill clean generate-deploy-key \
        register-webhook check-webhook process

## ── Environment ───────────────────────────────────────────────────────────────
ENV_FILE      := .env
COMPOSE       := docker compose
OPENCLAW_CTR  := voice-to-vault-openclaw
SKILL_DIR     := openclaw/skills/vault-writer

## ── Help ──────────────────────────────────────────────────────────────────────
help: ## Show this help message
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2}'

## ── Setup ─────────────────────────────────────────────────────────────────────
setup: ## Copy .env template and verify prerequisites
	@echo "── Checking prerequisites ────────────────────────────────────────────"
	@command -v docker >/dev/null 2>&1 || (echo "ERROR: docker not installed" && exit 1)
	@command -v docker compose >/dev/null 2>&1 || (echo "ERROR: docker compose not installed" && exit 1)
	@echo "✓ Docker found: $$(docker --version)"
	@echo ""
	@if [ ! -f "$(ENV_FILE)" ]; then \
		cp .env.template $(ENV_FILE); \
		echo "✓ Created $(ENV_FILE) from template."; \
		echo "  → Edit $(ENV_FILE) and fill all required values before proceeding."; \
	else \
		echo "✓ $(ENV_FILE) already exists."; \
	fi
	@echo ""
	@echo "Next steps:"
	@echo "  1. Edit .env and set all values"
	@echo "  2. make generate-deploy-key"
	@echo "  3. make deploy"
	@echo "  4. make register-webhook"
	@echo "  5. make smoke-test"

validate-env: ## Validate all required env vars are set in .env
	@echo "── Validating environment ────────────────────────────────────────────"
	@test -f $(ENV_FILE) || (echo "ERROR: $(ENV_FILE) not found. Run: make setup" && exit 1)
	@set -a; . ./$(ENV_FILE); set +a; \
	missing=""; \
	for var in TELEGRAM_BOT_TOKEN TELEGRAM_ALLOWED_USER_ID OPENAI_API_KEY \
	           ANTHROPIC_API_KEY VAULT_REPO VAULT_DEPLOY_KEY_PATH \
	           OPENCLAW_WEBHOOK_SECRET OPENCLAW_WEBHOOK_URL; do \
		val=$$(eval echo "\$$$$var"); \
		if [ -z "$$val" ]; then missing="$$missing $$var"; fi; \
	done; \
	if [ -n "$$missing" ]; then \
		echo "ERROR: Missing required variables:$$missing"; exit 1; \
	fi
	@echo "✓ All required environment variables are set."

## ── Deploy Key ────────────────────────────────────────────────────────────────
generate-deploy-key: ## Generate SSH deploy key for vault repo write access
	@echo "── Generating vault deploy key ───────────────────────────────────────"
	@mkdir -p ~/.ssh
	@ssh-keygen -t ed25519 -C "voice-to-vault-deploy-key" \
		-f ~/.ssh/vault_deploy_key -N "" -q
	@echo ""
	@echo "✓ Deploy key generated: ~/.ssh/vault_deploy_key"
	@echo ""
	@echo "Add this public key as a Deploy Key with WRITE access in:"
	@echo "  https://github.com/$$(grep VAULT_REPO $(ENV_FILE) | cut -d= -f2)/settings/keys"
	@echo ""
	@cat ~/.ssh/vault_deploy_key.pub
	@echo ""
	@echo "Set VAULT_DEPLOY_KEY_PATH=~/.ssh/vault_deploy_key in $(ENV_FILE)"

## ── Docker operations ─────────────────────────────────────────────────────────
pull: ## Pull latest Docker images
	$(COMPOSE) pull

deploy: validate-env pull ## Pull images and start all services
	@echo "── Deploying voice-to-vault ──────────────────────────────────────────"
	$(COMPOSE) up -d
	@echo ""
	@echo "✓ Services started. Run: make logs"

start: ## Start services (without pulling)
	$(COMPOSE) up -d

stop: ## Stop all services
	$(COMPOSE) stop

restart: ## Restart OpenClaw container (apply config changes)
	$(COMPOSE) restart $(OPENCLAW_CTR)

status: ## Show service status and health
	$(COMPOSE) ps

logs: ## Tail OpenClaw logs
	$(COMPOSE) logs -f --tail=100 $(OPENCLAW_CTR)

logs-all: ## Tail all service logs
	$(COMPOSE) logs -f --tail=50

clean: ## Remove containers, networks, and named volumes (DESTRUCTIVE)
	@echo "WARNING: This will delete all container data including the vault clone cache."
	@read -p "Are you sure? [y/N] " confirm && [ "$$confirm" = "y" ] || exit 1
	$(COMPOSE) down -v
	@echo "✓ All containers and volumes removed."

## ── Webhook ───────────────────────────────────────────────────────────────────
register-webhook: validate-env ## Register Telegram webhook with BotFather
	@echo "── Registering Telegram webhook ──────────────────────────────────────"
	@set -a; . ./$(ENV_FILE); set +a; \
	curl -sf \
		"https://api.telegram.org/bot$${TELEGRAM_BOT_TOKEN}/setWebhook" \
		-d "url=$${OPENCLAW_WEBHOOK_URL}/webhook/telegram" \
		-d "secret_token=$${OPENCLAW_WEBHOOK_SECRET}" \
		-d "max_connections=1" \
		-d "allowed_updates=[\"message\"]" \
		| python3 -m json.tool
	@echo ""
	@echo "✓ Webhook registered. Run: make check-webhook"

check-webhook: validate-env ## Verify Telegram webhook configuration
	@set -a; . ./$(ENV_FILE); set +a; \
	curl -sf \
		"https://api.telegram.org/bot$${TELEGRAM_BOT_TOKEN}/getWebhookInfo" \
		| python3 -m json.tool

## ── Testing ───────────────────────────────────────────────────────────────────
smoke-test: ## Run end-to-end smoke test (requires running services)
	@echo "── Smoke test ────────────────────────────────────────────────────────"
	@echo "Checking OpenClaw health endpoint..."
	@curl -sf http://localhost:8080/health | python3 -m json.tool
	@echo ""
	@echo "✓ OpenClaw is healthy."
	@echo ""
	@echo "Next: Send a voice message to your Telegram bot from your account."
	@echo "Expected: ACK message received within 30 seconds."
	@echo "Verify: Check https://github.com/$$(grep VAULT_REPO $(ENV_FILE) | cut -d= -f2)/commits/main"

test: smoke-test ## Alias for smoke-test

process: ## Trigger an immediate vault processing run via the trigger daemon
	@curl -s -X POST http://localhost:9999/trigger \
		-H "X-Trigger-Secret: $(shell grep TRIGGER_SECRET .env | cut -d= -f2)" \
		| python3 -m json.tool

## ── Skill development ─────────────────────────────────────────────────────────
update-skill: ## Reload vault-writer skill (restart OpenClaw)
	@echo "── Updating vault-writer skill ───────────────────────────────────────"
	$(COMPOSE) restart $(OPENCLAW_CTR)
	@echo "✓ Skill reloaded. Run: make logs"

lint: ## Lint Python skill code
	@echo "── Linting Python skill code ─────────────────────────────────────────"
	@command -v ruff >/dev/null 2>&1 || pip install ruff -q
	ruff check $(SKILL_DIR)/
	@echo "✓ Lint passed."

format: ## Auto-format Python skill code
	@command -v ruff >/dev/null 2>&1 || pip install ruff -q
	ruff format $(SKILL_DIR)/

## ── Test suite ────────────────────────────────────────────────────────────────
.PHONY: test-unit test-integration test-ci test-eval-classifier test-eval-agent test-smoke

test-unit: ## Run unit tests with coverage (≥85%)
	pytest tests/unit/ -v --cov=openclaw/skills/vault-writer \
	  --cov-report=term-missing --cov-fail-under=85

test-integration: ## Run integration tests (all external calls mocked)
	pytest tests/integration/ -v

test-ci: test-unit test-integration ## Run full CI test suite (unit + integration)

test-eval-classifier: ## Run classifier evaluation (real Anthropic API calls ~$$0.02)
	@echo "⚠️  This makes real Anthropic API calls (~\$$0.02)"
	@read -p "Continue? [y/N] " c; [ "$$c" = "y" ] || exit 1
	python tests/evaluation/classifier_eval.py

test-eval-agent: ## Run agent evaluation (real Claude Code calls against vault fixture)
	@echo "⚠️  This makes real Claude Code calls against vault fixture"
	@read -p "Continue? [y/N] " c; [ "$$c" = "y" ] || exit 1
	python tests/evaluation/agent_eval.py

test-smoke: ## Run smoke test (real APIs ~$$0.02, writes to smoke-test branch)
	@echo "⚠️  This makes real API calls (~\$$0.02) and writes to smoke-test branch"
	@read -p "Continue? [y/N] " c; [ "$$c" = "y" ] || exit 1
	python tests/smoke/smoke_test.py
