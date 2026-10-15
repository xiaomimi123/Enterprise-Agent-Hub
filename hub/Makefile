RAGFLOW_DIR := ragflow/upstream/docker

.PHONY: env up down ps logs ragflow-setup ragflow-up ragflow-down ragflow-ps all-up all-down

env:            ## 生成 .env（随机密码）
	@bash scripts/gen-env.sh

up:             ## 启动 Casdoor + New API + PostgreSQL + Redis
	docker compose up -d

down:
	docker compose down

ps:
	docker compose ps

logs:
	docker compose logs -f --tail=100

ragflow-setup:  ## 拉取 RAGFlow 官方部署文件并写入端口/密码
	@bash ragflow/setup.sh

ragflow-up: ragflow-setup
	cd $(RAGFLOW_DIR) && docker compose up -d

ragflow-down:
	cd $(RAGFLOW_DIR) && docker compose down

ragflow-ps:
	cd $(RAGFLOW_DIR) && docker compose ps

all-up: up ragflow-up

all-down: ragflow-down down
