#!/bin/bash
# 首次初始化 PostgreSQL 数据目录时执行一次：为 Casdoor、New API、中枢自研服务各建一个用户和数据库
set -euo pipefail

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" <<-EOSQL
	CREATE USER casdoor WITH PASSWORD '${CASDOOR_DB_PASSWORD}';
	CREATE DATABASE casdoor OWNER casdoor;
	CREATE USER newapi WITH PASSWORD '${NEWAPI_DB_PASSWORD}';
	CREATE DATABASE newapi OWNER newapi;
EOSQL

bash /ensure-hub-db.sh
