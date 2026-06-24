# Depara — local dev stack (API + Streamlit)
.PHONY: help setup up down status logs smoke

API_PORT ?= 8000
UI_PORT ?= 8501
RUN_DIR := .run

help:
	@echo "Depara — comandos locais"
	@echo ""
	@echo "  make setup   Instala deps, modelo spaCy e cria .env"
	@echo "  make up      Sobe API + Streamlit e aguarda ficarem prontos"
	@echo "  make down    Para API e Streamlit"
	@echo "  make status  Verifica se API e UI respondem"
	@echo "  make logs    Tail dos logs em $(RUN_DIR)/"
	@echo "  make smoke   sobe, testa health e desce (CI/local)"

setup:
	uv sync
	uv run python -m spacy download pt_core_news_md
	@test -f .env || cp .env.example .env
	@echo "Setup ok — edite .env se necessário, depois: make up"

$(RUN_DIR):
	@mkdir -p $(RUN_DIR)

_check-env:
	@test -d .venv || (echo "Run 'make setup' first." && exit 1)
	@test -f .env || (echo "Missing .env — run 'make setup' or cp .env.example .env" && exit 1)

up: _check-env $(RUN_DIR)
	@$(MAKE) --no-print-directory down
	@echo "Starting API on :$(API_PORT)..."
	@nohup uv run uvicorn depara.api.main:app --host 127.0.0.1 --port $(API_PORT) \
		>$(RUN_DIR)/api.log 2>&1 & echo $$! >$(RUN_DIR)/api.pid
	@$(MAKE) --no-print-directory _wait-api
	@echo "Starting Streamlit on :$(UI_PORT)..."
	@nohup uv run streamlit run depara/ui/app.py \
		--server.port $(UI_PORT) \
		--server.headless true \
		--browser.gatherUsageStats false \
		>$(RUN_DIR)/ui.log 2>&1 & echo $$! >$(RUN_DIR)/ui.pid
	@$(MAKE) --no-print-directory _wait-ui
	@echo ""
	@echo "Depara ready"
	@echo "  Streamlit: http://127.0.0.1:$(UI_PORT)"
	@echo "  API docs:  http://127.0.0.1:$(API_PORT)/docs"
	@echo "  Logs:      make logs"
	@echo "  Stop:      make down"

_wait-api:
	@i=0; while [ $$i -lt 30 ]; do \
		curl -sf "http://127.0.0.1:$(API_PORT)/health" | grep -q '"status":"ok"' && exit 0; \
		i=$$((i + 1)); sleep 1; \
	done; \
	echo "API failed — see $(RUN_DIR)/api.log"; tail -20 $(RUN_DIR)/api.log; exit 1

_wait-ui:
	@i=0; while [ $$i -lt 45 ]; do \
		curl -sf "http://127.0.0.1:$(UI_PORT)/_stcore/health" >/dev/null && exit 0; \
		i=$$((i + 1)); sleep 1; \
	done; \
	echo "Streamlit failed — see $(RUN_DIR)/ui.log"; tail -20 $(RUN_DIR)/ui.log; exit 1

down:
	@if [ -f $(RUN_DIR)/api.pid ]; then \
		kill $$(cat $(RUN_DIR)/api.pid) 2>/dev/null || true; \
		rm -f $(RUN_DIR)/api.pid; \
	fi
	@if [ -f $(RUN_DIR)/ui.pid ]; then \
		kill $$(cat $(RUN_DIR)/ui.pid) 2>/dev/null || true; \
		rm -f $(RUN_DIR)/ui.pid; \
	fi
	@for port in $(API_PORT) $(UI_PORT); do \
		pids=$$(lsof -ti:$$port 2>/dev/null || true); \
		[ -n "$$pids" ] && kill $$pids 2>/dev/null || true; \
	done
	@echo "Stopped."

status:
	@curl -sf "http://127.0.0.1:$(API_PORT)/health" >/dev/null \
		&& echo "API (:$(API_PORT)): up" || echo "API (:$(API_PORT)): down"
	@curl -sf "http://127.0.0.1:$(UI_PORT)/_stcore/health" >/dev/null \
		&& echo "UI  (:$(UI_PORT)): up" || echo "UI  (:$(UI_PORT)): down"

logs:
	@tail -f $(RUN_DIR)/api.log $(RUN_DIR)/ui.log

smoke: up
	@$(MAKE) --no-print-directory status
	@$(MAKE) --no-print-directory down
	@echo "smoke: ok"
