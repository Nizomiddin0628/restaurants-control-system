# RestoPOS — qisqa buyruqlar. `make help`
.DEFAULT_GOAL := help
PY ?= python
BACKEND := backend
FRONTEND := frontend

help: ## Buyruqlar ro'yxati
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

setup: ## Birinchi o'rnatish: venv + pip + pnpm + .env
	$(PY) -m venv .venv && . .venv/bin/activate && pip install -U pip && pip install -r $(BACKEND)/requirements.txt
	cd $(FRONTEND) && corepack enable && pnpm install
	@test -f .env || cp .env.example .env

up: ## Docker: db + redis + backend + worker
	docker compose up -d

down: ## Docker: to'xtatish
	docker compose down

bootstrap: ## Sxemalar, tariflar, demo restoran (lazzat.localhost)
	cd $(BACKEND) && $(PY) manage.py bootstrap_dev

migrate: ## Barcha sxemalarga migratsiya
	cd $(BACKEND) && $(PY) manage.py migrate_schemas

run: ## Django dev-server (:8000)
	cd $(BACKEND) && $(PY) manage.py runserver 0.0.0.0:8000

worker: ## Celery worker
	cd $(BACKEND) && celery -A config worker -l info -Q critical,default,bulk

web: ## Frontend dev-server (:5173) — .env'da VITE_DEV=1 qo'ying
	cd $(FRONTEND) && pnpm dev

build: ## Admin panelni yig'ish → backend/website/static/admin
	cd $(FRONTEND) && pnpm build

test: ## Backend testlari
	cd $(BACKEND) && $(PY) -m pytest -q

lint: ## ruff + vue-tsc
	cd $(BACKEND) && ruff check .
	cd $(FRONTEND) && pnpm typecheck

tenant: ## Yangi restoran: make tenant NAME="Chopar" SLUG=chopar PHONE=+998901112233 PRESET=fast_food
	cd $(BACKEND) && $(PY) manage.py create_tenant --name "$(NAME)" --slug $(SLUG) --phone $(PHONE) --preset $(PRESET)

.PHONY: help setup up down bootstrap migrate run worker web build test lint tenant
