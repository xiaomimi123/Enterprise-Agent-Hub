RAGFLOW_DIR := ragflow/upstream/docker

.PHONY: ragflow-bootstrap kb-sync env up down ps logs db-hub bootstrap bootstrap-demo ragflow-setup ragflow-up ragflow-down ragflow-ps all-up all-down

env:            ## 生成 .env（随机密码）
	@bash scripts/gen-env.sh

up:             ## 构建并启动全部服务（开源组件 + 控制台 + MCP Server）
	docker compose up -d --build

down:
	docker compose down

ps:
	docker compose ps

# 首次部署：初始化 Casdoor（企业组织、三个登录应用）和 New API（管理员、访问令牌），
# 凭证写回 .env，再重启自研服务使其生效
RUN_SCRIPT = docker compose run --rm --no-deps -v ./.env:/hub.env console-api python
CASDOOR_BOOTSTRAP = $(RUN_SCRIPT) scripts/casdoor_bootstrap.py --env-file /hub.env --casdoor-url http://casdoor:8000
NEWAPI_BOOTSTRAP = $(RUN_SCRIPT) scripts/newapi_bootstrap.py --env-file /hub.env --newapi-url http://new-api:3000

bootstrap:      ## 初始化 Casdoor 与 New API（生产）
	docker compose build console-api
	$(CASDOOR_BOOTSTRAP)
	$(NEWAPI_BOOTSTRAP)
	docker compose up -d

bootstrap-demo: ## 初始化，并创建测试部门、成员、模拟模型和模拟 GPU 节点（开发/演示）
	docker compose build console-api
	$(CASDOOR_BOOTSTRAP) --demo
	$(NEWAPI_BOOTSTRAP) --demo
	docker compose up -d

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

ragflow-bootstrap: ## RAGFlow 启动后执行一次：建管理员和 API Key，写回 .env
	cd ../console/backend && uv run python scripts/ragflow_bootstrap.py --env-file ../../hub/.env

kb-sync:        ## 把知识库文档（数据库里当前生效的版本）全量同步到 RAGFlow
	docker compose exec console-api python scripts/ragflow_sync.py --wait

all-up: up ragflow-up

all-down: ragflow-down down
