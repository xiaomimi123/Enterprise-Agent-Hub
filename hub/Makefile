RAGFLOW_DIR := ragflow/upstream/docker

.PHONY: env up down ps logs db-hub bootstrap bootstrap-demo ragflow-setup ragflow-up ragflow-down ragflow-ps all-up all-down

env:            ## 生成 .env（随机密码）
	@bash scripts/gen-env.sh

up:             ## 构建并启动全部服务（开源组件 + 控制台 + MCP Server）
	docker compose up -d --build

down:
	docker compose down

ps:
	docker compose ps

# 首次部署：在 Casdoor 中创建企业组织和三个登录应用，把凭证写回 .env，再重启自研服务使其生效
BOOTSTRAP = docker compose run --rm --no-deps -v ./.env:/hub.env console-api \
	python scripts/casdoor_bootstrap.py --env-file /hub.env --casdoor-url http://casdoor:8000

bootstrap:      ## 初始化 Casdoor 组织与应用（生产）
	$(BOOTSTRAP)
	docker compose up -d console-api hub-mcp console-web

bootstrap-demo: ## 初始化 Casdoor，并创建测试部门与成员（开发/演示）
	$(BOOTSTRAP) --demo
	docker compose up -d console-api hub-mcp console-web

db-hub:         ## 为已初始化过的 PostgreSQL 补建中枢数据库（可重复执行）
	docker compose exec postgres bash /ensure-hub-db.sh

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
