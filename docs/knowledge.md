# 知识库检索（RAGFlow 接入）

## 目的

员工通过中枢 MCP 的 `search_knowledge` 检索企业知识库。之前用本地 vault 的关键词打分（字符二元组），语义召回有限；现在接入 RAGFlow 向量检索，同时**保留本地检索作为自动回退**——RAGFlow 没部署、挂了、或没配 key，员工照常能查（效果退回关键词级），不会被挡住。

权限模型不变：仍由中枢按岗位包过滤知识库，RAGFlow 只会收到员工有权访问的库（见 [mcp-server.md](mcp-server.md)）。

## 结构

```
vault/<知识库名>/*.md   ──make ragflow-bootstrap──▶  RAGFlow dataset（名字 = 文件夹名）
                                                          │ 向量解析（内置 BAAI/bge-large-zh-v1.5，离线可用）
员工 search_knowledge ──▶ content.search() ──▶ RAGFlow /api/v1/retrieval（配置了且可用时）
                                          └──▶ 本地关键词检索（回退）── 两边返回相同的命中结构
```

| 模块 | 职责 |
|---|---|
| `app/ragflow.py` | RAGFlow 客户端：dataset 名单缓存、检索、建库/传文档/解析（bootstrap 用）；出错抛 `RagFlowError` |
| `app/content.py` | 统一入口 `search()`：配置了 RAGFlow 且可用则走向量检索，否则回退 `_local_search()` |
| `scripts/ragflow_bootstrap.py` | 灌库：自动创建 API key（管理员登录，写回 .env）→ 建 dataset → 上传 vault 文档 → 触发解析并等待完成；可重复执行 |

## 部署与使用

```bash
cd hub
make ragflow-up          # 首次拉约 10GB 镜像；Linux 需 vm.max_map_count=262144（setup.sh 会提示）
make ragflow-bootstrap   # 灌入 vault/ 全部知识库；自动创建 RAGFlow API key 写回 .env
# 之后在 .env 确认 RAGFLOW_ENDPOINT=http://<HUB_HOST>:9380（bootstrap 会创建 key，endpoint 手动填）
make up                  # 重启自研服务使配置生效
```

- `.env` 两项都配置（`RAGFLOW_ENDPOINT` + `RAGFLOW_API_KEY`）才启用 RAGFlow；留空即纯本地检索
- vault 里加文档后重跑 `make ragflow-bootstrap`，同名文档自动跳过
- RAGFlow 首次启动后再改 `RAGFLOW_*_PASSWORD` 会导致它连不上自己的数据库，不要改

## 关键设计与取舍

- **回退而非依赖**：检索是员工主链路，RAGFlow 故障不能挡住员工干活；回退在 `content.search()` 内部完成，调用方（MCP Server）无感。控制台与审计不区分检索来源（detail 一样）。
- **「0 条」不回退**：RAGFlow 正常返回空结果是真实答案（向量检索本就可能有召回空白），只有**出错**才回退，避免两边混着出结果。
- **dataset 名 = vault 文件夹名 = 岗位包里的知识库名**：三方共用一个名字，映射不需要维护表；bootstrap 按 `KB_REGISTRY` 对齐。
- **embedding 用 RAGFlow 内置模型**（`BAAI/bge-large-zh-v1.5`）：私有化环境不出网也能解析；换客户自有的 embedding 服务时在 RAGFlow 后台配模型供应商，重建 dataset 即可。
- **API key 自动创建**：bootstrap 用 `RAGFLOW_ADMIN_PASSWORD` 登录 `admin@ragflow.io` 创建 key（v0.27 的 `/api/v1/auth/login` → `/api/v1/system/tokens`）；若 RAGFlow 版本变动导致失败，脚本会提示去网页手动生成填入 .env。

## 本地验证（2026-10-15）

- 单元测试 `tests/test_ragflow.py`（6 个）：dataset 名单解析、命中结构映射（content/document_keyword/similarity → 与本地检索同构）、未知库返回空、上游报错抛异常、content.search 优先 RAGFlow / 出错回退 / 未配置走本地
- 本机 Docker 环境实测回退路径：未配 RAGFlow 时 MCP 检索正常（本地检索），39 个测试全过
- **RAGFlow 本体未在本机启动**（Docker VM 仅 8GB，官方要求 16GB+；启动计划本就安排在客户台式机上验证）——上台式机后执行 `make ragflow-up && make ragflow-bootstrap`，再用员工端实测向量检索

## 已知限制

- 本地回退检索是关键词级的，语义近义（「不能说的词」↔「极限词」）召回靠库名/文档名/标题兜底，不如向量检索
- 本地检索与 RAGFlow 的命中 `score` 量纲不同（重合度 vs 相似度），只在各自来源内部排序有意义，控制台不展示分数对比
