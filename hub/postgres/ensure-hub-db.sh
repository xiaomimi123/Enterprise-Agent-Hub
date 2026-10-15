#!/bin/bash
# 创建中枢自研服务的数据库用户和数据库（已存在则跳过，可重复执行）。
# 表结构由控制台后端启动时自动创建。
set -euo pipefail

psql -v ON_ERROR_STOP=1 --username "${POSTGRES_USER:-postgres}" <<-EOSQL
	DO \$\$ BEGIN
	  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'hub') THEN
	    CREATE USER hub WITH PASSWORD '${HUB_DB_PASSWORD}';
	  END IF;
	END \$\$;
EOSQL
if ! psql --username "${POSTGRES_USER:-postgres}" -tAc "SELECT 1 FROM pg_database WHERE datname='hub'" | grep -q 1; then
  psql -v ON_ERROR_STOP=1 --username "${POSTGRES_USER:-postgres}" -c "CREATE DATABASE hub OWNER hub"
fi
echo "hub 数据库就绪"
